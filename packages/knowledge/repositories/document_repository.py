from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import KnowledgeContentType, KnowledgeDocumentStatus, KnowledgeVisibility


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentListFilter:
    status: KnowledgeDocumentStatus | None = None
    content_type: KnowledgeContentType | None = None
    visibility: KnowledgeVisibility | None = None

class KnowledgeDocumentRepository(Protocol):
    """
    Persistence contract required by the knowledge application layer.

    Implementations may use PostgreSQL, an in-memory store, or another
    persistence mechanism. The domain/application layer does not care.
    """
    def add(self, document: KnowledgeDocument) -> None:
        """Persist a newly created knowledge document."""
        ...

    def get_by_id(self, document_id: UUID) -> KnowledgeDocument | None:
        """Return a document by identity, or None when it does not exist."""
        ...

    def get_by_id_for_update(self, document_id: UUID) -> KnowledgeDocument | None:
        """
        Return the document while acquiring a row-level write lock
        for the lifetime of the surrounding transaction.

        Used to serialize aggregate-level lifecycle operations such as
        publishing document versions.
        """
        ...

    def save(self, document: KnowledgeDocument) -> None:
        """
        Persist the current state of an existing document.

        Used after domain operations such as rename, archive, restore,
        or delete.
        """
        ...

    def exists(self, document_id: UUID) -> bool:
        """Return whether the document exists in persistence."""
        ...
        
    def get_by_id_for_update(self, document_id: UUID) -> KnowledgeDocument | None:
        ...

    def list(self, *, filter_: KnowledgeDocumentListFilter, limit: int, offset: int) -> list[KnowledgeDocument]:
        ...

    def count(self, *, filter_: KnowledgeDocumentListFilter) -> int:
        ...