from __future__ import annotations
from typing import Protocol
from uuid import UUID

from packages.knowledge.domain.embedding import KnowledgeChunkEmbedding
from packages.knowledge.embeddings.models import EmbeddingInputDescriptor, EmbeddingProviderDescriptor


class KnowledgeEmbeddingRepository(Protocol):
    """
    Persistence contract for model-dependent knowledge embedding artifacts.

    Implementations participate in the surrounding Unit of Work and must not commit transactions independently.
    """
    def add(self, embedding: KnowledgeChunkEmbedding) -> None:
        """Persist one newly generated embedding artifact."""
        ...

    def add_many(self, embeddings: list[KnowledgeChunkEmbedding]) -> None:
        """
        Persist multiple embedding artifacts as part of the surrounding transaction.
        """
        ...

    def get_by_id(self, embedding_id: UUID) -> KnowledgeChunkEmbedding | None:
        """Return an embedding artifact by identity, or None."""
        ...

    def list_for_chunk(self, chunk_id: UUID) -> list[KnowledgeChunkEmbedding]:
        """Return all embedding artifacts associated with a chunk."""
        ...

    def list_for_chunks(self, chunk_ids: list[UUID], *, provider: EmbeddingProviderDescriptor, input_descriptor: EmbeddingInputDescriptor) -> list[KnowledgeChunkEmbedding]:
        """
        Return existing artifacts for the supplied chunks under one exact embedding profile.

        Used by embedding workflows to avoid regenerating artifacts that already exist.
        """
        ...