"""JWT authentication utilities for StreamGuard.

Provides token creation, verification, and password hashing/verification
using python-jose (JWT) and passlib (bcrypt).
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
import bcrypt
from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Bcrypt password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Token expiration
ACCESS_TOKEN_EXPIRE_HOURS = 24


def create_access_token(user_id: str, username: str) -> str:
    """Create a JWT access token with user_id and username claims.

    Args:
        user_id: Unique user identifier (UUID string).
        username: User's display name.

    Returns:
        Encoded JWT token string.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    logger.debug("Created access token for user '%s' (expires: %s)", username, expire.isoformat())
    return token


def verify_token(token: str) -> dict[str, Any]:
    """Verify and decode a JWT token.

    Args:
        token: Encoded JWT token string.

    Returns:
        Decoded payload dictionary with 'sub' (user_id) and 'username' claims.

    Raises:
        HTTPException: 401 if token is invalid, expired, or missing required claims.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id: str | None = payload.get("sub")
        username: str | None = payload.get("username")
        if user_id is None or username is None:
            logger.warning("Token missing required claims (sub/username)")
            raise credentials_exception
        return {"user_id": user_id, "username": username}
    except JWTError as e:
        logger.warning("JWT verification failed: %s", e)
        raise credentials_exception from e


def hash_password(password: str) -> str:
   
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    
    return hashed.decode('utf-8') 


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Args:
        plain_password: Plaintext password to check.
        hashed_password: Stored bcrypt hash to compare against.

    Returns:
        True if password matches, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)
