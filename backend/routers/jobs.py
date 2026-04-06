"""
ClipForge -- API Router: jobs.py
Multi-source ingestion: YouTube, Vimeo, direct file upload.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import Video, Channel, Clip, SessionLocal
from backend.models.schemas import JobTriggerRequest, JobStatusResponse, JobListResponse
from celery.result import AsyncResult

log = logging.getLogger("clipforge.jobs_router")

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


async def get_db() -> AsyncSession:
    async with SessionLocal() as db:
        yield db


@router.post("/trigger", status_code=202)
async def trigger_job(
    data: JobTriggerRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger clip generation for an existing video."""
    stmt = select(Video).where(Video.id == data.video_id)
    result = await db.execute(stmt)
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    from backend.tasks.transcribe import transcribe_video

    task = transcribe_video.delay(str(video.id))
    video.status = "processing"
    await db.commit()

    log.info("Job triggered for video %s -> Celery task %s", data.video_id, task.id)
    return {"job_id": task.id, "video_id": str(video.id), "status": "queued"}


@router.post("/trigger-url", status_code=202)
async def trigger_job_from_url(
    source_url: str = Form(...),
    platform: str = Form("youtube"),
    channel_id: Optional[str] = Form(None),
    vimeo_token: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Ingest video from YouTube or Vimeo URL.
    Supports both platforms via yt-dlp.
    """
    from backend.services.ingestion import detect_source, download_youtube, download_vimeo, get_video_metadata
    from backend.tasks.transcribe import transcribe_video

    source_type = detect_source(source_url)

    job_id = str(uuid.uuid4())
    output_dir = os.path.join("/tmp", "clipforge", "ingestion", job_id)

    try:
        if source_type == "youtube":
            file_path = await download_youtube(source_url, output_dir)
        elif source_type == "vimeo":
            file_path = await download_vimeo(source_url, output_dir, vimeo_token)
        else:
            raise HTTPException(status_code=400, detail="URL not recognized as YouTube or Vimeo")
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Download failed for %s", source_url)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)[:200]}")

    # Get metadata
    metadata = get_video_metadata(file_path)
    metadata.update({"source_url": source_url, "source_type": source_type})

    # Create video record
    video = Video(
        channel_id=uuid.UUID(channel_id) if channel_id else None,
        youtube_video_id=source_url.split("=")[-1] if source_type == "youtube" else source_url.split("/")[-1],
        title=metadata.get("filename", os.path.basename(file_path)),
        duration_seconds=metadata.get("duration_seconds"),
        youtube_url=source_url,
        download_path=file_path,
        status="pending",
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)

    # Kick off transcription
    task = transcribe_video.delay(str(video.id))

    return {
        "job_id": task.id,
        "video_id": str(video.id),
        "status": "queued",
        "metadata": metadata,
    }


@router.post("/trigger-upload", status_code=202)
async def trigger_job_from_upload(
    file: UploadFile = File(...),
    channel_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept direct MP4/MOV file upload (max 2GB).
    Streams to disk, creates video record, triggers pipeline.
    """
    from backend.services.ingestion import handle_file_upload, get_video_metadata
    from backend.tasks.transcribe import transcribe_video

    job_id = str(uuid.uuid4())
    output_dir = os.path.join("/tmp", "clipforge", "uploads", job_id)

    try:
        file_path = await handle_file_upload(file, output_dir)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Get metadata
    metadata = get_video_metadata(file_path)

    # Create video record
    video = Video(
        channel_id=uuid.UUID(channel_id) if channel_id else None,
        youtube_video_id=f"upload_{job_id[:8]}",
        title=os.path.basename(file_path),
        duration_seconds=metadata.get("duration_seconds"),
        youtube_url=None,
        download_path=file_path,
        status="pending",
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)

    # Kick off transcription
    task = transcribe_video.delay(str(video.id))

    return {
        "job_id": task.id,
        "video_id": str(video.id),
        "status": "queued",
        "metadata": metadata,
    }


@router.get("/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get the status of a Celery job with progress percentage."""
    # Try to get Celery task result
    try:
        result = AsyncResult(job_id)
        progress = 0.0
        if result.state == "PENDING":
            progress = 0.0
        elif result.state == "STARTED":
            progress = result.info.get("progress", 10.0) if isinstance(result.info, dict) else 10.0
        elif result.state == "SUCCESS":
            progress = 100.0
        elif result.state == "FAILURE":
            progress = -1.0
    except Exception:
        progress = 0.0

    return JobStatusResponse(
        id=job_id,
        status="unknown",
        progress=max(0.0, progress),
        clip_count=0,
        created_at=None,
    )


@router.get("", response_model=JobListResponse)
async def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List recent processing jobs for a user."""
    stmt = select(Video).order_by(Video.created_at.desc())
    count_stmt = select(func.count(Video.id))

    if status:
        where = Video.status == status
        stmt = stmt.where(where)
        count_stmt = count_stmt.where(where)

    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(stmt)
    videos = result.scalars().all()

    jobs = []
    for v in videos:
        jobs.append(JobStatusResponse(
            id=str(v.id),
            video_id=str(v.id),
            status=v.status,
            progress=100.0 if v.status == "done" else (0.0 if v.status == "pending" else 50.0),
            clip_count=0,
            created_at=v.created_at,
        ))

    return JobListResponse(jobs=jobs, total=total)
