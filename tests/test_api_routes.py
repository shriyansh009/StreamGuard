"""Integration tests for StreamGuard REST API routes."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.auth import hash_password


class TestSystemRoutes:
    """Tests for system info and health check endpoints."""

    async def test_root_endpoint(self, client: AsyncClient):
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "StreamGuard"
        assert data["version"] == "1.0.0"
        assert "docs" in data

    async def test_health_check_endpoint(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "uptime_seconds" in data
        assert "active_workers" in data


class TestAuthRoutes:
    """Tests for user registration, authentication, and access control."""

    async def test_register_success(self, client: AsyncClient):
        payload = {
            "username": "newuser123",
            "password": "StrongPassword!2026",
        }
        response = await client.post("/api/auth/register", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_register_duplicate_username_conflict(self, client: AsyncClient, test_user: dict):
        payload = {
            "username": test_user["username"],
            "password": "AnotherPassword123!",
        }
        response = await client.post("/api/auth/register", json=payload)
        assert response.status_code == 409
        assert "already registered" in response.json()["detail"]

    async def test_register_invalid_payload(self, client: AsyncClient):
        # Password too short
        payload = {
            "username": "validname",
            "password": "123",
        }
        response = await client.post("/api/auth/register", json=payload)
        assert response.status_code == 422

    async def test_login_success(self, client: AsyncClient, test_user: dict):
        payload = {
            "username": test_user["username"],
            "password": test_user["password"],
        }
        response = await client.post("/api/auth/login", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_invalid_password(self, client: AsyncClient, test_user: dict):
        payload = {
            "username": test_user["username"],
            "password": "WrongPasswordHere!",
        }
        response = await client.post("/api/auth/login", json=payload)
        assert response.status_code == 401
        assert "Invalid username or password" in response.json()["detail"]

    async def test_login_nonexistent_user(self, client: AsyncClient):
        payload = {
            "username": "nosuchuser_exists",
            "password": "SomePassword123!",
        }
        response = await client.post("/api/auth/login", json=payload)
        assert response.status_code == 401
        assert "Invalid username or password" in response.json()["detail"]

    async def test_login_blacklisted_user(self, client: AsyncClient, db_session: AsyncSession):
        user = User(
            username="banned_user",
            hashed_password=hash_password("Pass12345!"),
            is_blacklisted=True,
        )
        db_session.add(user)
        await db_session.commit()

        payload = {
            "username": "banned_user",
            "password": "Pass12345!",
        }
        response = await client.post("/api/auth/login", json=payload)
        assert response.status_code == 403
        assert "suspended" in response.json()["detail"].lower()


class TestAnalyticsRoutes:
    """Tests for room statistics and top violator analytics."""

    async def test_room_stats_empty(self, client: AsyncClient):
        response = await client.get("/api/analytics/room-stats/test-room-empty")
        assert response.status_code == 200
        data = response.json()
        assert data["room_id"] == "test-room-empty"
        assert data["total_messages"] == 0
        assert data["flagged_messages"] == 0
        assert data["flagged_percentage"] == 0.0

    async def test_top_violators_empty(self, client: AsyncClient):
        response = await client.get("/api/analytics/top-violators?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
