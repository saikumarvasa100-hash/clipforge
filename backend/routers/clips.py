"""
ClipForge -- API Router: clips.py
Includes list, detail, download, delete, edit, caption style switch, and re-caption.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import Clip, PublishJob, Video, SessionLocal
from backend.models.schemas import ClipListResponse, ClipResponse

log = logging.getLogger("clipforge.clips_router")

router = APIRouter(prefix="/api/clips", tags=["clips"])


async def get_db() -> AsyncSession:
    async with SessionLocal() as db:
        yield db


class ClipEditRequest(BaseModel):
    trim_start: float = 0
    trim_end: float = 0
    edited_captions: Optional[List[Dict[str, Any]]] = None
    style_name: str = "classic"


class ReCaptionRequest(BaseModel):
    style_name: str


@router.get("", response_model=ClipListResponse)
async def list_clips(
    channel_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Clip)
    count_query = select(func.count(Clip.id))

    if status:
        query = query.where(Clip.status == status)
        count_query = count_query.where(Clip.status == status)
    if date_from:
        query = query.where(Clip.created_at >= date_from)
        count_query = count_query.where(Clip.created_at >= date_from)
    if date_to:
        query = query.where(Clip.created_at <= date_to)
        count_query = count_query.where(Clip.created_at <= date_to)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Clip.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    clips = result.scalars().all()

    return ClipListResponse(
        clips=[ClipResponse.model_validate(c) for c in clips],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{clip_id}", response_model=ClipResponse)
async def get_clip(clip_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Clip).where(Clip.id == clip_id)
    result = await db.execute(stmt)
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip


@router.get("/{clip_id}/download")
async def download_clip(clip_id: str, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import RedirectResponse
    import os, boto3
    from botocore.config import Config

    stmt = select(Clip).where(Clip.id == clip_id)
    result = await db.execute(stmt)
    clip = result.scalar_one_or_none()
    if not clip or not clip.storage_url:
        raise HTTPException(status_code=404, detail="Clip or storage URL not found")

    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.getenv('CLOUDFLARE_R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
            aws_access_key_id=os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", ""),
            config=Config(signature_version="s3v4"),
        )
        key = clip.storage_url.split("/")[-1] if "/" in clip.storage_url else clip.storage_url
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": os.getenv("CLOUDFLARE_R2_BUCKET_NAME", ""), "Key": key},
            ExpiresIn=3600,
        )
        return RedirectResponse(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{clip_id}", status_code=204)
async def delete_clip(clip_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Clip).where(Clip.id == clip_id)
    result = await db.execute(stmt)
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    pj_stmt = select(PublishJob).where(PublishJob.clip_id == clip_id)
    pj_result = await db.execute(pj_stmt)
    for pj in pj_result.scalars().all():
        await db.delete(pj)
    await db.delete(clip)
    await db.commit()
    log.info("Clip deleted: %s", clip_id)


@router.post("/{clip_id}/edit", status_code=202)
async def edit_clip(
    clip_id: str, data: ClipEditRequest, db: AsyncSession = Depends(get_db)
):
    """
    Re-render a clip with new trim times, edited captions, and/or new style.
    Enqueues a Celery re_render_clip task.
    """
    stmt = select(Clip).where(Clip.id == clip_id)
    result = await db.execute(stmt)
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Default trim to full range if not specified
    trim_start = data.trim_start if data.trim_start > 0 else 0
    trim_end = data.trim_end if data.trim_end > 0 else (clip.end_time - clip.start_time)

    from backend.tasks.re_render_clip import re_render_clip

    task = re_render_clip.delay(
        clip_id=str(clip.id),
        trim_start=trim_start,
        trim_end=trim_end,
        edited_captions=data.edited_captions,
        style_name=data.style_name,
    )

    log.info("Clip edit enqueued: %s -> task %s", clip_id, task.id)
    return {"task_id": task.id, "status": "queued"}


@router.post("/{clip_id}/re-caption", status_code=200)
async def re_caption_clip(
    clip_id: str, data: ReCaptionRequest, db: AsyncSession = Depends(get_db)
):
    """
    Re-burn captions with a different style, keeping existing trim.
    """
    from backend.tasks.re_render_clip import re_render_clip

    task = re_render_clip.delay(
        clip_id=clip_id,
        trim_start=0,
        trim_end=0,
        edited_captions=None,
        style_name=data.style_name,
    )
    return {"task_id": task.id, "status": "queued"}


@router.post("/{clip_id}/hashtags", status_code=200)
async def generate_clip_hashtags(
    clip_id: str, platform: str = "tiktok", db: AsyncSession = Depends(get_db)
):
    """Generate AI-powered hashtags for a clip on a specific platform."""
    from backend.services.hashtag_service import generate_hashtags

    stmt = select(Clip).where(Clip.id == clip_id)
    result = await db.execute(stmt)
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    hashtags = await generate_hashtags(
        hook_text=clip.hook_text or "",
        transcript_segment=clip.hook_text or "",
        platform=platform,
        clip_id=str(clip.id),
    )

    # Store in clip's virality_signals
    if clip.virality_signals is None:
        clip.virality_signals = {}
    clip.virality_signals["hashtags"] = hashtags
    await db.commit()

    return hashtags
