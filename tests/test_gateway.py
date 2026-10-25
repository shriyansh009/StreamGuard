"""Unit tests for WebSocket Gateway ConnectionManager."""

from unittest.mock import AsyncMock
import pytest
from app.gateway import ConnectionManager


class MockWebSocket:
    """Mock WebSocket for unit testing ConnectionManager."""

    def __init__(self, should_fail: bool = False):
        self.accepted = False
        self.sent_messages = []
        self.should_fail = should_fail

    async def accept(self):
        self.accepted = True

    async def send_text(self, message: str):
        if self.should_fail:
            raise RuntimeError("Connection dropped")
        self.sent_messages.append(message)


class TestConnectionManager:
    """Tests covering connection registration, room management, and broadcasting."""

    async def test_connect_and_disconnect(self):
        manager = ConnectionManager()
        ws = MockWebSocket()

        await manager.connect(ws, "room-1", "user-1")
        assert ws.accepted is True
        assert "room-1" in manager.active_connections
        assert "user-1" in manager.active_connections["room-1"]

        await manager.disconnect("room-1", "user-1")
        assert "room-1" not in manager.active_connections

    async def test_multiple_users_same_room(self):
        manager = ConnectionManager()
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()

        await manager.connect(ws1, "room-general", "alice")
        await manager.connect(ws2, "room-general", "bob")
        assert len(manager.active_connections["room-general"]) == 2

        await manager.disconnect("room-general", "alice")
        assert len(manager.active_connections["room-general"]) == 1
        assert "bob" in manager.active_connections["room-general"]

        await manager.disconnect("room-general", "bob")
        assert "room-general" not in manager.active_connections

    async def test_broadcast_to_room_excluding_sender(self):
        manager = ConnectionManager()
        ws_sender = MockWebSocket()
        ws_receiver1 = MockWebSocket()
        ws_receiver2 = MockWebSocket()

        await manager.connect(ws_sender, "room-chat", "sender")
        await manager.connect(ws_receiver1, "room-chat", "recv1")
        await manager.connect(ws_receiver2, "room-chat", "recv2")

        message = '{"type": "message", "content": "Hello everyone!"}'
        await manager.broadcast("room-chat", message, exclude_user="sender")

        assert ws_sender.sent_messages == []
        assert ws_receiver1.sent_messages == [message]
        assert ws_receiver2.sent_messages == [message]

    async def test_broadcast_cleans_up_broken_connections(self):
        manager = ConnectionManager()
        ws_broken = MockWebSocket(should_fail=True)
        ws_healthy = MockWebSocket(should_fail=False)

        await manager.connect(ws_broken, "room-err", "broken_client")
        await manager.connect(ws_healthy, "room-err", "healthy_client")

        await manager.broadcast("room-err", "broadcast test")

        assert ws_healthy.sent_messages == ["broadcast test"]
        # The broken client should have been pruned
        assert "broken_client" not in manager.active_connections["room-err"]
        assert "healthy_client" in manager.active_connections["room-err"]

    async def test_broadcast_nonexistent_room(self):
        manager = ConnectionManager()
        # Should not raise exception
        await manager.broadcast("non-existent-room", "message")
