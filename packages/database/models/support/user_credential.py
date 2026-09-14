# AI-customer-support-agent\packages\database\models\support\user_credential.py
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class UserCredentialModel(Base):
    """
    Local authentication credentials for a support user.

    A user may exist without credentials. This preserves compatibility with:
    - existing seeded users;
    - system users;
    - users created by integration tests;
    - future externally authenticated users.

    Passwords are never stored directly. ``password_hash`` contains an Argon2id encoded hash.
    """
    __tablename__ = "user_credentials"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(email_normalized)) > 0",
            name="email_not_blank",
        ),
        CheckConstraint(
            "email_normalized = lower(btrim(email_normalized))",
            name="email_is_normalized",
        ),
        CheckConstraint(
            "length(btrim(password_hash)) > 0",
            name="password_hash_not_blank",
        ),
        CheckConstraint(
            "failed_login_attempts >= 0",
            name="failed_login_attempts_non_negative",
        ),
        
        {"schema": "support"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.users.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    email_normalized: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        unique=True,
    )

    password_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )