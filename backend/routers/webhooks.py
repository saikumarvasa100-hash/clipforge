"""
ClipForge -- API Router: webhooks.py
YouTube PubSubHubbub + Stripe webhook handlers.
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
        log.info(
            "PubSub verified: mode=%s, topic=%s, lease=%s",
            hub_mode, hub_topic, hub_lease_seconds,
        )
        return PlainTextResponse(content=hub_challenge, status_code=200)
    raise HTTPException(status_code=400, detail="Invalid PubSub params")


@router.post("/youtube", status_code=204)
async def youtube_webhook_post(request: Request):
    """
    Receive PubSubHubbub video notification (Atom XML).
    Extract video_id and channel_id, then forward to backend /jobs/trigger.
    """
    body = await request.body()
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        log.warning("Invalid Atom XML from YouTube PubSub")
        raise HTTPException(status_code=400, detail="Invalid Atom XML")

    ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

    # Extract channel_id and video_id from Atom entry
    channel_id_el = root.find(".//yt:channelId", ns)
    video_id_el = root.find(".//yt:videoId", ns)

    if channel_id_el is None or video_id_el is None:
        log.warning("Missing channelId or videoId in PubSub notification")
        raise HTTPException(status_code=400, detail="Missing required fields")

    channel_id = channel_id_el.text
    video_id = video_id_el.text
    log.info("PubSub new video: channel=%s, video=%s", channel_id, video_id)

    # Forward to backend jobs trigger
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                "http://localhost:8000/api/jobs/trigger",
                json={"video_id": video_id, "channel_id": channel_id},
            )
    except Exception:
        log.exception("Failed to forward PubSub notification to jobs trigger")

    return Response(status_code=204)


# ── Stripe ────────────────────────────────────────────────────────────

@router.post("/stripe", status_code=200)
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events:
    - checkout.session.completed
    - customer.subscription.updated
    - customer.subscription.deleted
    Verify signature with stripe.webhooks.constructEvent().
    """
    import json
    import os
    import stripe

    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(body, sig_header, webhook_secret)
    except ValueError:
        log.warning("Invalid Stripe webhook payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        log.warning("Invalid Stripe webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    log.info("Stripe webhook event: %s", event_type)

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data)
    else:
        log.info("Unhandled Stripe event: %s", event_type)

    return {"received": True}


async def _handle_checkout_completed(session: dict):
    """checkout.session.completed -- update user plan in DB."""
    from backend.models.database import User, SessionLocal
    from sqlalchemy import update

    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    plan = session.get("metadata", {}).get("plan", "pro")

    async with SessionLocal() as db:
        await db.execute(
            update(User)
            .where(User.stripe_customer_id == customer_id)
            .values(plan=plan)
        )
        await db.commit()
    log.info("Checkout completed: customer=%s, plan=%s", customer_id, plan)


async def _handle_subscription_updated(sub: dict):
    """customer.subscription.updated -- update plan and period end."""
    from backend.models.database import User, Subscription, SessionLocal
    from sqlalchemy import select, update
    from datetime import datetime, timezone

    customer_id = sub.get("customer")
    plan = sub.get("metadata", {}).get("plan", "pro")
    period_end = datetime.fromtimestamp(sub["current_period_end"], tz=timezone.utc)
    status = sub.get("status", "active")

    async with SessionLocal() as db:
        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            log.warning("No user for stripe customer %s", customer_id)
            return

        # Update or create subscription record
        result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.stripe_subscription_id == sub["id"],
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.plan = plan
            existing.status = status
            existing.current_period_end = period_end
        else:
            db.add(Subscription(
                user_id=user.id,
                stripe_subscription_id=sub["id"],
                plan=plan,
                status=status,
                current_period_end=period_end,
            ))

        user.plan = plan
        await db.commit()
    log.info("Subscription updated: customer=%s, plan=%s", customer_id, plan)


async def _handle_subscription_deleted(sub: dict):
    """customer.subscription.deleted -- downgrade user to free."""
    from backend.models.database import User, Subscription, SessionLocal
    from sqlalchemy import select, update

    customer_id = sub.get("customer")

    async with SessionLocal() as db:
        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            log.warning("No user for stripe customer %s", customer_id)
            return

        user.plan = "free"
        user.clips_used_this_month = 0

        # Mark subscription as cancelled
        result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.stripe_subscription_id == sub.get("id"),
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.status = "cancelled"

        await db.commit()
    log.info("Subscription deleted / downgraded: customer=%s", customer_id)
