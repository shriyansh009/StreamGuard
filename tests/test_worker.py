"""Unit tests for StreamGuard Redis Stream Consumer and WorkerManager."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.nlp.content_analyzer import ContentAnalyzer
from app.worker.stream_consumer import StreamConsumer
from app.worker.worker_manager import WorkerManager
from app.models.user import User


class TestStreamConsumer:
    """Tests covering message extraction, moderation processing, and batch handling."""

    def test_extract_message_payload_direct(self):
        consumer = StreamConsumer()
        fields = {
            "user_id": "user-456",
            "text": "Hello world from stream!",
        }
        uid, text = consumer._extract_message_payload(fields)
        assert uid == "user-456"
        assert text == "Hello world from stream!"

    def test_extract_message_payload_nested_json(self):
        consumer = StreamConsumer()
        fields = {
            "data": json.dumps({"sender_id": "nested-user-99", "message": "Nested chat text"}),
        }
        uid, text = consumer._extract_message_payload(fields)
        assert uid == "nested-user-99"
        assert text == "Nested chat text"

    def test_extract_message_payload_fallback_field_names(self):
        consumer = StreamConsumer()
        fields = {
            "author_id": "author-77",
            "body": "Body content here",
        }
        uid, text = consumer._extract_message_payload(fields)
        assert uid == "author-77"
        assert text == "Body content here"

    async def test_process_batch_with_db_insertion(self, db_session: AsyncSession, test_user: dict):
        user_uuid = test_user["user_id"]

        mock_redis = AsyncMock()
        mock_rate_limiter = AsyncMock()
        mock_rate_limiter.record_violation.return_value = {"blacklisted": False, "violation_count": 1}

        # Session factory context manager mock
        class SessionContext:
            async def __aenter__(self):
                return db_session

            async def __aexit__(self, *args):
                pass

        session_factory = MagicMock(return_value=SessionContext())

        consumer = StreamConsumer(
            analyzer=ContentAnalyzer(),
            session_factory=session_factory,
            rate_limiter=mock_rate_limiter,
        )
        consumer.redis_client = mock_redis

        messages = [
            (
                "msg-1",
                {"user_id": user_uuid, "content": "Clean stream message", "room_id": "room-main"},
            ),
            (
                "msg-2",
                {"user_id": user_uuid, "content": "I will kill you all", "room_id": "room-main"},
            ),
        ]

        count = await consumer.process_batch("stream:chat:room-main", messages)
        assert count == 2

        # Verify rate limiter was invoked for the violating message
        mock_rate_limiter.record_violation.assert_called_once_with(user_uuid)
        # Verify XACK was called to acknowledge stream messages
        mock_redis.xack.assert_called_once()

    async def test_process_empty_batch(self):
        consumer = StreamConsumer()
        processed = await consumer.process_batch("stream:chat:test", [])
        assert processed == 0


class TestWorkerManager:
    """Tests for WorkerManager status reporting and lifecycle management."""

    def test_worker_manager_status_initial(self):
        manager = WorkerManager()
        status = manager.get_status()

        assert status["is_running"] is False
        assert status["target_workers"] == 3
        assert status["active_workers"] == 0
        assert len(status["slots"]) == 3
