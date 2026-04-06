"""
ClipForge — LinkedIn & Facebook Publishing (Playwright browser automation)
Replaces the old OAuth + Graph API flows with headless browser uploads.
Uses cookie-based auth — export session cookies from your browser (JSON).

Environment variables:
  LINKEDIN_COOKIES_FILE  — path to cookies JSON for linkedin.com
  FACEBOOK_COOKIES_FILE  — path to cookies JSON for facebook.com
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("clipforge.linkedin_facebook")


def _cookies(platform: str) -> str:
    """Resolve the cookies JSON path for a platform from env vars."""
    var = f"{platform.upper()}_COOKIES_FILE"
    path = os.getenv(var)
    if not path:
        raise FileNotFoundError(
            f"Browser auth required: set {var} to a cookies JSON file"
        )
    if not os.path.exists(path):
        raise FileNotFoundError(f"{var} file not found: {path}")
    return path


async def linkedin_video_upload(
    clip: dict,
    access_token: str,
    person_urn: str,
) -> str:
    """
    Publish a video to LinkedIn via Playwright browser automation.
    Requires LINKEDIN_COOKIES_FILE env var.
    access_token and person_urn kept for backward compat (unused).
    """
    from backend.services.browser_publisher import publish_linkedin_browser

    cookies_file = _cookies("linkedin")
    video_path = clip.get("output_path", "")
    description = clip.get("hook_text", "Check out this video")[:3000]

    log.info("LinkedIn: publishing via browser (cookies=%s)", cookies_file)
    result = await publish_linkedin_browser(
        video_path=video_path,
        description=description,
        cookies_file=cookies_file,
    )
    return result


async def facebook_reels_upload(
    clip: dict,
    page_access_token: str,
    page_id: str,
) -> str:
    """
    Publish a video to Facebook via Playwright browser automation.
    Requires FACEBOOK_COOKIES_FILE env var.
    page_access_token and page_id kept for backward compat (unused).
    """
    from backend.services.browser_publisher import publish_facebook_browser

    cookies_file = _cookies("facebook")
    video_path = clip.get("output_path", "")
    description = clip.get("hook_text", "")[:5000]

    log.info("Facebook: publishing via browser (cookies=%s)", cookies_file)
    result = await publish_facebook_browser(
        video_path=video_path,
        description=description,
        cookies_file=cookies_file,
    )
    return result
