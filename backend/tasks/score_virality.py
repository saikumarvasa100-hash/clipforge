     1|"""
     2|ClipForge -- Virality Scoring Engine (100% SELF-HOSTED)
     3|HERMES bridge replaces OpenAI GPT. Local heuristics + free models.
     4|"""
     5|from __future__ import annotations
     6|
     7|     8|import json
     9|import logging
    10|import os
    11|import re
    12|from typing import List, Dict, Any, Optional
    13|
    14|import numpy as np
    15|
    16|from backend.celery_app import celery_app
    17|from backend.models.database import Clip, Video, SessionLocal, ClipStatus
    18|from backend.hermes_bridge import get_bridge
    19|from sqlalchemy import select
    20|
    21|log = logging.getLogger("clipforge.score_virality")
    22|
    23|# ── Weighted scoring ─────────────────────────────────────────────────
    24|LLM_WEIGHT = 0.4       # Reduced — HERMES free models are good but heuristic is reliable
    25|AUDIO_WEIGHT = 0.3
    26|PHRASE_WEIGHT = 0.2
    27|STRUCTURE_WEIGHT = 0.1  # New: local structural analysis
    28|
    29|HOOK_PHRASES = [
    30|    r"nobody knows", r"secret", r"truth about", r"they don't want",
    31|    r"plot twist", r"here's why", r"i was wrong", r"changed my life",
    32|    r"biggest mistake", r"how i", r"step by step", r"warning",
    33|    r"don't do this", r"nobody talks about", r"here's the truth",
    34|    r"wait for it", r"let me tell you", "i'm going to show you",
    35|    r"did you know", r"this will blow your mind", r"you won't believe",
    36|]
    37|
    38|CONTRARIAN_HOOKS = [
    39|    r"stop ", r"don't ", r"never ", r"wrong", r"lying",
    40|    r"scam", r"overrated", r"waste", r"mistake", r"bad idea",
    41|]
    42|
    43|EMOTION_WORDS = [
    44|    r"love", r"amazing", r"insane", r"crazy", r"unbelievable",
    45|    r"perfect", r"terrible", r"awful", r"incredible", r"shocking",
    46|    r"surprised", r"discovered", r"exposed", r"destroyed", r"transformed",
    47|]
    48|
    49|
    50|# ── Signal 1: HERMES LLM Scoring ─────────────────────────────────────
    51|
    52|LLM_SYSTEM_PROMPT = (
    53|    "You are a viral short-form content strategist. Analyze this transcript "
    54|    "and identify the 5 best segments (45-90 seconds each) for short-form clips.\n\n"
    55|    "For each segment return JSON with: start_time, end_time, hook_score (0-10), "
    56|    "hook_text, hook_type (story|controversy|insight|humor|transformation|tutorial), "
    57|    "why_viral.\n\n"
    58|    "Prioritize: strong opening hooks in first 5 seconds, emotional peaks, "
    59|    "re-engagement phrases, complete narrative arcs, no dead air. "
    60|    "Return ONLY valid JSON array."
    61|)
    62|
    63|
    64|async def call_llm_scoring(transcript_text: str) -> Optional[List[Dict]]:
    65|    """Call HERMES bridge (OpenRouter free models) for LLM analysis."""
    66|    bridge = get_bridge()
    67|
    68|    # Keep context manageable — first 8000 chars of transcript
    69|    context = transcript_text[:8000]
    70|
    71|    result = await bridge.chat_json(
    72|        system_prompt=LLM_SYSTEM_PROMPT,
    73|        user_prompt=f"Transcript:\n{context}",
    74|        temperature=0.3,
    75|    )
    76|
    77|    if "error" in result:
    78|        log.warning("HERMES LLM scoring returned error: %s", result.get("error", ""))
    79|        return None
    80|
    81|    # Handle case where HERMES returns a dict with segments key vs direct array
    82|    if isinstance(result, list):
    83|        return result
    84|    if isinstance(result, dict) and "segments" in result:
    85|        return result["segments"]
    86|    # Check if it's a single segment dict — wrap it
    87|    if isinstance(result, dict) and "hook_score" in result:
    88|        return [result]
    89|
    90|    log.warning("Unexpected HERMES result type: %s", type(result))
    91|    return None
    92|
    93|
    94|# ── Signal 2: Audio Energy Peaks ─────────────────────────────────────
    95|
    96|def compute_audio_energy(audio_path: str) -> tuple:
    97|    """RMS energy + peak detection using librosa."""
    98|    import librosa
    99|    from scipy.signal import find_peaks
   100|
   101|    y, sr = librosa.load(audio_path, sr=None, mono=True)
   102|    frame_length = 2048
   103|    hop_length = 512
   104|    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
   105|    peaks, _ = find_peaks(rms, height=np.mean(rms), distance=5)
   106|    return rms, sr / hop_length, peaks
   107|
   108|
   109|def score_segment_energy(
   110|    start_time: float, end_time: float,
   111|    rms: np.ndarray, frames_per_sec: float, peaks: np.ndarray,
   112|) -> float:
   113|    start_frame = int(start_time * frames_per_sec)
   114|    end_frame = int(end_time * frames_per_sec)
   115|    if end_frame <= start_frame:
   116|        return 0.0
   117|
   118|    peak_mask = (peaks >= start_frame) & (peaks < end_frame)
   119|    peak_count = int(peak_mask.sum())
   120|    segment_rms = rms[start_frame:end_frame]
   121|    avg_energy = segment_rms.mean() if len(segment_rms) > 0 else 0
   122|    overall_avg = rms.mean() if rms.mean() > 0 else 1
   123|    return min(10.0, (peak_count * 2) + ((avg_energy / overall_avg) * 5))
   124|
   125|
   126|# ── Signal 3: Hook Phrase Detection ──────────────────────────────────
   127|
   128|def score_hook_phrases(transcript_text: str) -> int:
   129|    text_lower = transcript_text.lower()
   130|    return sum(len(re.findall(p, text_lower)) for p in HOOK_PHRASES)
   131|
   132|
   133|def score_segment_phrases(
   134|    transcript_text: str, start_time: float, end_time: float,
   135|    words: List[Dict[str, Any]],
   136|) -> int:
   137|    segment_words = [w["word"] for w in words if start_time <= w.get("start", 0) <= end_time]
   138|    segment_text = " ".join(segment_words).lower()
   139|    return sum(len(re.findall(p, segment_text)) for p in HOOK_PHRASES)
   140|
   141|
   142|# ── Signal 4: Local Structural Analysis (no API needed) ──────────────
   143|
   144|def score_structure(transcript_text: str, start_time: float, end_time: float,
   145|                    words: List[Dict[str, Any]]) -> float:
   146|    """
   147|    Local heuristic scoring — zero API calls.
   148|    Analyzes structural markers of viral content.
   149|    """
   150|    segment_words = [w for w in words if start_time <= w.get("start", 0) <= end_time]
   151|    text = " ".join(w["word"] for w in segment_words).lower()
   152|    score = 5.0  # baseline
   153|
   154|    # Contrarian hooks get bonus
   155|    for p in CONTRARIAN_HOOKS:
   156|        if re.search(p, text):
   157|            score += 0.5
   158|
   159|    # Emotional words get bonus
   160|    for p in EMOTION_WORDS:
   161|        if re.search(p, text):
   162|            score += 0.3
   163|
   164|    # Optimal length (45-120 seconds)
   165|    duration = end_time - start_time
   166|    if 30 <= duration <= 120:
   167|        score += 1.0
   168|    elif duration < 15:
   169|        score -= 2.0
   170|
   171|    # First 3 seconds: check if hook words appear early
   172|    early_words = [w for w in segment_words if w.get("start", 0) - start_time < 3]
   173|    early_text = " ".join(w["word"] for w in early_words).lower()
   174|    for p in ["why", "how", "what", "stop", "don't", "never", "secret", "truth"]:
   175|        if p in early_text:
   176|            score += 0.5
   177|
   178|    return min(10.0, max(0.0, score))
   179|
   180|
   181|# ── Generate clip segments ───────────────────────────────────────────
   182|
   183|def _generate_segments(transcript_text: str, words: List[Dict],
   184|                       total_duration: float, target_count: int = 5):
   185|    """Generate candidate segments from transcript using structural markers."""
   186|    if not words:
   187|        # No word-level timestamps — create rough segments
   188|        return [
   189|            {"start_time": i * (total_duration / target_count),
   190|             "end_time": (i + 1) * (total_duration / target_count),
   191|             "hook_text": transcript_text[:100]}
   192|            for i in range(target_count)
   193|        ]
   194|
   195|    segments = []
   196|    # Find natural breaks: longer pauses between words
   197|    pauses = []
   198|    for i in range(1, len(words)):
   199|        gap = words[i].get("start", 0) - words[i - 1].get("end", 0)
   200|        pauses.append((i, gap))
   201|
   202|    # Sort pauses by gap size (largest gaps = natural segment boundaries)
   203|    pauses.sort(key=lambda x: x[1], reverse=True)
   204|
   205|    # Use top N-1 pauses as split points
   206|    split_indices = sorted([p[0] for p in pauses[:target_count - 1]])
   207|    boundaries = [0] + split_indices + [len(words)]
   208|
   209|    for i in range(len(boundaries) - 1):
   210|        seg_words = words[boundaries[i]:boundaries[i + 1]]
   211|        if not seg_words:
   212|            continue
   213|        seg_text = " ".join(w["word"] for w in seg_words)
   214|        duration = seg_words[-1].get("end", 0) - seg_words[0].get("start", 0)
   215|        if 15 < duration < 300:  # 15s to 5min
   216|            segments.append({
   217|                "start_time": seg_words[0].get("start", 0),
   218|                "end_time": seg_words[-1].get("end", 0),
   219|                "hook_text": seg_text[:200],
   220|                "duration": duration,
   221|            })
   222|
   223|    return segments
   224|
   225|
   226|# ── Main Celery Task ─────────────────────────────────────────────────
   227|
   228|@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
   229|def score_virality(self, video_id: str):
   230|    """
   231|    Score all segments of a video's transcript for virality.
   232|    Creates Clip records for the top 4 segments.
   233|    Uses HERMES free models + local analysis.
   234|    """
   235|    def _run():
   236|        db = SessionLocal()
   237|            result = db.execute(select(Video).where(Video.id == video_id))
   238|            video = result.scalar_one_or_none()
   239|            if not video:
   240|                log.error("Video %s not found for scoring", video_id)
   241|                return
   242|
   243|            # Load transcript
   244|            transcript = {}
   245|            transcript_path = video.transcript_path
   246|            if transcript_path and os.path.exists(transcript_path):
   247|                with open(transcript_path) as f:
   248|                    transcript = json.load(f)
   249|
   250|            transcript_text = transcript.get("text", "")
   251|            words = transcript.get("words", [])
   252|            audio_path = video.download_path or ""
   253|
   254|            if not transcript_text:
   255|                log.error("Empty transcript for video %s", video_id)
   256|                video.status = "failed"
   257|                db.commit()
   258|                return
   259|
   260|            log.info("Scoring virality (HERMES) for %s (%d chars)", video_id, len(transcript_text))
   261|
   262|            # ── Generate candidate segments from structure ──────────
   263|            candidates = _generate_segments(transcript_text, words,
   264|                                           video.duration_seconds or 600)
   265|
   266|            # ── Signal 1: HERMES LLM Scoring ──────────────────────
   267|            llm_segments = await call_llm_scoring(transcript_text) or []
   268|            llm_scores = {i: s.get("hook_score", 5.0) for i, s in enumerate(llm_segments)}
   269|            max_llm = max(llm_scores.values()) if llm_scores else 1.0
   270|
   271|            # ── Signal 2: Audio Energy ─────────────────────────────
   272|            try:
   273|                rms, fps, peaks = compute_audio_energy(audio_path)
   274|            except Exception:
   275|                log.exception("Audio energy failed")
   276|                rms, fps, peaks = np.array([]), 1.0, np.array([])
   277|
   278|            # ── Score all candidates ───────────────────────────────
   279|            scored_segments = []
   280|            total_phrase = max(score_hook_phrases(transcript_text), 1)
   281|
   282|            # Score LLM-provided segments
   283|            for i, seg in enumerate(llm_segments):
   284|                start = seg.get("start_time", 0.0)
   285|                end = seg.get("end_time", 0.0)
   286|                llm_norm = llm_scores.get(i, 5.0) / max_llm
   287|                energy = score_segment_energy(start, end, rms, fps, peaks) / 10.0
   288|                phrase = score_segment_phrases(transcript_text, start, end, words) / total_phrase
   289|                struct = score_structure(transcript_text, start, end, words) / 10.0
   290|
   291|                final = (llm_norm * LLM_WEIGHT + energy * AUDIO_WEIGHT +
   292|                         phrase * PHRASE_WEIGHT + struct * STRUCTURE_WEIGHT)
   293|                scored_segments.append({
   294|                    "segment": seg,
   295|                    "final_score": round(final * 10, 2),
   296|                    "signals": {"llm": round(llm_norm * 10, 1), "energy": round(energy * 10, 1),
   297|                                "phrases": round(phrase * 10, 1), "structure": round(struct * 10, 1)},
   298|                })
   299|
   300|            # Also score structural segments that LLM may have missed
   301|            for cand in candidates:
   302|                start = cand.get("start_time", 0.0)
   303|                end = cand.get("end_time", 0.0)
   304|                energy = score_segment_energy(start, end, rms, fps, peaks) / 10.0
   305|                phrase = score_segment_phrases(transcript_text, start, end, words) / total_phrase
   306|                struct = score_structure(transcript_text, start, end, words) / 10.0
   307|
   308|                final = (0.5 * (energy * AUDIO_WEIGHT + phrase * PHRASE_WEIGHT + struct * STRUCTURE_WEIGHT) / 0.6 +
   309|                         0.5 * struct)  # LLM weight redistributed
   310|                scored_segments.append({
   311|                    "segment": {"start_time": start, "end_time": end,
   312|                                "hook_text": cand.get("hook_text", ""),
   313|                                "hook_type": "general",
   314|                                "why_viral": "Structural analysis: natural pause boundary"},
   315|                    "final_score": round(final * 10, 2),
   316|                    "signals": {"llm": -1, "energy": round(energy * 10, 1),
   317|                                "phrases": round(phrase * 10, 1), "structure": round(struct * 10, 1)},
   318|                })
   319|
   320|            # Sort and select top 4
   321|            scored_segments.sort(key=lambda x: x["final_score"], reverse=True)
   322|            top_segments = scored_segments[:4]
   323|
   324|            log.info("Top %d segments: %s", len(top_segments),
   325|                     [s["final_score"] for s in top_segments])
   326|
   327|            # Save Clips to DB
   328|            for item in top_segments:
   329|                seg = item["segment"]
   330|                clip = Clip(
   331|                    video_id=video.id,
   332|                    user_id=None,
   333|                    start_time=seg.get("start_time", 0.0),
   334|                    end_time=seg.get("end_time", 0.0),
   335|                    hook_score=item["final_score"],
   336|                    hook_text=seg.get("hook_text", ""),
   337|                    status=ClipStatus.PENDING,
   338|                    virality_signals={
   339|                        **item["signals"],
   340|                        "hook_type": seg.get("hook_type", "general"),
   341|                        "why_viral": seg.get("why_viral", ""),
   342|                    },
   343|                )
   344|                db.add(clip)
   345|
   346|            video.status = "done"
   347|            db.commit()
   348|
   349|            # Chain to cut_clips
   350|            from backend.tasks.cut_clips import cut_clips_for_video
   351|            cut_clips_for_video.delay(video_id)
   352|
   353|    _run()
   354|