"""
ClipForge -- Pydantic schemas for API validation.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    id: str
    email: str
    plan: str
    clips_used_this_month: int
    created_at: datetime
    class Config:
        from_attributes = True


class ChannelCreate(BaseModel):
    youtube_channel_id: str
    access_token: str
    refresh_token: Optional[str] = None


class ChannelResponse(BaseModel):
    id: str
    user_id: str
    youtube_channel_id: str
    channel_name: Optional[str]
    channel_thumbnail: Optional[str]
    is_active: bool
    last_checked_at: Optional[datetime]
    pubsub_expiry_at: Optional[datetime]
    created_at: datetime
    class Config:
        from_attributes = True


class ChannelListResponse(BaseModel):
    channels: List[ChannelResponse]
    total: int


class VideoResponse(BaseModel):
    id: str
    channel_id: str
    youtube_video_id: str
    title: Optional[str]
    duration_seconds: Optional[float]
    youtube_url: Optional[str]
    status: str
    transcript_path: Optional[str]
    created_at: datetime
    class Config:
        from_attributes = True


class ClipResponse(BaseModel):
    id: str
    video_id: str
    user_id: str
    start_time: float
    end_time: float
    hook_score: Optional[float]
    hook_text: Optional[str]
    output_path: Optional[str]
    storage_url: Optional[str]
    caption_data: Optional[Dict[str, Any]]
    virality_signals: Optional[Dict[str, Any]]
    status: str
    created_at: datetime
    class Config:
        from_attributes = True


class ClipListResponse(BaseModel):
    clips: List[ClipResponse]
    total: int
    page: int
    page_size: int


class PublishJobResponse(BaseModel):
    id: str
    clip_id: str
    platform: str
    status: str
    platform_post_id: Optional[str]
    published_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime
    class Config:
        from_attributes = True


class JobTriggerRequest(BaseModel):
    video_id: str


class JobStatusResponse(BaseModel):
    id: str
    video_id: Optional[str]
    status: str
    progress: float
    clip_count: int
    created_at: Optional[datetime]
    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    jobs: List[JobStatusResponse]
    total: int


class SubscriptionResponse(BaseModel):
    id: str
    user_id: str
    plan: str
    status: str
    current_period_end: datetime
    created_at: datetime
    class Config:
        from_attributes = True


class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"
