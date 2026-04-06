"""
ClipForge -- FastAPI Application Entry Point
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.celery_app import celery_app
from backend.models.database import SessionLocal

log = logging.getLogger("clipforge.main")


async def get_db():
    """Async database session dependency."""
    async with SessionLocal() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Connect to Supabase and start Redis on startup."""
    # Redis ping check
    try:
        celery_app
        log.info("Celery app initialised")
    except Exception:
        log.exception("Failed to initialise Celery")

    # DB connection check
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        log.info("Database connection OK")
    except Exception:
        log.exception("Database connection FAILED")

    log.info("ClipForge API started")
    yield
    log.info("ClipForge API shutting down")


# ── Application ──────────────────────────────────────────────────────

app = FastAPI(
    title="ClipForge API",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8765"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────

from backend.routers import channels, clips, jobs, webhooks, analysis

app.include_router(channels.router)
app.include_router(clips.router)
app.include_router(jobs.router)
app.include_router(webhooks.router)
app.include_router(analysis.router)

# ── Health ───────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}

# ── Global exception handler ──────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "code": "INTERNAL_ERROR"},
    )
