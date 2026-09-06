# AI-customer-support-agent\packages\database\models\support\escalation.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from packages.database.base import Base


class EscalationModel(Base):
    """
    Persistent human-review escalation for a support conversation.

    An escalation is a support-domain workflow entity, not merely AI telemetry.

    It may be caused by:
        - a deterministic AI decision;
        - response guardrails;
        - trusted system policy;
        - manual/support intervention.

    The originating AI run is optional so the model remains valid for escalations that are not created by an AI execution.

    Ticket ownership is intentionally modeled separately. A future ticket may reference this escalation rather than this table owning a ticket_id.
    """
    __tablename__ = "escalations"
    __table_args__ = (
        CheckConstraint(
            """
            source IN ('decision', 'guardrail', 'system', 'manual')
            """,
            name="valid_source",
        ),
        CheckConstraint(
            """
            priority IN ('low', 'normal', 'high', 'urgent')
            """,
            name="valid_priority",
        ),
        CheckConstraint(
            """
            status IN ('open', 'in_review', 'resolved', 'dismissed')
            """,
            name="valid_status",
        ),
        CheckConstraint(
            """
            (
                status IN ('resolved', 'dismissed')
                AND resolved_at IS NOT NULL
            )
            OR
            (
                status IN ('open', 'in_review')
                AND resolved_at IS NULL
            )
            """,
            name="valid_resolution_state",
        ),
        
        Index(
            "idx_escalations_conversation_created",
            "conversation_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_escalations_status_created",
            "status",
            text("created_at DESC"),
        ),
        Index(
            "idx_escalations_priority_status",
            "priority",
            "status",
        ),
        Index(
            "uq_escalations_ai_run",
            "ai_run_id",
            unique=True,
            postgresql_where=text(
                "ai_run_id IS NOT NULL"
            ),
        ),
        Index(
            "idx_escalations_trigger_message",
            "trigger_message_id",
        ),
        Index(
            "idx_escalations_reason_code",
            "reason_code",
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

    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai.runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    trigger_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.messages.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    reason_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    reason_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="normal",
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="open",
    )

    handoff_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
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

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )