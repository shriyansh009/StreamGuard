"""Async SQLAlchemy database connection and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Configure production-ready Async SQLAlchemy engine
engine: AsyncEngine = create_async_engine(
    url=settings.DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
    future=True,
)
async_engine: AsyncEngine = engine

# Configure session factory bound to async engine
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models in StreamGuard."""

    def __repr__(self) -> str:
        """String representation showing class name and primary attributes."""
        attrs = [f"{k}={v!r}" for k, v in self.__dict__.items() if not k.startswith("_")]
        return f"<{self.__class__.__name__}({', '.join(attrs)})>"


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager providing a transactional database session.

    Commits on successful block execution, rolls back on exception,
    and guarantees session closure.

    Yields:
        AsyncSession: An active SQLAlchemy async session.

    Example:
        ```python
        async with get_db_session() as session:
            result = await session.execute(select(Model))
        ```
    """
    session: AsyncSession = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error("Database session rolled back due to error: %s", exc, exc_info=True)
        raise
    finally:
        await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session per request.

    Yields:
        AsyncSession: An active SQLAlchemy async session.
    """
    async with get_db_session() as session:
        yield session


async def close_db_engine() -> None:
    """Gracefully dispose and close the async database connection pool."""
    logger.info("Disposing database connection pool...")
    await engine.dispose()
    logger.info("Database connection pool disposed.")
