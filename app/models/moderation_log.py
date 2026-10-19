"""ModerationLog model definition for StreamGuard."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
import uuid

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class ModerationLog(Base):
    """Moderation audit record for all processed stream messages.

    Attributes:
        id: Unique UUID primary key.
        user_id: Foreign key reference to users.id.
        room_id: Chat room or stream channel identifier, indexed for filtering.
        original_message: Raw message text sent by user.
        flagged: Flag indicating whether message violated moderation rules.
        toxicity_score: Computed ML/heuristic toxicity score (0.0 to 1.0).
        matched_patterns: Serialized JSON array of matched regex or keyword patterns.
        action_taken: Moderation action ('allowed', 'flagged', 'blocked').
        processed_at: Timestamp when moderation evaluation completed.
        created_at: Timestamp when message was initially logged.
        user: Many-to-one relationship back to User entity.
    """

    __tablename__ = "moderation_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    room_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )
    original_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    flagged: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    toxicity_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )
    matched_patterns: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    action_taken: Mapped[str] = mapped_column(
        String(32),
        default="allowed",
        nullable=False,
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # CRITICAL: Compound indexes for time-series queries and dashboard analytics
    __table_args__ = (
        Index("ix_moderation_user_created", "user_id", "created_at"),
        Index("ix_moderation_room_created", "room_id", "created_at"),
        Index("ix_moderation_flagged_created", "flagged", "created_at"),
    )

    # Relationship back to User
    user: Mapped[User] = relationship(
        "User",
        back_populates="moderation_logs",
    )

    def __repr__(self) -> str:
        """Return developer-friendly string representation."""
        return (
            f"<ModerationLog(id={self.id}, user_id={self.user_id}, "
            f"room_id='{self.room_id}', flagged={self.flagged}, action='{self.action_taken}')>"
        )
