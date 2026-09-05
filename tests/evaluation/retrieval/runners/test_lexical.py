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
from evaluation.retrieval.runners.lexical import (
    LexicalRetrievalEvaluationRunner,
)
from packages.knowledge.retrieval.lexical.service import (
    LexicalRetrievalService,
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


# ============================================================================
# Helpers
# ============================================================================


def make_query_preparation_service(
) -> RetrievalQueryPreparationService:
    return RetrievalQueryPreparationService(
        builder=DeterministicRetrievalQueryBuilder()
    )


def make_lexical_service() -> MagicMock:
    """
    Return a mock that passes the runner's isinstance check while
    preventing these tests from touching PostgreSQL.
    """
    return MagicMock(
        spec=LexicalRetrievalService
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
    lexical_score: float = 1.5,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        chunk_index=chunk_index,
        content=(
            "Refunds are normally processed "
            "within several business days."
        ),
        document_title=title,
        section_title=section_title,
        methods=frozenset(
            {RetrievalMethod.LEXICAL}
        ),
        scores=RetrievalScores(
            lexical_score=lexical_score
        ),
        metadata={},
    )


def make_runner(
    *,
    lexical_service: LexicalRetrievalService
        | MagicMock
        | None = None,
    candidate_limit: int = 20,
) -> LexicalRetrievalEvaluationRunner:
    if lexical_service is None:
        lexical_service = (
            make_lexical_service()
        )

    return LexicalRetrievalEvaluationRunner(
        query_preparation_service=(
            make_query_preparation_service()
        ),
        lexical_service=lexical_service,
        candidate_limit=candidate_limit,
    )


# ============================================================================
# Construction
# ============================================================================


class TestLexicalRunnerConstruction:
    def test_constructs_with_valid_dependencies(
        self,
    ) -> None:
        runner = make_runner(
            candidate_limit=17
        )

        assert runner.method == "lexical"
        assert runner.candidate_limit == 17

    def test_exposes_lexical_service(
        self,
    ) -> None:
        service = make_lexical_service()

        runner = make_runner(
            lexical_service=service
        )

        assert (
            runner.lexical_service
            is service
        )

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

    def test_rejects_invalid_lexical_service(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalRunnerConfigurationError,
            match="lexical_service",
        ):
            LexicalRetrievalEvaluationRunner(
                query_preparation_service=(
                    make_query_preparation_service()
                ),
                lexical_service=object(),
                candidate_limit=20,
            )


# ============================================================================
# Lexical query selection
# ============================================================================


class TestLexicalQuerySelection:
    def test_selects_first_lexical_query(
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
                "refund duration",
            ),
        )

        selected = (
            LexicalRetrievalEvaluationRunner
            ._select_lexical_query(
                prepared_query=prepared
            )
        )

        assert selected == (
            "refund processing delay"
        )

    def test_strips_selected_query(
        self,
    ) -> None:
        prepared = PreparedRetrievalQuery(
            original_query="refund question",
            semantic_query="refund question",
            lexical_queries=(
                "  refund processing  ",
            ),
        )

        selected = (
            LexicalRetrievalEvaluationRunner
            ._select_lexical_query(
                prepared_query=prepared
            )
        )

        assert selected == (
            "refund processing"
        )


# ============================================================================
# Retrieval execution
# ============================================================================


class TestLexicalRetrievalExecution:
    def test_executes_real_lexical_service_contract(
        self,
    ) -> None:
        service = make_lexical_service()

        candidate = make_candidate()

        service.search.return_value = (
            candidate,
        )

        runner = make_runner(
            lexical_service=service,
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
                    "long refund take "
                    "processing delay"
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

    def test_preserves_original_query_as_result_provenance(
        self,
    ) -> None:
        service = make_lexical_service()
        service.search.return_value = ()

        runner = make_runner(
            lexical_service=service
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

        assert result.query.text != (
            prepared.lexical_queries[0]
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
            semantic_query="refund policy",
            lexical_queries=(
                "refund policy india",
            ),
            filters=filters,
        )

        service = make_lexical_service()
        service.search.return_value = ()

        runner = make_runner(
            lexical_service=service
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
            lexical_score=5.0,
        )
        second = make_candidate(
            chunk_index=1,
            lexical_score=3.0,
        )
        third = make_candidate(
            chunk_index=2,
            lexical_score=1.0,
        )

        service = make_lexical_service()
        service.search.return_value = (
            first,
            second,
            third,
        )

        runner = make_runner(
            lexical_service=service
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
        service = make_lexical_service()
        service.search.return_value = ()

        runner = make_runner(
            lexical_service=service
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
        service = make_lexical_service()

        service.search.return_value = [
            make_candidate()
        ]

        runner = make_runner(
            lexical_service=service
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


class TestLexicalRunnerEndToEnd:
    def test_retrieve_prepares_then_executes_lexical_search(
        self,
    ) -> None:
        service = make_lexical_service()

        candidate = make_candidate()

        service.search.return_value = (
            candidate,
        )

        runner = make_runner(
            lexical_service=service,
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

        lexical_terms = set(
            retrieval_query.text.split()
        )

        assert {
            "refund",
            "processing",
            "delay",
        }.issubset(
            lexical_terms
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

        service = make_lexical_service()
        service.search.return_value = ()

        runner = make_runner(
            lexical_service=service
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

    def test_entities_remain_semantic_hints_not_filters(
        self,
    ) -> None:
        service = make_lexical_service()
        service.search.return_value = ()

        runner = make_runner(
            lexical_service=service
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

        # Semantic entity hints must never become
        # hard retrieval filters.
        assert (
            query.filters
            == RetrievalFilters()
        )

        # IDs are deliberately excluded by the
        # deterministic retrieval-query builder.
        assert (
            "ORD-12345"
            not in query.text
        )

        # Non-ID semantic hints may contribute
        # lexical terms.
        assert "refund" in query.text
        assert "delay" in query.text