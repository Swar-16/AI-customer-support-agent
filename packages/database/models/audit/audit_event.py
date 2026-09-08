# AI-customer-support-agent\packages\database\models\audit\audit_event.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class AuditEventModel(Base):
    """
    Immutable business audit event.

    Records security-relevant and business-relevant state mutations such as:

    - ticket creation and updates;
    - escalation creation and resolution;
    - feedback submission and review;
    - knowledge document/version lifecycle changes.

    Audit events are append-only. Application repositories must never expose update or delete operations for this model.

    Correlation identifiers intentionally do not use foreign keys. Audit history must remain attributable even if
    the corresponding operational record is later archived or deleted.
    """
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            """
            actor_type IN (
                'customer',
                'agent',
                'admin',
                'system',
                'ai'
            )
            """,
            name="valid_actor_type",
        ),
        CheckConstraint(
            "length(trim(event_type)) > 0",
            name="non_empty_event_type",
        ),
        CheckConstraint(
            "length(trim(entity_type)) > 0",
            name="non_empty_entity_type",
        ),
        CheckConstraint(
            "length(trim(action)) > 0",
            name="non_empty_action",
        ),
        CheckConstraint(
            """
            (
                actor_type IN ('system', 'ai')
                AND actor_id IS NULL
            )
            OR
            actor_type IN ('customer', 'agent', 'admin')
            """,
            name="valid_actor_identity",
        ),

        Index(
            "idx_audit_events_occurred",
            text("occurred_at DESC"),
        ),
        Index(
            "idx_audit_events_event_occurred",
            "event_type",
            text("occurred_at DESC"),
        ),
        Index(
            "idx_audit_events_entity_occurred",
            "entity_type",
            "entity_id",
            text("occurred_at DESC"),
        ),
        Index(
            "idx_audit_events_actor_occurred",
            "actor_type",
            "actor_id",
            text("occurred_at DESC"),
        ),
        Index(
            "idx_audit_events_trace",
            "trace_id",
        ),
        Index(
            "idx_audit_events_conversation",
            "conversation_id",
            text("occurred_at DESC"),
        ),
        Index(
            "idx_audit_events_ai_run",
            "ai_run_id",
            text("occurred_at DESC"),
        ),

        {
            "schema": "audit",
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    entity_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    actor_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    trace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    before_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    after_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    reason: Mapped[str | None] = mapped_column(
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

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )