"""
ClipForge -- Publisher Service
TikTok, YouTube Shorts, Instagram Reels upload.
API uploads for YouTube (official APIs); Playwright browser automation
for TikTok and Instagram (replaces fragile OAuth flows).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger("clipforge.publisher")

# ── Platform Cookie-file helpers ──────────────────────────────────────
def _cookies(platform: str) -> str:
    """Resolve the cookies JSON path for a platform from env vars.
    Env vars: TIKTOK_COOKIES_FILE, INSTAGRAM_COOKIES_FILE, ...
    """
    var = f"{platform.upper()}_COOKIES_FILE"
    path = os.getenv(var)
    if not path:
        raise FileNotFoundError(
            f"Browser auth required: set {var} to a cookies JSON file"
        )
    if not os.path.exists(path):
        raise FileNotFoundError(f"{var} file not found: {path}")
    return path


# ── TikTok (Playwright browser automation) ───────────────────────────

async def tiktok_upload(clip: dict, access_token: str) -> str:
    """
    Upload a video to TikTok via Playwright browser automation.
    Requires TIKTOK_COOKIES_FILE env var pointing to a cookies JSON file.
    The access_token parameter is kept for backward compatibility (unused).
    Returns a status string: 'published', 'pending', or raises on failure.
    """
    from backend.services.browser_publisher import publish_tiktok_browser

    video_path = clip.get("output_path", "")
    description = clip.get("hook_text", "Check out this clip")
    cookies_file = _cookies("tiktok")

    log.info("TikTok: publishing via browser (cookies=%s)", cookies_file)
    result = await publish_tiktok_browser(
        video_path=video_path,
        description=description,
        cookies_file=cookies_file,
    )
    return result


async def refresh_tiktok_token(refresh_token: str) -> dict:
    """Refresh TikTok OAuth access token.
    Kept for backward compatibility — not used in browser auth mode.
    """
    raise NotImplementedError(
        "Token refresh is not needed in browser auth mode. "
        "Update your TIKTOK_COOKIES_FILE with fresh session cookies instead."
    )


# ── YouTube Shorts (kept as-is; official API) ──────────────────────

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


# ── Instagram Reels (Playwright browser automation) ───────────────────

async def instagram_reels_upload(clip: dict, access_token: str, ig_user_id: str) -> str:
    """
    Publish a video to Instagram as a Reel via Playwright browser automation.
    Requires INSTAGRAM_COOKIES_FILE env var pointing to a cookies JSON file.
    The access_token and ig_user_id params are kept for backward compat (unused).
    Returns a status string: 'published'.
    """
    from backend.services.browser_publisher import publish_instagram_browser

    video_path = clip.get("storage_url", clip.get("output_path", ""))
    caption = clip.get("hook_text", "")[:]
    cookies_file = _cookies("instagram")

    log.info("Instagram: publishing via browser (cookies=%s)", cookies_file)
    result = await publish_instagram_browser(
        video_path=video_path,
        caption=caption,
        cookies_file=cookies_file,
    )
    return result
