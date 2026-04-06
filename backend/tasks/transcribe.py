     1|"""
     2|ClipForge -- Celery Task: Transcription
     3|Local faster-whisper (no API cost). Replaces OpenAI Whisper API.
     4|
     5|Uses the already-installed faster-whisper library with tiny/base/small/medium/large models.
     6|Configurable via WHISPER_MODEL env var. Default: large-v3 (best quality).
     7|"""
     8|from __future__ import annotations
     9|
    10|    11|import json
    12|import logging
    13|import os
    14|from typing import Dict, List, Any
    15|
    16|from backend.celery_app import celery_app
    17|from backend.models.database import Video, SessionLocal
    18|from sqlalchemy import select
    19|
    20|log = logging.getLogger("clipforge.transcribe")
    21|
    22|DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "base")
    23|COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE", "float16")
    24|
    25|_model = None
    26|_model_name = None
    27|
    28|
    29|def get_model():
    30|    """Lazy-load the Whisper model (keeps it in memory for subsequent calls)."""
    31|    global _model, _model_name
    32|    if _model is None or _model_name != DEFAULT_MODEL:
    33|        log.info("Loading faster-whisper model: %s (compute=%s)", DEFAULT_MODEL, COMPUTE_TYPE)
    34|        from faster_whisper import WhisperModel
    35|        _model = WhisperModel(DEFAULT_MODEL, compute_type=COMPUTE_TYPE)
    36|        _model_name = DEFAULT_MODEL
    37|        log.info("Whisper model loaded: %s", _model_name)
    38|    return _model
    39|
    40|
    41|def transcribe_file_local(audio_path: str) -> Dict[str, Any]:
    42|    """
    43|    Transcribe a local audio file using faster-whisper.
    44|    Returns: {text, segments: [{start, end, text}], words: [{word, start, end}]}
    45|    Word-level timestamps require word_timestamps=True (available in newer models).
    46|    """
    47|    model = get_model()
    48|
    49|    # Handle files > 25MB by splitting (Whisper context limit ~half hour audio)
    50|    file_size = os.path.getsize(audio_path)
    51|    if file_size > 25 * 1024 * 1024:
    52|        return _transcribe_chunked(audio_path)
    53|
    54|    segments_gen, _ = model.transcribe(
    55|        audio_path,
    56|        beam_size=5,
    57|        vad_filter=True,
    58|        vad_parameters=dict(min_silence_duration_ms=500),
    59|        word_timestamps=True,
    60|    )
    61|
    62|    segments = []
    63|    words = []
    64|    text_parts = []
    65|
    66|    for seg in segments_gen:
    67|        seg_dict = {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
    68|        segments.append(seg_dict)
    69|        text_parts.append(seg.text.strip())
    70|        if seg.words:
    71|            for w in seg.words:
    72|                words.append({
    73|                    "word": w.word,
    74|                    "start": w.start,
    75|                    "end": w.end,
    76|                })
    77|
    78|    return {
    79|        "text": " ".join(text_parts),
    80|        "segments": segments,
    81|        "words": words,
    82|    }
    83|
    84|
    85|def _transcribe_chunked(audio_path: str) -> Dict[str, Any]:
    86|    """Split large audio file into 24-minute chunks and merge results."""
    87|    import subprocess
    88|
    89|    chunks_dir = os.path.join("/tmp", "clipforge", "chunks")
    90|    os.makedirs(chunks_dir, exist_ok=True)
    91|
    92|    # Get duration via ffprobe
    93|    cmd = [
    94|        "ffprobe", "-v", "error",
    95|        "-show_entries", "format=duration",
    96|        "-of", "default=noprint_wrappers=1:nokey=1",
    97|        audio_path,
    98|    ]
    99|    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
   100|    try:
   101|        duration = float(proc.stdout.strip())
   102|    except (ValueError, TypeError):
   103|        duration = 0.0
   104|
   105|    chunk_duration = 24 * 60  # 24 minutes
   106|    num_chunks = max(1, int(duration / chunk_duration) + 1)
   107|
   108|    log.info("Splitting %.0fs audio into %d chunks", duration, num_chunks)
   109|
   110|    all_text = []
   111|    all_segments = []
   112|    all_words = []
   113|    time_offset = 0.0
   114|
   115|    for i in range(num_chunks):
   116|        start = i * chunk_duration
   117|        chunk_path = os.path.join(chunks_dir, f"chunk_{i:03d}.mp3")
   118|
   119|        cmd = [
   120|            "ffmpeg", "-y",
   121|            "-ss", str(start),
   122|            "-i", audio_path,
   123|            "-t", str(chunk_duration),
   124|            "-acodec", "libmp3lame",
   125|            "-q:a", "2",
   126|            chunk_path,
   127|        ]
   128|        subprocess.run(cmd, capture_output=True, text=True)
   129|
   130|        result = transcribe_file_local(chunk_path)
   131|
   132|        for seg in result["segments"]:
   133|            seg["start"] += time_offset
   134|            seg["end"] += time_offset
   135|            all_segments.append(seg)
   136|
   137|        for w in result["words"]:
   138|            w["start"] += time_offset
   139|            w["end"] += time_offset
   140|            all_words.append(w)
   141|
   142|        all_text.append(result["text"])
   143|        time_offset += chunk_duration
   144|
   145|        if os.path.exists(chunk_path):
   146|            os.remove(chunk_path)
   147|
   148|    return {
   149|        "text": " ".join(all_text),
   150|        "segments": all_segments,
   151|        "words": all_words,
   152|    }
   153|
   154|
   155|@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
   156|def transcribe_video(self, video_id: str):
   157|    """
   158|    Celery task: receive video_id, get audio path from DB,
   159|    transcribe with local faster-whisper, save transcript,
   160|    chain to score_virality.
   161|    """
   162|    def _run():
   163|        db = SessionLocal()
   164|            result = db.execute(select(Video).where(Video.id == video_id))
   165|            video = result.scalar_one_or_none()
   166|            if not video:
   167|                log.error("Video %s not found", video_id)
   168|                return
   169|
   170|            audio_path = video.download_path or ""
   171|            if not audio_path or not os.path.exists(audio_path):
   172|                log.error("Audio file not found: %s", audio_path)
   173|                video.status = "failed"
   174|                db.commit()
   175|                return
   176|
   177|            log.info("Transcribing video %s (audio: %s) with local Whisper", video_id, audio_path)
   178|
   179|            try:
   180|                transcript = transcribe_file_local(audio_path)
   181|            except Exception:
   182|                log.exception("Transcription failed for video %s", video_id)
   183|                self.retry(countdown=60)
   184|                return
   185|
   186|            # Save transcript to local file
   187|            transcript_dir = os.path.join("/tmp", "clipforge", "transcripts")
   188|            os.makedirs(transcript_dir, exist_ok=True)
   189|            transcript_path = os.path.join(transcript_dir, f"{video_id}.json")
   190|
   191|            with open(transcript_path, "w") as f:
   192|                json.dump(transcript, f, indent=2)
   193|
   194|            # Update video record
   195|            video.status = "transcribed"
   196|            video.transcript_path = transcript_path
   197|            db.commit()
   198|
   199|            log.info(
   200|                "Transcription complete for %s: %d segments, %d words",
   201|                video_id,
   202|                len(transcript.get("segments", [])),
   203|                len(transcript.get("words", [])),
   204|            )
   205|
   206|            # Chain to virality scoring
   207|            from backend.tasks.score_virality import score_virality
   208|            score_virality.delay(video_id)
   209|
   210|    _run()
   211|