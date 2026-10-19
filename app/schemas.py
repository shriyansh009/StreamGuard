"""Pydantic v2 request/response schemas for StreamGuard API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Auth Schemas ──────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    """Schema for user registration requests."""
    username: str = Field(..., min_length=3, max_length=64, description="Unique username")
    password: str = Field(..., min_length=8, description="Password (min 8 characters)")


class UserLogin(BaseModel):
    """Schema for user login requests."""
    username: str = Field(..., description="Username")
    password: str = Field(..., description="Password")


class TokenResponse(BaseModel):
    """Schema for JWT token responses."""
    access_token: str
    token_type: str = "bearer"


# ── WebSocket Schemas ─────────────────────────────────────────────────────────

class WebSocketMessage(BaseModel):
    """Schema for incoming WebSocket chat messages."""
    content: str = Field(..., max_length=2000, description="Message content (max 2000 chars)")
    room_id: str = Field(..., description="Target chat room ID")


# ── Moderation Schemas ────────────────────────────────────────────────────────

class ModerationResult(BaseModel):
    """Schema for content moderation analysis results."""
    message_id: str
    flagged: bool
    toxicity_score: float = Field(..., ge=0.0, le=1.0)
    action_taken: str = Field(..., description="'allowed', 'flagged', or 'blocked'")
    matched_patterns: list[str] = Field(default_factory=list)


# ── Analytics Schemas ─────────────────────────────────────────────────────────

class AnalyticsQuery(BaseModel):
    """Schema for analytics query parameters."""
    room_id: Optional[str] = None
    user_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    interval_minutes: int = Field(default=60, ge=1, le=1440, description="Aggregation interval in minutes")


class AnalyticsResponse(BaseModel):
    """Schema for a single analytics time-series data point."""
    interval_start: datetime
    interval_end: datetime
    total_messages: int
    flagged_messages: int
    avg_toxicity_score: float
    top_patterns: list[str] = Field(default_factory=list)


class RoomStatsResponse(BaseModel):
    """Schema for per-room statistics."""
    room_id: str
    total_messages: int
    flagged_messages: int
    flagged_percentage: float
    avg_toxicity_score: float
    active_users: int


class TopViolatorResponse(BaseModel):
    """Schema for top violator rankings."""
    user_id: str
    username: str
    flagged_count: int
    total_messages: int
    avg_toxicity_score: float


# ── Health Schemas ────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Schema for system health check responses."""
    status: str
    redis_connected: bool
    db_connected: bool
    uptime_seconds: float
    active_workers: int = 0
