"""
ClipForge -- Publisher Service
TikTok Content Posting API v2, YouTube Shorts, Instagram Reels upload.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Dict, Optional

import httpx

log = logging.getLogger("clipforge.publisher")

# ── TikTok ────────────────────────────────────────────────────────────

TIKTOK_BASE = "https://open.tiktokapis.com/v2/post/publish"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token"
TIKTOK_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB per chunk

TIKTOK_POLL_MAX_ATTEMPTS = 200
TIKTOK_POLL_INTERVAL = 3  # seconds


async def tiktok_upload(clip: dict, access_token: str) -> str:
    """
    Upload a video to TikTok via the Content Posting API v2.
    Returns the published post_id.
    """
    file_path = clip.get("output_path", "")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Clip file not found: {file_path}")

    file_size = os.path.getsize(file_path)
    total_chunks = (file_size + TIKTOK_CHUNK_SIZE - 1) // TIKTOK_CHUNK_SIZE

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    # ── Step 1: Init upload ──────────────────────────────────────────
    init_url = f"{TIKTOK_BASE}/inbox/video/init/"
    init_body = {
        "post_info": {
            "title": clip.get("hook_text", "Check out this clip")[:150],
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": TIKTOK_CHUNK_SIZE,
            "total_chunk_count": total_chunks,
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(init_url, headers=headers, json=init_body)
        resp.raise_for_status()
        init_data = resp.json()

    publish_id = init_data["data"]["publish_id"]
    upload_url = init_data["data"]["upload_url"]
    log.info("TikTok upload init: publish_id=%s, upload_url=%s", publish_id, upload_url)

    # ── Step 2: Chunked upload ───────────────────────────────────────
    with open(file_path, "rb") as f:
        for chunk_idx in range(total_chunks):
            data = f.read(TIKTOK_CHUNK_SIZE)
            content_range = (
                f"bytes {chunk_idx * TIKTOK_CHUNK_SIZE}-"
                f"{min((chunk_idx + 1) * TIKTOK_CHUNK_SIZE, file_size) - 1}/"
                f"{file_size}"
            )
            up_headers = {
                **headers,
                "Content-Type": "video/mp4",
                "Content-Range": content_range,
            }
            log.info(
                "Uploading chunk %d/%d (range %s)",
                chunk_idx + 1, total_chunks, content_range,
            )
            async with httpx.AsyncClient(timeout=120) as client:
                await client.put(upload_url, headers=up_headers, content=data)

    # ── Step 3: Poll for publish status ──────────────────────────────
    status_url = f"{TIKTOK_BASE}/status/fetch/"
    for attempt in range(TIKTOK_POLL_MAX_ATTEMPTS):
        await asyncio.sleep(TIKTOK_POLL_INTERVAL)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                status_url,
                headers=headers,
                json={"publish_id": publish_id},
            )
            resp.raise_for_status()
            status_data = resp.json()

        status = status_data.get("data", {}).get("status", "")
        if status == "PUBLISH_COMPLETE":
            post_id = (
                status_data.get("data", {}).get("publicly_available_post_id", [None])[0]
                or publish_id
            )
            log.info("TikTok publish complete: post_id=%s", post_id)
            return str(post_id)

        public_id = status_data.get("data", {}).get("publicly_available_post_id", [])
        if public_id:
            return str(public_id[0])

    raise TimeoutError("TikTok publish did not complete within timeout")


async def refresh_tiktok_token(refresh_token: str) -> dict:
    """Refresh TikTok OAuth access token."""
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TIKTOK_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        resp.raise_for_status()
        return resp.json()


# ── YouTube Shorts ────────────────────────────────────────────────────

async def youtube_shorts_upload(clip: dict, credentials: dict) -> str:
    """Upload a short video to YouTube as a Shorts video."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials

    creds = Credentials(
        token=credentials["access_token"],
        refresh_token=credentials.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
    )

    youtube = build("youtube", "v3", credentials=creds)

    title = clip.get("hook_text", "Clip")[:100]
    description = clip.get("description", f"Powered by ClipForge")
    tags = clip.get("hashtags", [])

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "public",
            "madeForKids": False,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        clip["output_path"],
        mimetype="video/mp4",
        chunksize=10 * 1024 * 1024,
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = request.execute()
    video_id = response["id"]
    log.info("YouTube Shorts upload complete: video_id=%s", video_id)
    return video_id


# ── Instagram Reels ───────────────────────────────────────────────────

INSTAGRAM_GRAPH = "https://graph.facebook.com/v20.0"


async def instagram_reels_upload(clip: dict, access_token: str, ig_user_id: str) -> str:
    """
    Two-step Instagram Reels upload:
    1. POST /{user-id}/media to create container
    2. POST /{user-id}/media_publish to publish
    """
    file_path = clip.get("storage_url", clip.get("output_path", ""))
    caption = clip.get("hook_text", "")[:2200]

    params = {"access_token": access_token}

    async with httpx.AsyncClient(timeout=60) as client:
        # Step 1: Create media container
        container_url = f"{INSTAGRAM_GRAPH}/{ig_user_id}/media"
        container_data = {
            "video_url": file_path,
            "media_type": "REELS",
            "caption": caption,
        }
        resp = await client.post(container_url, params=params, json=container_data)
        resp.raise_for_status()
        container_id = resp.json()["id"]
        log.info("Instagram container created: %s", container_id)

        # Step 2: Check status until READY
        for _ in range(30):
            await asyncio.sleep(5)
            status_url = f"{INSTAGRAM_GRAPH}/{container_id}"
            resp = await client.get(status_url, params=params)
            status = resp.json().get("status_code", "")
            if status in ("FINISHED", "PUBLISHED", "PROCESSING_COMPLETE"):
                break
            if status == "ERROR":
                raise RuntimeError(f"Instagram media processing error: {resp.json()}")

        # Step 3: Publish
        publish_url = f"{INSTAGRAM_GRAPH}/{ig_user_id}/media_publish"
        publish_data = {"creation_id": container_id}
        resp = await client.post(publish_url, params=params, json=publish_data)
        resp.raise_for_status()
        media_id = resp.json()["id"]
        log.info("Instagram Reels published: media_id=%s", media_id)
        return media_id
