"""Time-series analytics REST API routes for StreamGuard (Phase 6).

Provides aggregated toxicity trends, top violators, and per-room statistics
with Redis snapshot caching for fast repeated queries.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.moderation_log import ModerationLog
from app.models.user import User
from app.redis_client import redis_manager
from app.schemas import AnalyticsResponse, RoomStatsResponse, TopViolatorResponse

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


async def _get_cached_or_compute(cache_key: str, compute_fn, ttl: int | None = None) -> dict | list:
    """Check Redis cache first; on miss, compute, cache, and return.

    Args:
        cache_key: Redis key for the cached result.
        compute_fn: Async callable that computes the result.
        ttl: Cache TTL in seconds (defaults to settings.CACHE_TTL_SECONDS).

    Returns:
        Cached or freshly computed result.
    """
    effective_ttl = ttl or settings.CACHE_TTL_SECONDS
    try:
        if redis_manager.is_initialized:
            cached = await redis_manager.cache_client.get(cache_key)
            if cached:
                logger.debug("Cache HIT for key '%s'", cache_key)
                return json.loads(cached)
    except Exception as e:
        logger.warning("Cache read error for '%s': %s", cache_key, e)

    # Cache miss — compute result
    result = await compute_fn()

    # Store in cache
    try:
        if redis_manager.is_initialized:
            await redis_manager.cache_client.set(
                cache_key,
                json.dumps(result, default=str),
                ex=effective_ttl,
            )
            logger.debug("Cached result for key '%s' (TTL=%ds)", cache_key, effective_ttl)
    except Exception as e:
        logger.warning("Cache write error for '%s': %s", cache_key, e)

    return result


@router.get("/toxicity-trends", response_model=list[AnalyticsResponse])
async def get_toxicity_trends(
    room_id: Optional[str] = Query(None, description="Filter by room ID"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    start_time: Optional[datetime] = Query(None, description="Start of time range (ISO 8601)"),
    end_time: Optional[datetime] = Query(None, description="End of time range (ISO 8601)"),
    interval_minutes: int = Query(60, ge=1, le=1440, description="Aggregation interval in minutes"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get time-series toxicity data grouped by configurable time intervals.

    Uses SQL date_trunc to bucket moderation logs and compute per-interval
    aggregate statistics (total messages, flagged count, avg toxicity).

    Results are cached in Redis with configurable TTL.
    """
    # Build cache key from query parameters
    cache_key = f"analytics:trends:{room_id}:{user_id}:{start_time}:{end_time}:{interval_minutes}"

    async def compute():
        # Default time range: last 24 hours
        now = datetime.now(timezone.utc)
        effective_start = start_time or (now - timedelta(hours=24))
        effective_end = end_time or now

        # Determine PostgreSQL interval string
        if interval_minutes < 60:
            trunc_unit = "minute"
        elif interval_minutes < 1440:
            trunc_unit = "hour"
        else:
            trunc_unit = "day"

        # Build query with time bucketing
        stmt = (
            select(
                func.date_trunc(trunc_unit, ModerationLog.created_at).label("interval_start"),
                func.count().label("total_messages"),
                func.sum(func.cast(ModerationLog.flagged, type_=func.coalesce.type)).label("flagged_messages"),
                func.avg(ModerationLog.toxicity_score).label("avg_toxicity_score"),
            )
            .where(ModerationLog.created_at >= effective_start)
            .where(ModerationLog.created_at <= effective_end)
        )

        if room_id:
            stmt = stmt.where(ModerationLog.room_id == room_id)
        if user_id:
            stmt = stmt.where(ModerationLog.user_id == user_id)

        stmt = stmt.group_by("interval_start").order_by("interval_start")

        result = await db.execute(stmt)
        rows = result.all()

        trends = []
        for row in rows:
            interval_start = row.interval_start
            interval_end_dt = interval_start + timedelta(minutes=interval_minutes)
            trends.append({
                "interval_start": interval_start.isoformat(),
                "interval_end": interval_end_dt.isoformat(),
                "total_messages": row.total_messages or 0,
                "flagged_messages": int(row.flagged_messages or 0),
                "avg_toxicity_score": round(float(row.avg_toxicity_score or 0.0), 4),
                "top_patterns": [],
            })
        return trends

    return await _get_cached_or_compute(cache_key, compute)


@router.get("/top-violators", response_model=list[TopViolatorResponse])
async def get_top_violators(
    limit: int = Query(10, ge=1, le=100, description="Number of top violators to return"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get top users ranked by flagged message count.

    Returns top N users with the highest number of flagged moderation entries,
    along with their total message count and average toxicity score.

    Results are cached in Redis.
    """
    cache_key = f"analytics:top_violators:{limit}"

    async def compute():
        stmt = (
            select(
                ModerationLog.user_id,
                User.username,
                func.count().filter(ModerationLog.flagged.is_(True)).label("flagged_count"),
                func.count().label("total_messages"),
                func.avg(ModerationLog.toxicity_score).label("avg_toxicity_score"),
            )
            .join(User, User.id == ModerationLog.user_id)
            .group_by(ModerationLog.user_id, User.username)
            .order_by(func.count().filter(ModerationLog.flagged.is_(True)).desc())
            .limit(limit)
        )

        result = await db.execute(stmt)
        rows = result.all()

        return [
            {
                "user_id": str(row.user_id),
                "username": row.username,
                "flagged_count": row.flagged_count or 0,
                "total_messages": row.total_messages or 0,
                "avg_toxicity_score": round(float(row.avg_toxicity_score or 0.0), 4),
            }
            for row in rows
        ]

    return await _get_cached_or_compute(cache_key, compute)


@router.get("/room-stats/{room_id}", response_model=RoomStatsResponse)
async def get_room_stats(
    room_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get aggregate statistics for a specific chat room.

    Returns total messages, flagged percentage, average toxicity score,
    and number of distinct active users.

    Results are cached in Redis.
    """
    cache_key = f"analytics:room_stats:{room_id}"

    async def compute():
        stmt = (
            select(
                func.count().label("total_messages"),
                func.count().filter(ModerationLog.flagged.is_(True)).label("flagged_messages"),
                func.avg(ModerationLog.toxicity_score).label("avg_toxicity_score"),
                func.count(func.distinct(ModerationLog.user_id)).label("active_users"),
            )
            .where(ModerationLog.room_id == room_id)
        )

        result = await db.execute(stmt)
        row = result.one()

        total = row.total_messages or 0
        flagged = row.flagged_messages or 0
        flagged_pct = round((flagged / total * 100) if total > 0 else 0.0, 2)

        return {
            "room_id": room_id,
            "total_messages": total,
            "flagged_messages": flagged,
            "flagged_percentage": flagged_pct,
            "avg_toxicity_score": round(float(row.avg_toxicity_score or 0.0), 4),
            "active_users": row.active_users or 0,
        }

    return await _get_cached_or_compute(cache_key, compute)
