"""Unit tests for StreamGuard Authentication and JWT utilities."""

import uuid
from datetime import datetime, timedelta, timezone
from jose import jwt
import pytest
from fastapi import HTTPException

from app.auth import (
    create_access_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.config import get_settings

settings = get_settings()


class TestPasswordHashing:
    """Tests for bcrypt password hashing and verification."""

    def test_hash_and_verify_success(self):
        password = "SecurePassword#2026"
        hashed = hash_password(password)

        assert hashed != password
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
        assert verify_password(password, hashed) is True

    def test_verify_failure_wrong_password(self):
        password = "CorrectPassword123"
        hashed = hash_password(password)

        assert verify_password("WrongPassword456", hashed) is False

    def test_empty_password_handling(self):
        hashed = hash_password("notempty")
        assert verify_password("", hashed) is False


class TestJWTToken:
    """Tests for JWT token generation and claim validation."""

    def test_create_and_verify_token_success(self):
        user_id = str(uuid.uuid4())
        username = "charlie"

        token = create_access_token(user_id=user_id, username=username)
        assert isinstance(token, str)
        assert len(token) > 20

        claims = verify_token(token)
        assert claims["user_id"] == user_id
        assert claims["username"] == username

    def test_verify_token_invalid_signature(self):
        user_id = str(uuid.uuid4())
        token = create_access_token(user_id=user_id, username="alice")
        tampered_token = token[:-5] + "XXXXX"

        with pytest.raises(HTTPException) as exc_info:
            verify_token(tampered_token)
        assert exc_info.value.status_code == 401

    def test_verify_token_expired(self):
        user_id = str(uuid.uuid4())
        # Craft an expired token directly
        expired_payload = {
            "sub": user_id,
            "username": "expired_user",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        token = jwt.encode(expired_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)
        assert exc_info.value.status_code == 401

    def test_verify_token_missing_claims(self):
        # Payload missing 'username'
        payload = {
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)
        assert exc_info.value.status_code == 401
