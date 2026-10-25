"""Shared pytest configuration, fixtures, and mocks for StreamGuard test suite."""

import asyncio
from typing import AsyncGenerator, Dict, Any, List
import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from httpx import AsyncClient, ASGITransport

from app.database import Base, get_db
from app.main import app
from app.models.user import User
from app.auth import hash_password, create_access_token


class MockPipeline:
    """Mock Redis pipeline supporting transaction commands used by RateLimiter."""

    def __init__(self, storage: Dict[str, Dict[str, float]], kv_storage: Dict[str, Any]):
        self.storage = storage
        self.kv_storage = kv_storage
        self.ops: List[tuple] = []

    def zadd(self, key: str, mapping: Dict[str, float]) -> "MockPipeline":
        self.ops.append(("zadd", key, mapping))
        return self

    def zremrangebyscore(self, key: str, min_s: Any, max_s: float) -> "MockPipeline":
        self.ops.append(("zrem", key, min_s, max_s))
        return self

    def zcard(self, key: str) -> "MockPipeline":
        self.ops.append(("zcard", key))
        return self

    def expire(self, key: str, ttl: int) -> "MockPipeline":
        self.ops.append(("expire", key, ttl))
        return self

    async def execute(self) -> List[Any]:
        results = []
        for op in self.ops:
            op_name = op[0]
            if op_name == "zadd":
                key, mapping = op[1], op[2]
                if key not in self.storage:
                    self.storage[key] = {}
                self.storage[key].update(mapping)
                results.append(len(mapping))
            elif op_name == "zrem":
                key, min_s, max_s = op[1], op[2], op[3]
                z = self.storage.get(key, {})
                before = len(z)
                self.storage[key] = {m: s for m, s in z.items() if s > max_s}
                results.append(before - len(self.storage[key]))
            elif op_name == "zcard":
                results.append(len(self.storage.get(op[1], {})))
            elif op_name == "expire":
                results.append(True)
        return results

    async def __aenter__(self) -> "MockPipeline":
        return self

    async def __aexit__(self, *args) -> None:
        pass


class MockRedisClient:
    """Mock Redis client simulating KV, Sorted Set and ping operations."""

    def __init__(self):
        self.storage: Dict[str, Dict[str, float]] = {}
        self.kv: Dict[str, str] = {}

    def pipeline(self, transaction: bool = True) -> MockPipeline:
        return MockPipeline(self.storage, self.kv)

    async def get(self, key: str) -> Any:
        return self.kv.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        self.kv[key] = str(value)
        return True

    async def exists(self, key: str) -> int:
        return 1 if key in self.kv else 0

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self.kv:
                del self.kv[k]
                count += 1
            if k in self.storage:
                del self.storage[k]
                count += 1
        return count

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


@pytest.fixture
def mock_redis() -> MockRedisClient:
    """Fixture providing an isolated MockRedisClient."""
    return MockRedisClient()


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="function")
async def test_engine():
    """Create in-memory SQLite engine with StaticPool for test isolation."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated database session per test function."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture(scope="function")
async def client(test_engine, db_session) -> AsyncGenerator[AsyncClient, None]:
    """Provide an AsyncClient with database dependency override."""
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
async def test_user(db_session: AsyncSession) -> Dict[str, Any]:
    """Create a standard test user and return credentials and token."""
    user = User(
        username="testrunner",
        hashed_password=hash_password("SuperSecret123!"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(user_id=str(user.id), username=user.username)
    return {
        "user": user,
        "user_id": str(user.id),
        "username": user.username,
        "password": "SuperSecret123!",
        "token": token,
        "auth_headers": {"Authorization": f"Bearer {token}"},
    }
