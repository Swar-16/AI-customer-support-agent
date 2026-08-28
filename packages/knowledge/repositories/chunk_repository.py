from __future__ import annotations
from typing import Protocol
from uuid import UUID

from packages.knowledge.domain.chunk import KnowledgeChunk


class KnowledgeChunkRepository(Protocol):
    """
    Persistence contract for knowledge chunks.

    Chunks are derived retrieval units belonging to an exact knowledge
    document version.
    """

    def add(self, chunk: KnowledgeChunk) -> None:
        """Persist a single newly created chunk."""
        ...

    def add_many(self, chunks: list[KnowledgeChunk]) -> None:
        """
        Persist multiple chunks as part of the surrounding transaction.

        Implementations should optimize this operation appropriately rather
        than requiring callers to issue individual persistence operations.
        """
        ...

    def get_by_id(self, chunk_id: UUID) -> KnowledgeChunk | None:
        """Return a chunk by identity, or None if it does not exist."""
        ...

    def list_for_version(self, version_id: UUID) -> list[KnowledgeChunk]:
        """
        Return all chunks belonging to a version,
        ordered by chunk index.
        """
        ...

    def delete_for_version(self, version_id: UUID) -> None:
        """
        Remove derived chunks belonging to a version.

        Primarily used when a version is reprocessed before publication.
        """
        ...