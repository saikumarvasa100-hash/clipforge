"""
ClipForge -- API Router: webhooks.py
YouTube PubSubHubbub only. No Stripe -- billing is local-only.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

log = logging.getLogger("clipforge.webhooks_router")

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


# ── YouTube PubSubHubbub ─────────────────────────────────────────────

@router.get("/youtube")
async def youtube_webhook_get(
    hub_mode: Optional[str] = None,
    hub_topic: Optional[str] = None,
    hub_challenge: Optional[str] = None,
    hub_lease_seconds: Optional[str] = None,
):
    """PubSubHubbub subscription verification -- return hub.challenge."""
    if hub_mode == "subscribe" and hub_challenge:
        log.info("PubSub verified: mode=%s, topic=%s, lease=%s", hub_mode, hub_topic, hub_lease_seconds)
        return PlainTextResponse(content=hub_challenge, status_code=200)
    raise HTTPException(status_code=400, detail="Invalid PubSub params")


@router.post("/youtube", status_code=204)
async def youtube_webhook_post(request: Request):
    """
    Receive PubSubHubbub video notification (Atom XML).
    Parse Atom feed, extract video_id and channel_id,
    forward to backend jobs trigger.
    """
    body = await request.body()
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        log.warning("Invalid Atom XML from YouTube PubSub")
        raise HTTPException(status_code=400, detail="Invalid Atom XML")

    ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

    channel_id_el = root.find(".//yt:channelId", ns)
    video_id_el = root.find(".//yt:videoId", ns)

    if channel_id_el is None or video_id_el is None:
        log.warning("Missing channelId or videoId in PubSub notification")
        raise HTTPException(status_code=400, detail="Missing required fields")

    channel_id = channel_id_el.text
    video_id = video_id_el.text
    log.info("PubSub new video: channel=%s, video=%s", channel_id, video_id)

    # Forward to local jobs trigger
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                "http://localhost:8000/api/jobs/trigger",
                json={"video_id": video_id, "channel_id": channel_id},
            )
    except Exception:
        log.exception("Failed to forward PubSub notification")

    return Response(status_code=204)


# ── Health / Status ──────────────────────────────────────────────────

@router.get("/health")
async def health():
    """Simple health check endpoint for uptime monitors."""
    return {"status": "ok", "service": "clipforge", "self_hosted": True}
