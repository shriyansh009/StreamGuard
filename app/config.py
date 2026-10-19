"""Configuration settings for StreamGuard using Pydantic Settings."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables with STREAMGUARD_ prefix.

    Attributes:
        DATABASE_URL: Async PostgreSQL connection URL for SQLAlchemy async engine.
        REDIS_URL: Redis connection URL for streams, caching, and state management.
        JWT_SECRET: Cryptographic secret key used for JWT signing and verification.
        JWT_ALGORITHM: Algorithm used for JWT encoding and decoding.
        RATE_LIMIT_MAX_VIOLATIONS: Allowed violation threshold before escalation/blocking.
        RATE_LIMIT_WINDOW_SECONDS: Window duration in seconds for sliding rate limit evaluations.
        WORKER_BATCH_SIZE: Number of messages fetched per batch from Redis streams.
        WORKER_BLOCK_MS: Milliseconds to block waiting for new Redis stream events.
        CACHE_TTL_SECONDS: Default time-to-live in seconds for cached records in Redis.
    """

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://streamguard:streamguard_secret@localhost:5432/streamguard",
        description="Async PostgreSQL connection URL.",
    )
    REDIS_URL: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL.",
    )
    JWT_SECRET: str = Field(
        default="streamguard-dev-secret-change-in-production",
        description="Secret key used for signing JWT tokens.",
    )
    JWT_ALGORITHM: str = Field(
        default="HS256",
        description="Algorithm used for JWT token encoding and decoding.",
    )
    RATE_LIMIT_MAX_VIOLATIONS: int = Field(
        default=3,
        description="Maximum rate limit violations allowed before blocking or alerting.",
    )
    RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=10,
        description="Time window in seconds for sliding window rate limiting.",
    )
    WORKER_BATCH_SIZE: int = Field(
        default=50,
        description="Batch size for Redis stream consumer workers.",
    )
    WORKER_BLOCK_MS: int = Field(
        default=5000,
        description="Block duration in milliseconds when polling Redis streams.",
    )
    CACHE_TTL_SECONDS: int = Field(
        default=300,
        description="Default TTL in seconds for cached entities in Redis.",
    )

    model_config = SettingsConfigDict(
        env_prefix="STREAMGUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings.

    Returns:
        Settings: The loaded application settings instance.
    """
    return Settings()
