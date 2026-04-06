"""
ClipForge -- FastAPI Application Entry Point (Self-Hosted)
"""
from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

log = logging.getLogger("clipforge.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    from backend.models.database import init_db
    try:
        init_db()
        log.info("Database tables created/verified")
    except Exception as e:
        log.warning("DB check: %s", e)
    log.info("ClipForge API started -- 100%% self-hosted, zero paid APIs")
    yield
    log.info("ClipForge shutting down")


app = FastAPI(title="ClipForge API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from backend.routers import channels, clips, jobs, webhooks, analysis
app.include_router(channels.router)
app.include_router(clips.router)
app.include_router(jobs.router)
app.include_router(webhooks.router)
app.include_router(analysis.router)

# Frontend -- static SPA dashboard
FRONTEND_STATIC = "/home/saiku/clipforge/frontend_static"
os.makedirs(FRONTEND_STATIC, exist_ok=True)

@app.get("/")
async def index():
    return FileResponse(os.path.join(FRONTEND_STATIC, "dashboard.html"))

@app.get("/dashboard")
async def dashboard_page():
    return FileResponse(os.path.join(FRONTEND_STATIC, "dashboard.html"))

@app.get("/channels")
async def channels_page():
    return FileResponse(os.path.join(FRONTEND_STATIC, "dashboard.html"))

@app.get("/clips")
async def clips_page():
    return FileResponse(os.path.join(FRONTEND_STATIC, "dashboard.html"))

@app.get("/analytics")
async def analytics_page():
    return FileResponse(os.path.join(FRONTEND_STATIC, "dashboard.html"))

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "self_hosted": True}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content={"detail": str(exc)})
