from __future__ import annotations

from uuid import uuid4

import pytest

from packages.knowledge.embeddings.errors import (
    EmbeddingProviderTimeoutError,
)
from packages.knowledge.embeddings.models import (
    EmbeddingInputDescriptor,
    EmbeddingProviderDescriptor,
    EmbeddingVector,
)
from packages.knowledge.embeddings.provider.base import EmbeddingProvider
from packages.knowledge.retrieval.errors import (
    QueryEmbeddingDimensionError,
    QueryEmbeddingError,
    VectorRetrievalRepositoryError,
    VectorSearchError,
)
from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalFilters,
    RetrievalMethod,
    RetrievalQuery,
    RetrievalScores,
)
from packages.knowledge.retrieval.vector.repository import (
    VectorSearchMatch,
    VectorSearchRequest,
)
from packages.knowledge.retrieval.vector.service import (
    VectorRetrievalService,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


PROVIDER_DESCRIPTOR = EmbeddingProviderDescriptor(
    provider="test-provider",
    model="test-model",
    revision="1",
    dimensions=3,
)

INPUT_DESCRIPTOR = EmbeddingInputDescriptor(
    strategy_id="contextual",
    version="1",
    config_fingerprint="a" * 64,
)


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        vector: EmbeddingVector | None = None,
        error: Exception | None = None,
    ) -> None:
        self._vector = vector or EmbeddingVector(
            values=(1.0, 0.0, 0.0)
        )
        self._error = error
        self.query_calls: list[str] = []

    @property
    def descriptor(self) -> EmbeddingProviderDescriptor:
        return PROVIDER_DESCRIPTOR

    def embed_documents(self, texts):
        raise NotImplementedError

    def embed_query(self, text: str) -> EmbeddingVector:
        self.query_calls.append(text)

        if self._error is not None:
            raise self._error

        return self._vector


class InvalidEmbeddingProvider(EmbeddingProvider):
    @property
    def descriptor(self) -> EmbeddingProviderDescriptor:
        return PROVIDER_DESCRIPTOR

    def embed_documents(self, texts):
        raise NotImplementedError

    def embed_query(self, text: str):
        return "not-an-embedding-vector"


class FakeVectorRepository:
    def __init__(
        self,
        *,
        matches: tuple[VectorSearchMatch, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self._matches = matches
        self._error = error
        self.requests: list[VectorSearchRequest] = []

    def search(
        self,
        request: VectorSearchRequest,
    ) -> tuple[VectorSearchMatch, ...]:
        self.requests.append(request)

        if self._error is not None:
            raise self._error

        return self._matches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_candidate(
    *,
    methods: frozenset[RetrievalMethod] | None = None,
    scores: RetrievalScores | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid4(),
        version_id=uuid4(),
        document_id=uuid4(),
        chunk_index=0,
        content="Refunds are available within 30 days.",
        document_title="Refund Policy",
        section_title="Eligibility",
        methods=(
            methods
            if methods is not None
            else frozenset({RetrievalMethod.VECTOR})
        ),
        scores=(
            scores
            if scores is not None
            else RetrievalScores()
        ),
        metadata={"source": "test"},
    )


def build_query(
    *,
    text: str = "Can I get a refund?",
    filters: RetrievalFilters | None = None,
) -> RetrievalQuery:
    return RetrievalQuery(
        text=text,
        filters=(
            filters
            if filters is not None
            else RetrievalFilters()
        ),
    )


def build_service(
    *,
    provider: EmbeddingProvider | None = None,
    repository=None,
) -> VectorRetrievalService:
    return VectorRetrievalService(
        provider=provider or FakeEmbeddingProvider(),
        repository=repository or FakeVectorRepository(),
        input_descriptor=INPUT_DESCRIPTOR,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestVectorRetrievalServiceSuccess:
    def test_embeds_query_exactly_once(self):
        provider = FakeEmbeddingProvider()
        repository = FakeVectorRepository()

        service = build_service(
            provider=provider,
            repository=repository,
        )

        service.search(
            query=build_query(text="Where is my refund?"),
            limit=10,
        )

        assert provider.query_calls == [
            "Where is my refund?"
        ]

    def test_builds_repository_request_with_correct_provenance(self):
        provider = FakeEmbeddingProvider()
        repository = FakeVectorRepository()

        filters = RetrievalFilters(
            document_ids=(uuid4(),),
            visibilities=("customer", "both"),
        )

        query = build_query(filters=filters)

        service = build_service(
            provider=provider,
            repository=repository,
        )

        service.search(
            query=query,
            limit=7,
        )

        assert len(repository.requests) == 1

        request = repository.requests[0]

        assert request.query_vector == EmbeddingVector(
            values=(1.0, 0.0, 0.0)
        )
        assert request.provider == PROVIDER_DESCRIPTOR
        assert request.input_descriptor == INPUT_DESCRIPTOR
        assert request.filters == filters
        assert request.limit == 7

    def test_converts_cosine_distance_to_similarity(self):
        candidate = build_candidate()

        repository = FakeVectorRepository(
            matches=(
                VectorSearchMatch(
                    candidate=candidate,
                    distance=0.25,
                ),
            )
        )

        service = build_service(
            repository=repository,
        )

        results = service.search(
            query=build_query(),
            limit=5,
        )

        assert len(results) == 1

        result = results[0]

        assert result.scores.vector_distance == pytest.approx(
            0.25
        )
        assert result.scores.vector_similarity == pytest.approx(
            0.75
        )

    def test_preserves_existing_non_vector_scores(self):
        candidate = build_candidate(
            scores=RetrievalScores(
                lexical_score=0.91,
                fusion_score=0.72,
            )
        )

        repository = FakeVectorRepository(
            matches=(
                VectorSearchMatch(
                    candidate=candidate,
                    distance=0.2,
                ),
            )
        )

        service = build_service(
            repository=repository,
        )

        result = service.search(
            query=build_query(),
            limit=5,
        )[0]

        assert result.scores.vector_distance == pytest.approx(
            0.2
        )
        assert result.scores.vector_similarity == pytest.approx(
            0.8
        )

        assert result.scores.lexical_score == pytest.approx(
            0.91
        )
        assert result.scores.fusion_score == pytest.approx(
            0.72
        )

    def test_preserves_existing_methods_and_adds_vector_method(self):
        candidate = build_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.LEXICAL,
                }
            )
        )

        repository = FakeVectorRepository(
            matches=(
                VectorSearchMatch(
                    candidate=candidate,
                    distance=0.1,
                ),
            )
        )

        service = build_service(
            repository=repository,
        )

        result = service.search(
            query=build_query(),
            limit=5,
        )[0]

        assert result.methods == frozenset(
            {
                RetrievalMethod.LEXICAL,
                RetrievalMethod.VECTOR,
            }
        )

    def test_preserves_candidate_identity_and_content(self):
        candidate = build_candidate()

        repository = FakeVectorRepository(
            matches=(
                VectorSearchMatch(
                    candidate=candidate,
                    distance=0.1,
                ),
            )
        )

        service = build_service(
            repository=repository,
        )

        result = service.search(
            query=build_query(),
            limit=5,
        )[0]

        assert result.chunk_id == candidate.chunk_id
        assert result.version_id == candidate.version_id
        assert result.document_id == candidate.document_id
        assert result.chunk_index == candidate.chunk_index
        assert result.content == candidate.content
        assert result.document_title == candidate.document_title
        assert result.section_title == candidate.section_title
        assert result.metadata == candidate.metadata

    def test_empty_repository_result_returns_empty_tuple(self):
        service = build_service(
            repository=FakeVectorRepository(
                matches=()
            )
        )

        results = service.search(
            query=build_query(),
            limit=5,
        )

        assert results == ()


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestVectorRetrievalServiceValidation:
    def test_rejects_non_retrieval_query(self):
        service = build_service()

        with pytest.raises(
            TypeError,
            match="RetrievalQuery",
        ):
            service.search(
                query="refund policy",
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
    def test_rejects_non_positive_limit(self, limit):
        service = build_service()

        with pytest.raises(
            ValueError,
            match="greater than zero",
        ):
            service.search(
                query=build_query(),
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
    def test_rejects_invalid_limit_type(self, limit):
        service = build_service()

        with pytest.raises(
            TypeError,
            match="integer",
        ):
            service.search(
                query=build_query(),
                limit=limit,
            )


# ---------------------------------------------------------------------------
# Embedding failures
# ---------------------------------------------------------------------------


class TestVectorRetrievalServiceEmbeddingFailures:
    def test_translates_embedding_provider_failure(self):
        provider = FakeEmbeddingProvider(
            error=EmbeddingProviderTimeoutError(
                provider="test-provider",
                model="test-model",
                timeout_seconds=5.0,
            )
        )

        service = build_service(
            provider=provider,
        )

        with pytest.raises(
            QueryEmbeddingError
        ) as exc_info:
            service.search(
                query=build_query(),
                limit=5,
            )

        assert isinstance(
            exc_info.value.__cause__,
            EmbeddingProviderTimeoutError,
        )

    def test_does_not_swallow_unexpected_provider_programming_error(
        self,
    ):
        provider = FakeEmbeddingProvider(
            error=RuntimeError(
                "programming bug"
            )
        )

        service = build_service(
            provider=provider,
        )

        with pytest.raises(
            RuntimeError,
            match="programming bug",
        ):
            service.search(
                query=build_query(),
                limit=5,
            )

    def test_rejects_invalid_provider_return_type(self):
        service = build_service(
            provider=InvalidEmbeddingProvider(),
        )

        with pytest.raises(
            QueryEmbeddingError,
            match="invalid query embedding type",
        ):
            service.search(
                query=build_query(),
                limit=5,
            )

    def test_detects_query_embedding_dimension_mismatch(self):
        provider = FakeEmbeddingProvider(
            vector=EmbeddingVector(
                values=(1.0, 0.0)
            )
        )

        service = build_service(
            provider=provider,
        )

        with pytest.raises(
            QueryEmbeddingDimensionError
        ) as exc_info:
            service.search(
                query=build_query(),
                limit=5,
            )

        error = exc_info.value

        assert error.expected_dimensions == 3
        assert error.actual_dimensions == 2


# ---------------------------------------------------------------------------
# Repository failures
# ---------------------------------------------------------------------------


class TestVectorRetrievalServiceRepositoryFailures:
    def test_translates_repository_failure(self):
        repository = FakeVectorRepository(
            error=VectorRetrievalRepositoryError(
                "database query failed"
            )
        )

        service = build_service(
            repository=repository,
        )

        with pytest.raises(
            VectorSearchError
        ) as exc_info:
            service.search(
                query=build_query(),
                limit=5,
            )

        assert isinstance(
            exc_info.value.__cause__,
            VectorRetrievalRepositoryError,
        )

    def test_does_not_swallow_unexpected_repository_programming_error(
        self,
    ):
        repository = FakeVectorRepository(
            error=RuntimeError(
                "repository programming bug"
            )
        )

        service = build_service(
            repository=repository,
        )

        with pytest.raises(
            RuntimeError,
            match="repository programming bug",
        ):
            service.search(
                query=build_query(),
                limit=5,
            )


# ---------------------------------------------------------------------------
# Repository result validation
# ---------------------------------------------------------------------------


class TestVectorRetrievalServiceRepositoryResults:
    def test_rejects_non_finite_distance(self):
        candidate = build_candidate()

        # VectorSearchMatch itself should normally reject this.
        # We bypass construction because this test specifically verifies
        # the service boundary remains defensive.
        match = object.__new__(VectorSearchMatch)
        object.__setattr__(match, "candidate", candidate)
        object.__setattr__(match, "distance", float("nan"))

        repository = FakeVectorRepository(
            matches=(match,)
        )

        service = build_service(
            repository=repository,
        )

        with pytest.raises(
            VectorSearchError,
            match="non-finite",
        ):
            service.search(
                query=build_query(),
                limit=5,
            )

    def test_rejects_negative_distance(self):
        candidate = build_candidate()

        match = object.__new__(VectorSearchMatch)
        object.__setattr__(match, "candidate", candidate)
        object.__setattr__(match, "distance", -0.1)

        repository = FakeVectorRepository(
            matches=(match,)
        )

        service = build_service(
            repository=repository,
        )

        with pytest.raises(
            VectorSearchError,
            match="negative distance",
        ):
            service.search(
                query=build_query(),
                limit=5,
            )