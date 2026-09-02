from __future__ import annotations
from dataclasses import replace
from math import isfinite

from packages.knowledge.embeddings.models import EmbeddingInputDescriptor, EmbeddingVector
from packages.knowledge.embeddings.provider.base import EmbeddingProvider
from packages.knowledge.retrieval.errors import QueryEmbeddingDimensionError, QueryEmbeddingError, VectorSearchError, VectorRetrievalRepositoryError
from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalMethod, RetrievalQuery, RetrievalScores
from packages.knowledge.retrieval.vector.repository import VectorRetrievalRepository, VectorSearchRequest
from packages.knowledge.embeddings.errors import KnowledgeEmbeddingError

class VectorRetrievalService:
    """
    Application/domain service for semantic knowledge retrieval.

    Responsibilities:
      1. Convert the user's query text into an embedding.
      2. Validate that the query embedding matches the configured provider.
      3. Ask the vector repository for nearest persisted chunks.
      4. Convert raw vector-distance evidence into canonical retrieval candidates and scores.
    """
    def __init__(self, *, provider: EmbeddingProvider, repository: VectorRetrievalRepository, input_descriptor: EmbeddingInputDescriptor) -> None:
        if not isinstance(provider, EmbeddingProvider):
            raise TypeError("provider must satisfy the EmbeddingProvider contract.")

        if repository is None:
            raise TypeError("repository must not be None.")

        if not callable(getattr(repository, "search", None)):
            raise TypeError("repository must provide a callable search() method.")

        if not isinstance(input_descriptor, EmbeddingInputDescriptor):
            raise TypeError("input_descriptor must be an EmbeddingInputDescriptor instance.")

        self._provider = provider
        self._repository = repository
        self._input_descriptor = input_descriptor

    @property
    def provider(self) -> EmbeddingProvider:
        return self._provider

    @property
    def input_descriptor(self) -> EmbeddingInputDescriptor:
        return self._input_descriptor

    def search(self, *, query: RetrievalQuery, limit: int) -> tuple[RetrievalCandidate, ...]:
        """
        Perform semantic retrieval for one normalized retrieval query.

        The caller controls candidate count through `limit`; a higher-level retrieval profile will eventually supply that value.
        """
        self._validate_request(query=query, limit=limit)
        query_vector = self._embed_query(query.text)
        self._validate_query_vector(query_vector)

        request = VectorSearchRequest(
            query_vector=query_vector,
            provider=self._provider.descriptor,
            input_descriptor=self._input_descriptor,
            filters=query.filters,
            limit=limit,
        )

        try:
            matches = self._repository.search(request)
            
        except VectorRetrievalRepositoryError as exc:
            raise VectorSearchError("Vector repository search failed.") from exc

        return tuple(self._to_candidate(match) for match in matches)

    @staticmethod
    def _validate_request(*, query: RetrievalQuery, limit: int) -> None:
        if not isinstance(query, RetrievalQuery):
            raise TypeError("query must be a RetrievalQuery instance.")

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer.")

        if limit <= 0:
            raise ValueError("limit must be greater than zero.")

    def _embed_query(self, text: str) -> EmbeddingVector:
        """
        Generate the embedding representing retrieval intent.

        Query embedding is intentionally generated here rather than inside the repository so the persistence
        layer remains embedding-provider agnostic.
        """
        try:
            vector = self._provider.embed_query(text)

        except KnowledgeEmbeddingError as exc:
            raise QueryEmbeddingError("Failed to generate query embedding.") from exc

        if not isinstance(vector, EmbeddingVector):
            raise QueryEmbeddingError("Embedding provider returned an invalid query embedding type.")

        return vector

    def _validate_query_vector(self, vector: EmbeddingVector) -> None:
        expected_dimensions = self._provider.descriptor.dimensions
        actual_dimensions = vector.dimensions

        if actual_dimensions != expected_dimensions:
            raise QueryEmbeddingDimensionError(expected_dimensions=expected_dimensions, actual_dimensions=actual_dimensions)

    @staticmethod
    def _to_candidate(match) -> RetrievalCandidate:
        """
        Convert raw repository evidence into the canonical retrieval model.

        pgvector cosine distance semantics:

            smaller distance = better match

        For cosine distance:

            cosine_similarity = 1 - cosine_distance

        We retain BOTH values. Later fusion/reranking must never have to reverse-engineer one representation from the other.
        """
        distance = float(match.distance)
        if not isfinite(distance):
            raise VectorSearchError("Vector repository returned a non-finite distance.")

        if distance < 0:
            raise VectorSearchError("Vector repository returned a negative distance.")

        similarity = 1.0 - distance
        candidate = match.candidate
        if not isinstance(candidate, RetrievalCandidate):
            raise VectorSearchError("Vector repository returned an invalid candidate.")

        scores = replace(candidate.scores, vector_distance=distance, vector_similarity=similarity)

        methods = frozenset({*candidate.methods, RetrievalMethod.VECTOR,})

        return replace(candidate, methods=methods, scores=scores)