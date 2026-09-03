from __future__ import annotations
from typing import Final

from packages.knowledge.retrieval.reranking.base import Reranker
from packages.knowledge.retrieval.reranking.models import RerankedCandidate, RerankerDescriptor, RerankingRequest, RerankingResponse


class PassthroughReranker(Reranker):
    """
    Deterministic no-op reranker.

    This implementation preserves the ordering produced by the previous retrieval/fusion stage and applies only the requested result limit.

    It is useful when reranking is disabled while still allowing the application pipeline to 
    depend on the Reranker abstraction rather than branching around the reranking stage.

    No external service, model, network request, or mutable state is used.
    """
    RERANKER_ID: Final[str] = "passthrough"
    PROVIDER_NAME: Final[str] = "internal"
    _DESCRIPTOR: Final[RerankerDescriptor] = RerankerDescriptor(reranker_id=RERANKER_ID, provider=PROVIDER_NAME, model=None, revision=None)

    @property
    def descriptor(self) -> RerankerDescriptor:
        return self._DESCRIPTOR

    def rerank(self, request: RerankingRequest) -> RerankingResponse:
        if not isinstance(request, RerankingRequest):
            raise TypeError("request must be a RerankingRequest instance.")

        results = tuple(RerankedCandidate(chunk_id=candidate.chunk_id, score=None) for candidate in request.candidates[:request.limit])

        return RerankingResponse(results=results, descriptor=self.descriptor)