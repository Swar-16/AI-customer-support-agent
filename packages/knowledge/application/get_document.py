from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID

from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory


# Application errors
class GetKnowledgeDocumentError(RuntimeError):
    """Base application error for knowledge-document retrieval."""

class KnowledgeDocumentDoesNotExistError(GetKnowledgeDocumentError):
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(f"Knowledge document does not exist: {document_id}")


# Contracts
@dataclass(frozen=True, slots=True)
class GetKnowledgeDocumentQuery:
    document_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, UUID):
            raise TypeError("document_id must be a UUID.")


@dataclass(frozen=True, slots=True)
class GetKnowledgeDocumentResult:
    document: KnowledgeDocument
    versions: tuple[KnowledgeDocumentVersion, ...]
    published_version_id: UUID | None


# Application service
class GetKnowledgeDocument:
    """
    Return one logical knowledge document together with its version history.

    This is an administrative read use case and therefore includes archived and deleted documents when addressed directly by ID.
    """

    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        self._uow_factory = uow_factory

    def execute(self, query: GetKnowledgeDocumentQuery) -> GetKnowledgeDocumentResult:
        if not isinstance(query, GetKnowledgeDocumentQuery):
            raise TypeError("query must be a GetKnowledgeDocumentQuery.")

        with self._uow_factory() as uow:
            document = uow.documents.get_by_id(query.document_id)
            if document is None:
                raise KnowledgeDocumentDoesNotExistError(query.document_id)

            versions = tuple(uow.versions.list_for_document(document.id))
            published = uow.versions.get_published_for_document(document.id)

        return GetKnowledgeDocumentResult(
            document=document,
            versions=versions,
            published_version_id=(published.id if published is not None else None),
        )