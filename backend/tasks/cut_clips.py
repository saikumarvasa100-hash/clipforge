"""
ClipForge -- Celery Task: Cut Clips
Takes scored clips, runs FFmpeg pipeline, stores locally.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import List


from backend.celery_app import celery_app
from backend.models.database import Clip, Video, SessionLocal, ClipStatus
from backend.services.ffmpeg_service import (
    cut_clip,
    reformat_to_9_16,
    burn_captions,
    add_intro_zoom,
)
from backend.services.caption_styles import burn_styled_captions
from backend.services.silence_remover import remove_silence, remove_filler_words, shift_captions
from backend.services.hashtag_service import generate_hashtags
from backend.services.platform_presets import encode_for_platform
from sqlalchemy import select

log = logging.getLogger("clipforge.cut_clips")

# ── Local Storage ────────────────────────────────────────────────────

def upload_to_local(local_path: str, clip_id: str) -> str:
    """Store a processed clip in the local filesystem. Return the file path."""
    from backend.services.local_storage import upload_clip
    stored_path = upload_clip(local_path, clip_id)
    log.info("Stored clip locally: %s", stored_path)
    return stored_path


# ── FFmpeg Processing Pipeline ───────────────────────────────────────

def process_clip(clip_data: dict, audio_path: str) -> str:
    """
    Full pipeline: cut -> reformat -> burn captions -> zoom intro -> return path.
    """
    clip_id = clip_data["id"]
    start = clip_data["start_time"]
    end = clip_data["end_time"]
    words_json = json.dumps(clip_data.get("caption_words", []))

    work_dir = os.path.join("/tmp", "clipforge", clip_id)
    os.makedirs(work_dir, exist_ok=True)

    # Step 1: Cut segment
    cut_path = os.path.join(work_dir, "cut.mp4")
    cut_clip(audio_path, start, end, cut_path)
    log.info("Step 1/3: cut %s", cut_path)

    # Step 2: Reformat to 9:16
    reformatted = os.path.join(work_dir, "9x16.mp4")
    reformat_to_9_16(cut_path, reformatted)
    log.info("Step 2/3: reformatted %s", reformatted)

    # Step 3: Add intro zoom
    zoomed = os.path.join(work_dir, "zoomed.mp4")
    add_intro_zoom(reformatted, zoomed, duration=0.5)
    log.info("Step 3/3: zoomed %s", zoomed)

    # Step 4: Burn captions (requires video, so run on zoomed)
    final_path = f"{work_dir}/final_{clip_id}.mp4"
    if words_json and words_json != "[]":
        burn_captions(zoomed, words_json, final_path)
    else:
        final_path = zoomed
        log.info("No caption words available, skipping burn_captions")

    return final_path


# ── Celery Task ──────────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def cut_clips_for_video(self, video_id: str):
    """
    Load all pending clips for a video, process each through the
    FFmpeg pipeline, store locally, and update DB.
    """
    async def _run():
        async with SessionLocal() as db:
            result = await db.execute(
                select(Clip).where(Clip.video_id == video_id, Clip.status != ClipStatus.READY)
            )
            clips = result.scalars().all()

            if not clips:
                log.warning("No pending clips found for video %s", video_id)
                return

            # Get the original audio path
            v_result = await db.execute(select(Video).where(Video.id == video_id))
            video = v_result.scalar_one_or_none()
            if not video:
                log.error("Video %s not found", video_id)
                return

            audio_path = video.download_path or ""
            if not audio_path or not os.path.exists(audio_path):
                log.error("Audio file not found: %s", audio_path)
                return

            log.info("Processing %d clips for video %s", len(clips), video_id)

            for clip in clips:
                try:
                    clip_data = {
                        "id": str(clip.id),
                        "start_time": clip.start_time,
                        "end_time": clip.end_time,
                        "caption_words": clip.caption_data or [],
                    }

                    final_path = process_clip(clip_data, audio_path)

                    # Store locally
                    storage_path = upload_to_local(final_path, str(clip.id))

                    # Update clip record
                    clip.output_path = final_path
                    clip.storage_url = storage_path
                    clip.status = ClipStatus.READY

                    await db.commit()
                    log.info("Clip %s ready: %s", clip.id, storage_path)

                    # Create publish jobs for each platform
                    from backend.models.database import PublishJob, PublishPlatform, PublishStatus
                    for platform in [
                        PublishPlatform.SHORTS,
                        PublishPlatform.TIKTOK,
                        PublishPlatform.REELS,
                    ]:
                        job = PublishJob(
                            clip_id=clip.id,
                            platform=platform,
                            status=PublishStatus.QUEUED,
                        )
                        db.add(job)
                    await db.commit()

                except Exception:
                    log.exception("Failed to process clip %s", clip.id)
                    clip.status = ClipStatus.FAILED
                    await db.commit()

    asyncio.run(_run())
