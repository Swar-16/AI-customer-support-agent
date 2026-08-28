from __future__ import annotations
from typing import Protocol
from uuid import UUID

from packages.knowledge.domain.document import KnowledgeDocument


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