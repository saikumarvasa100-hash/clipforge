"""
ClipForge -- Local Storage Manager
Handles uploading, retrieving, and serving clip files from the local filesystem.
Replaces Cloudflare R2 boto3 storage for self-hosted deployments.
"""
from __future__ import annotations

import logging
import os
import shutil

log = logging.getLogger("clipforge.local_storage")

# Default storage root; override with LOCAL_STORAGE_PATH env var
_STORAGE_ROOT = os.getenv("LOCAL_STORAGE_PATH", "/home/saiku/clipforge/storage")

CLIPS_SUBDIR = "clips"


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def get_storage_root() -> str:
    """Return the configured storage root directory."""
    _ensure_dir(_STORAGE_ROOT)
    return _STORAGE_ROOT


def get_clips_dir() -> str:
    """Return the clips subdirectory, creating it if needed."""
    clips_dir = os.path.join(get_storage_root(), CLIPS_SUBDIR)
    _ensure_dir(clips_dir)
    return clips_dir


def upload_clip(local_path: str, clip_id: str) -> str:
    """
    Copy a processed clip into the local storage directory.

    Args:
        local_path: Path to the source file on disk (e.g., from FFmpeg output dir).
        clip_id:      String identifier used as the output filename.

    Returns:
        Absolute filesystem path to the stored clip.
    """
    clips_dir = get_clips_dir()
    dest = os.path.join(clips_dir, f"{clip_id}.mp4")
    _ensure_dir(clips_dir)

    shutil.copy2(local_path, dest)
    log.info("Stored clip locally: %s -> %s", local_path, dest)
    return dest


def get_clip_path(clip_id: str) -> str | None:
    """
    Return the filesystem path for a stored clip, or None if it doesn't exist.
    """
    path = os.path.join(get_clips_dir(), f"{clip_id}.mp4")
    if os.path.isfile(path):
        return path
    return None


def delete_clip(clip_id: str) -> bool:
    """
    Remove a stored clip from local storage.

    Returns:
        True if the file was deleted, False if it didn't exist.
    """
    path = os.path.join(get_clips_dir(), f"{clip_id}.mp4")
    if os.path.isfile(path):
        os.remove(path)
        log.info("Deleted local clip: %s", path)
        return True
    return False
