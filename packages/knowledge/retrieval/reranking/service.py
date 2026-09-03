from __future__ import annotations
from dataclasses import replace
from uuid import UUID

from packages.knowledge.retrieval.errors import RerankerCardinalityError, RerankerProviderError, RerankerResponseError
from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalQuery
from packages.knowledge.retrieval.reranking.base import Reranker
from packages.knowledge.retrieval.reranking.models import RerankedCandidate, RerankingRequest, RerankingResponse

class RerankingService:
    """
    Application-facing boundary around a Reranker implementation.

    Responsibilities:
      - build the canonical reranking request;
      - invoke the configured reranker;
      - validate the reranker response against the request;
      - reject fabricated or duplicate candidate identities;
      - validate reranker identity/descriptor consistency;
      - preserve trusted RetrievalCandidate provenance;
      - apply the reranker's returned ordering;
      - attach reranker scores to RetrievalScores;
      - ensure passthrough/no-score semantics remain explicit.

    The reranker is never trusted to recreate or modify knowledge candidates. It may only return chunk IDs, scores, and ordering.
    """
    def __init__(self, *, reranker: Reranker) -> None:
        if not isinstance(reranker, Reranker):
            raise TypeError("reranker must be a Reranker instance.")

        self._reranker = reranker

    @property
    def reranker(self) -> Reranker:
        return self._reranker

    def rerank(self, *, query: RetrievalQuery, candidates: tuple[RetrievalCandidate, ...], limit: int) -> tuple[RetrievalCandidate, ...]:
        """
        Rerank trusted retrieval candidates.

        The returned tuple follows the ordering supplied by the configured reranker, but every returned
        RetrievalCandidate originates from the trusted input tuple.

        A reranker can never inject or replace candidate content, provenance, metadata, or retrieval scores.
        """
        request = RerankingRequest(query=query, candidates=candidates, limit=limit)
        if request.is_empty:
            return ()

        try:
            response = self._reranker.rerank(request)
            
        except RerankerProviderError:
            # Provider adapters are expected to translate known external failures into the retrieval reranking error hierarchy.
            # Preserve that typed failure and its original cause rather than obscuring it behind another generic exception.
            raise

        self._validate_response(request=request, response=response)

        return self._materialize_candidates(request=request, response=response)

    def _validate_response(self, *, request: RerankingRequest, response: RerankingResponse) -> None:
        """
        Validate everything that requires knowledge of both the request and the reranker's response.

        Structural invariants local to RerankingResponse are validated by the response model itself. Cross-boundary trust checks live here.
        """
        if not isinstance(response, RerankingResponse):
            raise RerankerResponseError("Reranker returned an invalid response type.")

        self._validate_descriptor(response=response)
        self._validate_cardinality(request=request, response=response)
        self._validate_membership(request=request, response=response)

    def _validate_descriptor(self, *, response: RerankingResponse) -> None:
        """
        Ensure the response was produced by the configured reranker.

        A provider adapter must not silently report a different model, provider, revision, or reranker identity.
        """
        expected = self._reranker.descriptor
        actual = response.descriptor
        if actual != expected:
            raise RerankerResponseError("Reranker response descriptor does not match the configured reranker.")

    @staticmethod
    def _validate_cardinality(*, request: RerankingRequest, response: RerankingResponse) -> None:
        """
        A reranker may return fewer than ``limit`` candidates, but it may never return more
        candidates than were requested or more than the configured output limit.

        We intentionally do not require exact cardinality here. Some future rerankers may legitimately
        filter candidates rather than score every candidate.
        """
        maximum_allowed = min(request.limit, request.candidate_count)
        actual_count = response.count
        if actual_count > maximum_allowed:
            raise RerankerCardinalityError(expected_count=maximum_allowed, actual_count=actual_count)

    @staticmethod
    def _validate_membership(*, request: RerankingRequest, response: RerankingResponse) -> None:
        """
        Reject candidate IDs that were not present in the trusted request.

        This is a critical trust-boundary invariant for external reranking services: provider output 
        may reorder/filter candidates, but it may never fabricate knowledge identities.
        """
        requested_ids = {candidate.chunk_id for candidate in request.candidates}
        for result in response.results:
            if result.chunk_id not in requested_ids:
                raise RerankerResponseError("Reranker returned a chunk ID that was not present in the reranking request.")

    @staticmethod
    def _materialize_candidates(*, request: RerankingRequest, response: RerankingResponse) -> tuple[RetrievalCandidate, ...]:
        """
        Convert the untrusted reranking response back into trusted RetrievalCandidate objects.

        Provider-returned ordering is respected, but canonical candidate data always comes from the original request.
        """
        candidates_by_id: dict[UUID, RetrievalCandidate] = {candidate.chunk_id: candidate for candidate in request.candidates}
        reranked: list[RetrievalCandidate] = []

        for result in response.results:
            trusted_candidate = candidates_by_id.get(result.chunk_id)
            # Membership was already validated. Keeping this guard makes this method safe even if called independently in the future.
            if trusted_candidate is None:
                raise RerankerResponseError("Reranker result could not be mapped to a trusted retrieval candidate.")

            reranked.append(_attach_reranker_result(candidate=trusted_candidate, result=result))

        return tuple(reranked)


def _attach_reranker_result(*, candidate: RetrievalCandidate, result: RerankedCandidate) -> RetrievalCandidate:
    """
    Attach the current reranking stage's score to a trusted candidate.

    ``None`` is meaningful: it means that no model-derived reranking score was produced, as with PassthroughReranker.

    Therefore this function deliberately overwrites any pre-existing reranker_score rather than
    preserving stale data from an earlier reranking invocation.
    """
    updated_scores = replace(candidate.scores, reranker_score=result.score)
    return replace(candidate, scores=updated_scores)