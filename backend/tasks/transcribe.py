"""
ClipForge -- Celery Task: Transcription
Local faster-whisper (no API cost). Replaces OpenAI Whisper API.

Uses the already-installed faster-whisper library with tiny/base/small/medium/large models.
Configurable via WHISPER_MODEL env var. Default: large-v3 (best quality).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Dict, List, Any

from backend.celery_app import celery_app
from backend.models.database import Video, SessionLocal
from sqlalchemy import select

log = logging.getLogger("clipforge.transcribe")

DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "base")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE", "float16")

_model = None
_model_name = None


def get_model():
    """Lazy-load the Whisper model (keeps it in memory for subsequent calls)."""
    global _model, _model_name
    if _model is None or _model_name != DEFAULT_MODEL:
        log.info("Loading faster-whisper model: %s (compute=%s)", DEFAULT_MODEL, COMPUTE_TYPE)
        from faster_whisper import WhisperModel
        _model = WhisperModel(DEFAULT_MODEL, compute_type=COMPUTE_TYPE)
        _model_name = DEFAULT_MODEL
        log.info("Whisper model loaded: %s", _model_name)
    return _model


def transcribe_file_local(audio_path: str) -> Dict[str, Any]:
    """
    Transcribe a local audio file using faster-whisper.
    Returns: {text, segments: [{start, end, text}], words: [{word, start, end}]}
    Word-level timestamps require word_timestamps=True (available in newer models).
    """
    model = get_model()

    # Handle files > 25MB by splitting (Whisper context limit ~half hour audio)
    file_size = os.path.getsize(audio_path)
    if file_size > 25 * 1024 * 1024:
        return _transcribe_chunked(audio_path)

    segments_gen, _ = model.transcribe(
        audio_path,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        word_timestamps=True,
    )

    segments = []
    words = []
    text_parts = []

    for seg in segments_gen:
        seg_dict = {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
        segments.append(seg_dict)
        text_parts.append(seg.text.strip())
        if seg.words:
            for w in seg.words:
                words.append({
                    "word": w.word,
                    "start": w.start,
                    "end": w.end,
                })

    return {
        "text": " ".join(text_parts),
        "segments": segments,
        "words": words,
    }


def _transcribe_chunked(audio_path: str) -> Dict[str, Any]:
    """Split large audio file into 24-minute chunks and merge results."""
    import subprocess

    chunks_dir = os.path.join("/tmp", "clipforge", "chunks")
    os.makedirs(chunks_dir, exist_ok=True)

    # Get duration via ffprobe
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        duration = float(proc.stdout.strip())
    except (ValueError, TypeError):
        duration = 0.0

    chunk_duration = 24 * 60  # 24 minutes
    num_chunks = max(1, int(duration / chunk_duration) + 1)

    log.info("Splitting %.0fs audio into %d chunks", duration, num_chunks)

    all_text = []
    all_segments = []
    all_words = []
    time_offset = 0.0

    for i in range(num_chunks):
        start = i * chunk_duration
        chunk_path = os.path.join(chunks_dir, f"chunk_{i:03d}.mp3")

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", audio_path,
            "-t", str(chunk_duration),
            "-acodec", "libmp3lame",
            "-q:a", "2",
            chunk_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True)

        result = transcribe_file_local(chunk_path)

        for seg in result["segments"]:
            seg["start"] += time_offset
            seg["end"] += time_offset
            all_segments.append(seg)

        for w in result["words"]:
            w["start"] += time_offset
            w["end"] += time_offset
            all_words.append(w)

        all_text.append(result["text"])
        time_offset += chunk_duration

        if os.path.exists(chunk_path):
            os.remove(chunk_path)

    return {
        "text": " ".join(all_text),
        "segments": all_segments,
        "words": all_words,
    }


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def transcribe_video(self, video_id: str):
    """
    Celery task: receive video_id, get audio path from DB,
    transcribe with local faster-whisper, save transcript,
    chain to score_virality.
    """
    async def _run():
        async with SessionLocal() as db:
            result = await db.execute(select(Video).where(Video.id == video_id))
            video = result.scalar_one_or_none()
            if not video:
                log.error("Video %s not found", video_id)
                return

            audio_path = video.download_path or ""
            if not audio_path or not os.path.exists(audio_path):
                log.error("Audio file not found: %s", audio_path)
                video.status = "failed"
                await db.commit()
                return

            log.info("Transcribing video %s (audio: %s) with local Whisper", video_id, audio_path)

            try:
                transcript = transcribe_file_local(audio_path)
            except Exception:
                log.exception("Transcription failed for video %s", video_id)
                self.retry(countdown=60)
                return

            # Save transcript to local file
            transcript_dir = os.path.join("/tmp", "clipforge", "transcripts")
            os.makedirs(transcript_dir, exist_ok=True)
            transcript_path = os.path.join(transcript_dir, f"{video_id}.json")

            with open(transcript_path, "w") as f:
                json.dump(transcript, f, indent=2)

            # Update video record
            video.status = "transcribed"
            video.transcript_path = transcript_path
            await db.commit()

            log.info(
                "Transcription complete for %s: %d segments, %d words",
                video_id,
                len(transcript.get("segments", [])),
                len(transcript.get("words", [])),
            )

            # Chain to virality scoring
            from backend.tasks.score_virality import score_virality
            score_virality.delay(video_id)

    asyncio.run(_run())
