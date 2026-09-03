from __future__ import annotations
from abc import ABC, abstractmethod

from packages.knowledge.retrieval.reranking.models import RerankerDescriptor, RerankingRequest, RerankingResponse


class Reranker(ABC):
    """
    Abstract contract for retrieval reranking implementations.

    A reranker receives an already-retrieved, already-fused set of candidates and produces a relevance-based 
    ordering for those same candidates.

    Implementations may be backed by:
      - an external reranking API;
      - a local cross-encoder;
      - another learned ranking model;
      - a deterministic passthrough implementation.

    Architectural guarantees
    ------------------------
    A reranker is not the source of truth for knowledge content.

    It may determine:
      - candidate relevance;
      - candidate ordering;
      - reranking scores.

    It must not determine or modify:
      - chunk content;
      - document/version identity;
      - metadata;
      - retrieval provenance;
      - vector/lexical/fusion scores.

    The caller remains responsible for reconciling the reranking response with the trusted RetrievalCandidate objects from the retrieval pipeline.
    """

    @property
    @abstractmethod
    def descriptor(self) -> RerankerDescriptor:
        """
        Return the immutable identity of this reranker.

        The descriptor is used for configuration, observability, reproducibility, and provider/model attribution.
        """
        raise NotImplementedError

    @abstractmethod
    def rerank(self, request: RerankingRequest) -> RerankingResponse:
        """
        Rerank the candidates contained in ``request``.

        Contract
        --------
        Implementations must:

        1. Treat ``request.query`` and ``request.candidates`` as immutable.
        2. Return only chunk IDs originating from ``request.candidates``.
        3. Return each chunk ID at most once.
        4. Return results ordered from highest relevance to lowest relevance.
        5. Return at most ``request.limit`` results.
        6. Return a response whose descriptor identifies the implementation that actually produced the result.
        7. Return finite relevance scores.

        Empty input
        -----------
        A request containing no candidates is valid. Implementations should return an empty RerankingResponse rather than treating it as an error.

        Failure semantics
        -----------------
        Provider implementations should translate expected backend/provider failures into the retrieval reranking error hierarchy.

        Unexpected programming errors should not be broadly swallowed or converted into generic provider failures.

        Validation that requires comparing the request and response (membership, cardinality, descriptor consistency, etc.)
        belongs at the reranking service boundary.
        """
        raise NotImplementedError

    def health_check(self) -> bool:
        """
        Return whether the reranker appears operational.

        Stateless/local implementations may retain this default. External provider implementations 
        may override it with an appropriate lightweight health check.

        This method must not be interpreted as a guarantee that a future reranking request will succeed.
        """
        return True