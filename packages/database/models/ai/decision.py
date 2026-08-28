import uuid
from datetime import datetime
from typing import Any
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class AIDecisionModel(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        CheckConstraint(
            """
            decision_type IN (
                'answer',
                'retrieve_information',
                'perform_action',
                'ask_clarification',
                'escalate'
            )
            """,
            name="valid_decision_type",
        ),
        CheckConstraint(
            """
            confidence IS NULL
            OR (confidence >= 0 AND confidence <= 1)
            """,
            name="valid_confidence",
        ),

        Index(
            "idx_ai_decisions_run",
            "ai_run_id",
        ),
        Index(
            "idx_ai_decisions_llm_call",
            "llm_call_id",
        ),
        Index(
            "idx_ai_decisions_type_created",
            "decision_type",
            text("created_at DESC"),
        ),
        Index(
            "idx_ai_decisions_reason_code",
            "reason_code",
        ),

        {"schema": "ai"},
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

    llm_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai.llm_calls.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    decision_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )

    reason_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    reason_summary: Mapped[str | None] = mapped_column(
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