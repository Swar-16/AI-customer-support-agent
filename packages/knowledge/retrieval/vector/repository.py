from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID
from math import isfinite

from packages.knowledge.embeddings.models import EmbeddingInputDescriptor, EmbeddingProviderDescriptor, EmbeddingVector
from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalFilters


@dataclass(frozen=True, slots=True)
class VectorSearchRequest:
    """
    Persistence-facing request for semantic retrieval.

    This object deliberately contains only the information required by the repository to execute a vector search.

    The repository must not generate embeddings itself. Query embedding generation belongs to the vector retrieval service.
    """

    query_vector: EmbeddingVector
    provider: EmbeddingProviderDescriptor
    input_descriptor: EmbeddingInputDescriptor
    filters: RetrievalFilters
    limit: int

    def __post_init__(self) -> None:
        if not isinstance(self.query_vector, EmbeddingVector):
            raise TypeError("query_vector must be an EmbeddingVector instance.")

        if not isinstance(self.provider, EmbeddingProviderDescriptor):
            raise TypeError("provider must be an EmbeddingProviderDescriptor instance.")

        if not isinstance(self.input_descriptor, EmbeddingInputDescriptor):
            raise TypeError("input_descriptor must be an EmbeddingInputDescriptor instance.")

        if not isinstance(self.filters, RetrievalFilters):
            raise TypeError("filters must be a RetrievalFilters instance.")

        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer.")

        if self.limit <= 0:
            raise ValueError("limit must be greater than zero.")

        if self.query_vector.dimensions != self.provider.dimensions:
            raise ValueError(
                "Query vector dimensions do not match the configured embedding provider dimensions: "
                f"expected {self.provider.dimensions}, got {self.query_vector.dimensions}."
            )


@dataclass(frozen=True, slots=True)
class VectorSearchMatch:
    """
    Raw semantic-search result returned by persistence.

    Distance is kept separate from RetrievalCandidate because the repository returns raw vector-search evidence.
    The service converts this into the canonical retrieval-domain representation.
    """
    candidate: RetrievalCandidate
    distance: float

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, RetrievalCandidate):
            raise TypeError("candidate must be a RetrievalCandidate instance.")

        if isinstance(self.distance, bool) or not isinstance(self.distance, (int, float)):
            raise TypeError("distance must be a number.")

        distance = float(self.distance)
        if distance < 0:
            raise ValueError("distance cannot be negative.")

        if distance != distance:
            raise ValueError("distance must be finite.")

        if not isfinite(distance):
            raise ValueError("distance must be finite.")

        object.__setattr__(self, "distance", distance)


class VectorRetrievalRepository(Protocol):
    """
    Persistence contract for semantic knowledge retrieval.

    Implementations are responsible for:
      - searching persisted chunk embeddings;
      - matching the exact embedding provider/model/profile;
      - enforcing knowledge lifecycle visibility invariants;
      - applying supported retrieval filters;
      - ranking by vector distance;
      - returning at most request.limit results.

    Implementations must not:
      - call embedding providers;
      - perform query rewriting;
      - perform rank fusion;
      - rerank results;
      - build LLM grounding context;
      - commit transactions.
    """
    def search(self, request: VectorSearchRequest) -> tuple[VectorSearchMatch, ...]:
        ...