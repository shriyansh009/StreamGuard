"""Authentication REST API routes for StreamGuard.

Provides user registration and login endpoints returning JWT tokens.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models.user import User
from app.schemas import TokenResponse, UserLogin, UserRegister

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """Register a new user account and return a JWT access token.

    Args:
        payload: Username and password for registration.
        db: Async database session (injected).

    Returns:
        TokenResponse with JWT access_token.

    Raises:
        HTTPException 409: Username already exists.
    """
    # Check if username already exists
    result = await db.execute(select(User).where(User.username == payload.username))
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{payload.username}' is already registered",
        )

    # Create new user
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("New user registered: '%s' (id=%s)", user.username, user.id)

    # Generate JWT token
    token = create_access_token(user_id=str(user.id), username=user.username)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """Authenticate a user and return a JWT access token.

    Args:
        payload: Username and password for login.
        db: Async database session (injected).

    Returns:
        TokenResponse with JWT access_token.

    Raises:
        HTTPException 401: Invalid credentials.
    """
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if user.is_blacklisted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended due to policy violations",
        )

    logger.info("User logged in: '%s' (id=%s)", user.username, user.id)

    token = create_access_token(user_id=str(user.id), username=user.username)
    return TokenResponse(access_token=token)
