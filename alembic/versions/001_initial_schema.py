"""Initial database schema creating users and moderation_logs tables.

Revision ID: 001_initial
Revises: None
Create Date: 2026-10-19 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial tables and indexes for users and moderation logs."""
    # Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("hashed_password", sa.String(length=256), nullable=False),
        sa.Column("is_blacklisted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("blacklisted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("violation_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_index(op.f("ix_users_is_blacklisted"), "users", ["is_blacklisted"], unique=False)

    # Create moderation_logs table
    op.create_table(
        "moderation_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.String(length=128), nullable=False),
        sa.Column("original_message", sa.Text(), nullable=False),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("toxicity_score", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("matched_patterns", sa.Text(), nullable=True),
        sa.Column("action_taken", sa.String(length=32), nullable=False, server_default=sa.text("'allowed'")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_moderation_logs_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moderation_logs")),
    )

    # Single-column indexes on moderation_logs
    op.create_index(op.f("ix_moderation_logs_room_id"), "moderation_logs", ["room_id"], unique=False)
    op.create_index(op.f("ix_moderation_logs_flagged"), "moderation_logs", ["flagged"], unique=False)

    # Compound indexes for time-series queries and moderation dashboards
    op.create_index(
        "ix_moderation_user_created",
        "moderation_logs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_moderation_room_created",
        "moderation_logs",
        ["room_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_moderation_flagged_created",
        "moderation_logs",
        ["flagged", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop moderation_logs and users tables and all associated indexes."""
    # Drop moderation_logs compound indexes
    op.drop_index("ix_moderation_flagged_created", table_name="moderation_logs")
    op.drop_index("ix_moderation_room_created", table_name="moderation_logs")
    op.drop_index("ix_moderation_user_created", table_name="moderation_logs")

    # Drop moderation_logs single-column indexes
    op.drop_index(op.f("ix_moderation_logs_flagged"), table_name="moderation_logs")
    op.drop_index(op.f("ix_moderation_logs_room_id"), table_name="moderation_logs")

    # Drop moderation_logs table
    op.drop_table("moderation_logs")

    # Drop users indexes
    op.drop_index(op.f("ix_users_is_blacklisted"), table_name="users")
    op.drop_index(op.f("ix_users_username"), table_name="users")

    # Drop users table
    op.drop_table("users")
