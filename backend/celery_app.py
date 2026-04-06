"""
ClipForge -- Celery Application Configuration
"""
from __future__ import annotations

import os
from datetime import timedelta
from celery import Celery

# ── Configuration ─────────────────────────────────────────────────────

# Redis or local filesystem fallback (no external deps needed)
REDIS_URL = os.getenv("REDIS_URL", "")
if REDIS_URL:
    broker = REDIS_URL
    backend_broker = REDIS_URL
else:
    # No redis-server? Use memory broker (tasks run in-process)
    # OR use filesystem as last resort
    try:
        import redis
        r = redis.Redis()
        r.ping()
        broker = REDIS_URL or "redis://localhost:6379/0"
        backend_broker = broker
        print("Redis available, using redis broker")
    except:
        # No redis, use memory broker (tasks inline)
        broker = "memory://"
        backend_broker = "cache+"

celery_app = Celery(
    "clipforge",
    broker=broker,
    backend=backend_broker,
)

# ── Celery Settings ───────────────────────────────────────────────────

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "backend.tasks.transcribe.*": {"queue": "transcription"},
        "backend.tasks.score_virality.*": {"queue": "processing"},
        "backend.tasks.cut_clips.*": {"queue": "processing"},
        "backend.tasks.publish.*": {"queue": "publishing"},
    },
    task_default_queue="default",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Retry settings
    task_annotations={
        "*": {
            "max_retries": 3,
            "default_retry_delay": 60,
        }
    },
    # Beat schedule
    beat_schedule={
        "check-new-videos": {
            "task": "backend.tasks.publish.publish_clips",
            "schedule": timedelta(minutes=5),
            "options": {"queue": "publishing"},
        },
        "renew-pubsub-subscriptions": {
            "task": "backend.services.youtube.renew_expiring_subscriptions",
            "schedule": timedelta(hours=12),
        },
    },
)

# ── Autodiscover tasks ────────────────────────────────────────────────

celery_app.autodiscover_tasks(packages=["backend.tasks"])
