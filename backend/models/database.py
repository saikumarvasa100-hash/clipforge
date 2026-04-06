"""
ClipForge -- Database Models (SQLAlchemy ORM)
Supabase/PostgreSQL schema with 6 tables + indexes.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, Text, ForeignKey,
    Enum as SAEnum, Index, func, JSON, create_engine
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://clipforge:clipforge_local@localhost:5432/clipforge")

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


class VideoStatus(PyEnum):
    PENDING = "pending"
    TRANSCRIBED = "transcribed"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class ClipStatus(PyEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class PublishStatus(PyEnum):
    QUEUED = "queued"
    UPLOADING = "uploading"
    PUBLISHED = "published"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    stripe_customer_id = Column(String(255), nullable=True, index=True)
    plan = Column(String(20), nullable=False, default="free")
    clips_used_this_month = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    channels = relationship("Channel", back_populates="user", cascade="all, delete-orphan")
    clips = relationship("Clip", back_populates="user", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_users_email", "email"), Index("ix_users_stripe", "stripe_customer_id"))


class Channel(Base):
    __tablename__ = "channels"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    youtube_channel_id = Column(String(255), nullable=False, index=True)
    channel_name = Column(String(255), nullable=True)
    channel_thumbnail = Column(Text, nullable=True)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    pubsub_lease_seconds = Column(Integer, nullable=True)
    pubsub_expiry_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="channels")
    videos = relationship("Video", back_populates="channel", cascade="all, delete-orphan")
    __table_args__ = (
        Index("ix_channels_user", "user_id"),
        Index("ix_channels_yt", "youtube_channel_id"),
        Index("ix_channels_pubsub", "pubsub_expiry_at"),
    )


class Video(Base):
    __tablename__ = "videos"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id = Column(UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True)
    youtube_video_id = Column(String(255), nullable=False, index=True)
    title = Column(String(1000), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    youtube_url = Column(Text, nullable=True)
    download_path = Column(Text, nullable=True)
    transcript_path = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    channel = relationship("Channel", back_populates="videos")
    clips = relationship("Clip", back_populates="video", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_videos_channel", "channel_id"), Index("ix_videos_yt", "youtube_video_id"), Index("ix_videos_status", "status"))


class Clip(Base):
    __tablename__ = "clips"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    hook_score = Column(Float, nullable=True)
    hook_text = Column(Text, nullable=True)
    output_path = Column(Text, nullable=True)
    storage_url = Column(Text, nullable=True)
    caption_data = Column(JSON, nullable=True)
    virality_signals = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    video = relationship("Video", back_populates="clips")
    user = relationship("User", back_populates="clips")
    publish_jobs = relationship("PublishJob", back_populates="clip", cascade="all, delete-orphan")
    __table_args__ = (
        Index("ix_clips_video", "video_id"), Index("ix_clips_user", "user_id"),
        Index("ix_clips_hook", "hook_score"), Index("ix_clips_status", "status"), Index("ix_clips_created", "created_at"),
    )


class PublishJob(Base):
    __tablename__ = "publish_jobs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clip_id = Column(UUID(as_uuid=True), ForeignKey("clips.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    platform_post_id = Column(String(255), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    clip = relationship("Clip", back_populates="publish_jobs")
    __table_args__ = (Index("ix_pj_clip", "clip_id"), Index("ix_pj_status", "status"), Index("ix_pj_platform", "platform"))


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    stripe_subscription_id = Column(String(255), nullable=False, unique=True)
    plan = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    current_period_end = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="subscriptions")
    __table_args__ = (Index("ix_sub_user", "user_id"), Index("ix_sub_stripe", "stripe_subscription_id"))
