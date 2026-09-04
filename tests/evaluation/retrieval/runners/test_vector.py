from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from evaluation.retrieval.models import (
    RetrievalEvaluationCase,
    RetrievalEvaluationInput,
)
from evaluation.retrieval.runners.base import (
    RetrievalRunnerConfigurationError,
    RetrievalRunnerContractError,
)
from evaluation.retrieval.runners.vector import (
    VectorRetrievalEvaluationRunner,
)
from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalFilters,
    RetrievalMethod,
    RetrievalQuery,
    RetrievalResult,
    RetrievalScores,
)
from packages.knowledge.retrieval.query.builder import (
    DeterministicRetrievalQueryBuilder,
)
from packages.knowledge.retrieval.query.models import (
    PreparedRetrievalQuery,
)
from packages.knowledge.retrieval.query.service import (
    RetrievalQueryPreparationService,
)
from packages.knowledge.retrieval.vector.service import (
    VectorRetrievalService,
)


# ============================================================================
# Helpers
# ============================================================================


def make_query_preparation_service(
) -> RetrievalQueryPreparationService:
    return RetrievalQueryPreparationService(
        builder=DeterministicRetrievalQueryBuilder()
    )


def make_vector_service() -> MagicMock:
    """
    Mock the production vector service contract without invoking an
    embedding provider or PostgreSQL.
    """
    return MagicMock(
        spec=VectorRetrievalService
    )


def make_case(
    *,
    query: str = "How long does my refund take?",
    intent_key: str | None = "refund_request",
    retrieval_input:
        RetrievalEvaluationInput | None = None,
) -> RetrievalEvaluationCase:
    return RetrievalEvaluationCase(
        case_id="refund_001",
        query=query,
        intent_key=intent_key,
        expected_document_titles=(
            "Refund Policy",
        ),
        retrieval_input=(
            retrieval_input
            or RetrievalEvaluationInput()
        ),
    )


def make_candidate(
    *,
    chunk_index: int = 0,
    title: str = "Refund Policy",
    section_title: str | None = (
        "Refund Processing"
    ),
    vector_distance: float = 0.15,
    vector_similarity: float = 0.85,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        chunk_index=chunk_index,
        content=(
            "Refunds are typically processed "
            "within several business days."
        ),
        document_title=title,
        section_title=section_title,
        methods=frozenset(
            {RetrievalMethod.VECTOR}
        ),
        scores=RetrievalScores(
            vector_distance=vector_distance,
            vector_similarity=vector_similarity,
        ),
        metadata={},
    )


def make_runner(
    *,
    vector_service:
        VectorRetrievalService
        | MagicMock
        | None = None,
    candidate_limit: int = 20,
) -> VectorRetrievalEvaluationRunner:
    if vector_service is None:
        vector_service = make_vector_service()

    return VectorRetrievalEvaluationRunner(
        query_preparation_service=(
            make_query_preparation_service()
        ),
        vector_service=vector_service,
        candidate_limit=candidate_limit,
    )


# ============================================================================
# Construction
# ============================================================================


class TestVectorRunnerConstruction:
    def test_constructs_with_valid_dependencies(
        self,
    ) -> None:
        runner = make_runner(
            candidate_limit=17
        )

        assert runner.method == "vector"
        assert runner.candidate_limit == 17

    def test_exposes_vector_service(
        self,
    ) -> None:
        service = make_vector_service()

        runner = make_runner(
            vector_service=service
        )

        assert runner.vector_service is service

    @pytest.mark.parametrize(
        "candidate_limit",
        [
            0,
            -1,
            -100,
            True,
            False,
            1.5,
            "20",
            None,
        ],
    )
    def test_rejects_invalid_candidate_limit(
        self,
        candidate_limit,
    ) -> None:
        with pytest.raises(
            RetrievalRunnerConfigurationError,
            match="candidate_limit",
        ):
            make_runner(
                candidate_limit=candidate_limit
            )

    def test_rejects_invalid_vector_service(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalRunnerConfigurationError,
            match="vector_service",
        ):
            VectorRetrievalEvaluationRunner(
                query_preparation_service=(
                    make_query_preparation_service()
                ),
                vector_service=object(),
                candidate_limit=20,
            )


# ============================================================================
# Semantic query selection
# ============================================================================


