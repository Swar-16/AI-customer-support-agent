import uuid
from datetime import datetime
from typing import Any
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class IntentPredictionModel(Base):
    __tablename__ = "intent_predictions"
    __table_args__ = (
        CheckConstraint(
            """
            confidence IS NULL
            OR (confidence >= 0 AND confidence <= 1)
            """,
            name="valid_confidence",
        ),

        Index(
            "idx_intent_predictions_ai_run",
            "ai_run_id",
        ),
        Index(
            "idx_intent_predictions_intent_created",
            "intent",
            "created_at",
        ),
        Index(
            "idx_intent_predictions_confidence",
            "confidence",
        ),
        Index(
            "idx_intent_predictions_llm_call",
            "llm_call_id",
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

    intent: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )

    entities: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    needs_clarification: Mapped[bool] = mapped_column(
        nullable=False,
        server_default="false",
    )

    reasoning_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )