"""
ClipForge — Multi-Source Video Ingestion
YouTube + Vimeo + direct file upload (MP4/MOV/AVI/MKV/WebM).
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import re
import subprocess
from enum import Enum
from typing import Literal

from fastapi import UploadFile

log = logging.getLogger("clipforge.ingestion")

MAX_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB
ALLOWED_MIMES = {
    "video/mp4", "video/quicktime", "video/x-msvideo",
    "video/x-matroska", "video/webm",
}
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


class SourceType(str, Enum):
    YOUTUBE = "youtube"
    VIMEO = "vimeo"
    UPLOAD = "upload"


def detect_source(url_or_path: str) -> Literal["youtube", "vimeo", "upload"]:
    """Detect the video source type from a URL or file path."""
    lower = (url_or_path or "").lower()
    if "youtube.com" in lower or "youtu.be" in lower:
        return "youtube"
    if "vimeo.com" in lower:
        return "vimeo"
    return "upload"


async def download_youtube(url: str, output_dir: str) -> str:
    """Download YouTube video using yt-dlp. Returns path to MP4."""
    os.makedirs(output_dir, exist_ok=True)
    output_template = os.path.join(output_dir, "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
        "--merge-output-format", "mp4",
        "-o", output_template,
        "--no-playlist",
        "--restrict-filenames",
        url,
    ]

    log.info("Downloading YouTube: %s", url)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[:500]
        log.error("YouTube download failed: %s", err)
        raise RuntimeError(f"yt-dlp YouTube download failed: {err}")

    # Find the downloaded file
    for f in os.listdir(output_dir):
        if f.endswith(".mp4"):
            path = os.path.join(output_dir, f)
            log.info("YouTube download complete: %s (%d bytes)", path, os.path.getsize(path))
            return path

    raise FileNotFoundError(f"No MP4 found in {output_dir} after yt-dlp")


async def download_vimeo(url: str, output_dir: str, vimeo_token: str | None = None) -> str:
    """Download Vimeo video using yt-dlp. Handles private links with token."""
    os.makedirs(output_dir, exist_ok=True)
    output_template = os.path.join(output_dir, "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
        "--merge-output-format", "mp4",
        "-o", output_template,
        "--no-playlist",
        "--restrict-filenames",
    ]
    if vimeo_token:
        cmd.extend(["--add-header", f"Authorization:Bearer {vimeo_token}"])
    cmd.append(url)

    log.info("Downloading Vimeo: %s", url)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[:500]
        log.error("Vimeo download failed: %s", err)
        raise RuntimeError(f"yt-dlp Vimeo download failed: {err}")

    for f in os.listdir(output_dir):
        if f.endswith(".mp4"):
            path = os.path.join(output_dir, f)
            log.info("Vimeo download complete: %s (%d bytes)", path, os.path.getsize(path))
            return path

    raise FileNotFoundError(f"No MP4 found in {output_dir} after yt-dlp")


async def handle_file_upload(file: UploadFile, output_dir: str) -> str:
    """
    Stream-write an uploaded file to disk in chunks.
    Validates MIME type and max size (2 GB).
    Returns saved file path.
    """
    # Validate extension
    _, ext = os.path.splitext(file.filename or "")
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Allowed: {ALLOWED_EXTENSIONS}")

    # Validate MIME
    if file.content_type and file.content_type not in ALLOWED_MIMES:
        raise ValueError(f"Unsupported MIME type: {file.content_type}")

    os.makedirs(output_dir, exist_ok=True)
    safe_name = re.sub(r"[^\w\-.]", "_", file.filename or "upload.mp4")
    output_path = os.path.join(output_dir, safe_name)

    total_size = 0
    chunk_size = 1024 * 1024  # 1 MB chunks

    with open(output_path, "wb") as f:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > MAX_UPLOAD_SIZE:
                os.remove(output_path)
                raise ValueError(f"File exceeds 2 GB limit (got {total_size / (1024**3):.1f} GB)")
            f.write(chunk)

    log.info("File upload complete: %s (%.1f MB)", output_path, total_size / (1024 ** 2))
    return output_path


def get_video_metadata(file_path: str) -> dict:
    """
    Use ffprobe to extract video metadata.
    Returns dict with duration, dimensions, fps, audio info, size.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Video not found: {file_path}")

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size",
        "-show_entries", "stream=width,height,r_frame_rate,codec_type,has_b_frames",
        "-of", "json",
        file_path,
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        log.error("ffprobe failed: %s", proc.stderr[:300])
        return {"error": "ffprobe failed", "file": file_path}

    import json
    data = json.loads(proc.stdout)

    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    audio_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {}
    )
    fmt = data.get("format", {})

    # Parse FPS from r_frame_rate (e.g. "30000/1001")
    fps_str = video_stream.get("r_frame_rate", "0/1")
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        fps = 30.0

    file_size_mb = float(fmt.get("size", 0)) / (1024 * 1024)

    return {
        "duration_seconds": float(fmt.get("duration", 0)),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": round(fps, 2),
        "has_audio": bool(audio_stream),
        "file_size_mb": round(file_size_mb, 1),
        "codec": video_stream.get("codec_name", "unknown"),
    }
