"""
ClipForge -- Celery Application Configuration
"""
from __future__ import annotations

import os
from datetime import timedelta
from celery import Celery

# ── Configuration ─────────────────────────────────────────────────────

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "clipforge",
    broker=REDIS_URL,
    backend=REDIS_URL,
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
