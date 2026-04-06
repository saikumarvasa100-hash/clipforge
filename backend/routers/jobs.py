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
from sqlalchemy import func, select, text

from backend.models.database import Video, Clip, SessionLocal
from backend.models.schemas import JobTriggerRequest, JobStatusResponse, JobListResponse

log = logging.getLogger("clipforge.jobs_router")

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/trigger", status_code=202)
def trigger_job(data: JobTriggerRequest, db=Depends(get_db)):
    """Manually trigger clip generation for an existing video."""
    from backend.tasks.transcribe import transcribe_video

    stmt = select(Video).where(Video.id == data.video_id)
    result = db.execute(stmt)
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    task = transcribe_video.delay(str(video.id))
    video.status = "processing"
    db.commit()

    log.info("Job triggered for video %s -> Celery task %s", data.video_id, task.id)
    return {"job_id": task.id, "video_id": str(video.id), "status": "queued"}


@router.get("/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: str, db=Depends(get_db)):
    """Get the status of a Celery job with progress percentage."""
    from celery.result import AsyncResult
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
        id=job_id, status="unknown", progress=max(0.0, progress),
        clip_count=0, created_at=None,
    )


@router.get("", response_model=JobListResponse)
def list_jobs(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None), db=Depends(get_db),
):
    """List recent processing jobs for a user."""
    stmt = select(Video).order_by(Video.created_at.desc())
    count_stmt = select(func.count(Video.id))

    if status:
        where = Video.status == status
        stmt = stmt.where(where)
        count_stmt = count_stmt.where(where)

    total = db.execute(count_stmt).scalar() or 0
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = db.execute(stmt)
    videos = result.scalars().all()

    jobs = []
    for v in videos:
        jobs.append(JobStatusResponse(
            id=str(v.id), video_id=str(v.id), status=v.status,
            progress=100.0 if v.status == "done" else (0.0 if v.status == "pending" else 50.0),
            clip_count=0, created_at=v.created_at,
        ))

    return JobListResponse(jobs=jobs, total=total)
