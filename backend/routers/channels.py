"""
ClipForge -- API Router: channels.py
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from backend.models.database import Channel, Video, SessionLocal
from backend.models.schemas import ChannelCreate, ChannelResponse, ChannelListResponse

log = logging.getLogger("clipforge.channels_router")

router = APIRouter(prefix="/api/channels", tags=["channels"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
def connect_channel(
    data: ChannelCreate,
    db = Depends(get_db),
):
    """Connect a YouTube channel (tokens provided from OAuth redirect)."""
    try:
        from backend.services.youtube import get_channel_info, subscribe_to_channel
        info = asyncio.get_event_loop().run_until_complete(get_channel_info(data.youtube_channel_id))
        if "error" in info:
            raise HTTPException(status_code=400, detail=info["error"])

        sub_info = asyncio.get_event_loop().run_until_complete(subscribe_to_channel(data.youtube_channel_id))

        channel = Channel(
            youtube_channel_id=data.youtube_channel_id,
            channel_name=info.get("name"),
            channel_thumbnail=info.get("thumbnail"),
            access_token=data.access_token,
            refresh_token=data.refresh_token,
            pubsub_lease_seconds=sub_info.get("lease_seconds"),
            pubsub_expiry_at=sub_info.get("pubsub_expiry_at"),
        )
        db.add(channel)
        db.commit()
        db.refresh(channel)
        log.info("Channel connected: %s (%s)", info.get("name"), channel.id)
        return channel
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to connect channel")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=ChannelListResponse)
def list_channels(db=Depends(get_db)):
    """List all connected YouTube channels for the authenticated user."""
    stmt = select(Channel).where(Channel.is_active == True)
    result = db.execute(stmt)
    channels = result.scalars().all()
    return ChannelListResponse(
        channels=[ChannelResponse.model_validate(c) for c in channels],
        total=len(channels),
    )


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_channel(channel_id: str, db=Depends(get_db)):
    """Disconnect a YouTube channel (soft-delete: set is_active=False)."""
    stmt = select(Channel).where(Channel.id == channel_id)
    result = db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    channel.is_active = False
    db.commit()
    log.info("Channel disconnected: %s", channel_id)


@router.post("/{channel_id}/sync", status_code=status.HTTP_202_ACCEPTED)
def sync_channel(channel_id: str, db=Depends(get_db)):
    """Manually trigger processing of the latest video for a channel."""
    from backend.tasks.transcribe import transcribe_video

    stmt = select(Channel).where(Channel.id == channel_id, Channel.is_active == True)
    result = db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found or inactive")

    try:
        from backend.services.youtube import fetch_latest_video
        video_data = asyncio.get_event_loop().run_until_complete(fetch_latest_video(channel.youtube_channel_id))
        if not video_data:
            raise HTTPException(status_code=404, detail="No video found for channel")

        video = Video(
            channel_id=channel.id,
            youtube_video_id=video_data["video_id"],
            title=video_data["title"],
            duration_seconds=video_data["duration_seconds"],
            youtube_url=video_data["url"],
            status="pending",
        )
        db.add(video)
        db.commit()
        db.refresh(video)

        task = transcribe_video.delay(str(video.id))
        log.info("Sync triggered for channel %s, video %s", channel_id, video.id)
        return {"video_id": str(video.id), "status": "queued"}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Sync failed for channel %s", channel_id)
        raise HTTPException(status_code=500, detail=str(e))
