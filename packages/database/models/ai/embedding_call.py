# AI-customer-support-agent\packages\database\models\ai\embedding_call.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class EmbeddingCallModel(Base):
    """
    Durable telemetry for one embedding-provider invocation.

    This represents a provider call, not a persisted chunk embedding.

    It supports:

    - query-time embeddings linked to an AI run;
    - knowledge-ingestion embedding batches;
    - re-indexing and evaluation calls;
    - provider latency and failure monitoring.

    Raw input text and vectors must never be stored in this table.
    """
    __tablename__ = "embedding_calls"
    __table_args__ = (
        CheckConstraint(
            """
            purpose IN (
                'query',
                'document_ingestion',
                'reindex',
                'evaluation',
                'other'
            )
            """,
            name="valid_purpose",
        ),
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
            "input_count > 0",
            name="positive_input_count",
        ),
        CheckConstraint(
            "total_input_characters >= 0",
            name="non_negative_input_characters",
        ),
        CheckConstraint(
            """
            dimensions IS NULL
            OR dimensions > 0
            """,
            name="positive_dimensions",
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
                AND error_code IS NULL
                AND dimensions IS NOT NULL
            )
            OR
            (
                status IN ('failed', 'timeout')
                AND completed_at IS NOT NULL
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
            "idx_embedding_calls_ai_run",
            "ai_run_id",
            "started_at",
        ),
        Index(
            "idx_embedding_calls_trace",
            "trace_id",
            "started_at",
        ),
        Index(
            "idx_embedding_calls_version",
            "knowledge_version_id",
            "started_at",
        ),
        Index(
            "idx_embedding_calls_provider_started",
            "provider",
            "model",
            text("started_at DESC"),
        ),
        Index(
            "idx_embedding_calls_purpose_started",
            "purpose",
            text("started_at DESC"),
        ),
        Index(
            "idx_embedding_calls_status_started",
            "status",
            text("started_at DESC"),
        ),
        Index(
            "idx_embedding_calls_error_started",
            "error_code",
            text("started_at DESC"),
        ),
        Index(
            "idx_embedding_calls_latency",
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

    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai.runs.id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )

    trace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    knowledge_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge.knowledge_document_versions.id",
            ondelete="SET NULL",
        ),
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

    provider_revision: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    input_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    total_input_characters: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    request_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    dimensions: Mapped[int | None] = mapped_column(
        Integer,
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