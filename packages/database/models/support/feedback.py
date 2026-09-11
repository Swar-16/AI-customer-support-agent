# AI-customer-support-agent\packages\database\models\support\feedback.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base

class FeedbackModel(Base):
    """
    Customer feedback for one AI-generated assistant response.

    The model deliberately links feedback to both the visible assistant message and its AI run:

    - response_message_id identifies what the customer evaluated;
    - ai_run_id connects the feedback to intent, decision, retrieval, generation, guardrail, latency, and token telemetry;
    - conversation_id and customer_id support ownership validation and dashboard aggregation.

    A response can receive at most one feedback record. A later application service may allow the 
    customer to update that record without creating duplicate ratings.
    """
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            "rating BETWEEN 1 AND 5",
            name="valid_rating",
        ),
        CheckConstraint(
            """
            status IN (
                'pending',
                'reviewed',
                'actioned',
                'dismissed'
            )
            """,
            name="valid_status",
        ),
        CheckConstraint(
            """
            comment IS NULL
            OR length(btrim(comment)) > 0
            """,
            name="comment_not_blank",
        ),
        CheckConstraint(
            """
            review_notes IS NULL
            OR length(btrim(review_notes)) > 0
            """,
            name="review_notes_not_blank",
        ),
        CheckConstraint(
            """
            (
                status = 'pending'
                AND reviewed_at IS NULL
                AND reviewed_by_user_id IS NULL
                AND review_notes IS NULL
            )
            OR
            (
                status IN ('reviewed', 'actioned', 'dismissed')
                AND reviewed_at IS NOT NULL
            )
            """,
            name="valid_review_state",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="valid_updated_at",
        ),
        CheckConstraint(
            "row_version > 0",
            name="positive_row_version",
        ),
        
        UniqueConstraint(
            "response_message_id",
            name="uq_feedback_response_message",
        ),
        
        Index(
            "idx_feedback_conversation_created",
            "conversation_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_feedback_customer_created",
            "customer_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_feedback_ai_run",
            "ai_run_id",
        ),
        Index(
            "idx_feedback_status_created",
            "status",
            text("created_at DESC"),
        ),
        Index(
            "idx_feedback_rating_created",
            "rating",
            text("created_at DESC"),
        ),
        Index(
            "idx_feedback_helpful_created",
            "helpful",
            text("created_at DESC"),
        ),
        Index(
            "idx_feedback_reason_codes_gin",
            "reason_codes",
            postgresql_using="gin",
        ),
        
        {
            "schema": "support",
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.conversations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    response_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.messages.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai.runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    rating: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    helpful: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    reason_codes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="pending",
    )

    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    review_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    row_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
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

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __mapper_args__ = {
        "version_id_col": row_version,
        "version_id_generator": (
            lambda current_version: (current_version or 0) + 1
        ),
    }