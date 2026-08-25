import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class AIRunModel(Base):
    __tablename__ = "runs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="valid_status",
        ),
        CheckConstraint(
            "total_latency_ms IS NULL OR total_latency_ms >= 0",
            name="valid_total_latency",
        ),
        Index(
            "idx_ai_runs_conversation_started",
            "conversation_id",
            "started_at",
        ),
        Index(
            "idx_ai_runs_trace",
            "trace_id",
        ),
        Index(
            "idx_ai_runs_parent",
            "parent_run_id",
        ),
        Index(
            "idx_ai_runs_status_started",
            "status",
            "started_at",
        ),
        
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        server_default=text("uuidv7()"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support.conversations.id"),
        nullable=False,
    )

    trigger_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support.messages.id"),
        nullable=False,
    )

    response_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support.messages.id"),
    )

    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.runs.id"),
    )

    pipeline_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="running",
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    total_latency_ms: Mapped[int | None] = mapped_column(Integer)

    error_code: Mapped[str | None] = mapped_column(String(100))

    error_message: Mapped[str | None] = mapped_column(Text)