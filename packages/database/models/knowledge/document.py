from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID
from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.database.base import Base
from packages.knowledge.domain.document import MAX_DOCUMENT_TITLE_LENGTH
from packages.knowledge.domain.enums import KnowledgeContentType, KnowledgeDocumentStatus, KnowledgeVisibility
from packages.database.models._helpers import enum_check_sql

if TYPE_CHECKING:
    from packages.database.models.knowledge.document_version import KnowledgeDocumentVersionModel
    

# ORM model
class KnowledgeDocumentModel(Base):
    """
    Persistent representation of a logical knowledge document.

    A knowledge document represents the stable identity of a piece of
    knowledge, while individual revisions are stored separately as
    KnowledgeDocumentVersionModel rows.

    Example:

        Refund Policy
            ├── version 1
            ├── version 2
            └── version 3

    The model intentionally contains no publication pointer such as
    ``current_version_id``. Publication state belongs to document versions
    and is coordinated transactionally by the application layer.

    Business behavior belongs to the knowledge domain layer rather than this
    persistence model.
    """
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(title)) > 0",
            name="ck_knowledge_documents_title_not_blank",
        ),
        CheckConstraint(
            enum_check_sql("content_type", KnowledgeContentType),
            name="ck_knowledge_documents_content_type",
        ),
        CheckConstraint(
            enum_check_sql("visibility", KnowledgeVisibility),
            name="ck_knowledge_documents_visibility",
        ),
        CheckConstraint(
            enum_check_sql("status", KnowledgeDocumentStatus),
            name="ck_knowledge_documents_status",
        ),
        CheckConstraint(
            """
            (
                status = 'active'
                AND archived_at IS NULL
                AND deleted_at IS NULL
            )
            OR
            (
                status = 'archived'
                AND archived_at IS NOT NULL
                AND deleted_at IS NULL
            )
            OR
            (
                status = 'deleted'
                AND deleted_at IS NOT NULL
            )
            """,
            name="ck_knowledge_documents_lifecycle",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_knowledge_documents_timestamp_order",
        ),
        CheckConstraint(
            "archived_at IS NULL OR archived_at >= created_at",
            name="ck_knowledge_documents_archived_at_order",
        ),
        CheckConstraint(
            "deleted_at IS NULL OR deleted_at >= created_at",
            name="ck_knowledge_documents_deleted_at_order",
        ),
        
        Index(
            "ix_knowledge_documents_status",
            "status",
        ),
        Index(
            "ix_knowledge_documents_content_type",
            "content_type",
        ),
        Index(
            "ix_knowledge_documents_visibility",
            "visibility",
        ),
        Index(
            "ix_knowledge_documents_created_at",
            "created_at",
        ),
        
        {
            "schema": "knowledge",
        },
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )

    title: Mapped[str] = mapped_column(
        String(MAX_DOCUMENT_TITLE_LENGTH),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    content_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    visibility: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default=text(f"'{KnowledgeDocumentStatus.ACTIVE.value}'"),
    )

    # ``metadata`` is reserved by SQLAlchemy's Declarative API.
    #
    # The Python attribute therefore uses ``metadata_`` while PostgreSQL
    # still sees the natural column name ``metadata``.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
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

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    versions: Mapped[list[KnowledgeDocumentVersionModel]] = relationship(
        "KnowledgeDocumentVersionModel",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="KnowledgeDocumentVersionModel.version_number",
    )