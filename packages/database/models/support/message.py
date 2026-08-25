import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class MessageModel(Base):
    __tablename__ = "messages"

    __table_args__ = (
        CheckConstraint(
            """
            role IN (
                'customer',
                'assistant',
                'support_agent',
                'system',
                'tool'
            )
            """,
            name="valid_role",
        ),
        UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_messages_conversation_sequence",
        ),
        Index(
            "idx_messages_conversation_sequence",
            "conversation_id",
            "sequence_number",
        ),
        {"schema": "support"},
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

    role: Mapped[str] = mapped_column(
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    sequence_number: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
    ## metadata_ used intead of metadata
    ## because SQLAlchemy already uses metadata.
    ## The actual database column is still called: metadata

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )