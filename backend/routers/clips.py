"""
ClipForge -- API Router: clips.py
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import Clip, PublishJob, SessionLocal
from backend.models.schemas import ClipListResponse, ClipResponse

log = logging.getLogger("clipforge.clips_router")

router = APIRouter(prefix="/api/clips", tags=["clips"])


async def get_db() -> AsyncSession:
    async with SessionLocal() as db:
        yield db


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
    """List clips with optional filters, paginated."""
    stmt = select(Clip)
    count_stmt = select(func.count(Clip.id))

    if channel_id:
        stmt = stmt.where(Clip.video_id.in_(
            select(Clip.video_id).where(Clip.video_id == channel_id)
        ))  # simplified -- normally join with Video
    if status:
        stmt = stmt.where(Clip.status == status)
    if date_from:
        stmt = stmt.where(Clip.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Clip.created_at <= date_to)

    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = (
        stmt.order_by(Clip.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    clips = result.scalars().all()

    return ClipListResponse(
        clips=[ClipResponse.model_validate(c) for c in clips],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{clip_id}", response_model=ClipResponse)
async def get_clip(clip_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single clip's detail with virality signals."""
    stmt = select(Clip).where(Clip.id == clip_id)
    result = await db.execute(stmt)
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip


@router.get("/{clip_id}/download")
async def download_clip(clip_id: str, db: AsyncSession = Depends(get_db)):
    """Redirect to a signed Cloudflare R2 URL for the clip."""
    from botocore.config import Config
    import os
    import boto3

    stmt = select(Clip).where(Clip.id == clip_id)
    result = await db.execute(stmt)
    clip = result.scalar_one_or_none()
    if not clip or not clip.storage_url:
        raise HTTPException(status_code=404, detail="Clip or storage URL not found")

    # Generate presigned R2 URL
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.getenv('CLOUDFLARE_R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
            aws_access_key_id=os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", ""),
            config=Config(signature_version="s3v4"),
        )
        key = clip.storage_url.split("/")[-1]
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": os.getenv("CLOUDFLARE_R2_BUCKET_NAME", ""), "Key": key},
            ExpiresIn=3600,
        )
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url)
    except Exception as e:
        log.exception("Failed to generate presigned URL")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{clip_id}", status_code=204)
async def delete_clip(clip_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a clip and its publish jobs."""
    stmt = select(Clip).where(Clip.id == clip_id)
    result = await db.execute(stmt)
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Delete associated publish jobs
    pj_stmt = select(PublishJob).where(PublishJob.clip_id == clip_id)
    pj_result = await db.execute(pj_stmt)
    for pj in pj_result.scalars().all():
        await db.delete(pj)

    await db.delete(clip)
    await db.commit()
    log.info("Clip deleted: %s", clip_id)
