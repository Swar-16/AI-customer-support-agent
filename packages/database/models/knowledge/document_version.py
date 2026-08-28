from __future__ import annotations
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.database.base import Base
from packages.knowledge.domain.enums import KnowledgeIngestionStatus, KnowledgeSourceType, KnowledgeVersionStatus
from packages.knowledge.domain.version import MAX_FAILURE_CODE_LENGTH, MAX_SOURCE_NAME_LENGTH
from packages.database.models._helpers import enum_check_sql

if TYPE_CHECKING:
    from packages.database.models.knowledge.chunk import KnowledgeChunkModel
    from packages.database.models.knowledge.document import KnowledgeDocumentModel


class KnowledgeDocumentVersionModel(Base):
    """
    Persisted immutable revision of a logical knowledge document.

    Source content belongs to a version and is never overwritten when a
    document changes. A new revision must be created instead.
    """
    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_knowledge_document_versions_document_version",
        ),

        CheckConstraint(
            "version_number > 0",
            name="ck_knowledge_document_versions_positive_version",
        ),
        CheckConstraint(
            "length(btrim(source_content)) > 0",
            name="ck_knowledge_document_versions_content_not_blank",
        ),
        CheckConstraint(
            "length(btrim(content_hash)) > 0",
            name="ck_knowledge_document_versions_hash_not_blank",
        ),
        CheckConstraint(
            enum_check_sql("source_type", KnowledgeSourceType),
            name="ck_knowledge_document_versions_source_type",
        ),
        CheckConstraint(
            enum_check_sql("status", KnowledgeVersionStatus),
            name="ck_knowledge_document_versions_status",
        ),
        CheckConstraint(
            enum_check_sql("ingestion_status", KnowledgeIngestionStatus),
            name="ck_knowledge_document_versions_ingestion_status",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_knowledge_document_versions_timestamp_order",
        ),

        # At most one PUBLISHED version may exist for a document.
        Index(
            "uq_knowledge_document_versions_published",
            "document_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
        Index(
            "ix_knowledge_document_versions_document_id",
            "document_id",
        ),
        Index(
            "ix_knowledge_document_versions_status",
            "status",
        ),
        Index(
            "ix_knowledge_document_versions_ingestion_status",
            "ingestion_status",
        ),

        {"schema": "knowledge"},
    )

    # Identity
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )

    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "knowledge.knowledge_documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Source
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    source_content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    content_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    source_name: Mapped[str | None] = mapped_column(
        String(MAX_SOURCE_NAME_LENGTH),
        nullable=True,
    )

    source_uri: Mapped[str | None] = mapped_column(
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

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default=text("'draft'"),
    )

    ingestion_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default=text("'pending'"),
    )

    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    processing_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    failure_code: Mapped[str | None] = mapped_column(
        String(MAX_FAILURE_CODE_LENGTH),
    )

    failure_message: Mapped[str | None] = mapped_column(
        Text,
    )

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
    document: Mapped["KnowledgeDocumentModel"] = relationship(
        "KnowledgeDocumentModel",
        back_populates="versions",
    )

    chunks: Mapped[list["KnowledgeChunkModel"]] = relationship(
        "KnowledgeChunkModel",
        back_populates="version",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="KnowledgeChunkModel.chunk_index",
    )