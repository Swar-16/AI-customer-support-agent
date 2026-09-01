from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.database.base import Base

if TYPE_CHECKING:
    from packages.database.models.knowledge.document_version import KnowledgeDocumentVersionModel
    from packages.database.models.knowledge.chunk_embedding import KnowledgeChunkEmbeddingModel


class KnowledgeChunkModel(Base):
    """
    Persisted retrieval unit derived from a knowledge document version.

    Chunks are version-specific derived artifacts. They preserve enough
    provenance to trace retrieved content back to the exact document version
    from which it was generated.

    Embeddings are intentionally excluded because they depend on a particular
    embedding model and may need to be regenerated independently.
    """
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        # A version cannot contain two chunks at the same position.
        UniqueConstraint(
            "version_id",
            "chunk_index",
            name="uq_knowledge_chunks_version_index",
        ),

        CheckConstraint(
            "chunk_index >= 0",
            name="ck_knowledge_chunks_nonnegative_index",
        ),
        CheckConstraint(
            "length(btrim(content)) > 0",
            name="ck_knowledge_chunks_content_not_blank",
        ),
        CheckConstraint(
            """
            (
                start_offset IS NULL
                AND end_offset IS NULL
            )
            OR
            (
                start_offset IS NOT NULL
                AND end_offset IS NOT NULL
                AND start_offset >= 0
                AND end_offset > start_offset
            )
            """,
            name="ck_knowledge_chunks_valid_offsets",
        ),
        CheckConstraint(
            "token_count IS NULL OR token_count > 0",
            name="ck_knowledge_chunks_positive_token_count",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_knowledge_chunks_timestamp_order",
        ),

        Index(
            "ix_knowledge_chunks_version_id",
            "version_id",
        ),

        {"schema": "knowledge"},
    )

    # Identity
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )

    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "knowledge.knowledge_document_versions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Retrieval content
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    section_title: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Half-open source range:     [start_offset, end_offset)
    # This maps naturally to:     source[start_offset:end_offset]
    #
    # Offsets remain nullable because not every parser can provide reliable character positions.
    start_offset: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    end_offset: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    token_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Extensible derived metadata
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    version: Mapped["KnowledgeDocumentVersionModel"] = relationship(
        "KnowledgeDocumentVersionModel",
        back_populates="chunks",
    )
    
    embeddings: Mapped[list["KnowledgeChunkEmbeddingModel"]] = relationship(
        "KnowledgeChunkEmbeddingModel",
        back_populates="chunk",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )