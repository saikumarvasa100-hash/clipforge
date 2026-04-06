"""
ClipForge -- Virality Scoring Engine (100% SELF-HOSTED)
HERMES bridge replaces OpenAI GPT. Local heuristics + free models.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import List, Dict, Any, Optional

import numpy as np

from backend.celery_app import celery_app
from backend.models.database import Clip, Video, SessionLocal, ClipStatus
from backend.hermes_bridge import get_bridge
from sqlalchemy import select

log = logging.getLogger("clipforge.score_virality")

# ── Weighted scoring ─────────────────────────────────────────────────
LLM_WEIGHT = 0.4       # Reduced — HERMES free models are good but heuristic is reliable
AUDIO_WEIGHT = 0.3
PHRASE_WEIGHT = 0.2
STRUCTURE_WEIGHT = 0.1  # New: local structural analysis

HOOK_PHRASES = [
    r"nobody knows", r"secret", r"truth about", r"they don't want",
    r"plot twist", r"here's why", r"i was wrong", r"changed my life",
    r"biggest mistake", r"how i", r"step by step", r"warning",
    r"don't do this", r"nobody talks about", r"here's the truth",
    r"wait for it", r"let me tell you", "i'm going to show you",
    r"did you know", r"this will blow your mind", r"you won't believe",
]

CONTRARIAN_HOOKS = [
    r"stop ", r"don't ", r"never ", r"wrong", r"lying",
    r"scam", r"overrated", r"waste", r"mistake", r"bad idea",
]

EMOTION_WORDS = [
    r"love", r"amazing", r"insane", r"crazy", r"unbelievable",
    r"perfect", r"terrible", r"awful", r"incredible", r"shocking",
    r"surprised", r"discovered", r"exposed", r"destroyed", r"transformed",
]


# ── Signal 1: HERMES LLM Scoring ─────────────────────────────────────

LLM_SYSTEM_PROMPT = (
    "You are a viral short-form content strategist. Analyze this transcript "
    "and identify the 5 best segments (45-90 seconds each) for short-form clips.\n\n"
    "For each segment return JSON with: start_time, end_time, hook_score (0-10), "
    "hook_text, hook_type (story|controversy|insight|humor|transformation|tutorial), "
    "why_viral.\n\n"
    "Prioritize: strong opening hooks in first 5 seconds, emotional peaks, "
    "re-engagement phrases, complete narrative arcs, no dead air. "
    "Return ONLY valid JSON array."
)


async def call_llm_scoring(transcript_text: str) -> Optional[List[Dict]]:
    """Call HERMES bridge (OpenRouter free models) for LLM analysis."""
    bridge = get_bridge()

    # Keep context manageable — first 8000 chars of transcript
    context = transcript_text[:8000]

    result = await bridge.chat_json(
        system_prompt=LLM_SYSTEM_PROMPT,
        user_prompt=f"Transcript:\n{context}",
        temperature=0.3,
    )

    if "error" in result:
        log.warning("HERMES LLM scoring returned error: %s", result.get("error", ""))
        return None

    # Handle case where HERMES returns a dict with segments key vs direct array
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and "segments" in result:
        return result["segments"]
    # Check if it's a single segment dict — wrap it
    if isinstance(result, dict) and "hook_score" in result:
        return [result]

    log.warning("Unexpected HERMES result type: %s", type(result))
    return None


# ── Signal 2: Audio Energy Peaks ─────────────────────────────────────

def compute_audio_energy(audio_path: str) -> tuple:
    """RMS energy + peak detection using librosa."""
    import librosa
    from scipy.signal import find_peaks

    y, sr = librosa.load(audio_path, sr=None, mono=True)
    frame_length = 2048
    hop_length = 512
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    peaks, _ = find_peaks(rms, height=np.mean(rms), distance=5)
    return rms, sr / hop_length, peaks


def score_segment_energy(
    start_time: float, end_time: float,
    rms: np.ndarray, frames_per_sec: float, peaks: np.ndarray,
) -> float:
    start_frame = int(start_time * frames_per_sec)
    end_frame = int(end_time * frames_per_sec)
    if end_frame <= start_frame:
        return 0.0

    peak_mask = (peaks >= start_frame) & (peaks < end_frame)
    peak_count = int(peak_mask.sum())
    segment_rms = rms[start_frame:end_frame]
    avg_energy = segment_rms.mean() if len(segment_rms) > 0 else 0
    overall_avg = rms.mean() if rms.mean() > 0 else 1
    return min(10.0, (peak_count * 2) + ((avg_energy / overall_avg) * 5))


# ── Signal 3: Hook Phrase Detection ──────────────────────────────────

def score_hook_phrases(transcript_text: str) -> int:
    text_lower = transcript_text.lower()
    return sum(len(re.findall(p, text_lower)) for p in HOOK_PHRASES)


def score_segment_phrases(
    transcript_text: str, start_time: float, end_time: float,
    words: List[Dict[str, Any]],
) -> int:
    segment_words = [w["word"] for w in words if start_time <= w.get("start", 0) <= end_time]
    segment_text = " ".join(segment_words).lower()
    return sum(len(re.findall(p, segment_text)) for p in HOOK_PHRASES)


# ── Signal 4: Local Structural Analysis (no API needed) ──────────────

def score_structure(transcript_text: str, start_time: float, end_time: float,
                    words: List[Dict[str, Any]]) -> float:
    """
    Local heuristic scoring — zero API calls.
    Analyzes structural markers of viral content.
    """
    segment_words = [w for w in words if start_time <= w.get("start", 0) <= end_time]
    text = " ".join(w["word"] for w in segment_words).lower()
    score = 5.0  # baseline

    # Contrarian hooks get bonus
    for p in CONTRARIAN_HOOKS:
        if re.search(p, text):
            score += 0.5

    # Emotional words get bonus
    for p in EMOTION_WORDS:
        if re.search(p, text):
            score += 0.3

    # Optimal length (45-120 seconds)
    duration = end_time - start_time
    if 30 <= duration <= 120:
        score += 1.0
    elif duration < 15:
        score -= 2.0

    # First 3 seconds: check if hook words appear early
    early_words = [w for w in segment_words if w.get("start", 0) - start_time < 3]
    early_text = " ".join(w["word"] for w in early_words).lower()
    for p in ["why", "how", "what", "stop", "don't", "never", "secret", "truth"]:
        if p in early_text:
            score += 0.5

    return min(10.0, max(0.0, score))


# ── Generate clip segments ───────────────────────────────────────────

def _generate_segments(transcript_text: str, words: List[Dict],
                       total_duration: float, target_count: int = 5):
    """Generate candidate segments from transcript using structural markers."""
    if not words:
        # No word-level timestamps — create rough segments
        return [
            {"start_time": i * (total_duration / target_count),
             "end_time": (i + 1) * (total_duration / target_count),
             "hook_text": transcript_text[:100]}
            for i in range(target_count)
        ]

    segments = []
    # Find natural breaks: longer pauses between words
    pauses = []
    for i in range(1, len(words)):
        gap = words[i].get("start", 0) - words[i - 1].get("end", 0)
        pauses.append((i, gap))

    # Sort pauses by gap size (largest gaps = natural segment boundaries)
    pauses.sort(key=lambda x: x[1], reverse=True)

    # Use top N-1 pauses as split points
    split_indices = sorted([p[0] for p in pauses[:target_count - 1]])
    boundaries = [0] + split_indices + [len(words)]

    for i in range(len(boundaries) - 1):
        seg_words = words[boundaries[i]:boundaries[i + 1]]
        if not seg_words:
            continue
        seg_text = " ".join(w["word"] for w in seg_words)
        duration = seg_words[-1].get("end", 0) - seg_words[0].get("start", 0)
        if 15 < duration < 300:  # 15s to 5min
            segments.append({
                "start_time": seg_words[0].get("start", 0),
                "end_time": seg_words[-1].get("end", 0),
                "hook_text": seg_text[:200],
                "duration": duration,
            })

    return segments


# ── Main Celery Task ─────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def score_virality(self, video_id: str):
    """
    Score all segments of a video's transcript for virality.
    Creates Clip records for the top 4 segments.
    Uses HERMES free models + local analysis.
    """
    async def _run():
        async with SessionLocal() as db:
            result = await db.execute(select(Video).where(Video.id == video_id))
            video = result.scalar_one_or_none()
            if not video:
                log.error("Video %s not found for scoring", video_id)
                return

            # Load transcript
            transcript = {}
            transcript_path = video.transcript_path
            if transcript_path and os.path.exists(transcript_path):
                with open(transcript_path) as f:
                    transcript = json.load(f)

            transcript_text = transcript.get("text", "")
            words = transcript.get("words", [])
            audio_path = video.download_path or ""

            if not transcript_text:
                log.error("Empty transcript for video %s", video_id)
                video.status = "failed"
                await db.commit()
                return

            log.info("Scoring virality (HERMES) for %s (%d chars)", video_id, len(transcript_text))

            # ── Generate candidate segments from structure ──────────
            candidates = _generate_segments(transcript_text, words,
                                           video.duration_seconds or 600)

            # ── Signal 1: HERMES LLM Scoring ──────────────────────
            llm_segments = await call_llm_scoring(transcript_text) or []
            llm_scores = {i: s.get("hook_score", 5.0) for i, s in enumerate(llm_segments)}
            max_llm = max(llm_scores.values()) if llm_scores else 1.0

            # ── Signal 2: Audio Energy ─────────────────────────────
            try:
                rms, fps, peaks = compute_audio_energy(audio_path)
            except Exception:
                log.exception("Audio energy failed")
                rms, fps, peaks = np.array([]), 1.0, np.array([])

            # ── Score all candidates ───────────────────────────────
            scored_segments = []
            total_phrase = max(score_hook_phrases(transcript_text), 1)

            # Score LLM-provided segments
            for i, seg in enumerate(llm_segments):
                start = seg.get("start_time", 0.0)
                end = seg.get("end_time", 0.0)
                llm_norm = llm_scores.get(i, 5.0) / max_llm
                energy = score_segment_energy(start, end, rms, fps, peaks) / 10.0
                phrase = score_segment_phrases(transcript_text, start, end, words) / total_phrase
                struct = score_structure(transcript_text, start, end, words) / 10.0

                final = (llm_norm * LLM_WEIGHT + energy * AUDIO_WEIGHT +
                         phrase * PHRASE_WEIGHT + struct * STRUCTURE_WEIGHT)
                scored_segments.append({
                    "segment": seg,
                    "final_score": round(final * 10, 2),
                    "signals": {"llm": round(llm_norm * 10, 1), "energy": round(energy * 10, 1),
                                "phrases": round(phrase * 10, 1), "structure": round(struct * 10, 1)},
                })

            # Also score structural segments that LLM may have missed
            for cand in candidates:
                start = cand.get("start_time", 0.0)
                end = cand.get("end_time", 0.0)
                energy = score_segment_energy(start, end, rms, fps, peaks) / 10.0
                phrase = score_segment_phrases(transcript_text, start, end, words) / total_phrase
                struct = score_structure(transcript_text, start, end, words) / 10.0

                final = (0.5 * (energy * AUDIO_WEIGHT + phrase * PHRASE_WEIGHT + struct * STRUCTURE_WEIGHT) / 0.6 +
                         0.5 * struct)  # LLM weight redistributed
                scored_segments.append({
                    "segment": {"start_time": start, "end_time": end,
                                "hook_text": cand.get("hook_text", ""),
                                "hook_type": "general",
                                "why_viral": "Structural analysis: natural pause boundary"},
                    "final_score": round(final * 10, 2),
                    "signals": {"llm": -1, "energy": round(energy * 10, 1),
                                "phrases": round(phrase * 10, 1), "structure": round(struct * 10, 1)},
                })

            # Sort and select top 4
            scored_segments.sort(key=lambda x: x["final_score"], reverse=True)
            top_segments = scored_segments[:4]

            log.info("Top %d segments: %s", len(top_segments),
                     [s["final_score"] for s in top_segments])

            # Save Clips to DB
            for item in top_segments:
                seg = item["segment"]
                clip = Clip(
                    video_id=video.id,
                    user_id=None,
                    start_time=seg.get("start_time", 0.0),
                    end_time=seg.get("end_time", 0.0),
                    hook_score=item["final_score"],
                    hook_text=seg.get("hook_text", ""),
                    status=ClipStatus.PENDING,
                    virality_signals={
                        **item["signals"],
                        "hook_type": seg.get("hook_type", "general"),
                        "why_viral": seg.get("why_viral", ""),
                    },
                )
                db.add(clip)

            video.status = "done"
            await db.commit()

            # Chain to cut_clips
            from backend.tasks.cut_clips import cut_clips_for_video
            cut_clips_for_video.delay(video_id)

    asyncio.run(_run())
