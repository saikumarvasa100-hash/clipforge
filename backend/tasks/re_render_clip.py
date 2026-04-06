     1|"""
     2|ClipForge — Celery Task: Re-Render Clip
     3|Handles in-app editor changes: trim adjustment, caption edits, style switch.
     4|"""
     5|from __future__ import annotations
     6|
     7|     8|import json
     9|import logging
    10|import os
    11|from typing import List, Dict, Optional
    12|
    13|from backend.celery_app import celery_app
    14|from backend.models.database import Clip, Video, SessionLocal, ClipStatus
    15|from backend.services.ffmpeg_service import cut_clip, probe_duration
    16|from backend.services.caption_styles import burn_styled_captions
    17|from backend.services.ingestion import get_video_metadata
    18|from sqlalchemy import select
    19|
    20|log = logging.getLogger("clipforge.re_render")
    21|
    22|
    23|@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
    24|def re_render_clip(
    25|    self,
    26|    clip_id: str,
    27|    trim_start: float,
    28|    trim_end: float,
    29|    edited_captions: Optional[List[Dict]] = None,
    30|    style_name: str = "classic",
    31|):
    32|    """
    33|    Re-cut a clip with new trim times and recaption.
    34|    Stores replacement locally, updates clip record.
    35|    """
    36|    def _run():
    37|        db = SessionLocal()
    38|            # Load clip
    39|            clip_result = db.execute(select(Clip).where(Clip.id == clip_id))
    40|            clip = clip_result.scalar_one_or_none()
    41|            if not clip:
    42|                log.error("Clip %s not found", clip_id)
    43|                return
    44|
    45|            # Load video to get source path
    46|            video_result = db.execute(select(Video).where(Video.id == clip.video_id))
    47|            video = video_result.scalar_one_or_none()
    48|            if not video:
    49|                log.error("Video %s not found", clip.video_id)
    50|                return
    51|
    52|            source_path = video.download_path or ""
    53|            if not os.path.exists(source_path):
    54|                log.error("Source file not found: %s", source_path)
    55|                return
    56|
    57|            total_duration = probe_duration(source_path) if os.path.exists(source_path) else 0
    58|
    59|            # Step 1: Cut clip with new trim times (relative to video)
    60|            abs_start = clip.start_time + trim_start
    61|            abs_end = clip.start_time + trim_end
    62|            abs_end = min(abs_end, total_duration)
    63|
    64|            if abs_end <= abs_start:
    65|                log.error("Invalid trim: start=%s > end=%s", abs_start, abs_end)
    66|                return
    67|
    68|            work_dir = os.path.join("/tmp", "clipforge", "reedit", clip_id)
    69|            os.makedirs(work_dir, exist_ok=True)
    70|
    71|            cut_path = os.path.join(work_dir, "reedit_cut.mp4")
    72|            cut_clip(source_path, abs_start, abs_end, cut_path)
    73|
    74|            # Step 2: Build caption words from edited captions or original
    75|            words_json = None
    76|            if edited_captions:
    77|                words_json = json.dumps(edited_captions)
    78|            elif clip.caption_data:
    79|                words_json = json.dumps(clip.caption_data)
    80|
    81|            # Step 3: Burn captions with new style
    82|            styled_path = os.path.join(work_dir, f"reedit_{style_name}.mp4")
    83|            from backend.services.ffmpeg_service import reformat_to_9_16
    84|
    85|            reformatted = os.path.join(work_dir, "reedit_9x16.mp4")
    86|            reformat_to_9_16(cut_path, reformatted)
    87|
    88|            if words_json and words_json != "[]":
    89|                burn_styled_captions(reformatted, words_json, style_name, styled_path)
    90|            else:
    91|                styled_path = reformatted
    92|
    93|            # Step 4: Store replacement locally
    94|            from backend.tasks.cut_clips import upload_to_local
    95|            storage_path = upload_to_local(styled_path, f"{clip_id}")
    96|
    97|            # Step 5: Update clip record
    98|            clip.output_path = styled_path
    99|            clip.storage_url = storage_path
   100|            clip.status = ClipStatus.READY
   101|
   102|            # Update caption style if column exists
   103|            try:
   104|                clip.caption_data = edited_captions or clip.caption_data
   105|            except Exception:
   106|                pass
   107|
   108|            db.commit()
   109|
   110|            log.info("Clip re-rendered: %s (style=%s, trim=%.1f-%.1f, url=%s)",
   111|                     clip_id, style_name, trim_start, trim_end, storage_path)
   112|
   113|    _run()
   114|