"""WebSocket Gateway for StreamGuard (Phase 2 Core).

Manages persistent WebSocket connections for real-time chat rooms.
Authenticates users via JWT, checks blacklists, validates messages,
offloads to Redis Streams, and broadcasts to room participants.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.auth import verify_token
from app.rate_limiter import RateLimiter
from app.redis_client import redis_manager

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections organized by chat rooms.

    Attributes:
        active_connections: Nested dict mapping room_id -> {user_id: WebSocket}.
    """

    def __init__(self) -> None:
        """Initialize the ConnectionManager with empty connection registry."""
        self.active_connections: dict[str, dict[str, WebSocket]] = {}
        self._rate_limiter: Optional[RateLimiter] = None

    @property
    def rate_limiter(self) -> RateLimiter:
        """Lazy-initialize rate limiter using the shared Redis client."""
        if self._rate_limiter is None:
            try:
                self._rate_limiter = RateLimiter(redis_client=redis_manager.client)
            except RuntimeError:
                # Redis not yet initialized, create standalone
                self._rate_limiter = RateLimiter()
        return self._rate_limiter

    async def connect(self, websocket: WebSocket, room_id: str, user_id: str) -> None:
        """Accept a WebSocket connection and register it to a room.

        Args:
            websocket: The WebSocket connection to accept.
            room_id: Chat room identifier.
            user_id: Authenticated user identifier.
        """
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = {}
        self.active_connections[room_id][user_id] = websocket
        logger.info(
            "User '%s' connected to room '%s' (room size: %d)",
            user_id, room_id, len(self.active_connections[room_id]),
        )

    async def disconnect(self, room_id: str, user_id: str) -> None:
        """Remove a WebSocket connection from the room registry.

        Args:
            room_id: Chat room identifier.
            user_id: User identifier to disconnect.
        """
        if room_id in self.active_connections:
            self.active_connections[room_id].pop(user_id, None)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]
        logger.info("User '%s' disconnected from room '%s'", user_id, room_id)

    async def broadcast(self, room_id: str, message: str, exclude_user: str | None = None) -> None:
        """Broadcast a message to all participants in a room.

        Args:
            room_id: Chat room to broadcast to.
            message: Message text to send.
            exclude_user: Optional user_id to exclude from broadcast (typically the sender).
        """
        if room_id not in self.active_connections:
            return

        disconnected: list[str] = []
        for uid, ws in self.active_connections[room_id].items():
            if uid == exclude_user:
                continue
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(uid)

        # Clean up broken connections
        for uid in disconnected:
            self.active_connections[room_id].pop(uid, None)
            logger.debug("Removed stale connection for user '%s' in room '%s'", uid, room_id)

    def get_room_count(self) -> int:
        """Return the number of active rooms."""
        return len(self.active_connections)

    def get_total_connections(self) -> int:
        """Return the total number of active WebSocket connections across all rooms."""
        return sum(len(users) for users in self.active_connections.values())


# Module-level singleton
connection_manager = ConnectionManager()

# Maximum message length (chars)
MAX_MESSAGE_LENGTH = 2000


async def websocket_gateway(websocket: WebSocket, room_id: str) -> None:
    """WebSocket endpoint handler for chat room messaging.

    Protocol:
        1. Client connects to /ws/chat/{room_id}
        2. First message MUST be a valid JWT token for authentication
        3. Server checks if user is blacklisted (Redis cache, then DB fallback)
        4. If blacklisted, server sends error and closes connection
        5. Subsequent messages are validated, pushed to Redis Stream, and broadcast

    Args:
        websocket: FastAPI WebSocket connection.
        room_id: Chat room identifier from URL path.
    """
    user_id: str | None = None
    username: str | None = None

    try:
        # ── Step 1: Accept connection temporarily for auth handshake ──
        await websocket.accept()

        # ── Step 2: First message must be JWT token ──
        try:
            token = await websocket.receive_text()
        except WebSocketDisconnect:
            logger.debug("Client disconnected before sending auth token (room=%s)", room_id)
            return

        # Verify JWT
        try:
            claims = verify_token(token)
            user_id = claims["user_id"]
            username = claims["username"]
        except Exception:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Authentication failed. Send a valid JWT token as the first message.",
            }))
            await websocket.close(code=4001, reason="Authentication failed")
            return

        # ── Step 3: Check blacklist ──
        is_blocked = False
        try:
            is_blocked = await connection_manager.rate_limiter.is_blacklisted(user_id)
        except Exception as e:
            logger.warning("Blacklist check failed for user '%s': %s", user_id, e)

        if is_blocked:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Your account is temporarily suspended due to policy violations.",
            }))
            await websocket.close(code=4003, reason="Account blacklisted")
            logger.warning("Blacklisted user '%s' (%s) rejected from room '%s'", username, user_id, room_id)
            return

        # ── Step 4: Register connection ──
        if room_id not in connection_manager.active_connections:
            connection_manager.active_connections[room_id] = {}
        connection_manager.active_connections[room_id][user_id] = websocket

        # Send auth success confirmation
        await websocket.send_text(json.dumps({
            "type": "system",
            "message": f"Connected to room '{room_id}' as '{username}'",
        }))

        logger.info("User '%s' (%s) authenticated and joined room '%s'", username, user_id, room_id)

        # ── Step 5: Main message loop ──
        while True:
            data = await websocket.receive_text()

            # Validate message length
            if len(data) > MAX_MESSAGE_LENGTH:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Message too long. Maximum {MAX_MESSAGE_LENGTH} characters.",
                }))
                continue

            # Skip empty messages
            if not data.strip():
                continue

            # Push to Redis Stream for async worker processing
            try:
                if redis_manager.is_initialized:
                    stream_key = f"stream:chat:{room_id}"
                    await redis_manager.stream_client.xadd(
                        stream_key,
                        {
                            "message": data,
                            "user_id": user_id,
                            "username": username,
                            "room_id": room_id,
                            "timestamp": str(time.time()),
                        },
                    )
            except Exception as e:
                logger.error("Failed to push message to Redis Stream: %s", e)

            # Broadcast to room participants (including sender for echo)
            broadcast_payload = json.dumps({
                "type": "message",
                "room_id": room_id,
                "user_id": user_id,
                "username": username,
                "content": data,
                "timestamp": time.time(),
            })
            await connection_manager.broadcast(room_id, broadcast_payload)

    except WebSocketDisconnect:
        logger.info("User '%s' disconnected from room '%s'", username or "unknown", room_id)
    except Exception as e:
        logger.error("WebSocket error in room '%s' for user '%s': %s", room_id, user_id, e, exc_info=True)
    finally:
        # Clean up connection
        if user_id:
            await connection_manager.disconnect(room_id, user_id)
