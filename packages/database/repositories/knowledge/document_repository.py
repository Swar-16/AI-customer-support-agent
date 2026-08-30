from __future__ import annotations
from uuid import UUID
from sqlalchemy import exists, select, func
from sqlalchemy.orm import Session

from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.repositories.knowledge.mappers import document_to_domain, document_to_model, update_document_model
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.repositories.document_repository import KnowledgeDocumentListFilter


class SQLAlchemyKnowledgeDocumentRepository:
    """
    SQLAlchemy/PostgreSQL implementation of the knowledge-document
    persistence contract.

    Transaction ownership deliberately remains outside this repository.
    The surrounding Unit of Work is responsible for commit/rollback.
    """
    def __init__(self, session: Session) -> None:
        self._session = session
        
    @staticmethod
    def _apply_filter(statement, filter_: KnowledgeDocumentListFilter):
        if filter_.status is not None:
            statement = statement.where(KnowledgeDocumentModel.status == filter_.status.value)

        if filter_.content_type is not None:
            statement = statement.where(KnowledgeDocumentModel.content_type == filter_.content_type.value)

        if filter_.visibility is not None:
            statement = statement.where(KnowledgeDocumentModel.visibility == filter_.visibility.value)

        return statement

    def add(self, document: KnowledgeDocument) -> None:
        """
        Stage a new document for persistence.

        No commit or flush is performed here. Transaction boundaries belong
        to the Unit of Work / application service.
        """
        model = document_to_model(document)
        self._session.add(model)

    def get_by_id(self, document_id: UUID) -> KnowledgeDocument | None:
        model = self._session.get(KnowledgeDocumentModel, document_id)
        if model is None:
            return None

        return document_to_domain(model)
    
    def get_by_id_for_update(self, document_id: UUID) -> KnowledgeDocument | None:
        statement = (select(KnowledgeDocumentModel)
                     .where(KnowledgeDocumentModel.id == document_id)
                     .with_for_update()
        )

        model = self._session.scalar(statement)
        if model is None:
            return None

        return document_to_domain(model)

    def save(self, document: KnowledgeDocument) -> None:
        """
        Persist the mutable state of an existing document.

        Raises LookupError if the row no longer exists. This avoids silently
        turning an expected UPDATE into an INSERT.
        """
        model = self._session.get(KnowledgeDocumentModel, document.id)

        if model is None:
            raise LookupError(f"Knowledge document {document.id} does not exist.")

        update_document_model(model=model, document=document)

    def exists(self, document_id: UUID) -> bool:
        statement = select(
                    exists()
                    .where(KnowledgeDocumentModel.id == document_id)
        )

        return bool(self._session.scalar(statement))
    
    def list(self, *, filter_: KnowledgeDocumentListFilter, limit: int, offset: int) -> list[KnowledgeDocument]:
        statement = select(KnowledgeDocumentModel)
        statement = self._apply_filter(statement, filter_,)
        statement = (statement
                     .order_by(
                         KnowledgeDocumentModel.created_at.desc(),
                         KnowledgeDocumentModel.id.asc()
                         )
                     .limit(limit)
                     .offset(offset)
        )
        models = self._session.scalars(statement).all()

        return [document_to_domain(model) for model in models]
    
    def count(self, *, filter_: KnowledgeDocumentListFilter) -> int:
        statement = select(func.count(KnowledgeDocumentModel.id))
        statement = self._apply_filter(statement, filter_)

        return int(self._session.scalar(statement) or 0)