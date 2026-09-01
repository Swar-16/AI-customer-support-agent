from __future__ import annotations
from typing import Protocol
from uuid import UUID

from packages.knowledge.domain.version import KnowledgeDocumentVersion


class KnowledgeVersionRepository(Protocol):
    """
    Persistence contract for knowledge document versions.

    The contract exposes operations required by version lifecycle use cases
    without leaking SQLAlchemy or PostgreSQL details into the knowledge layer.
    """

    def add(self, version: KnowledgeDocumentVersion) -> None:
        """Persist a newly created document version."""
        ...

    def get_by_id(self, version_id: UUID) -> KnowledgeDocumentVersion | None:
        """Return a version by identity, or None if it does not exist."""
        ...
        
    def get_by_id_for_update(self, version_id: UUID) -> KnowledgeDocumentVersion | None:
        """
        Return a version while acquiring a row-level write lock
        for the lifetime of the surrounding transaction.
        """
        ...

    def save(self, version: KnowledgeDocumentVersion) -> None:
        """Persist the current state of an existing version."""
        ...

    def get_published_for_document(self, document_id: UUID) -> KnowledgeDocumentVersion | None:
        """Return the currently published version of a document."""
        ...

    def list_for_document(self, document_id: UUID) -> list[KnowledgeDocumentVersion]:
        """
        Return all versions belonging to a document,
        ordered by version number.
        """
        ...

    def next_version_number(self, document_id: UUID) -> int:
        """
        Determine the next version number for a document.

        The concrete implementation must provide concurrency-safe allocation
        when used within the surrounding transaction.
        """
        ...
    
    def list_embedding_candidates(self) -> list[KnowledgeDocumentVersion]:
        """
        Return knowledge versions eligible for embedding/backfill.

        Only successfully ingested published versions are returned.
        """
        ...