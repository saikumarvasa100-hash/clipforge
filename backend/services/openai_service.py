"""
ClipForge -- OpenAI Service
Whisper transcription with file splitting, retry, chunk handling.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from typing import List, Dict, Any

import openai

log = logging.getLogger("clipforge.openai_service")

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
CHUNK_SIZE = 24 * 60  # 24-minute chunks (Whisper limit ~150MB but conservative)


class OpenAIService:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.client = openai.AsyncOpenAI(api_key=self.api_key)

    async def transcribe_audio(self, audio_path: str) -> Dict[str, Any]:
        """
        Transcribe audio with Whisper. Splits files > 25MB into chunks,
        merges results. Retries on RateLimitError with backoff.
        """
        file_size = os.path.getsize(audio_path)

        if file_size > MAX_FILE_SIZE:
            log.info("File %d bytes exceeds 25MB, splitting into chunks", file_size)
            return await self._transcribe_chunked(audio_path)
        else:
            return await self._transcribe_single(audio_path)

    async def _transcribe_single(self, audio_path: str, max_retries: int = 3) -> Dict[str, Any]:
        """Transcribe a single audio file with retry logic."""
        for attempt in range(max_retries):
            try:
                with open(audio_path, "rb") as f:
                    response = await self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=f,
                        response_format="verbose_json",
                        timestamp_granularities=["word", "segment"],
                    )

                return {
                    "text": response.text,
                    "segments": [
                        {"start": s.start, "end": s.end, "text": s.text}
                        for s in response.segments or []
                    ],
                    "words": [
                        {"word": w.word, "start": w.start, "end": w.end}
                        for w in response.words or []
                    ],
                }

            except openai.RateLimitError:
                wait = 2 ** (attempt + 1) * 5
                log.warning("Rate limit hit, retrying in %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
                await asyncio.sleep(wait)
            except Exception:
                log.exception("Transcription failed on attempt %d", attempt + 1)
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** (attempt + 1))

        raise RuntimeError("Transcription failed after all retries")

    async def _transcribe_chunked(self, audio_path: str) -> Dict[str, Any]:
        """Split large audio file into 24-minute chunks and merge results."""
        chunks_dir = os.path.join("/tmp", "clipforge", "chunks")
        os.makedirs(chunks_dir, exist_ok=True)

        # Use ffprobe to get duration
        duration = self._get_duration(audio_path)
        chunk_duration = CHUNK_SIZE
        num_chunks = int(duration / chunk_duration) + 1

        log.info("Splitting %.0fs audio into %d chunks", duration, num_chunks)

        all_text = []
        all_segments = []
        all_words = []
        time_offset = 0.0

        for i in range(num_chunks):
            start = i * chunk_duration
            chunk_path = os.path.join(chunks_dir, f"chunk_{i:03d}.mp3")

            # Extract chunk with ffmpeg
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", audio_path,
                "-t", str(chunk_duration),
                "-acodec", "libmp3lame",
                "-q:a", "2",
                chunk_path,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                log.error("FFmpeg chunking failed: %s", proc.stderr[:300])
                continue

            # Transcribe chunk
            result = await self._transcribe_single(chunk_path)

            # Adjust timestamps
            for seg in result["segments"]:
                seg["start"] += time_offset
                seg["end"] += time_offset
                all_segments.append(seg)

            for w in result["words"]:
                w["start"] += time_offset
                w["end"] += time_offset
                all_words.append(w)

            all_text.append(result["text"])
            time_offset += chunk_duration

            # Cleanup chunk
            if os.path.exists(chunk_path):
                os.remove(chunk_path)

        return {
            "text": " ".join(all_text),
            "segments": all_segments,
            "words": all_words,
        }

    @staticmethod
    def _get_duration(audio_path: str) -> float:
        """Get audio duration in seconds using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(proc.stdout.strip())
        except (ValueError, TypeError):
            return 0.0


# Singleton instance
_service: OpenAIService | None = None


def get_service() -> OpenAIService:
    global _service
    if _service is None:
        _service = OpenAIService()
    return _service


async def transcribe_audio(audio_path: str) -> Dict[str, Any]:
    """Convenience function for transcription."""
    return await get_service().transcribe_audio(audio_path)
