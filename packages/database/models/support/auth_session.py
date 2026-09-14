# AI-customer-support-agent\packages\database\models\support\auth_session.py
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class AuthSessionModel(Base):
    """
    Persisted refresh-token session.

    The raw refresh token must never be stored. Only its cryptographic hash is persisted.

    Refresh-token rotation creates a new session and marks the previous session as revoked with
    ``replaced_by_session_id`` pointing to the replacement.
    """
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(refresh_token_hash)) > 0",
            name="refresh_token_hash_not_blank",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="expires_after_creation",
        ),
        CheckConstraint(
            """
            (revoked_at IS NULL AND revocation_reason IS NULL)
            OR
            (revoked_at IS NOT NULL)
            """,
            name="valid_revocation_state",
        ),
        CheckConstraint(
            """
            replaced_by_session_id IS NULL
            OR revoked_at IS NOT NULL
            """,
            name="replacement_requires_revocation",
        ),
        
        Index(
            "idx_auth_sessions_user_created",
            "user_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_auth_sessions_family",
            "family_id",
        ),
        Index(
            "idx_auth_sessions_expires",
            "expires_at",
        ),
        Index(
            "idx_auth_sessions_active_user",
            "user_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        
        {"schema": "support"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    refresh_token_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )

    replaced_by_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.auth_sessions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        unique=True,
    )

    client_ip: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    user_agent: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    revocation_reason: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )