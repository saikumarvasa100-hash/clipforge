"""
ClipForge -- Celery Task: Transcribe Video
Calls OpenAI Whisper API with word/segment timestamps, saves transcript.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from backend.celery_app import celery_app
from backend.models.database import Video, SessionLocal
from backend.services.openai_service import transcribe_audio
from sqlalchemy import select

log = logging.getLogger("clipforge.transcribe")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def transcribe_video(self, video_id: str):
    """
    Receive video_id, get audio path, call Whisper, save transcript,
    chain to score_virality.
    """
    async def _run():
        async with SessionLocal() as db:
            result = await db.execute(select(Video).where(Video.id == video_id))
            video = result.scalar_one_or_none()
            if not video:
                log.error("Video %s not found", video_id)
                return

            audio_path = video.download_path or ""
            if not audio_path or not os.path.exists(audio_path):
                log.error("Audio file not found: %s", audio_path)
                video.status = "failed"
                await db.commit()
                return

            log.info("Transcribing video %s (audio: %s)", video_id, audio_path)

            try:
                transcript = await transcribe_audio(audio_path)
            except Exception:
                log.exception("Transcription failed for video %s", video_id)
                self.retry(countdown=60)
                return

            # Save transcript to local file (or upload to Supabase in production)
            transcript_dir = os.path.join("/tmp", "clipforge", "transcripts")
            os.makedirs(transcript_dir, exist_ok=True)
            transcript_path = os.path.join(transcript_dir, f"{video_id}.json")

            with open(transcript_path, "w") as f:
                json.dump(transcript, f, indent=2)

            # Update video record
            video.status = "transcribed"
            video.transcript_path = transcript_path
            await db.commit()

            log.info(
                "Transcription complete for %s: %d segments, %d words",
                video_id,
                len(transcript.get("segments", [])),
                len(transcript.get("words", [])),
            )

            # Chain to virality scoring
            from backend.tasks.score_virality import score_virality
            score_virality.delay(video_id)

    asyncio.run(_run())
