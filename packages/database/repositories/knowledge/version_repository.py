from __future__ import annotations
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.document_version import KnowledgeDocumentVersionModel
from packages.database.repositories.knowledge.mappers import update_version_model, version_to_domain, version_to_model
from packages.knowledge.domain.version import KnowledgeDocumentVersion


class SQLAlchemyKnowledgeVersionRepository:
    """
    SQLAlchemy/PostgreSQL implementation of knowledge-version persistence.

    Transaction ownership remains with the surrounding Unit of Work.
    """
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, version: KnowledgeDocumentVersion) -> None:
        """
        Stage a new knowledge-document version for persistence.

        Does not flush or commit.
        """
        self._session.add(version_to_model(version))

    def get_by_id(self, version_id: UUID) -> KnowledgeDocumentVersion | None:
        model = self._session.get(KnowledgeDocumentVersionModel, version_id)
        if model is None:
            return None

        return version_to_domain(model)
    
    def get_by_id_for_update(self, version_id: UUID) -> KnowledgeDocumentVersion | None:
        """
        Load a knowledge-document version while acquiring a PostgreSQL
        row-level write lock for the lifetime of the current transaction.

        Intended for lifecycle transitions such as:
            DRAFT -> PROCESSING
            PROCESSING -> READY
            PROCESSING -> FAILED
            READY -> PUBLISHED

        The lock prevents two concurrent workers from successfully claiming
        or completing the same version at the same time.

        Transaction ownership remains with the surrounding Unit of Work.
        """
        statement = (select(KnowledgeDocumentVersionModel)
                     .where(KnowledgeDocumentVersionModel.id == version_id)
                     .with_for_update()
        )

        model = self._session.scalar(statement)
        if model is None:
            return None

        return version_to_domain(model)

    def save(self, version: KnowledgeDocumentVersion) -> None:
        """
        Persist mutable lifecycle state of an existing version.

        Immutable identity/source fields are protected by the mapper.
        """
        model = self._session.get(KnowledgeDocumentVersionModel, version.id)
        if model is None:
            raise LookupError(f"Knowledge document version {version.id} does not exist.")

        update_version_model(model=model,version=version)

    def get_published_for_document(self, document_id: UUID) -> KnowledgeDocumentVersion | None:
        statement = (
            select(KnowledgeDocumentVersionModel)
            .where(
                KnowledgeDocumentVersionModel.document_id == document_id,
                KnowledgeDocumentVersionModel.status == "published",
            )
        )

        model = self._session.scalar(statement)
        if model is None:
            return None

        return version_to_domain(model)

    def list_for_document(self, document_id: UUID) -> list[KnowledgeDocumentVersion]:
        statement = (
            select(KnowledgeDocumentVersionModel)
            .where(KnowledgeDocumentVersionModel.document_id == document_id)
            .order_by(KnowledgeDocumentVersionModel.version_number.asc())
        )
        models = self._session.scalars(statement).all()

        return [version_to_domain(model) for model in models]

    def next_version_number(self, document_id: UUID) -> int:
        """
        Allocate the next version number while holding a row-level lock on
        the parent document for the lifetime of the current transaction.

        All version creation for the same document must use this method
        inside the transaction that inserts the resulting version.
        """
        # Serialize version allocation for this particular document.
        document_statement = (
            select(KnowledgeDocumentModel.id)
            .where(KnowledgeDocumentModel.id == document_id)
            .with_for_update() ## locks the parent document row, not existing version rows.
        )

        locked_document_id = self._session.scalar(document_statement)
        if locked_document_id is None:
            raise LookupError(f"Knowledge document {document_id} does not exist.")

        max_version_statement = select(
            func.max(KnowledgeDocumentVersionModel.version_number)
        ).where(KnowledgeDocumentVersionModel.document_id == document_id)

        current_max = self._session.scalar(max_version_statement)

        return 1 if current_max is None else current_max + 1
    
    def list_embedding_candidates(self) -> list[KnowledgeDocumentVersion]:
        statement = (select(KnowledgeDocumentVersionModel)
                     .where(KnowledgeDocumentVersionModel.status == "published",
                            KnowledgeDocumentVersionModel.ingestion_status == "completed")
                     .order_by(KnowledgeDocumentVersionModel.created_at.asc(),
                               KnowledgeDocumentVersionModel.id.asc())
        )

        models = self._session.scalars(statement).all()

        return [version_to_domain(model) for model in models]