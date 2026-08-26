import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class ConversationModel(Base):
    __tablename__ = "conversations"

    __table_args__ = (
        CheckConstraint(
            """
            status IN (
                'open',
                'waiting_for_customer',
                'waiting_for_agent',
                'escalated',
                'resolved',
                'closed'
            )
            """,
            name="valid_status",
        ),
        CheckConstraint(
            "channel IN ('web', 'mobile', 'email', 'api')",
            name="valid_channel",
        ),
        CheckConstraint(
            "next_message_sequence >= 1",
            name="valid_next_message_sequence",
        ),
        
        Index(
            "idx_conversations_user_created_at",
            "user_id",
            "created_at",
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
        ForeignKey("support.users.id"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="open",
    )

    channel: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="web",
    )

    title: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    
    next_message_sequence: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
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

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )