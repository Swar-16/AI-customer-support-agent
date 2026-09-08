# AI-customer-support-agent\packages\database\models\ai\stage_event.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class AIStageEventModel(Base):
    """
    Durable lifecycle event for one AI orchestration stage.

    One row represents a stage start, completion, or failure. The table contains correlation, timing, and safe low-cardinality metadata only.

    Customer messages, conversation context, retrieved content, prompts, and generated responses must never be stored here.
    """
    __tablename__ = "stage_events"
    __table_args__ = (
        CheckConstraint(
            """
            event_type IN (
                'stage_started',
                'stage_completed',
                'stage_failed'
            )
            """,
            name="valid_event_type",
        ),
        CheckConstraint(
            """
            stage IN (
                'received',
                'context_built',
                'intent_classified',
                'decision_made',
                'retrieval_completed',
                'response_generated',
                'guardrails_completed',
                'action_proposed',
                'action_completed',
                'escalated',
                'completed',
                'failed'
            )
            """,
            name="valid_stage",
        ),
        CheckConstraint(
            """
            duration_ms IS NULL
            OR duration_ms >= 0
            """,
            name="non_negative_duration",
        ),
        CheckConstraint(
            """
            (
                event_type = 'stage_started'
                AND duration_ms IS NULL
                AND error_code IS NULL
                AND retryable IS NULL
            )
            OR
            (
                event_type = 'stage_completed'
                AND error_code IS NULL
                AND retryable IS NULL
            )
            OR
            (
                event_type = 'stage_failed'
                AND error_code IS NOT NULL
                AND retryable IS NOT NULL
            )
            """,
            name="valid_event_payload",
        ),

        Index(
            "idx_ai_stage_events_run_occurred",
            "ai_run_id",
            "occurred_at",
        ),
        Index(
            "idx_ai_stage_events_trace_occurred",
            "trace_id",
            "occurred_at",
        ),
        Index(
            "idx_ai_stage_events_conversation_occurred",
            "conversation_id",
            text("occurred_at DESC"),
        ),
        Index(
            "idx_ai_stage_events_stage_occurred",
            "stage",
            text("occurred_at DESC"),
        ),
        Index(
            "idx_ai_stage_events_type_occurred",
            "event_type",
            text("occurred_at DESC"),
        ),
        Index(
            "idx_ai_stage_events_error_occurred",
            "error_code",
            text("occurred_at DESC"),
        ),

        {
            "schema": "ai",
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    ai_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai.runs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    trigger_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    stage: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    retryable: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )