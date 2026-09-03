from __future__ import annotations

from uuid import uuid4

import pytest

from packages.knowledge.retrieval.errors import (
    LexicalRetrievalRepositoryError,
    LexicalSearchError,
)
from packages.knowledge.retrieval.lexical.repository import (
    LexicalSearchMatch,
)
from packages.knowledge.retrieval.lexical.service import (
    LexicalRetrievalService,
)
from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalFilters,
    RetrievalMethod,
    RetrievalQuery,
    RetrievalScores,
)


def make_candidate(
    *,
    methods: frozenset[RetrievalMethod] | None = None,
    scores: RetrievalScores | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid4(),
        version_id=uuid4(),
        document_id=uuid4(),
        chunk_index=0,
        content="Refunds are available within thirty days.",
        document_title="Refund Policy",
        section_title="Eligibility",
        methods=(
            methods
            if methods is not None
            else frozenset({RetrievalMethod.LEXICAL,})
        ),
        scores=(
            scores
            if scores is not None
            else RetrievalScores()
        ),
        metadata={
            "section_path": ["Refunds", "Eligibility"]
        },
    )


class FakeLexicalRepository:
    def __init__(
        self,
        *,
        matches: tuple[LexicalSearchMatch, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.matches = matches
        self.error = error
        self.calls = []

    def search(self, request):
        self.calls.append(request)

        if self.error is not None:
            raise self.error

        return self.matches


class TestLexicalRetrievalService:
    def test_builds_repository_request_from_query(self):
        repository = FakeLexicalRepository()

        service = LexicalRetrievalService(
            repository=repository
        )

        query = RetrievalQuery(
            text="refund eligibility",
            filters=RetrievalFilters(
                content_types=("policy",),
                visibilities=("customer",),
            ),
        )

        service.search(
            query=query,
            limit=7,
        )

        assert len(repository.calls) == 1

        request = repository.calls[0]

        assert request.query_text == "refund eligibility"
        assert request.filters == query.filters
        assert request.limit == 7

    def test_maps_repository_score_to_lexical_score(self):
        candidate = make_candidate()

        repository = FakeLexicalRepository(
            matches=(
                LexicalSearchMatch(
                    candidate=candidate,
                    score=0.73,
                ),
            )
        )

        service = LexicalRetrievalService(
            repository=repository
        )

        result = service.search(
            query=RetrievalQuery(
                text="refund"
            ),
            limit=5,
        )

        assert len(result) == 1
        assert result[0].scores.lexical_score == pytest.approx(
            0.73
        )

    def test_preserves_existing_scores(self):
        candidate = make_candidate(
            scores=RetrievalScores(
                vector_distance=0.2,
                vector_similarity=0.8,
                fusion_score=0.5,
            )
        )

        repository = FakeLexicalRepository(
            matches=(
                LexicalSearchMatch(
                    candidate=candidate,
                    score=0.61,
                ),
            )
        )

        service = LexicalRetrievalService(
            repository=repository
        )

        result = service.search(
            query=RetrievalQuery(
                text="refund"
            ),
            limit=5,
        )

        scores = result[0].scores

        assert scores.vector_distance == pytest.approx(0.2)
        assert scores.vector_similarity == pytest.approx(0.8)
        assert scores.fusion_score == pytest.approx(0.5)
        assert scores.lexical_score == pytest.approx(0.61)

    def test_adds_lexical_method_without_removing_existing_methods(self):
        candidate = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                }
            )
        )

        repository = FakeLexicalRepository(
            matches=(
                LexicalSearchMatch(
                    candidate=candidate,
                    score=0.5,
                ),
            )
        )

        service = LexicalRetrievalService(
            repository=repository
        )

        result = service.search(
            query=RetrievalQuery(
                text="refund"
            ),
            limit=5,
        )

        assert result[0].methods == frozenset(
            {
                RetrievalMethod.VECTOR,
                RetrievalMethod.LEXICAL,
            }
        )

    def test_preserves_candidate_identity_and_content(self):
        candidate = make_candidate()

        repository = FakeLexicalRepository(
            matches=(
                LexicalSearchMatch(
                    candidate=candidate,
                    score=0.5,
                ),
            )
        )

        service = LexicalRetrievalService(
            repository=repository
        )

        result = service.search(
            query=RetrievalQuery(
                text="refund"
            ),
            limit=5,
        )

        actual = result[0]

        assert actual.chunk_id == candidate.chunk_id
        assert actual.version_id == candidate.version_id
        assert actual.document_id == candidate.document_id
        assert actual.chunk_index == candidate.chunk_index
        assert actual.content == candidate.content
        assert actual.document_title == candidate.document_title
        assert actual.section_title == candidate.section_title
        assert actual.metadata == candidate.metadata

    def test_returns_empty_tuple_when_repository_returns_no_matches(self):
        repository = FakeLexicalRepository()

        service = LexicalRetrievalService(
            repository=repository
        )

        result = service.search(
            query=RetrievalQuery(
                text="nothing relevant"
            ),
            limit=5,
        )

        assert result == ()

    def test_rejects_invalid_query_type(self):
        repository = FakeLexicalRepository()

        service = LexicalRetrievalService(
            repository=repository
        )

        with pytest.raises(
            TypeError,
            match="query must be a RetrievalQuery instance",
        ):
            service.search(
                query="refund",  # type: ignore[arg-type]
                limit=5,
            )

    @pytest.mark.parametrize(
        "limit",
        [
            0,
            -1,
            -100,
        ],
    )
    def test_rejects_non_positive_limit(
        self,
        limit: int,
    ):
        repository = FakeLexicalRepository()

        service = LexicalRetrievalService(
            repository=repository
        )

        with pytest.raises(
            ValueError,
            match="limit must be greater than zero",
        ):
            service.search(
                query=RetrievalQuery(
                    text="refund"
                ),
                limit=limit,
            )

    @pytest.mark.parametrize(
        "limit",
        [
            True,
            False,
            1.5,
            "5",
            None,
        ],
    )
    def test_rejects_non_integer_limit(
        self,
        limit,
    ):
        repository = FakeLexicalRepository()

        service = LexicalRetrievalService(
            repository=repository
        )

        with pytest.raises(
            TypeError,
            match="limit must be an integer",
        ):
            service.search(
                query=RetrievalQuery(
                    text="refund"
                ),
                limit=limit,
            )

    def test_rejects_repository_without_search_method(self):
        class InvalidRepository:
            pass

        with pytest.raises(
            TypeError,
            match="repository must provide a callable search method",
        ):
            LexicalRetrievalService(
                repository=InvalidRepository()
            )

    def test_rejects_none_repository(self):
        with pytest.raises(
            TypeError,
            match="repository must not be None",
        ):
            LexicalRetrievalService(
                repository=None  # type: ignore[arg-type]
            )

    def test_translates_repository_error(self):
        repository_error = (
            LexicalRetrievalRepositoryError(
                "database unavailable"
            )
        )

        repository = FakeLexicalRepository(
            error=repository_error
        )

        service = LexicalRetrievalService(
            repository=repository
        )

        with pytest.raises(
            LexicalSearchError
        ) as exc_info:
            service.search(
                query=RetrievalQuery(
                    text="refund"
                ),
                limit=5,
            )

        assert exc_info.value.__cause__ is repository_error

    def test_unexpected_repository_error_is_not_hidden(self):
        unexpected_error = RuntimeError(
            "programming bug"
        )

        repository = FakeLexicalRepository(
            error=unexpected_error
        )

        service = LexicalRetrievalService(
            repository=repository
        )

        with pytest.raises(
            RuntimeError,
            match="programming bug",
        ):
            service.search(
                query=RetrievalQuery(
                    text="refund"
                ),
                limit=5,
            )

    def test_preserves_repository_order(self):
        first = make_candidate()
        second = make_candidate()
        third = make_candidate()

        repository = FakeLexicalRepository(
            matches=(
                LexicalSearchMatch(
                    candidate=first,
                    score=0.9,
                ),
                LexicalSearchMatch(
                    candidate=second,
                    score=0.7,
                ),
                LexicalSearchMatch(
                    candidate=third,
                    score=0.4,
                ),
            )
        )

        service = LexicalRetrievalService(
            repository=repository
        )

        result = service.search(
            query=RetrievalQuery(
                text="refund"
            ),
            limit=10,
        )

        assert [
            candidate.chunk_id
            for candidate in result
        ] == [
            first.chunk_id,
            second.chunk_id,
            third.chunk_id,
        ]