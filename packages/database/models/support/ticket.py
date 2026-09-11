# AI-customer-support-agent\packages\database\models\support\ticket.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text, Identity
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class TicketModel(Base):
    """
    Persistent support work item.

    A ticket is different from an escalation:

    - an escalation records why human review became necessary;
    - a ticket is the durable work item owned and managed by support staff.

    A ticket may originate from:
    - an AI or guardrail escalation;
    - a customer-created request;
    - a manually created support workflow;
    - a system-created workflow.

    One escalation may create at most one ticket. Tickets created directly by customers or support staff have escalation_id=None.
    """
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            """
            source IN (
                'customer',
                'escalation',
                'agent',
                'system'
            )
            """,
            name="valid_source",
        ),
        CheckConstraint(
            """
            category IN (
                'billing',
                'refund',
                'order',
                'account',
                'technical',
                'security',
                'product',
                'general',
                'other'
            )
            """,
            name="valid_category",
        ),
        CheckConstraint(
            """
            priority IN (
                'low',
                'normal',
                'high',
                'urgent'
            )
            """,
            name="valid_priority",
        ),
        CheckConstraint(
            """
            status IN (
                'open',
                'in_progress',
                'waiting_for_customer',
                'resolved',
                'closed',
                'reopened'
            )
            """,
            name="valid_status",
        ),
        CheckConstraint(
            "length(btrim(subject)) > 0",
            name="subject_not_blank",
        ),
        CheckConstraint(
            "length(btrim(description)) > 0",
            name="description_not_blank",
        ),
        CheckConstraint(
            """
            resolution_summary IS NULL
            OR length(btrim(resolution_summary)) > 0
            """,
            name="resolution_summary_not_blank",
        ),
        CheckConstraint(
            """
            (
                status IN ('resolved', 'closed')
                AND resolved_at IS NOT NULL
                AND resolution_summary IS NOT NULL
            )
            OR
            (
                status NOT IN ('resolved', 'closed')
                AND resolved_at IS NULL
                AND resolution_summary IS NULL
            )
            """,
            name="valid_resolution_state",
        ),
        CheckConstraint(
            """
            (
                status = 'closed'
                AND closed_at IS NOT NULL
            )
            OR
            (
                status <> 'closed'
                AND closed_at IS NULL
            )
            """,
            name="valid_closed_state",
        ),
        CheckConstraint(
            """
            assigned_agent_id IS NULL
            OR assigned_at IS NOT NULL
            """,
            name="valid_assignment_state",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="valid_updated_at",
        ),
        CheckConstraint(
            """
            assigned_at IS NULL
            OR assigned_at >= created_at
            """,
            name="valid_assigned_at",
        ),
        CheckConstraint(
            """
            resolved_at IS NULL
            OR resolved_at >= created_at
            """,
            name="valid_resolved_at",
        ),
        CheckConstraint(
            """
            closed_at IS NULL
            OR closed_at >= created_at
            """,
            name="valid_closed_at",
        ),
        CheckConstraint(
            "row_version > 0",
            name="positive_row_version",
        ),
        
        UniqueConstraint(
            "ticket_number",
            name="uq_tickets_ticket_number",
        ),
        
        Index(
            "uq_tickets_escalation",
            "escalation_id",
            unique=True,
            postgresql_where=text("escalation_id IS NOT NULL"),
        ),
        Index(
            "idx_tickets_customer_created",
            "customer_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_tickets_conversation_created",
            "conversation_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_tickets_status_created",
            "status",
            text("created_at DESC"),
        ),
        Index(
            "idx_tickets_priority_status",
            "priority",
            "status",
        ),
        Index(
            "idx_tickets_assignee_status",
            "assigned_agent_id",
            "status",
        ),
        Index(
            "idx_tickets_category_created",
            "category",
            text("created_at DESC"),
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

    ticket_number: Mapped[int] = mapped_column(
        BigInteger,
        Identity(
            start=1,
            increment=1,
        ),
        nullable=False,
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.conversations.id",
            ondelete="RESTRICT",
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

    source_message_id: Mapped[
        uuid.UUID | None
    ] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.messages.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    escalation_id: Mapped[
        uuid.UUID | None
    ] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.escalations.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    assigned_agent_id: Mapped[
        uuid.UUID | None
    ] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    subject: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="general",
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

    resolution_summary: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    metadata_: Mapped[
        dict[str, Any]
    ] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    row_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
        default=1,
    )
    
    __mapper_args__ = {
        "version_id_col": row_version,
        "version_id_generator": (
            lambda current_version:
            (current_version or 0) + 1
        ),
    }

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

    assigned_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    resolved_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )