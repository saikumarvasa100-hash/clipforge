"""
ClipForge -- YouTube Service
Subscribe to PubSubHubbub, download videos, resolve channel info.
"""
from __future__ import annotations

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
YT_DATA_API = "https://www.googleapis.com/youtube/v3"


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


# ── Video fetching ────────────────────────────────────────────────────

async def fetch_latest_video(channel_id: str) -> Optional[Dict]:
    """Use YouTube Data API v3 to get the latest video for a channel."""
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        log.warning("YOUTUBE_API_KEY not set — skipping fetch_latest_video")
        return None

    url = f"{YT_DATA_API}/search"
    params = {
        "part": "snippet,id",
        "channelId": channel_id,
        "order": "date",
        "maxResults": 1,
        "type": "video",
        "key": api_key,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    items = data.get("items", [])
    if not items:
        return None

    item = items[0]
    video_id = item["id"]["videoId"]
    snippet = item["snippet"]

    # resolve duration
    dur_url = f"{YT_DATA_API}/videos"
    dur_params = {"part": "contentDetails", "id": video_id, "key": api_key}
    dur_resp = await client.get(dur_url, params=dur_params)
    dur_data = dur_resp.json()
    duration_raw = dur_data["items"][0]["contentDetails"]["duration"]
    duration_sec = _parse_iso8601_duration(duration_raw)

    return {
        "video_id": video_id,
        "title": snippet["title"],
        "duration_seconds": duration_sec,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


async def download_video_audio(youtube_url: str, output_path: str) -> str:
    """Download best audio from YouTube using yt-dlp."""
    import subprocess

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


# ── Channel info ──────────────────────────────────────────────────────

async def get_channel_info(channel_id: str) -> Dict:
    """Return channel name, thumbnail URL, subscriber count."""
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    url = f"{YT_DATA_API}/channels"
    params = {
        "part": "snippet,statistics",
        "id": channel_id,
        "key": api_key,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    items = data.get("items", [])
    if not items:
        return {"error": "Channel not found"}

    snippet = items[0]["snippet"]
    stats = items[0]["statistics"]
    return {
        "name": snippet["title"],
        "thumbnail": snippet["thumbnails"]["high"]["url"],
        "subscribers": stats.get("subscriberCount", "hidden"),
    }


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


# Import asyncio at top for the download function
import asyncio
