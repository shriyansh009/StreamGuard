"""User model definition for StreamGuard."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
import uuid

from sqlalchemy import Boolean, DateTime, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.moderation_log import ModerationLog


class User(Base):
    """User entity representing a registered platform user.

    Attributes:
        id: Unique UUID primary key.
        username: Unique username, indexed for fast lookups.
        hashed_password: Argon2 or bcrypt password hash string.
        is_blacklisted: Flag denoting whether user is banned/blacklisted.
        blacklisted_at: Timestamp when user was blacklisted, if applicable.
        violation_count: Running count of moderation violations recorded.
        created_at: Timestamp when account was created (server default UTC).
        updated_at: Timestamp when account was last updated (server default UTC).
        moderation_logs: Relational collection of moderation events tied to this user.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    username: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )
    is_blacklisted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    blacklisted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    violation_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationship to moderation_logs
    moderation_logs: Mapped[list[ModerationLog]] = relationship(
        "ModerationLog",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        """Return developer-friendly string representation."""
        return (
            f"<User(id={self.id}, username='{self.username}', "
            f"is_blacklisted={self.is_blacklisted}, violations={self.violation_count})>"
        )
