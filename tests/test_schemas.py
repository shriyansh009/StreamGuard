"""Unit tests for StreamGuard Pydantic request/response schemas."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.schemas import (
    AnalyticsQuery,
    AnalyticsResponse,
    HealthResponse,
    ModerationResult,
    RoomStatsResponse,
    TokenResponse,
    TopViolatorResponse,
    UserLogin,
    UserRegister,
    WebSocketMessage,
)


class TestSchemas:
    """Tests covering schema validation, constraints, and default field handling."""

    def test_user_register_valid(self):
        user = UserRegister(username="validuser", password="securepassword123")
        assert user.username == "validuser"
        assert user.password == "securepassword123"

    def test_user_register_too_short_username(self):
        with pytest.raises(ValidationError):
            UserRegister(username="ab", password="securepassword123")

    def test_user_register_too_short_password(self):
        with pytest.raises(ValidationError):
            UserRegister(username="validuser", password="short")

    def test_user_login_valid(self):
        login = UserLogin(username="validuser", password="securepassword123")
        assert login.username == "validuser"

    def test_token_response_default_type(self):
        token_resp = TokenResponse(access_token="sample.jwt.token")
        assert token_resp.access_token == "sample.jwt.token"
        assert token_resp.token_type == "bearer"

    def test_websocket_message_length_limit(self):
        valid_msg = WebSocketMessage(content="Hello world", room_id="room-1")
        assert valid_msg.content == "Hello world"

        # Exceed 2000 chars
        with pytest.raises(ValidationError):
            WebSocketMessage(content="A" * 2001, room_id="room-1")

    def test_moderation_result_validation(self):
        mod = ModerationResult(
            message_id="msg-123",
            flagged=True,
            toxicity_score=0.85,
            action_taken="blocked",
            matched_patterns=["threat"],
        )
        assert mod.toxicity_score == 0.85

        # Score out of range (> 1.0)
        with pytest.raises(ValidationError):
            ModerationResult(
                message_id="msg-123",
                flagged=True,
                toxicity_score=1.5,
                action_taken="blocked",
            )

        # Score out of range (< 0.0)
        with pytest.raises(ValidationError):
            ModerationResult(
                message_id="msg-123",
                flagged=False,
                toxicity_score=-0.1,
                action_taken="allowed",
            )

    def test_analytics_query_validation(self):
        q = AnalyticsQuery(interval_minutes=30)
        assert q.interval_minutes == 30

        # Out of bounds (< 1 or > 1440)
        with pytest.raises(ValidationError):
            AnalyticsQuery(interval_minutes=0)

        with pytest.raises(ValidationError):
            AnalyticsQuery(interval_minutes=2000)

    def test_health_response_schema(self):
        health = HealthResponse(
            status="healthy",
            redis_connected=True,
            db_connected=True,
            uptime_seconds=120.5,
            active_workers=3,
        )
        assert health.status == "healthy"
        assert health.active_workers == 3
