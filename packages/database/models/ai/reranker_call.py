# AI-customer-support-agent\packages\database\models\ai\reranker_call.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class RerankerCallModel(Base):
    """
    Durable telemetry for one reranking execution.

    Supports deterministic passthrough reranking, local models, and external provider APIs. Query and candidate content must not be persisted here.
    """
    __tablename__ = "reranker_calls"
    __table_args__ = (
        CheckConstraint(
            """
            status IN (
                'started',
                'success',
                'failed',
                'timeout'
            )
            """,
            name="valid_status",
        ),
        CheckConstraint(
            "input_candidate_count >= 0",
            name="non_negative_input_candidates",
        ),
        CheckConstraint(
            "requested_limit > 0",
            name="positive_requested_limit",
        ),
        CheckConstraint(
            "output_candidate_count >= 0",
            name="non_negative_output_candidates",
        ),
        CheckConstraint(
            """
            output_candidate_count
            <= input_candidate_count
            """,
            name="valid_output_cardinality",
        ),
        CheckConstraint(
            """
            output_candidate_count
            <= requested_limit
            """,
            name="output_within_requested_limit",
        ),
        CheckConstraint(
            """
            latency_ms IS NULL
            OR latency_ms >= 0
            """,
            name="non_negative_latency",
        ),
        CheckConstraint(
            """
            (
                status = 'started'
                AND completed_at IS NULL
                AND latency_ms IS NULL
                AND error_code IS NULL
            )
            OR
            (
                status = 'success'
                AND completed_at IS NOT NULL
                AND latency_ms IS NOT NULL
                AND error_code IS NULL
            )
            OR
            (
                status IN ('failed', 'timeout')
                AND completed_at IS NOT NULL
                AND latency_ms IS NOT NULL
                AND error_code IS NOT NULL
            )
            """,
            name="valid_lifecycle_state",
        ),
        CheckConstraint(
            """
            completed_at IS NULL
            OR completed_at >= started_at
            """,
            name="valid_completion_time",
        ),

        Index(
            "idx_reranker_calls_retrieval_run",
            "retrieval_run_id",
            "started_at",
        ),
        Index(
            "idx_reranker_calls_trace",
            "trace_id",
            "started_at",
        ),
        Index(
            "idx_reranker_calls_provider_started",
            "provider",
            "model",
            text("started_at DESC"),
        ),
        Index(
            "idx_reranker_calls_identity_started",
            "reranker_id",
            text("started_at DESC"),
        ),
        Index(
            "idx_reranker_calls_status_started",
            "status",
            text("started_at DESC"),
        ),
        Index(
            "idx_reranker_calls_error_started",
            "error_code",
            text("started_at DESC"),
        ),
        Index(
            "idx_reranker_calls_latency",
            text("latency_ms DESC"),
        ),

        {
            "schema": "ai",
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    retrieval_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai.retrieval_runs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    trace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    reranker_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    revision: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    query_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    input_candidate_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    requested_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    output_candidate_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
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

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
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