class TestSemanticQuerySelection:
    def test_selects_semantic_query(
        self,
    ) -> None:
        prepared = PreparedRetrievalQuery(
            original_query=(
                "How long does a refund take?"
            ),
            semantic_query=(
                "How long does a refund take?"
            ),
            lexical_queries=(
                "refund processing delay",
            ),
        )

        selected = (
            VectorRetrievalEvaluationRunner
            ._select_semantic_query(
                prepared_query=prepared
            )
        )

        assert selected == (
            "How long does a refund take?"
        )

    def test_strips_semantic_query(
        self,
    ) -> None:
        prepared = PreparedRetrievalQuery(
            original_query="refund question",
            semantic_query=(
                "  refund processing question  "
            ),
            lexical_queries=("refund",),
        )

        selected = (
            VectorRetrievalEvaluationRunner
            ._select_semantic_query(
                prepared_query=prepared
            )
        )

        assert selected == (
            "refund processing question"
        )


# ============================================================================
# Retrieval execution
# ============================================================================


class TestVectorRetrievalExecution:
    def test_executes_real_vector_service_contract(
        self,
    ) -> None:
        service = make_vector_service()

        candidate = make_candidate()

        service.search.return_value = (
            candidate,
        )

        runner = make_runner(
            vector_service=service,
            candidate_limit=13,
        )

        prepared = PreparedRetrievalQuery(
            original_query=(
                "How long does my refund take?"
            ),
            semantic_query=(
                "How long does my refund take?"
            ),
            lexical_queries=(
                "long refund take "
                "processing delay",
            ),
        )

        result = runner._execute_retrieval(
            prepared_query=prepared
        )

        service.search.assert_called_once_with(
            query=RetrievalQuery(
                text=(
                    "How long does my refund take?"
                ),
                filters=prepared.filters,
            ),
            limit=13,
        )

        assert isinstance(
            result,
            RetrievalResult,
        )

        assert result.candidates == (
            candidate,
        )

    def test_uses_semantic_not_lexical_query(
        self,
    ) -> None:
        service = make_vector_service()
        service.search.return_value = ()

        runner = make_runner(
            vector_service=service
        )

        prepared = PreparedRetrievalQuery(
            original_query=(
                "Where is my refund?"
            ),
            semantic_query=(
                "Where is my refund?"
            ),
            lexical_queries=(
                "refund processing delay",
            ),
        )

        runner._execute_retrieval(
            prepared_query=prepared
        )

        query = (
            service.search.call_args
            .kwargs["query"]
        )

        assert query.text == (
            prepared.semantic_query
        )

        assert query.text != (
            prepared.lexical_queries[0]
        )

    def test_preserves_original_query_as_result_provenance(
        self,
    ) -> None:
        service = make_vector_service()
        service.search.return_value = ()

        runner = make_runner(
            vector_service=service
        )

        prepared = PreparedRetrievalQuery(
            original_query=(
                "Where is my refund?"
            ),
            semantic_query=(
                "Where is my refund?"
            ),
            lexical_queries=(
                "refund processing delay",
            ),
        )

        result = runner._execute_retrieval(
            prepared_query=prepared
        )

        assert result.query.text == (
            "Where is my refund?"
        )

    def test_preserves_filters_for_search_and_result(
        self,
    ) -> None:
        filters = RetrievalFilters(
            visibilities=("customer",),
            content_types=("policy",),
            metadata={
                "region": "india",
            },
        )

        prepared = PreparedRetrievalQuery(
            original_query="refund policy",
            semantic_query=(
                "What is the refund policy "
                "for customers in India?"
            ),
            lexical_queries=(
                "refund policy india",
            ),
            filters=filters,
        )

        service = make_vector_service()
        service.search.return_value = ()

        runner = make_runner(
            vector_service=service
        )

        result = runner._execute_retrieval(
            prepared_query=prepared
        )

        search_query = (
            service.search.call_args
            .kwargs["query"]
        )

        assert search_query.filters == filters
        assert result.query.filters == filters

    def test_preserves_service_ranking(
        self,
    ) -> None:
        first = make_candidate(
            chunk_index=0,
            vector_distance=0.05,
            vector_similarity=0.95,
        )
        second = make_candidate(
            chunk_index=1,
            vector_distance=0.20,
            vector_similarity=0.80,
        )
        third = make_candidate(
            chunk_index=2,
            vector_distance=0.40,
            vector_similarity=0.60,
        )

        service = make_vector_service()
        service.search.return_value = (
            first,
            second,
            third,
        )

        runner = make_runner(
            vector_service=service
        )

        prepared = PreparedRetrievalQuery(
            original_query="refund",
            semantic_query="refund",
            lexical_queries=("refund",),
        )

        result = runner._execute_retrieval(
            prepared_query=prepared
        )

        assert result.candidates == (
            first,
            second,
            third,
        )

    def test_empty_service_result_is_valid(
        self,
    ) -> None:
        service = make_vector_service()
        service.search.return_value = ()

        runner = make_runner(
            vector_service=service
        )

        prepared = PreparedRetrievalQuery(
            original_query="refund",
            semantic_query="refund",
            lexical_queries=("refund",),
        )

        result = runner._execute_retrieval(
            prepared_query=prepared
        )

        assert result.is_empty
        assert result.candidates == ()

    def test_rejects_non_tuple_service_result(
        self,
    ) -> None:
        service = make_vector_service()

        service.search.return_value = [
            make_candidate()
        ]

        runner = make_runner(
            vector_service=service
        )

        prepared = PreparedRetrievalQuery(
            original_query="refund",
            semantic_query="refund",
            lexical_queries=("refund",),
        )

        with pytest.raises(
            RetrievalRunnerContractError,
            match="must return a tuple",
        ):
            runner._execute_retrieval(
                prepared_query=prepared
            )

    def test_rejects_invalid_prepared_query(
        self,
    ) -> None:
        runner = make_runner()

        with pytest.raises(
            RetrievalRunnerContractError,
            match="prepared_query",
        ):
            runner._execute_retrieval(
                prepared_query=object()
            )


