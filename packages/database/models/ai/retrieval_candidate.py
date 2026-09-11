# AI-customer-support-agent\packages\database\models\ai\retrieval_candidate.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base


class RetrievalCandidateModel(Base):
    """
    Durable score and ranking provenance for one retrieval candidate.

    Chunk content is deliberately not duplicated. Historical document, version, and chunk identifiers remain
    stored even if the corresponding knowledge artifacts are later removed.
    """
    __tablename__ = "retrieval_candidates"
    __table_args__ = (
        UniqueConstraint(
            "retrieval_run_id",
            "chunk_id",
            name="uq_retrieval_candidates_run_chunk",
        ),
        CheckConstraint(
            """
            vector_rank IS NULL
            OR vector_rank > 0
            """,
            name="positive_vector_rank",
        ),
        CheckConstraint(
            """
            lexical_rank IS NULL
            OR lexical_rank > 0
            """,
            name="positive_lexical_rank",
        ),
        CheckConstraint(
            """
            fusion_rank IS NULL
            OR fusion_rank > 0
            """,
            name="positive_fusion_rank",
        ),
        CheckConstraint(
            """
            reranker_rank IS NULL
            OR reranker_rank > 0
            """,
            name="positive_reranker_rank",
        ),
        CheckConstraint(
            """
            final_rank IS NULL
            OR final_rank > 0
            """,
            name="positive_final_rank",
        ),
        CheckConstraint(
            """
            vector_similarity IS NULL
            OR (
                vector_similarity >= -1
                AND vector_similarity <= 1
            )
            """,
            name="valid_vector_similarity",
        ),
        CheckConstraint(
            """
            lexical_score IS NULL
            OR lexical_score >= 0
            """,
            name="non_negative_lexical_score",
        ),
        CheckConstraint(
            """
            fusion_score IS NULL
            OR fusion_score >= 0
            """,
            name="non_negative_fusion_score",
        ),
        CheckConstraint(
            """
            reranker_score IS NULL
            OR reranker_score >= 0
            """,
            name="non_negative_reranker_score",
        ),
        CheckConstraint(
            """
            final_score IS NULL
            OR final_score >= 0
            """,
            name="non_negative_final_score",
        ),
        CheckConstraint(
            """
            vector_rank IS NOT NULL
            OR lexical_rank IS NOT NULL
            """,
            name="has_retrieval_origin",
        ),
        CheckConstraint(
            """
            selected_for_context = false
            OR final_rank IS NOT NULL
            """,
            name="selected_candidate_has_final_rank",
        ),

        Index(
            "idx_retrieval_candidates_run_final_rank",
            "retrieval_run_id",
            "final_rank",
        ),
        Index(
            "idx_retrieval_candidates_run_selected",
            "retrieval_run_id",
            "selected_for_context",
        ),
        Index(
            "idx_retrieval_candidates_chunk",
            "chunk_id",
        ),
        Index(
            "idx_retrieval_candidates_document",
            "document_id",
        ),
        Index(
            "idx_retrieval_candidates_version",
            "version_id",
        ),
        Index(
            "idx_retrieval_candidates_final_score",
            text("final_score DESC"),
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

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    content_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    vector_rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    lexical_rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    fusion_rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    reranker_rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    final_rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    vector_similarity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    lexical_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    fusion_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    reranker_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    final_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    selected_for_context: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )