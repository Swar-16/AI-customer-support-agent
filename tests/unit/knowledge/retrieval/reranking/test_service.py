from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from packages.knowledge.retrieval.errors import (
    RerankerCardinalityError,
    RerankerProviderError,
    RerankerResponseError,
)
from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalMethod,
    RetrievalQuery,
    RetrievalScores,
)
from packages.knowledge.retrieval.reranking.base import (
    Reranker,
)
from packages.knowledge.retrieval.reranking.models import (
    RerankedCandidate,
    RerankerDescriptor,
    RerankingRequest,
    RerankingResponse,
)
from packages.knowledge.retrieval.reranking.passthrough import (
    PassthroughReranker,
)
from packages.knowledge.retrieval.reranking.service import (
    RerankingService,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def make_candidate(
    *,
    chunk_id: UUID | None = None,
    version_id: UUID | None = None,
    document_id: UUID | None = None,
    chunk_index: int = 0,
    content: str = "Refunds are available within thirty days.",
    document_title: str = "Refund Policy",
    section_title: str | None = "Eligibility",
    methods: frozenset[RetrievalMethod] | None = None,
    scores: RetrievalScores | None = None,
    metadata: dict | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id or uuid4(),
        version_id=version_id or uuid4(),
        document_id=document_id or uuid4(),
        chunk_index=chunk_index,
        content=content,
        document_title=document_title,
        section_title=section_title,
        methods=(
            methods
            if methods is not None
            else frozenset(
                {
                    RetrievalMethod.VECTOR,
                    RetrievalMethod.LEXICAL,
                }
            )
        ),
        scores=(
            scores
            if scores is not None
            else RetrievalScores(
                vector_distance=0.10,
                vector_similarity=0.90,
                lexical_score=0.75,
                fusion_score=0.032,
            )
        ),
        metadata=(
            metadata
            if metadata is not None
            else {
                "section_path": [
                    "Refund Policy",
                    "Eligibility",
                ],
                "language": "en",
            }
        ),
    )


class FakeReranker(Reranker):
    """
    Controllable reranker used to test the service boundary.

    It records requests and delegates response construction to the supplied
    callback so individual tests can simulate arbitrary provider behavior.
    """

    def __init__(
        self,
        *,
        descriptor: RerankerDescriptor | None = None,
        handler=None,
    ) -> None:
        self._descriptor = (
            descriptor
            if descriptor is not None
            else RerankerDescriptor(
                reranker_id="fake",
                provider="test",
                model="test-model",
                revision="v1",
            )
        )
        self._handler = handler
        self.requests: list[RerankingRequest] = []

    @property
    def descriptor(self) -> RerankerDescriptor:
        return self._descriptor

    def rerank(
        self,
        request: RerankingRequest,
    ) -> RerankingResponse:
        self.requests.append(request)

        if self._handler is not None:
            return self._handler(request)

        return RerankingResponse(
            results=tuple(
                RerankedCandidate(
                    chunk_id=candidate.chunk_id,
                    score=1.0 / rank,
                )
                for rank, candidate in enumerate(
                    request.candidates[
                        :request.limit
                    ],
                    start=1,
                )
            ),
            descriptor=self.descriptor,
        )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestRerankingServiceConstruction:
    def test_accepts_reranker(self):
        reranker = FakeReranker()

        service = RerankingService(
            reranker=reranker
        )

        assert service.reranker is reranker

    @pytest.mark.parametrize(
        "reranker",
        [
            None,
            object(),
            "reranker",
            123,
        ],
    )
    def test_rejects_invalid_reranker(
        self,
        reranker,
    ):
        with pytest.raises(
            TypeError,
            match="reranker must be a Reranker instance",
        ):
            RerankingService(
                reranker=reranker,  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Request construction
# ---------------------------------------------------------------------------


class TestRerankingServiceRequest:
    def test_builds_request_from_service_arguments(
        self,
    ):
        candidate = make_candidate()
        query = RetrievalQuery(
            text="What is the refund policy?"
        )

        reranker = FakeReranker()

        service = RerankingService(
            reranker=reranker
        )

        service.rerank(
            query=query,
            candidates=(candidate,),
            limit=1,
        )

        assert len(reranker.requests) == 1

        request = reranker.requests[0]

        assert request.query == query
        assert request.candidates == (candidate,)
        assert request.limit == 1

    def test_request_validation_rejects_invalid_query(
        self,
    ):
        service = RerankingService(
            reranker=FakeReranker()
        )

        with pytest.raises(
            TypeError,
            match="query must be a RetrievalQuery instance",
        ):
            service.rerank(
                query="refund",  # type: ignore[arg-type]
                candidates=(),
                limit=1,
            )

    def test_request_validation_rejects_non_tuple_candidates(
        self,
    ):
        service = RerankingService(
            reranker=FakeReranker()
        )

        with pytest.raises(
            TypeError,
            match="candidates must be a tuple",
        ):
            service.rerank(
                query=RetrievalQuery(
                    text="refund"
                ),
                candidates=[],  # type: ignore[arg-type]
                limit=1,
            )

    @pytest.mark.parametrize(
        "limit",
        [
            0,
            -1,
            -10,
        ],
    )
    def test_request_validation_rejects_non_positive_limit(
        self,
        limit,
    ):
        service = RerankingService(
            reranker=FakeReranker()
        )

        with pytest.raises(
            ValueError,
            match="limit must be greater than zero",
        ):
            service.rerank(
                query=RetrievalQuery(
                    text="refund"
                ),
                candidates=(),
                limit=limit,
            )

    @pytest.mark.parametrize(
        "limit",
        [
            True,
            False,
            1.0,
            "1",
            None,
        ],
    )
    def test_request_validation_rejects_non_integer_limit(
        self,
        limit,
    ):
        service = RerankingService(
            reranker=FakeReranker()
        )

        with pytest.raises(
            TypeError,
            match="limit must be an integer",
        ):
            service.rerank(
                query=RetrievalQuery(
                    text="refund"
                ),
                candidates=(),
                limit=limit,  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


class TestRerankingServiceEmptyInput:
    def test_empty_candidates_returns_empty_tuple(
        self,
    ):
        reranker = FakeReranker()

        result = RerankingService(
            reranker=reranker
        ).rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=(),
            limit=10,
        )

        assert result == ()

    def test_empty_candidates_does_not_call_reranker(
        self,
    ):
        reranker = FakeReranker()

        RerankingService(
            reranker=reranker
        ).rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=(),
            limit=10,
        )

        assert reranker.requests == []


# ---------------------------------------------------------------------------
# Ordering and score attachment
# ---------------------------------------------------------------------------


class TestRerankingServiceResults:
    def test_applies_reranker_order(
        self,
    ):
        first = make_candidate()
        second = make_candidate()
        third = make_candidate()

        descriptor = RerankerDescriptor(
            reranker_id="fake",
            provider="test",
            model="model",
        )

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            return RerankingResponse(
                results=(
                    RerankedCandidate(
                        chunk_id=third.chunk_id,
                        score=0.95,
                    ),
                    RerankedCandidate(
                        chunk_id=first.chunk_id,
                        score=0.80,
                    ),
                    RerankedCandidate(
                        chunk_id=second.chunk_id,
                        score=0.70,
                    ),
                ),
                descriptor=descriptor,
            )

        service = RerankingService(
            reranker=FakeReranker(
                descriptor=descriptor,
                handler=handler,
            )
        )

        result = service.rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=(
                first,
                second,
                third,
            ),
            limit=3,
        )

        assert [
            candidate.chunk_id
            for candidate in result
        ] == [
            third.chunk_id,
            first.chunk_id,
            second.chunk_id,
        ]

    def test_attaches_real_reranker_scores(
        self,
    ):
        first = make_candidate()
        second = make_candidate()

        descriptor = RerankerDescriptor(
            reranker_id="fake",
            provider="test",
        )

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            return RerankingResponse(
                results=(
                    RerankedCandidate(
                        chunk_id=second.chunk_id,
                        score=8.75,
                    ),
                    RerankedCandidate(
                        chunk_id=first.chunk_id,
                        score=-1.25,
                    ),
                ),
                descriptor=descriptor,
            )

        result = RerankingService(
            reranker=FakeReranker(
                descriptor=descriptor,
                handler=handler,
            )
        ).rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=(
                first,
                second,
            ),
            limit=2,
        )

        assert (
            result[0].scores.reranker_score
            == 8.75
        )
        assert (
            result[1].scores.reranker_score
            == -1.25
        )

    def test_none_score_clears_stale_reranker_score(
        self,
    ):
        candidate = make_candidate(
            scores=RetrievalScores(
                vector_similarity=0.90,
                fusion_score=0.03,
                reranker_score=999.0,
            )
        )

        descriptor = RerankerDescriptor(
            reranker_id="fake",
            provider="test",
        )

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            return RerankingResponse(
                results=(
                    RerankedCandidate(
                        chunk_id=candidate.chunk_id,
                        score=None,
                    ),
                ),
                descriptor=descriptor,
            )

        result = RerankingService(
            reranker=FakeReranker(
                descriptor=descriptor,
                handler=handler,
            )
        ).rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=(candidate,),
            limit=1,
        )

        assert (
            result[0].scores.reranker_score
            is None
        )

    def test_passthrough_preserves_order_and_has_no_reranker_score(
        self,
    ):
        first = make_candidate()
        second = make_candidate()
        third = make_candidate()

        service = RerankingService(
            reranker=PassthroughReranker()
        )

        result = service.rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=(
                first,
                second,
                third,
            ),
            limit=2,
        )

        assert [
            candidate.chunk_id
            for candidate in result
        ] == [
            first.chunk_id,
            second.chunk_id,
        ]

        assert all(
            candidate.scores.reranker_score
            is None
            for candidate in result
        )

    def test_allows_reranker_to_return_subset(
        self,
    ):
        first = make_candidate()
        second = make_candidate()
        third = make_candidate()

        descriptor = RerankerDescriptor(
            reranker_id="filtering",
            provider="test",
        )

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            return RerankingResponse(
                results=(
                    RerankedCandidate(
                        chunk_id=second.chunk_id,
                        score=0.99,
                    ),
                ),
                descriptor=descriptor,
            )

        result = RerankingService(
            reranker=FakeReranker(
                descriptor=descriptor,
                handler=handler,
            )
        ).rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=(
                first,
                second,
                third,
            ),
            limit=3,
        )

        assert len(result) == 1
        assert (
            result[0].chunk_id
            == second.chunk_id
        )


# ---------------------------------------------------------------------------
# Trusted provenance
# ---------------------------------------------------------------------------


class TestRerankingServiceProvenance:
    def test_preserves_trusted_candidate_data(
        self,
    ):
        candidate = make_candidate(
            chunk_index=17,
            content="Canonical trusted content.",
            document_title="Trusted Policy",
            section_title="Trusted Section",
            metadata={
                "language": "en",
                "region": "IN",
            },
            scores=RetrievalScores(
                vector_distance=0.12,
                vector_similarity=0.88,
                lexical_score=0.72,
                fusion_score=0.031,
            ),
        )

        descriptor = RerankerDescriptor(
            reranker_id="fake",
            provider="test",
        )

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            return RerankingResponse(
                results=(
                    RerankedCandidate(
                        chunk_id=candidate.chunk_id,
                        score=0.97,
                    ),
                ),
                descriptor=descriptor,
            )

        result = RerankingService(
            reranker=FakeReranker(
                descriptor=descriptor,
                handler=handler,
            )
        ).rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=(candidate,),
            limit=1,
        )

        reranked = result[0]

        assert reranked.chunk_id == candidate.chunk_id
        assert reranked.version_id == candidate.version_id
        assert reranked.document_id == candidate.document_id
        assert reranked.chunk_index == 17
        assert (
            reranked.content
            == "Canonical trusted content."
        )
        assert (
            reranked.document_title
            == "Trusted Policy"
        )
        assert (
            reranked.section_title
            == "Trusted Section"
        )
        assert dict(reranked.metadata) == {
            "language": "en",
            "region": "IN",
        }

    def test_preserves_pre_reranking_scores(
        self,
    ):
        candidate = make_candidate(
            scores=RetrievalScores(
                vector_distance=0.15,
                vector_similarity=0.85,
                lexical_score=0.65,
                fusion_score=0.029,
            )
        )

        descriptor = RerankerDescriptor(
            reranker_id="fake",
            provider="test",
        )

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            return RerankingResponse(
                results=(
                    RerankedCandidate(
                        chunk_id=candidate.chunk_id,
                        score=0.91,
                    ),
                ),
                descriptor=descriptor,
            )

        result = RerankingService(
            reranker=FakeReranker(
                descriptor=descriptor,
                handler=handler,
            )
        ).rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=(candidate,),
            limit=1,
        )

        scores = result[0].scores

        assert scores.vector_distance == 0.15
        assert scores.vector_similarity == 0.85
        assert scores.lexical_score == 0.65
        assert scores.fusion_score == 0.029
        assert scores.reranker_score == 0.91


# ---------------------------------------------------------------------------
# Trust-boundary validation
# ---------------------------------------------------------------------------


class TestRerankingServiceTrustBoundary:
    def test_rejects_invalid_response_type(
        self,
    ):
        def handler(
            request: RerankingRequest,
        ):
            return "invalid-response"

        service = RerankingService(
            reranker=FakeReranker(
                handler=handler,
            )
        )

        with pytest.raises(
            RerankerResponseError,
            match="invalid response type",
        ):
            service.rerank(
                query=RetrievalQuery(
                    text="refund"
                ),
                candidates=(
                    make_candidate(),
                ),
                limit=1,
            )

    def test_rejects_descriptor_mismatch(
        self,
    ):
        candidate = make_candidate()

        configured_descriptor = RerankerDescriptor(
            reranker_id="configured",
            provider="test",
            model="model-a",
            revision="v1",
        )

        returned_descriptor = RerankerDescriptor(
            reranker_id="different",
            provider="test",
            model="model-b",
            revision="v2",
        )

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            return RerankingResponse(
                results=(
                    RerankedCandidate(
                        chunk_id=candidate.chunk_id,
                        score=0.9,
                    ),
                ),
                descriptor=returned_descriptor,
            )

        service = RerankingService(
            reranker=FakeReranker(
                descriptor=configured_descriptor,
                handler=handler,
            )
        )

        with pytest.raises(
            RerankerResponseError,
            match="descriptor does not match",
        ):
            service.rerank(
                query=RetrievalQuery(
                    text="refund"
                ),
                candidates=(candidate,),
                limit=1,
            )

    def test_rejects_fabricated_chunk_id(
        self,
    ):
        candidate = make_candidate()

        descriptor = RerankerDescriptor(
            reranker_id="fake",
            provider="test",
        )

        fabricated_id = uuid4()

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            return RerankingResponse(
                results=(
                    RerankedCandidate(
                        chunk_id=fabricated_id,
                        score=0.99,
                    ),
                ),
                descriptor=descriptor,
            )

        service = RerankingService(
            reranker=FakeReranker(
                descriptor=descriptor,
                handler=handler,
            )
        )

        with pytest.raises(
            RerankerResponseError,
            match="not present in the reranking request",
        ):
            service.rerank(
                query=RetrievalQuery(
                    text="refund"
                ),
                candidates=(candidate,),
                limit=1,
            )

    def test_rejects_more_results_than_limit(
        self,
    ):
        first = make_candidate()
        second = make_candidate()

        descriptor = RerankerDescriptor(
            reranker_id="fake",
            provider="test",
        )

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            return RerankingResponse(
                results=(
                    RerankedCandidate(
                        chunk_id=first.chunk_id,
                        score=0.9,
                    ),
                    RerankedCandidate(
                        chunk_id=second.chunk_id,
                        score=0.8,
                    ),
                ),
                descriptor=descriptor,
            )

        service = RerankingService(
            reranker=FakeReranker(
                descriptor=descriptor,
                handler=handler,
            )
        )

        with pytest.raises(
            RerankerCardinalityError,
        ):
            service.rerank(
                query=RetrievalQuery(
                    text="refund"
                ),
                candidates=(
                    first,
                    second,
                ),
                limit=1,
            )

    def test_rejects_more_results_than_input_candidates(
        self,
    ):
        candidate = make_candidate()

        descriptor = RerankerDescriptor(
            reranker_id="fake",
            provider="test",
        )

        fabricated_id = uuid4()

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            return RerankingResponse(
                results=(
                    RerankedCandidate(
                        chunk_id=candidate.chunk_id,
                        score=0.9,
                    ),
                    RerankedCandidate(
                        chunk_id=fabricated_id,
                        score=0.8,
                    ),
                ),
                descriptor=descriptor,
            )

        service = RerankingService(
            reranker=FakeReranker(
                descriptor=descriptor,
                handler=handler,
            )
        )

        # Cardinality is checked before membership.
        with pytest.raises(
            RerankerCardinalityError,
        ):
            service.rerank(
                query=RetrievalQuery(
                    text="refund"
                ),
                candidates=(candidate,),
                limit=10,
            )


