"""Unit tests for StreamGuard Sliding Window Rate Limiter."""

import pytest
from app.rate_limiter import RateLimiter
from tests.conftest import MockRedisClient


@pytest.fixture
def rate_limiter(mock_redis: MockRedisClient) -> RateLimiter:
    return RateLimiter(
        redis_client=mock_redis,
        window_seconds=10,
        max_violations=3,
        blacklist_ttl=60,
    )


class TestRateLimiter:
    """Tests covering sliding window violation tracking, pruning, and blacklisting."""

    async def test_record_single_violation(self, rate_limiter: RateLimiter):
        result = await rate_limiter.record_violation("user-123")
        assert result["blacklisted"] is False
        assert result["violation_count"] == 1

        count = await rate_limiter.get_violation_count("user-123")
        assert count == 1
        assert await rate_limiter.is_blacklisted("user-123") is False

    async def test_threshold_triggers_blacklist(self, rate_limiter: RateLimiter):
        # 1st violation
        r1 = await rate_limiter.record_violation("user-bad")
        assert r1["blacklisted"] is False
        assert r1["violation_count"] == 1

        # 2nd violation
        r2 = await rate_limiter.record_violation("user-bad")
        assert r2["blacklisted"] is False
        assert r2["violation_count"] == 2

        # 3rd violation -> threshold is 3 -> triggers blacklist
        r3 = await rate_limiter.record_violation("user-bad")
        assert r3["blacklisted"] is True
        assert r3["violation_count"] == 3

        # Verify state
        assert await rate_limiter.is_blacklisted("user-bad") is True

    async def test_clear_violations(self, rate_limiter: RateLimiter):
        await rate_limiter.record_violation("user-reset")
        await rate_limiter.record_violation("user-reset")
        await rate_limiter.record_violation("user-reset")
        assert await rate_limiter.is_blacklisted("user-reset") is True

        await rate_limiter.clear_violations("user-reset")
        assert await rate_limiter.is_blacklisted("user-reset") is False
        assert await rate_limiter.get_violation_count("user-reset") == 0

    async def test_empty_user_id(self, rate_limiter: RateLimiter):
        res = await rate_limiter.record_violation("")
        assert res["blacklisted"] is False
        assert res["violation_count"] == 0
        assert await rate_limiter.is_blacklisted("") is False
        assert await rate_limiter.get_violation_count("") == 0

    async def test_independent_users(self, rate_limiter: RateLimiter):
        await rate_limiter.record_violation("user-a")
        await rate_limiter.record_violation("user-a")
        await rate_limiter.record_violation("user-b")

        assert await rate_limiter.get_violation_count("user-a") == 2
        assert await rate_limiter.get_violation_count("user-b") == 1
        assert await rate_limiter.is_blacklisted("user-a") is False
        assert await rate_limiter.is_blacklisted("user-b") is False

    async def test_async_context_manager(self, mock_redis: MockRedisClient):
        async with RateLimiter(redis_client=mock_redis) as limiter:
            res = await limiter.record_violation("u_ctx")
            assert res["violation_count"] == 1
