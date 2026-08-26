import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class LLMCallModel(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint(
            """
            purpose IN (
                'intent_classification',
                'query_rewrite',
                'answer_generation',
                'action_decision',
                'escalation_summary',
                'guardrail_validation',
                'conversation_summary',
                'other'
            )
            """,
            name="valid_purpose",
        ),

        CheckConstraint(
            "status IN ('started','success', 'failed', 'timeout')",
            name="valid_status",
        ),
        CheckConstraint(
            "input_tokens >= 0",
            name="valid_input_tokens",
        ),
        CheckConstraint(
            "output_tokens >= 0",
            name="valid_output_tokens",
        ),
        CheckConstraint(
            "cached_input_tokens >= 0",
            name="valid_cached_input_tokens",
        ),
        CheckConstraint(
            "total_tokens >= 0",
            name="valid_total_tokens",
        ),
        CheckConstraint(
            "estimated_cost_usd IS NULL OR estimated_cost_usd >= 0",
            name="valid_estimated_cost",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="valid_latency",
        ),
        CheckConstraint(
            "temperature IS NULL OR (temperature >= 0 AND temperature <= 2)",
            name="valid_temperature",
        ),

        Index(
            "idx_llm_calls_ai_run",
            "ai_run_id",
        ),
        Index(
            "idx_llm_calls_model_started",
            "provider",
            "model",
            "started_at",
        ),
        Index(
            "idx_llm_calls_purpose_started",
            "purpose",
            "started_at",
        ),
        Index(
            "idx_llm_calls_status_started",
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

    ai_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai.runs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("config.prompt_versions.id"),
        nullable=True,
    )

    purpose: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    model: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    cached_input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    total_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 8),
        nullable=True,
    )

    temperature: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 3),
        nullable=True,
    )

    latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    provider_request_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )