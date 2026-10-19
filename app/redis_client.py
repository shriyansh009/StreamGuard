"""Redis connection manager with connection pooling and specialized clients."""

from __future__ import annotations

import logging
from typing import Optional

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError as RedisConnectionError, RedisError

from app.config import get_settings

logger = logging.getLogger(__name__)


class RedisManager:
    """Async Redis manager providing connection pooling and specialized clients.

    Separates clients into distinct interfaces for general operations,
    Redis Streams (producers/consumers), and caching layers to prevent
    blocking calls from starving other operations.
    """

    def __init__(self) -> None:
        """Initialize unconfigured RedisManager instance."""
        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[Redis] = None
        self._stream_client: Optional[Redis] = None
        self._cache_client: Optional[Redis] = None
        self._initialized: bool = False

    @property
    def client(self) -> Redis:
        """General-purpose Redis client instance.

        Returns:
            Redis: Async Redis client.

        Raises:
            RuntimeError: If RedisManager has not been initialized.
        """
        if self._client is None:
            raise RuntimeError(
                "RedisManager has not been initialized. Call initialize(redis_url) first."
            )
        return self._client

    @property
    def stream_client(self) -> Redis:
        """Dedicated Redis client for stream operations (XADD, XREAD, XACK, etc.).

        Returns:
            Redis: Async Redis client configured for stream processing.

        Raises:
            RuntimeError: If RedisManager has not been initialized.
        """
        if self._stream_client is None:
            raise RuntimeError(
                "RedisManager has not been initialized. Call initialize(redis_url) first."
            )
        return self._stream_client

    @property
    def cache_client(self) -> Redis:
        """Dedicated Redis client for cache operations (GET, SET, TTL, etc.).

        Returns:
            Redis: Async Redis client configured for caching.

        Raises:
            RuntimeError: If RedisManager has not been initialized.
        """
        if self._cache_client is None:
            raise RuntimeError(
                "RedisManager has not been initialized. Call initialize(redis_url) first."
            )
        return self._cache_client

    @property
    def is_initialized(self) -> bool:
        """Check whether RedisManager has active connection pools and clients.

        Returns:
            bool: True if initialized and ready, False otherwise.
        """
        return self._initialized and self._pool is not None

    async def initialize(self, redis_url: Optional[str] = None) -> None:
        """Initialize connection pool and client instances.

        Args:
            redis_url: Optional Redis URL. Defaults to STREAMGUARD_REDIS_URL from config.

        Raises:
            RedisError: If initial connectivity ping fails.
        """
        if self._initialized:
            logger.warning("RedisManager is already initialized. Skipping re-initialization.")
            return

        target_url = redis_url or get_settings().REDIS_URL
        logger.info("Initializing Redis connection pool to %s with max_connections=50", target_url)

        try:
            # Create connection pool with max 50 connections and auto-decoding
            self._pool = ConnectionPool.from_url(
                url=target_url,
                max_connections=50,
                decode_responses=True,
            )

            # Instantiate specialized clients bound to connection pool
            self._client = Redis(connection_pool=self._pool)
            self._stream_client = Redis(connection_pool=self._pool)
            self._cache_client = Redis(connection_pool=self._pool)

            # Verify connectivity
            await self._client.ping()
            self._initialized = True
            logger.info("RedisManager successfully initialized and connected to Redis.")
        except (RedisConnectionError, RedisError) as exc:
            logger.error("Failed to connect to Redis at %s: %s", target_url, exc, exc_info=True)
            await self.close()
            raise

    async def ping(self) -> bool:
        """Perform health-check ping against Redis.

        Returns:
            bool: True if ping is acknowledged, False otherwise.
        """
        if not self._initialized or self._client is None:
            return False
        try:
            return bool(await self._client.ping())
        except RedisError:
            return False

    async def close(self) -> None:
        """Gracefully close all Redis client connections and dispose connection pool."""
        logger.info("Closing Redis connections and releasing pool...")

        if self._client is not None:
            await self._client.aclose()
            self._client = None

        if self._stream_client is not None:
            await self._stream_client.aclose()
            self._stream_client = None

        if self._cache_client is not None:
            await self._cache_client.aclose()
            self._cache_client = None

        if self._pool is not None:
            await self._pool.disconnect()
            self._pool = None

        self._initialized = False
        logger.info("RedisManager shutdown complete.")


# Module-level singleton instance
redis_manager: RedisManager = RedisManager()
