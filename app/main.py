"""StreamGuard FastAPI Application Entry Point.

Integrates all phases:
  - Phase 1: Docker infrastructure (external via docker-compose.yml)
  - Phase 2: WebSocket ingestion gateway
  - Phase 3: Relational schema (SQLAlchemy models + Alembic)
  - Phase 4: Distributed worker pool (Redis Stream consumers + NLP)
  - Phase 5: Rate limiting & blacklisting
  - Phase 6: Time-series analytics dashboards
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, async_engine, close_db_engine, AsyncSessionLocal
from app.gateway import connection_manager, websocket_gateway
from app.redis_client import redis_manager
from app.routes.auth_routes import router as auth_router
from app.routes.analytics_routes import router as analytics_router
from app.schemas import HealthResponse
from app.worker.worker_manager import WorkerManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("streamguard")
settings = get_settings()

# Worker manager singleton
worker_manager = WorkerManager(
    redis_url=settings.REDIS_URL,
    session_factory=AsyncSessionLocal,
)

# Track server start time for uptime
_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager handling startup and shutdown.

    Startup:
        1. Initialize Redis connection pools
        2. Create database tables (if not exist)
        3. Start background worker pool (3 consumers)

    Shutdown:
        1. Stop all background workers
        2. Close Redis connections
        3. Dispose database engine
    """
    global _start_time
    _start_time = time.time()

    logger.info("═══ StreamGuard Starting Up ═══")

    # ── Phase 1: Redis Connection ──
    try:
        await redis_manager.initialize(settings.REDIS_URL)
        logger.info("✓ Redis connection pool initialized")
    except Exception as exc:
        logger.warning("⚠ Redis not available at startup: %s (will retry on demand)", exc)

    # ── Phase 3: Database Tables ──
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✓ Database tables verified/created")
    except Exception as exc:
        logger.error("✗ Database initialization failed: %s", exc)

    # ── Phase 4: Background Workers ──
    try:
        await worker_manager.start(num_workers=3)
        logger.info("✓ Worker pool started (3 consumers)")
    except Exception as exc:
        logger.warning("⚠ Worker pool startup failed: %s", exc)

    # Store references in app state
    app.state.connection_manager = connection_manager
    app.state.worker_manager = worker_manager
    app.state.start_time = _start_time

    logger.info("═══ StreamGuard Ready — Accepting Connections ═══")

    yield

    # ── Shutdown ──
    logger.info("═══ StreamGuard Shutting Down ═══")

    try:
        await worker_manager.stop()
        logger.info("✓ Workers stopped")
    except Exception as exc:
        logger.error("Error stopping workers: %s", exc)

    try:
        await redis_manager.close()
        logger.info("✓ Redis connections closed")
    except Exception as exc:
        logger.error("Error closing Redis: %s", exc)

    try:
        await close_db_engine()
        logger.info("✓ Database engine disposed")
    except Exception as exc:
        logger.error("Error closing database: %s", exc)

    logger.info("═══ StreamGuard Shutdown Complete ═══")


# ── Application Factory ──────────────────────────────────────────────────────

app = FastAPI(
    title="StreamGuard",
    version="1.0.0",
    description=(
        "Enterprise-grade, high-throughput content moderation data pipeline. "
        "Real-time WebSocket ingestion → Redis Stream brokering → "
        "NLP analysis workers → PostgreSQL audit logging."
    ),
    lifespan=lifespan,
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Phase 2: WebSocket Gateway Route ─────────────────────────────────────────
app.websocket("/ws/chat/{room_id}")(websocket_gateway)

# ── Phase 2 & 6: REST API Routes ─────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(analytics_router)


# ── Health Check Endpoint ─────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> HealthResponse:
    """System health check verifying Redis, database, and worker pool status."""
    # Redis health
    redis_ok = await redis_manager.ping()

    # Database health
    db_ok = False
    try:
        from sqlalchemy import text as sql_text
        from app.database import get_db_session
        async with get_db_session() as session:
            await session.execute(sql_text("SELECT 1"))
            db_ok = True
    except Exception:
        pass

    # Worker status
    worker_status = worker_manager.get_status()
    active_workers = worker_status.get("active_workers", 0)

    status_str = "healthy" if (redis_ok and db_ok) else "degraded"

    return HealthResponse(
        status=status_str,
        redis_connected=redis_ok,
        db_connected=db_ok,
        uptime_seconds=round(time.time() - _start_time, 2),
        active_workers=active_workers,
    )


@app.get("/", tags=["System"])
async def root() -> dict:
    """Root endpoint with service information."""
    return {
        "service": "StreamGuard",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "websocket": "/ws/chat/{room_id}",
    }
