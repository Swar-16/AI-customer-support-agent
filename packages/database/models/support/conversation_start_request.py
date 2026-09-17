# AI-customer-support-agent\packages\database\models\support\conversation_start_request.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base

class ConversationStartRequestModel(Base):
    """
    Durable idempotency and recovery record for starting a conversation.

    The raw idempotency key is never persisted. The API/application layer stores a SHA-256 digest scoped to the authenticated customer.

    The conversation, first customer message, and this row must be created in one transaction.
    AI/provider execution begins only after that transaction commits.
    """
    __tablename__ = "conversation_start_requests"

    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "idempotency_key_hash",
            name="uq_conversation_start_requests_customer_key",
        ),
        CheckConstraint(
            """
            status IN (
                'accepted',
                'processing',
                'completed',
                'failed'
            )
            """,
            name="valid_status",
        ),
        CheckConstraint(
            """
            idempotency_key_hash
            ~ '^[0-9a-f]{64}$'
            """,
            name="valid_idempotency_key_hash",
        ),
        CheckConstraint(
            """
            request_fingerprint
            ~ '^[0-9a-f]{64}$'
            """,
            name="valid_request_fingerprint",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="nonnegative_attempt_count",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="valid_timestamp_order",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="valid_expiration",
        ),
        CheckConstraint(
            """
            completed_at IS NULL
            OR completed_at >= created_at
            """,
            name="valid_completion_timestamp",
        ),
        CheckConstraint(
            """
            response_snapshot IS NULL
            OR jsonb_typeof(response_snapshot) = 'object'
            """,
            name="response_snapshot_is_object",
        ),
        CheckConstraint(
            """
            (
                status = 'accepted'
                AND processing_token IS NULL
                AND processing_expires_at IS NULL
                AND completed_at IS NULL
                AND response_snapshot IS NULL
            )
            OR
            (
                status = 'processing'
                AND processing_token IS NOT NULL
                AND processing_expires_at IS NOT NULL
                AND completed_at IS NULL
                AND response_snapshot IS NULL
                AND attempt_count > 0
            )
            OR
            (
                status IN ('completed', 'failed')
                AND processing_token IS NULL
                AND processing_expires_at IS NULL
                AND completed_at IS NOT NULL
                AND response_snapshot IS NOT NULL
                AND attempt_count > 0
            )
            """,
            name="valid_lifecycle_state",
        ),
        
        Index(
            "idx_conversation_start_requests_status_lease",
            "status",
            "processing_expires_at",
        ),
        Index(
            "idx_conversation_start_requests_expires_at",
            "expires_at",
        ),
        Index(
            "idx_conversation_start_requests_conversation",
            "conversation_id",
        ),
        
        {"schema": "support"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    idempotency_key_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    request_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="accepted",
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.conversations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    customer_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.messages.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    latest_ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai.runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    processing_token: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    processing_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    response_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
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

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )