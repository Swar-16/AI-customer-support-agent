# AI-customer-support-agent\packages\database\models\ai\retrieval_run.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class RetrievalRunModel(Base):
    """
    Durable summary of one complete retrieval execution.

    This record covers query preparation, lexical/vector branches, fusion, optional reranking, and grounding-context selection.

    Raw customer queries and retrieved chunk content must not be stored here.
    """
    __tablename__ = "retrieval_runs"
    __table_args__ = (
        CheckConstraint(
            """
            retrieval_mode IN (
                'vector',
                'lexical',
                'hybrid'
            )
            """,
            name="valid_retrieval_mode",
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
            "query_character_count >= 0",
            name="non_negative_query_characters",
        ),
        CheckConstraint(
            "requested_limit > 0",
            name="positive_requested_limit",
        ),
        CheckConstraint(
            "vector_candidate_count >= 0",
            name="non_negative_vector_candidates",
        ),
        CheckConstraint(
            "lexical_candidate_count >= 0",
            name="non_negative_lexical_candidates",
        ),
        CheckConstraint(
            "fused_candidate_count >= 0",
            name="non_negative_fused_candidates",
        ),
        CheckConstraint(
            "reranked_candidate_count >= 0",
            name="non_negative_reranked_candidates",
        ),
        CheckConstraint(
            "selected_candidate_count >= 0",
            name="non_negative_selected_candidates",
        ),
        CheckConstraint(
            "context_block_count >= 0",
            name="non_negative_context_blocks",
        ),
        CheckConstraint(
            "context_token_count >= 0",
            name="non_negative_context_tokens",
        ),
        CheckConstraint(
            """
            total_latency_ms IS NULL
            OR total_latency_ms >= 0
            """,
            name="non_negative_total_latency",
        ),
        CheckConstraint(
            """
            vector_latency_ms IS NULL
            OR vector_latency_ms >= 0
            """,
            name="non_negative_vector_latency",
        ),
        CheckConstraint(
            """
            lexical_latency_ms IS NULL
            OR lexical_latency_ms >= 0
            """,
            name="non_negative_lexical_latency",
        ),
        CheckConstraint(
            """
            fusion_latency_ms IS NULL
            OR fusion_latency_ms >= 0
            """,
            name="non_negative_fusion_latency",
        ),
        CheckConstraint(
            """
            reranker_latency_ms IS NULL
            OR reranker_latency_ms >= 0
            """,
            name="non_negative_reranker_latency",
        ),
        CheckConstraint(
            """
            context_build_latency_ms IS NULL
            OR context_build_latency_ms >= 0
            """,
            name="non_negative_context_latency",
        ),
        CheckConstraint(
            """
            (
                status = 'started'
                AND completed_at IS NULL
                AND total_latency_ms IS NULL
                AND zero_result IS NULL
                AND error_code IS NULL
            )
            OR
            (
                status = 'success'
                AND completed_at IS NOT NULL
                AND total_latency_ms IS NOT NULL
                AND zero_result IS NOT NULL
                AND error_code IS NULL
            )
            OR
            (
                status IN ('failed', 'timeout')
                AND completed_at IS NOT NULL
                AND total_latency_ms IS NOT NULL
                AND error_code IS NOT NULL
            )
            """,
            name="valid_lifecycle_state",
        ),
        CheckConstraint(
            """
            zero_result IS NULL
            OR zero_result = (selected_candidate_count = 0)
            """,
            name="valid_zero_result",
        ),
        CheckConstraint(
            """
            completed_at IS NULL
            OR completed_at >= started_at
            """,
            name="valid_completion_time",
        ),

        Index(
            "idx_retrieval_runs_ai_run_started",
            "ai_run_id",
            "started_at",
        ),
        Index(
            "idx_retrieval_runs_trace_started",
            "trace_id",
            "started_at",
        ),
        Index(
            "idx_retrieval_runs_conversation_started",
            "conversation_id",
            text("started_at DESC"),
        ),
        Index(
            "idx_retrieval_runs_status_started",
            "status",
            text("started_at DESC"),
        ),
        Index(
            "idx_retrieval_runs_mode_started",
            "retrieval_mode",
            text("started_at DESC"),
        ),
        Index(
            "idx_retrieval_runs_zero_result_started",
            "zero_result",
            text("started_at DESC"),
        ),
        Index(
            "idx_retrieval_runs_profile_started",
            "profile_identity",
            text("started_at DESC"),
        ),
        Index(
            "idx_retrieval_runs_latency",
            text("total_latency_ms DESC"),
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

    embedding_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai.embedding_calls.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    trace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    retrieval_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    profile_identity: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    configuration_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    query_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    query_character_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    requested_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    vector_candidate_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    lexical_candidate_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    fused_candidate_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    reranked_candidate_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    selected_candidate_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    context_block_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    context_token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    reranker_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    context_truncated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    zero_result: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    vector_latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    lexical_latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    fusion_latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    reranker_latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    context_build_latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    total_latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
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