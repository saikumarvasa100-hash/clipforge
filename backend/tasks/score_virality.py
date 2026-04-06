"""
ClipForge -- Virality Scoring Engine (CORE IP)
Multi-signal scoring: LLM hook analysis + audio energy peaks + hook phrase detection.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import List, Dict, Any, Optional

import numpy as np

from backend.celery_app import celery_app
from backend.models.database import Clip, Video, SessionLocal, ClipStatus
from sqlalchemy import select, text

log = logging.getLogger("clipforge.score_virality")

# ── Weighted scoring ─────────────────────────────────────────────────

LLM_WEIGHT = 0.5
AUDIO_WEIGHT = 0.3
PHRASE_WEIGHT = 0.2

HOOK_PHRASES = [
    r"nobody knows", r"secret", r"truth about", r"they don't want",
    r"plot twist", r"here's why", r"i was wrong", r"changed my life",
    r"biggest mistake", r"how i", r"step by step", r"warning",
    r"don't do this", r"nobody talks about", r"here's the truth",
    r"wait for it",
]

# ── Signal 1: LLM Hook Scoring ───────────────────────────────────────

LLM_SYSTEM_PROMPT = (
    "You are a viral short-form content strategist with 10 years of experience "
    "editing for TikTok, YouTube Shorts, and Instagram Reels. You have analyzed "
    "100,000+ viral clips and know exactly what makes people stop scrolling.\n\n"
    "Analyze this transcript and identify the 5 best segments (45-90 seconds "
    "each) that would perform best as standalone short-form clips.\n\n"
    "For each segment return:\n"
    "- start_time (seconds, float)\n"
    "- end_time (seconds, float)\n"
    "- hook_score (0.0-10.0)\n"
    "- hook_text (the first sentence that would appear on screen)\n"
    "- hook_type (story|controversy|insight|humor|transformation|tutorial)\n"
    "- why_viral (one sentence explanation)\n\n"
    "Prioritize segments with:\n"
    "1. Strong opening hook in first 5 seconds (question, bold claim, surprising fact)\n"
    "2. Emotional peaks (surprise, humor, conflict, inspiration)\n"
    "3. Re-engagement phrases: 'nobody talks about this', 'here's the truth', "
    "'I was wrong', 'wait for it', 'plot twist'\n"
    "4. Complete narrative arc (setup -> conflict -> payoff)\n"
    "5. No dead air, no intros, no outros\n\n"
    "Return ONLY valid JSON array. No markdown. No explanation."
)


async def call_llm_scoring(transcript_text: str) -> Optional[List[Dict]]:
    """Call GPT-4o-mini to score transcript segments for virality."""
    import openai
    import json as json_mod

    client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": LLM_SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript:\n{transcript_text}"},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown code block if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines)

        segments = json_mod.loads(raw)
        if isinstance(segments, list):
            log.info("LLM returned %d segments", len(segments))
            return segments
    except Exception:
        log.exception("LLM scoring failed")

    return None


# ── Signal 2: Audio Energy Peaks ─────────────────────────────────────

def compute_audio_energy(audio_path: str) -> tuple:
    """
    Use librosa to compute RMS energy per frame and find peaks.
    Returns (rms_array, sample_rate, peak_indices).
    """
    import librosa
    from scipy.signal import find_peaks

    y, sr = librosa.load(audio_path, sr=None, mono=True)
    frame_length = 2048
    hop_length = 512

    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    peaks, _ = find_peaks(rms, height=np.mean(rms), distance=5)

    return rms, sr / hop_length, peaks  # rms, frames_per_sec, peak_indices


def score_segment_energy(
    start_time: float,
    end_time: float,
    rms: np.ndarray,
    frames_per_sec: float,
    peaks: np.ndarray,
) -> float:
    """
    Score a time segment by how many energy peaks it contains.
    Normalised 0-10 scale.
    """
    start_frame = int(start_time * frames_per_sec)
    end_frame = int(end_time * frames_per_sec)

    segment_frames = end_frame - start_frame
    if segment_frames <= 0:
        return 0.0

    # Count peaks in this segment
    peak_mask = (peaks >= start_frame) & (peaks < end_frame)
    peak_count = int(peak_mask.sum())

    # Average energy in the segment
    segment_rms = rms[start_frame:end_frame]
    if len(segment_rms) == 0:
        return 0.0

    avg_energy = segment_rms.mean()
    overall_avg = rms.mean()

    # Combine peak count and energy
    energy_ratio = avg_energy / overall_avg if overall_avg > 0 else 0
    score = min(10.0, (peak_count * 2) + (energy_ratio * 5))
    return score


# ── Signal 3: Hook Phrase Detection ──────────────────────────────────

def score_hook_phrases(transcript_text: str) -> int:
    """Count how many viral hook phrases appear in the transcript."""
    text_lower = transcript_text.lower()
    score = 0
    for pattern in HOOK_PHRASES:
        matches = re.findall(pattern, text_lower)
        score += len(matches)
    return score


def score_segment_phrases(
    transcript_text: str,
    start_time: float,
    end_time: float,
    words: List[Dict[str, Any]],
) -> int:
    """Count hook phrases within a specific time segment."""
    segment_words = [
        w["word"] for w in words
        if start_time <= w.get("start", 0) <= end_time
    ]
    segment_text = " ".join(segment_words).lower()

    score = 0
    for pattern in HOOK_PHRASES:
        matches = re.findall(pattern, segment_text)
        score += len(matches)
    return score


# ── Main Celery Task ─────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def score_virality(self, video_id: str):
    """
    Score all segments of a video's transcript for virality.
    Creates Clip records for the top 4 segments.
    """
    import asyncio
    import os

    async def _run():
        async with SessionLocal() as db:
            # Load video + transcript
            result = await db.execute(
                select(Video).where(Video.id == video_id)
            )
            video = result.scalar_one_or_none()
            if not video:
                log.error("Video %s not found for scoring", video_id)
                return

            # Load transcript
            transcript_path = video.transcript_path
            transcript = {}
            try:
                # Try local file first
                if transcript_path and os.path.exists(transcript_path):
                    with open(transcript_path) as f:
                        transcript = json.load(f)
            except Exception:
                log.warning("Could not load transcript from %s", transcript_path)

            transcript_text = transcript.get("text", "")
            words = transcript.get("words", [])
            audio_path = video.download_path or ""

            if not transcript_text:
                log.error("Empty transcript for video %s", video_id)
                video.status = "failed"
                await db.commit()
                return

            log.info("Scoring virality for video %s (transcript %d chars)", video_id, len(transcript_text))

            # ── Signal 1: LLM Scoring ────────────────────────────────
            llm_segments = await call_llm_scoring(transcript_text) or []
            llm_scores = {i: s.get("hook_score", 5.0) for i, s in enumerate(llm_segments)}
            max_llm = max(llm_scores.values()) if llm_scores else 1.0

            # ── Signal 2: Audio Energy ───────────────────────────────
            try:
                rms, fps, peaks = compute_audio_energy(audio_path)
            except Exception:
                log.exception("Audio energy computation failed")
                rms, fps, peaks = np.array([]), 1.0, np.array([])

            # ── Signal 3: Hook Phrases ───────────────────────────────
            total_phrase_matches = score_hook_phrases(transcript_text)
            phrase_score_cap = max(total_phrase_matches, 1)

            # ── Compute final scores ─────────────────────────────────
            scored_segments = []
            for i, seg in enumerate(llm_segments):
                start = seg.get("start_time", 0.0)
                end = seg.get("end_time", 0.0)

                llm_norm = llm_scores.get(i, 5.0) / max_llm

                energy_score = score_segment_energy(start, end, rms, fps, peaks)
                energy_norm = min(energy_score / 10.0, 1.0)

                phrase_count = score_segment_phrases(transcript_text, start, end, words)
                phrase_norm = min(phrase_count / phrase_score_cap, 1.0) if phrase_score_cap > 0 else 0.0

                final_score = (llm_norm * LLM_WEIGHT) + (energy_norm * AUDIO_WEIGHT) + (phrase_norm * PHRASE_WEIGHT)
                final_score_10 = round(final_score * 10, 2)  # 0-10 scale

                scored_segments.append({
                    "segment": seg,
                    "llm_score_raw": llm_scores.get(i, 5.0),
                    "energy_score": round(energy_score, 2),
                    "phrase_count": phrase_count,
                    "final_score": final_score_10,
                })

            # Sort by final score, pick top 4
            scored_segments.sort(key=lambda x: x["final_score"], reverse=True)
            top_segments = scored_segments[:4]

            log.info("Top %d segments selected (scores: %s)", len(top_segments), [s["final_score"] for s in top_segments])

            # Save Clips to DB
            clip_ids = []
            for item in top_segments:
                seg = item["segment"]
                clip = Clip(
                    video_id=video.id,
                    user_id=None,  # will be set when user is known
                    start_time=seg.get("start_time", 0.0),
                    end_time=seg.get("end_time", 0.0),
                    hook_score=item["final_score"],
                    hook_text=seg.get("hook_text", ""),
                    status=ClipStatus.PENDING,
                    virality_signals={
                        "llm_score": item["llm_score_raw"],
                        "energy_score": item["energy_score"],
                        "hook_phrase_count": item["phrase_count"],
                        "hook_type": seg.get("hook_type", "general"),
                        "why_viral": seg.get("why_viral", ""),
                    },
                )
                db.add(clip)
                clip_ids.append(str(clip.id))

            video.status = "done"
            await db.commit()
            log.info("Created %d clips for video %s: %s", len(clip_ids), video_id, clip_ids)

            # Chain to cut_clips
            from backend.tasks.cut_clips import cut_clips_for_video
            cut_clips_for_video.delay(video_id)

    asyncio.run(_run())
