# AI-customer-support-agent\packages\database\models\support\ticket_comment.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class TicketCommentModel(Base):
    """
    Append-only comment belonging to a support ticket.

    Comments support two visibility levels:

    customer:
        Visible to the customer and support staff.

    internal:
        Visible only to support agents and administrators.

    Customer-authored comments can never be internal notes.

    Comments are intentionally append-only for the MVP. If correction is required, another comment should be added.
    This preserves a truthful support and audit history.
    """
    __tablename__ = "ticket_comments"
    __table_args__ = (
        CheckConstraint(
            """
            author_role IN (
                'customer',
                'support_agent',
                'admin',
                'system'
            )
            """,
            name="valid_author_role",
        ),
        CheckConstraint(
            """
            visibility IN (
                'customer',
                'internal'
            )
            """,
            name="valid_visibility",
        ),
        CheckConstraint(
            """
            author_role <> 'customer'
            OR visibility = 'customer'
            """,
            name="customer_comment_visibility",
        ),
        CheckConstraint(
            "length(btrim(content)) > 0",
            name="content_not_blank",
        ),
        
        Index(
            "idx_ticket_comments_ticket_created",
            "ticket_id",
            "created_at",
            "id",
        ),
        Index(
            "idx_ticket_comments_author_created",
            "author_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_ticket_comments_visibility_created",
            "visibility",
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

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.tickets.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    author_id: Mapped[
        uuid.UUID | None
    ] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "support.users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    author_role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    visibility: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="customer",
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    metadata_: Mapped[
        dict[str, Any]
    ] = mapped_column(
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