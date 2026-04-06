"""
ClipForge — AI Analysis Router
Context-Aware Analysis™: show WHY a clip scored high, channel insights aggregation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, text


from backend.models.database import Clip, Video, Channel, SessionLocal

log = logging.getLogger("clipforge.analysis_router")

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/clip/{clip_id}")
def get_clip_analysis(clip_id: str, db = Depends(get_db)):
    """
    Full signal breakdown for a clip.
    Returns virality_signals with all scoring detail.
    """
    stmt = select(Clip).where(Clip.id == clip_id)
    result = db.execute(stmt)
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    signals = clip.virality_signals or {}

    # Compute per-platform fit scores
    hook_score = clip.hook_score or 0.0
    platform_fit = {
        "tiktok": round(min(10.0, hook_score * 1.1), 1),
        "shorts": round(min(10.0, hook_score * 0.97), 1),
        "reels": round(min(10.0, hook_score * 0.94), 1),
    }

    # Extract hook phrases found in virality signals
    hook_phrases = signals.get("hook_phrases_found", [])

    return {
        "overall_score": round(hook_score, 1),
        "llm_hook_score": round(signals.get("llm_score", 0.0), 1),
        "audio_energy_score": round(signals.get("energy_score", 0.0), 1),
        "hook_phrase_score": round(signals.get("hook_phrase_count", 0), 1),
        "signal_weights": {"llm": 0.5, "audio": 0.3, "phrases": 0.2},
        "hook_type": signals.get("hook_type", "general"),
        "why_viral": signals.get("why_viral", ""),
        "hook_phrases_found": hook_phrases,
        "audio_peaks": signals.get("audio_peaks", []),
        "estimated_reach": "high" if hook_score > 7 else ("medium" if hook_score > 4 else "low"),
        "platform_fit": platform_fit,
    }


@router.get("/channel/{channel_id}/insights")
def get_channel_insights(
    channel_id: str,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate analytics across all clips for a channel.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Get all clips for this channel's videos
    video_ids_stmt = select(Video.id).where(Video.channel_id == channel_id)
    video_ids_result = db.execute(video_ids_stmt)
    video_ids = [str(v) for v in video_ids_result.scalars().all()]

    if not video_ids:
        return {"error": "No videos found for channel"}

    # Get clips
    clips_stmt = (
        select(Clip)
        .where(Clip.video_id.in_(video_ids), Clip.created_at >= since)
        .order_by(Clip.created_at.desc())
    )
    clips_result = db.execute(clips_stmt)
    clips = clips_result.scalars().all()

    if not clips:
        return {"message": "No clips in this period"}

    # Compute aggregates
    hook_scores = [c.hook_score for c in clips if c.hook_score is not None]
    avg_score = round(sum(hook_scores) / len(hook_scores), 1) if hook_scores else 0.0

    # Hook type distribution
    hook_type_counts: dict[str, int] = {}
    for c in clips:
        signals = c.virality_signals or {}
        ht = signals.get("hook_type", "general")
        hook_type_counts[ht] = hook_type_counts.get(ht, 0) + 1

    # Published ratio
    published = sum(1 for c in clips if c.status in ("published", "ready"))
    total = len(clips)

    # Top 3 clips
    top3 = sorted(clips, key=lambda c: c.hook_score or 0, reverse=True)[:3]
    top3_data = [
        {
            "id": str(c.id),
            "hook_score": round(c.hook_score or 0, 1),
            "hook_text": c.hook_text or "",
            "created_at": c.created_at.isoformat(),
        }
        for c in top3
    ]

    return {
        "period_days": days,
        "total_clips": total,
        "published": published,
        "avg_hook_score": avg_score,
        "hook_type_distribution": hook_type_counts,
        "top_clips": top3_data,
        "score_trend": [
            {"date": c.created_at.strftime("%Y-%m-%d"), "score": round(c.hook_score or 0, 1)}
            for c in sorted(clips, key=lambda c: c.created_at)
        ],
    }
