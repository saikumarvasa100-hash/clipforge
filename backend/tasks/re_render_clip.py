"""
ClipForge — Celery Task: Re-Render Clip
Handles in-app editor changes: trim adjustment, caption edits, style switch.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import List, Dict, Optional

from backend.celery_app import celery_app
from backend.models.database import Clip, Video, SessionLocal, ClipStatus
from backend.services.ffmpeg_service import cut_clip, probe_duration
from backend.services.caption_styles import burn_styled_captions
from backend.services.ingestion import get_video_metadata
from sqlalchemy import select

log = logging.getLogger("clipforge.re_render")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def re_render_clip(
    self,
    clip_id: str,
    trim_start: float,
    trim_end: float,
    edited_captions: Optional[List[Dict]] = None,
    style_name: str = "classic",
):
    """
    Re-cut a clip with new trim times and recaption.
    Stores replacement locally, updates clip record.
    """
    async def _run():
        async with SessionLocal() as db:
            # Load clip
            clip_result = await db.execute(select(Clip).where(Clip.id == clip_id))
            clip = clip_result.scalar_one_or_none()
            if not clip:
                log.error("Clip %s not found", clip_id)
                return

            # Load video to get source path
            video_result = await db.execute(select(Video).where(Video.id == clip.video_id))
            video = video_result.scalar_one_or_none()
            if not video:
                log.error("Video %s not found", clip.video_id)
                return

            source_path = video.download_path or ""
            if not os.path.exists(source_path):
                log.error("Source file not found: %s", source_path)
                return

            total_duration = probe_duration(source_path) if os.path.exists(source_path) else 0

            # Step 1: Cut clip with new trim times (relative to video)
            abs_start = clip.start_time + trim_start
            abs_end = clip.start_time + trim_end
            abs_end = min(abs_end, total_duration)

            if abs_end <= abs_start:
                log.error("Invalid trim: start=%s > end=%s", abs_start, abs_end)
                return

            work_dir = os.path.join("/tmp", "clipforge", "reedit", clip_id)
            os.makedirs(work_dir, exist_ok=True)

            cut_path = os.path.join(work_dir, "reedit_cut.mp4")
            cut_clip(source_path, abs_start, abs_end, cut_path)

            # Step 2: Build caption words from edited captions or original
            words_json = None
            if edited_captions:
                words_json = json.dumps(edited_captions)
            elif clip.caption_data:
                words_json = json.dumps(clip.caption_data)

            # Step 3: Burn captions with new style
            styled_path = os.path.join(work_dir, f"reedit_{style_name}.mp4")
            from backend.services.ffmpeg_service import reformat_to_9_16

            reformatted = os.path.join(work_dir, "reedit_9x16.mp4")
            reformat_to_9_16(cut_path, reformatted)

            if words_json and words_json != "[]":
                burn_styled_captions(reformatted, words_json, style_name, styled_path)
            else:
                styled_path = reformatted

            # Step 4: Store replacement locally
            from backend.tasks.cut_clips import upload_to_local
            storage_path = upload_to_local(styled_path, f"{clip_id}")

            # Step 5: Update clip record
            clip.output_path = styled_path
            clip.storage_url = storage_path
            clip.status = ClipStatus.READY

            # Update caption style if column exists
            try:
                clip.caption_data = edited_captions or clip.caption_data
            except Exception:
                pass

            await db.commit()

            log.info("Clip re-rendered: %s (style=%s, trim=%.1f-%.1f, url=%s)",
                     clip_id, style_name, trim_start, trim_end, storage_path)

    asyncio.run(_run())
