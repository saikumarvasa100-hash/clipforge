     1|"""
     2|ClipForge -- Celery Task: Cut Clips
     3|Takes scored clips, runs FFmpeg pipeline, stores locally.
     4|"""
     5|from __future__ import annotations
     6|
     7|     8|import json
     9|import logging
    10|import os
    11|from typing import List
    12|
    13|
    14|from backend.celery_app import celery_app
    15|from backend.models.database import Clip, Video, SessionLocal, ClipStatus
    16|from backend.services.ffmpeg_service import (
    17|    cut_clip,
    18|    reformat_to_9_16,
    19|    burn_captions,
    20|    add_intro_zoom,
    21|)
    22|from backend.services.caption_styles import burn_styled_captions
    23|from backend.services.silence_remover import remove_silence, remove_filler_words, shift_captions
    24|from backend.services.hashtag_service import generate_hashtags
    25|from backend.services.platform_presets import encode_for_platform
    26|from sqlalchemy import select
    27|
    28|log = logging.getLogger("clipforge.cut_clips")
    29|
    30|# ── Local Storage ────────────────────────────────────────────────────
    31|
    32|def upload_to_local(local_path: str, clip_id: str) -> str:
    33|    """Store a processed clip in the local filesystem. Return the file path."""
    34|    from backend.services.local_storage import upload_clip
    35|    stored_path = upload_clip(local_path, clip_id)
    36|    log.info("Stored clip locally: %s", stored_path)
    37|    return stored_path
    38|
    39|
    40|# ── FFmpeg Processing Pipeline ───────────────────────────────────────
    41|
    42|def process_clip(clip_data: dict, audio_path: str) -> str:
    43|    """
    44|    Full pipeline: cut -> reformat -> burn captions -> zoom intro -> return path.
    45|    """
    46|    clip_id = clip_data["id"]
    47|    start = clip_data["start_time"]
    48|    end = clip_data["end_time"]
    49|    words_json = json.dumps(clip_data.get("caption_words", []))
    50|
    51|    work_dir = os.path.join("/tmp", "clipforge", clip_id)
    52|    os.makedirs(work_dir, exist_ok=True)
    53|
    54|    # Step 1: Cut segment
    55|    cut_path = os.path.join(work_dir, "cut.mp4")
    56|    cut_clip(audio_path, start, end, cut_path)
    57|    log.info("Step 1/3: cut %s", cut_path)
    58|
    59|    # Step 2: Reformat to 9:16
    60|    reformatted = os.path.join(work_dir, "9x16.mp4")
    61|    reformat_to_9_16(cut_path, reformatted)
    62|    log.info("Step 2/3: reformatted %s", reformatted)
    63|
    64|    # Step 3: Add intro zoom
    65|    zoomed = os.path.join(work_dir, "zoomed.mp4")
    66|    add_intro_zoom(reformatted, zoomed, duration=0.5)
    67|    log.info("Step 3/3: zoomed %s", zoomed)
    68|
    69|    # Step 4: Burn captions (requires video, so run on zoomed)
    70|    final_path = f"{work_dir}/final_{clip_id}.mp4"
    71|    if words_json and words_json != "[]":
    72|        burn_captions(zoomed, words_json, final_path)
    73|    else:
    74|        final_path = zoomed
    75|        log.info("No caption words available, skipping burn_captions")
    76|
    77|    return final_path
    78|
    79|
    80|# ── Celery Task ──────────────────────────────────────────────────────
    81|
    82|@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
    83|def cut_clips_for_video(self, video_id: str):
    84|    """
    85|    Load all pending clips for a video, process each through the
    86|    FFmpeg pipeline, store locally, and update DB.
    87|    """
    88|    def _run():
    89|        db = SessionLocal()
    90|            result = db.execute(
    91|                select(Clip).where(Clip.video_id == video_id, Clip.status != ClipStatus.READY)
    92|            )
    93|            clips = result.scalars().all()
    94|
    95|            if not clips:
    96|                log.warning("No pending clips found for video %s", video_id)
    97|                return
    98|
    99|            # Get the original audio path
   100|            v_result = db.execute(select(Video).where(Video.id == video_id))
   101|            video = v_result.scalar_one_or_none()
   102|            if not video:
   103|                log.error("Video %s not found", video_id)
   104|                return
   105|
   106|            audio_path = video.download_path or ""
   107|            if not audio_path or not os.path.exists(audio_path):
   108|                log.error("Audio file not found: %s", audio_path)
   109|                return
   110|
   111|            log.info("Processing %d clips for video %s", len(clips), video_id)
   112|
   113|            for clip in clips:
   114|                try:
   115|                    clip_data = {
   116|                        "id": str(clip.id),
   117|                        "start_time": clip.start_time,
   118|                        "end_time": clip.end_time,
   119|                        "caption_words": clip.caption_data or [],
   120|                    }
   121|
   122|                    final_path = process_clip(clip_data, audio_path)
   123|
   124|                    # Store locally
   125|                    storage_path = upload_to_local(final_path, str(clip.id))
   126|
   127|                    # Update clip record
   128|                    clip.output_path = final_path
   129|                    clip.storage_url = storage_path
   130|                    clip.status = ClipStatus.READY
   131|
   132|                    db.commit()
   133|                    log.info("Clip %s ready: %s", clip.id, storage_path)
   134|
   135|                    # Create publish jobs for each platform
   136|                    from backend.models.database import PublishJob, PublishPlatform, PublishStatus
   137|                    for platform in [
   138|                        PublishPlatform.SHORTS,
   139|                        PublishPlatform.TIKTOK,
   140|                        PublishPlatform.REELS,
   141|                    ]:
   142|                        job = PublishJob(
   143|                            clip_id=clip.id,
   144|                            platform=platform,
   145|                            status=PublishStatus.QUEUED,
   146|                        )
   147|                        db.add(job)
   148|                    db.commit()
   149|
   150|                except Exception:
   151|                    log.exception("Failed to process clip %s", clip.id)
   152|                    clip.status = ClipStatus.FAILED
   153|                    db.commit()
   154|
   155|    _run()
   156|