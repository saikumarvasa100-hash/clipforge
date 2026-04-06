"""
ClipForge -- Celery Task: Publish Clips
Reads publish_jobs queue, calls the correct platform publisher.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from backend.celery_app import celery_app
from backend.models.database import (
    PublishJob, Clip, Channel, SessionLocal,
    PublishStatus, PublishPlatform,
)
from backend.services.publisher import (
    tiktok_upload,
    refresh_tiktok_token,
    youtube_shorts_upload,
    instagram_reels_upload,
)
from sqlalchemy import select

log = logging.getLogger("clipforge.publish")


# ── Token helpers ─────────────────────────────────────────────────────

async def _get_channel_for_clip(db, clip) -> Channel | None:
    """Resolve the Channel that produced this clip's video."""
    from backend.models.database import Video
    v_result = await db.execute(select(Video).where(Video.id == clip.video_id))
    video = v_result.scalar_one_or_none()
    if not video:
        return None
    ch_result = await db.execute(select(Channel).where(Channel.id == video.channel_id))
    return ch_result.scalar_one_or_none()


# ── Platform dispatchers ─────────────────────────────────────────────

async def _publish_tiktok(clip, publish_job, db):
    """Publish to TikTok with automatic token refresh."""
    channel = await _get_channel_for_clip(db, clip)
    if not channel or not channel.access_token:
        raise ValueError("No TikTok access token available")

    access_token = channel.access_token
    refresh_token = channel.refresh_token

    try:
        post_id = await tiktok_upload(
            clip={"output_path": clip.output_path or "/tmp/fallback", "hook_text": clip.hook_text or ""},
            access_token=access_token,
        )
        return post_id
    except Exception as e:
        # Try refreshing token
        if refresh_token:
            try:
                new_tokens = await refresh_tiktok_token(refresh_token)
                access_token = new_tokens.get("access_token", access_token)
                post_id = await tiktok_upload(
                    clip={"output_path": clip.output_path or "/tmp/fallback", "hook_text": clip.hook_text or ""},
                    access_token=access_token,
                )
                return post_id
            except Exception as e2:
                log.exception("TikTok publish failed after token refresh")
                raise
        raise


async def _publish_shorts(clip, publish_job, db):
    """Publish to YouTube Shorts."""
    channel = await _get_channel_for_clip(db, clip)
    if not channel:
        raise ValueError("No channel found for clip")

    credentials = {
        "access_token": channel.access_token,
        "refresh_token": channel.refresh_token,
    }
    video_id = await youtube_shorts_upload(
        clip={"output_path": clip.output_path, "hook_text": clip.hook_text or "", "hashtags": []},
        credentials=credentials,
    )
    return video_id


async def _publish_reels(clip, publish_job, db):
    """Publish to Instagram Reels."""
    channel = await _get_channel_for_clip(db, clip)
    if not channel or not channel.access_token:
        raise ValueError("No Instagram access token available")

    media_id = await instagram_reels_upload(
        clip={"output_path": clip.output_path, "hook_text": clip.hook_text or ""},
        access_token=channel.access_token,
        ig_user_id=channel.youtube_channel_id,  # IG user id stored separately
    )
    return media_id


# ── Celery Task ──────────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=3, default_retry_delay=120)
def publish_clips(self):
    """
    Process all QUEUED publish jobs. Dispatch to the correct platform,
    handle token expiry, retry on failure, update status.
    """
    async def _run():
        async with SessionLocal() as db:
            result = await db.execute(
                select(PublishJob).where(PublishJob.status == PublishStatus.QUEUED)
            )
            jobs = result.scalars().all()

            if not jobs:
                log.info("No queued publish jobs")
                return

            log.info("Processing %d queued publish jobs", len(jobs))

            for job in jobs:
                try:
                    # Load clip
                    clip_result = await db.execute(select(Clip).where(Clip.id == job.clip_id))
                    clip = clip_result.scalar_one_or_none()
                    if not clip:
                        log.error("Clip %s not found for publish job %s", job.clip_id, job.id)
                        job.status = PublishStatus.FAILED
                        job.error_message = "Clip not found"
                        await db.commit()
                        continue

                    job.status = PublishStatus.UPLOADING
                    await db.commit()

                    platform_post_id: str | None = None

                    if job.platform == PublishPlatform.TIKTOK:
                        platform_post_id = await _publish_tiktok(clip, job, db)
                    elif job.platform == PublishPlatform.SHORTS:
                        platform_post_id = await _publish_shorts(clip, job, db)
                    elif job.platform in (PublishPlatform.INSTAGRAM, PublishPlatform.REELS):
                        platform_post_id = await _publish_reels(clip, job, db)
                    else:
                        raise ValueError(f"Unknown platform: {job.platform}")

                    job.status = PublishStatus.PUBLISHED
                    job.platform_post_id = platform_post_id
                    job.published_at = datetime.now(timezone.utc)
                    job.error_message = None
                    await db.commit()
                    log.info("Published job %s to %s: %s", job.id, job.platform, platform_post_id)

                except Exception as e:
                    log.exception("Publish job %s failed", job.id)
                    retry_count = getattr(self.request, "retries", 0)
                    if retry_count >= self.max_retries:
                        job.status = PublishStatus.FAILED
                        job.error_message = str(e)[:500]
                    else:
                        job.status = PublishStatus.QUEUED  # re-queue
                    await db.commit()

    asyncio.run(_run())
