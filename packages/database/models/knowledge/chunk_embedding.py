from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from typing import TYPE_CHECKING

from packages.database.base import Base
if TYPE_CHECKING:
    from packages.database.models.knowledge.chunk import KnowledgeChunkModel


class KnowledgeChunkEmbeddingModel(Base):
    """
    Immutable embedding artifact generated from a canonical knowledge chunk.

    Embeddings are intentionally stored separately from knowledge_chunks because they depend on:
    - embedding provider,
    - embedding model / revision,
    - dimensionality,
    - embedding-input construction strategy.

    The same canonical chunk may therefore have multiple valid embedding artifacts over its lifetime.

    This table stores provenance required to reproduce and validate the vector later.
    """
    __tablename__ = "knowledge_chunk_embeddings"
    __table_args__ = (
        CheckConstraint(
            "dimensions > 0",
            name="dimensions_positive",
        ),
        
        UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            "model_revision",
            "dimensions",
            "input_strategy_id",
            "input_strategy_version",
            "input_config_fingerprint",
            "input_fingerprint",
            name="uq_knowledge_chunk_embeddings_artifact",
            postgresql_nulls_not_distinct=True,
        ),
        
        Index(
            "ix_knowledge_chunk_embeddings_chunk_id",
            "chunk_id",
        ),
        Index(
            "ix_knowledge_chunk_embeddings_provider_model_dimensions",
            "provider",
            "model",
            "dimensions",
        ),
        
        {
            "schema": "knowledge",
        },
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )

    chunk_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "knowledge.knowledge_chunks.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    # Embedding-provider provenance
    provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    model: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    model_revision: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    dimensions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    embedding: Mapped[list[float]] = mapped_column(
        Vector(),
        nullable=False,
    )

    # Embedding-input provenance
    input_strategy_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    input_strategy_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    input_config_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    input_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    
    # Relationship
    chunk: Mapped["KnowledgeChunkModel"] = relationship(
        "KnowledgeChunkModel",
        back_populates="embeddings",
    )