"""
ClipForge -- YouTube Service
Subscribe to PubSubHubbub, download videos, resolve channel info.
All YouTube operations use yt-dlp (no YouTube Data API dependency).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
from urllib.parse import urlencode

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import Channel, Video, SessionLocal

log = logging.getLogger("clipforge.youtube")

PUBSUB_SUBSCRIBE_URL = "https://pubsubhubbub.appspot.com/subscribe"

# ── PubSubHubbub ─────────────────────────────────────────────────────

async def subscribe_to_channel(channel_id: str) -> dict:
    """Send a subscription request to YouTube's PubSubHubbub feed."""
    callback_url = _callback_url()
    topic = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}"

    params = {
        "hub.mode": "subscribe",
        "hub.topic": topic,
        "hub.callback": callback_url,
        "hub.lease_seconds": 864000,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(PUBSUB_SUBSCRIBE_URL, data=urlencode(params))
        resp.raise_for_status()

    expiry = datetime.now(timezone.utc) + timedelta(days=10)
    return {
        "lease_seconds": 864000,
        "pubsub_expiry_at": expiry,
        "status": resp.status_code,
    }


async def renew_expiring_subscriptions(db: AsyncSession) -> int:
    """Re-subscribe to channels whose PubSub lease expires within 2 days."""
    threshold = datetime.now(timezone.utc) + timedelta(days=2)
    stmt = select(Channel).where(
        Channel.is_active == True,
        Channel.pubsub_expiry_at < threshold,
    )
    result = await db.execute(stmt)
    channels = result.scalars().all()

    renewed = 0
    for ch in channels:
        try:
            info = await subscribe_to_channel(ch.youtube_channel_id)
            await db.execute(
                update(Channel)
                .where(Channel.id == ch.id)
                .values(
                    pubsub_lease_seconds=info["lease_seconds"],
                    pubsub_expiry_at=info["pubsub_expiry_at"],
                )
            )
            renewed += 1
            log.info("Renewed PubSub for channel %s", ch.youtube_channel_id)
        except Exception:
            log.exception("Failed to renew PubSub for %s", ch.youtube_channel_id)

    await db.commit()
    return renewed


# ── Channel info ──────────────────────────────────────────────────────

async def get_channel_info(channel_id: str) -> Dict:
    """Return channel name, thumbnail URL, subscriber count using yt-dlp."""
    channel_url = f"https://www.youtube.com/channel/{channel_id}"

    # Grab channel name and thumbnail
    name_thumb_cmd = [
        "yt-dlp",
        "--print", "%(channel)s|%(channel_id)s|%(thumbnail)s",
        "--no-download",
        "--skip-download",
        channel_url,
    ]

    # Attempt to grab subscriber count (may be hidden or unavailable)
    sub_cmd = [
        "yt-dlp",
        "--print", "%(channel_follower_count)s",
        "--no-download",
        "--skip-download",
        channel_url,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *name_thumb_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0 or not stdout:
            log.error(
                "yt-dlp channel info failed: %s",
                stderr.decode(errors="replace")[:300],
            )
            return {"error": "Failed to fetch channel info"}

        output = stdout.decode(errors="replace").strip()
        parts = output.split("|")

        name = parts[0].strip() if len(parts) > 0 else ""
        thumbnail = parts[2].strip() if len(parts) > 2 else ""

        # Try subscriber count separately (often returns 'NA')
        subscriber_count = "hidden"
        try:
            sub_proc = await asyncio.create_subprocess_exec(
                *sub_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            sub_stdout, _ = await sub_proc.communicate()
            sub_raw = sub_stdout.decode(errors="replace").strip()
            if sub_raw and sub_raw != "NA":
                subscriber_count = int(sub_raw)
        except (ValueError, Exception):
            pass

        if not name:
            return {"error": "Channel not found or name unavailable"}

        return {
            "name": name,
            "thumbnail": thumbnail,
            "subscribers": subscriber_count,
        }

    except Exception:
        log.exception("yt-dlp channel info error for %s", channel_id)
        return {"error": "Failed to fetch channel info"}


# ── Video fetching ────────────────────────────────────────────────────

async def fetch_latest_video(channel_id: str) -> Optional[Dict]:
    """Use yt-dlp to get the latest video from a channel."""
    channel_url = f"https://www.youtube.com/channel/{channel_id}"

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--print", "%(id)s|%(title)s|%(duration)s",
        "--playlist-end", "1",
        channel_url,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            log.warning(
                "yt-dlp fetch_latest_video for %s: %s",
                channel_id,
                stderr.decode(errors="replace")[:300],
            )
            return None

        line = stdout.decode(errors="replace").strip()
        if not line:
            return None

        parts = line.split("|")
        video_id = parts[0].strip() if len(parts) > 0 else ""
        title = parts[1].strip() if len(parts) > 1 else ""
        duration_raw = parts[2].strip() if len(parts) > 2 else "0"

        if not video_id or video_id == "NA":
            return None

        # yt-dlp flat-playlist returns duration as an integer (seconds)
        # or "NA" / "none" if unavailable
        try:
            duration_sec = int(duration_raw)
        except (ValueError, TypeError):
            duration_sec = 0

        return {
            "video_id": video_id,
            "title": title,
            "duration_seconds": duration_sec,
            "url": f"https://www.youtube.com/watch?v={video_id}",
        }

    except Exception:
        log.exception("yt-dlp fetch_latest_video error for %s", channel_id)
        return None


async def download_video_audio(youtube_url: str, output_path: str) -> str:
    """Download best audio from YouTube using yt-dlp."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", "mp4a",
        "--audio-quality", "0",
        "-o", output_path,
        "--no-playlist",
        youtube_url,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        log.error("yt-dlp failed: %s", stderr.decode(errors="replace")[:500])
        raise RuntimeError(f"yt-dlp download failed: {stderr.decode(errors='replace')[:300]}")

    # yt-dlp may add an extension
    if os.path.exists(output_path):
        return output_path
    # try common extensions
    for ext in (".mp4a", ".m4a", ".mp4", ".webm"):
        candidate = output_path + ext
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(f"Expected output not found: {output_path}")


# ── Helpers ───────────────────────────────────────────────────────────

def _callback_url() -> str:
    base = os.getenv("PUBSUBHUBBUB_CALLBACK_URL", "http://localhost:8000")
    return f"{base.rstrip('/')}/api/webhooks/youtube"


def _parse_iso8601_duration(duration: str) -> float:
    """Parse ISO 8601 duration e.g. PT1H2M3S -> seconds."""
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration
    )
    if not match:
        return 0.0
    h, m, s = (int(g or 0) for g in match.groups())
    return h * 3600 + m * 60 + s
