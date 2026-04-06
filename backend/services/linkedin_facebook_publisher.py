"""
ClipForge — LinkedIn & Facebook Publishing
Added to publisher.py for platforms beyond TikTok/YT/IG.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict

import httpx

log = logging.getLogger("clipforge.linkedin_facebook")

LINKEDIN_BASE = "https://api.linkedin.com/v2"
FACEBOOK_GRAPH = "https://graph.facebook.com/v18.0"


async def linkedin_video_upload(
    clip: dict,
    access_token: str,
    person_urn: str,
) -> str:
    """
    Publish a video to LinkedIn via the UGC API.
    3 steps: register upload → PUT binary → create UGC post.
    """
    file_path = clip.get("output_path", "")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Clip file not found: {file_path}")

    file_size = os.path.getsize(file_path)
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient() as client:
        # Step 1: Register upload
        register_url = f"{LINKEDIN_BASE}/assets?action=registerUpload"
        register_body = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-video"],
                "owner": person_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        resp = await client.post(register_url, json=register_body, headers=headers)
        resp.raise_for_status()
        upload_data = resp.json()
        upload_url = upload_data["value"]["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn = upload_data["value"]["asset"]

        log.info("LinkedIn upload registered: asset=%s, upload_url=%s", asset_urn, upload_url)

        # Step 2: PUT binary video
        with open(file_path, "rb") as f:
            upload_headers = {
                "Content-Type": "application/octet-stream",
                "Content-Length": str(file_size),
            }
            resp2 = await client.put(upload_url, data=f, headers=upload_headers)
            resp2.raise_for_status()

        log.info("LinkedIn video uploaded, creating post...")

        # Step 3: Create UGC post
        post_url = f"{LINKEDIN_BASE}/ugcPosts"
        post_body = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": clip.get("hook_text", "Check out this video")[:3000],
                    },
                    "shareMediaCategory": "VIDEO",
                    "media": [{"status": "READY", "entity": asset_urn}],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        resp3 = await client.post(post_url, json=post_body, headers=headers)
        resp3.raise_for_status()
        post_data = resp3.json()
        post_id = post_data.get("id", asset_urn)

        log.info("LinkedIn video published: post_id=%s", post_id)
        return str(post_id)


async def facebook_reels_upload(
    clip: dict,
    page_access_token: str,
    page_id: str,
) -> str:
    """
    Publish a video to Facebook Reels via Graph API.
    3 steps: start upload → upload bytes → finish.
    """
    file_path = clip.get("output_path", "")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Clip file not found: {file_path}")

    params = {"access_token": page_access_token}
    description = clip.get("hook_text", "")[:5000]
    title = clip.get("hook_text", "Clip")[:255]

    base_url = f"{FACEBOOK_GRAPH}/{page_id}/video_reels"

    async with httpx.AsyncClient(timeout=120) as client:
        # Step 1: Start upload
        start_resp = await client.post(
            base_url,
            params={**params, "upload_phase": "start"},
            data={
                "file_size": str(os.path.getsize(file_path)),
            },
        )
        start_resp.raise_for_status()
        video_id = start_resp.json().get("id", "")
        session_id = start_resp.json().get("video_session_id", "")

        log.info("Facebook Reels upload started: video_id=%s, session=%s", video_id, session_id)

        # Step 2: Upload video bytes
        with open(file_path, "rb") as f:
            upload_resp = await client.post(
                base_url,
                params={**params, "upload_phase": "transfer", "video_id": video_id},
                data={"file": f},
            )
            upload_resp.raise_for_status()

        log.info("Facebook Reels video uploaded")

        # Step 3: Finish upload
        finish_resp = await client.post(
            base_url,
            params={**params, "upload_phase": "finish", "video_id": video_id},
            data={"description": description, "title": title},
        )
        finish_resp.raise_for_status()
        result = finish_resp.json()
        post_id = result.get("id", video_id)

        log.info("Facebook Reels published: post_id=%s", post_id)
        return str(post_id)