# ---------------------------------------------------------------------------
# Failure semantics
# ---------------------------------------------------------------------------


class TestRerankingServiceFailures:
    def test_preserves_known_provider_failure(
        self,
    ):
        candidate = make_candidate()

        provider_error = RerankerProviderError(
            "Provider unavailable."
        )

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            raise provider_error

        service = RerankingService(
            reranker=FakeReranker(
                handler=handler,
            )
        )

        with pytest.raises(
            RerankerProviderError,
        ) as exc_info:
            service.rerank(
                query=RetrievalQuery(
                    text="refund"
                ),
                candidates=(candidate,),
                limit=1,
            )

        assert exc_info.value is provider_error

    def test_does_not_swallow_unexpected_programming_error(
        self,
    ):
        candidate = make_candidate()

        def handler(
            request: RerankingRequest,
        ) -> RerankingResponse:
            raise RuntimeError(
                "programming defect"
            )

        service = RerankingService(
            reranker=FakeReranker(
                handler=handler,
            )
        )

        with pytest.raises(
            RuntimeError,
            match="programming defect",
        ):
            service.rerank(
                query=RetrievalQuery(
                    text="refund"
                ),
                candidates=(candidate,),
                limit=1,
            )


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestRerankingServiceImmutability:
    def test_does_not_mutate_original_candidate(
        self,
    ):
        original_scores = RetrievalScores(
            vector_distance=0.10,
            vector_similarity=0.90,
            lexical_score=0.75,
            fusion_score=0.032,
        )

        candidate = make_candidate(
            scores=original_scores
        )

        service = RerankingService(
            reranker=FakeReranker()
        )

        result = service.rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=(candidate,),
            limit=1,
        )

        assert candidate.scores == original_scores
        assert (
            candidate.scores.reranker_score
            is None
        )

        assert result[0] is not candidate
        assert (
            result[0].scores.reranker_score
            == 1.0
        )

    def test_does_not_mutate_input_candidate_tuple(
        self,
    ):
        first = make_candidate()
        second = make_candidate()

        candidates = (
            first,
            second,
        )

        original = candidates

        RerankingService(
            reranker=FakeReranker()
        ).rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=candidates,
            limit=2,
        )

        assert candidates == original

    def test_does_not_modify_candidate_methods(
        self,
    ):
        candidate = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                    RetrievalMethod.LEXICAL,
                }
            )
        )

        result = RerankingService(
            reranker=FakeReranker()
        ).rerank(
            query=RetrievalQuery(
                text="refund"
            ),
            candidates=(candidate,),
            limit=1,
        )

        assert result[0].methods == frozenset(
            {
                RetrievalMethod.VECTOR,
                RetrievalMethod.LEXICAL,
            }
        )