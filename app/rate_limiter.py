"""StreamGuard Redis-Based Sliding Window Rate Limiter.

Tracks user moderation violations in real-time using Redis sorted sets (ZSET),
pruning expired infractions on the fly and enforcing temporary blacklists
when violations exceed configured thresholds.
"""

import logging
import os
import time
import uuid
from typing import Any, Dict, Optional, Union

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window rate limiter for tracking user moderation violations.

    Uses Redis Sorted Sets (ZSET) where scores represent timestamps of violations.
    When a user breaches the violation threshold within the rolling time window,
    they are automatically blacklisted for a defined cooldown period.
    """

    # Default configuration values
    DEFAULT_WINDOW_SECONDS: int = 60
    DEFAULT_MAX_VIOLATIONS: int = 5
    DEFAULT_BLACKLIST_TTL_SECONDS: int = 3600

    def __init__(
        self,
        redis_client: Optional[Redis] = None,
        redis_url: Optional[str] = None,
        window_seconds: Optional[int] = None,
        max_violations: Optional[int] = None,
        blacklist_ttl: Optional[int] = None,
    ) -> None:
        """Initialize the RateLimiter.

        Args:
            redis_client: Optional pre-configured aioredis client instance.
            redis_url: Optional Redis connection URL (defaults to env REDIS_URL or localhost).
            window_seconds: Sliding window duration in seconds (defaults to env or 60).
            max_violations: Maximum violations permitted in window before blacklisting (defaults to env or 5).
            blacklist_ttl: Blacklist expiration duration in seconds (defaults to env or 3600).
        """
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._client: Optional[Redis] = redis_client
        self._owns_client: bool = redis_client is None

        # Configuration parameters
        self.window_seconds: int = int(
            window_seconds
            or os.getenv("RATE_LIMIT_WINDOW_SECONDS", str(self.DEFAULT_WINDOW_SECONDS))
        )
        self.max_violations: int = int(
            max_violations
            or os.getenv("RATE_LIMIT_MAX_VIOLATIONS", str(self.DEFAULT_MAX_VIOLATIONS))
        )
        self.blacklist_ttl: int = int(
            blacklist_ttl
            or os.getenv("BLACKLIST_TTL_SECONDS", str(self.DEFAULT_BLACKLIST_TTL_SECONDS))
        )

        logger.info(
            "RateLimiter initialized (window=%ds, max_violations=%d, blacklist_ttl=%ds)",
            self.window_seconds,
            self.max_violations,
            self.blacklist_ttl,
        )

    async def get_client(self) -> Redis:
        """Lazily initialize and return the async Redis client.

        Returns:
            Active Redis client instance.
        """
        if self._client is None:
            logger.debug("Creating new Redis connection to %s", self._redis_url)
            self._client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                protocol=2,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                retry_on_timeout=True,
            )
        return self._client

    @staticmethod
    def _violation_key(user_id: str) -> str:
        """Format the Redis key for a user's violation sorted set."""
        return f"violations:{user_id}"

    @staticmethod
    def _blacklist_key(user_id: str) -> str:
        """Format the Redis key for a user's blacklist entry."""
        return f"blacklist:{user_id}"

    async def record_violation(self, user_id: str) -> Dict[str, Union[bool, int]]:
        """Record a moderation violation for the given user in the sliding window.

        Steps:
            1. Form Redis keys: 'violations:{user_id}' and 'blacklist:{user_id}'
            2. Add new violation entry with current timestamp score via ZADD
            3. Prune violations older than RATE_LIMIT_WINDOW_SECONDS via ZREMRANGEBYSCORE
            4. Count surviving violations via ZCARD
            5. If count >= RATE_LIMIT_MAX_VIOLATIONS:
               - Set 'blacklist:{user_id}' with TTL
               - Return {'blacklisted': True, 'violation_count': count}
            6. Return {'blacklisted': False, 'violation_count': count}

        Args:
            user_id: Unique identifier of the violating user.

        Returns:
            dict containing:
                - blacklisted: bool (True if user is now blacklisted)
                - violation_count: int (number of active violations in current window)
        """
        if not user_id:
            logger.warning("record_violation called with empty user_id")
            return {"blacklisted": False, "violation_count": 0}

        client = await self.get_client()
        v_key = self._violation_key(user_id)
        b_key = self._blacklist_key(user_id)

        now = time.time()
        cutoff = now - self.window_seconds
        unique_violation_id = f"{now:.6f}:{uuid.uuid4().hex}"

        try:
            # Atomic pipeline for sliding window recording and pruning
            async with client.pipeline(transaction=True) as pipe:
                pipe.zadd(v_key, {unique_violation_id: now})
                pipe.zremrangebyscore(v_key, "-inf", cutoff)
                pipe.zcard(v_key)
                # Keep TTL on sorted set so idle keys are automatically reaped by Redis
                pipe.expire(v_key, max(self.window_seconds * 2, 300))
                results = await pipe.execute()

            # results: [zadd_count, pruned_count, zcard_count, expire_result]
            current_count = int(results[2])

            if current_count >= self.max_violations:
                # User has exceeded the violation threshold, apply blacklist
                await client.set(b_key, "1", ex=self.blacklist_ttl)
                logger.warning(
                    "User '%s' blacklisted! Violations in window: %d (threshold: %d, ttl: %ds)",
                    user_id,
                    current_count,
                    self.max_violations,
                    self.blacklist_ttl,
                )
                return {"blacklisted": True, "violation_count": current_count}

            logger.info(
                "Violation recorded for user '%s'. Current window count: %d/%d",
                user_id,
                current_count,
                self.max_violations,
            )
            return {"blacklisted": False, "violation_count": current_count}

        except (RedisConnectionError, RedisError) as e:
            logger.error("Redis error recording violation for user '%s': %s", user_id, e)
            return {"blacklisted": False, "violation_count": 1}
        except Exception as e:
            logger.error("Unexpected error recording violation for user '%s': %s", user_id, e, exc_info=True)
            return {"blacklisted": False, "violation_count": 0}

    async def is_blacklisted(self, user_id: str) -> bool:
        """Check if a user is currently blacklisted.

        Args:
            user_id: Unique identifier of the user.

        Returns:
            bool: True if blacklist key exists, False otherwise.
        """
        if not user_id:
            return False

        try:
            client = await self.get_client()
            b_key = self._blacklist_key(user_id)
            exists = await client.exists(b_key)
            return bool(exists > 0)
        except (RedisConnectionError, RedisError) as e:
            logger.error("Redis error checking blacklist for user '%s': %s", user_id, e)
            return False
        except Exception as e:
            logger.error("Unexpected error checking blacklist for user '%s': %s", user_id, e, exc_info=True)
            return False

    async def get_violation_count(self, user_id: str) -> int:
        """Get the current active violation count in the sliding window.

        Prunes entries older than window_seconds prior to counting.

        Args:
            user_id: Unique identifier of the user.

        Returns:
            int: Number of violations in the current rolling window.
        """
        if not user_id:
            return 0

        try:
            client = await self.get_client()
            v_key = self._violation_key(user_id)
            now = time.time()
            cutoff = now - self.window_seconds

            async with client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(v_key, "-inf", cutoff)
                pipe.zcard(v_key)
                results = await pipe.execute()

            return int(results[1])
        except (RedisConnectionError, RedisError) as e:
            logger.error("Redis error getting violation count for user '%s': %s", user_id, e)
            return 0
        except Exception as e:
            logger.error("Unexpected error getting violation count for user '%s': %s", user_id, e, exc_info=True)
            return 0

    async def clear_violations(self, user_id: str) -> None:
        """Clear all violation records and blacklist status for the specified user.

        Args:
            user_id: Unique identifier of the user.
        """
        if not user_id:
            return

        try:
            client = await self.get_client()
            v_key = self._violation_key(user_id)
            b_key = self._blacklist_key(user_id)
            await client.delete(v_key, b_key)
            logger.info("Cleared violations and blacklist for user '%s'", user_id)
        except (RedisConnectionError, RedisError) as e:
            logger.error("Redis error clearing violations for user '%s': %s", user_id, e)
        except Exception as e:
            logger.error("Unexpected error clearing violations for user '%s': %s", user_id, e, exc_info=True)

    async def close(self) -> None:
        """Close the underlying Redis client connection if owned by this instance."""
        if self._owns_client and self._client is not None:
            try:
                await self._client.aclose()
                logger.debug("RateLimiter Redis client closed.")
            except Exception as e:
                logger.warning("Error closing RateLimiter Redis client: %s", e)
            finally:
                self._client = None

    async def __aenter__(self) -> "RateLimiter":
        """Support async context manager entry."""
        await self.get_client()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Support async context manager exit."""
        await self.close()