# ============================================================================
# Complete runner path
# ============================================================================


class TestVectorRunnerEndToEnd:
    def test_retrieve_prepares_then_executes_vector_search(
        self,
    ) -> None:
        service = make_vector_service()

        candidate = make_candidate()

        service.search.return_value = (
            candidate,
        )

        runner = make_runner(
            vector_service=service,
            candidate_limit=10,
        )

        case = make_case(
            query=(
                "How long does my refund take?"
            ),
            retrieval_input=(
                RetrievalEvaluationInput(
                    entities={
                        "issue_type": (
                            "refund processing delay"
                        ),
                    }
                )
            ),
        )

        result = runner.retrieve(
            case=case
        )

        assert isinstance(
            result,
            RetrievalResult,
        )

        assert result.query.text == (
            case.query
        )

        assert result.candidates == (
            candidate,
        )

        service.search.assert_called_once()

        call = service.search.call_args

        retrieval_query = (
            call.kwargs["query"]
        )

        assert isinstance(
            retrieval_query,
            RetrievalQuery,
        )

        # Vector retrieval must consume the semantic,
        # natural-language query rather than the
        # token-oriented lexical representation.
        assert retrieval_query.text == (
            case.query
        )

        assert (
            call.kwargs["limit"]
            == 10
        )

    def test_retrieve_preserves_trusted_filters(
        self,
    ) -> None:
        filters = RetrievalFilters(
            visibilities=("customer",),
            content_types=("policy",),
            metadata={
                "region": "india",
            },
        )

        service = make_vector_service()
        service.search.return_value = ()

        runner = make_runner(
            vector_service=service
        )

        case = make_case(
            retrieval_input=(
                RetrievalEvaluationInput(
                    filters=filters
                )
            )
        )

        result = runner.retrieve(
            case=case
        )

        call_query = (
            service.search.call_args
            .kwargs["query"]
        )

        assert call_query.filters == filters
        assert result.query.filters == filters

    def test_entities_do_not_become_hard_filters(
        self,
    ) -> None:
        service = make_vector_service()
        service.search.return_value = ()

        runner = make_runner(
            vector_service=service
        )

        case = make_case(
            retrieval_input=(
                RetrievalEvaluationInput(
                    entities={
                        "issue_type": (
                            "refund delay"
                        ),
                        "order_id": (
                            "ORD-12345"
                        ),
                    }
                )
            )
        )

        runner.retrieve(
            case=case
        )

        query = (
            service.search.call_args
            .kwargs["query"]
        )

        assert (
            query.filters
            == RetrievalFilters()
        )

    def test_ground_truth_never_enters_vector_query(
        self,
    ) -> None:
        service = make_vector_service()
        service.search.return_value = ()

        runner = make_runner(
            vector_service=service
        )

        case = RetrievalEvaluationCase(
            case_id="no_leakage_vector_001",
            query="Where is my money?",
            intent_key="refund_request",
            expected_document_titles=(
                "SECRET REFUND DOCUMENT",
            ),
            expected_section_titles=(
                "SECRET TIMELINE SECTION",
            ),
            expected_topics=(
                "secret refund topic",
            ),
        )

        runner.retrieve(
            case=case
        )

        query = (
            service.search.call_args
            .kwargs["query"]
        )

        searchable_text = (
            query.text.casefold()
        )

        assert (
            "secret refund document"
            not in searchable_text
        )
        assert (
            "secret timeline section"
            not in searchable_text
        )
        assert (
            "secret refund topic"
            not in searchable_text
        )