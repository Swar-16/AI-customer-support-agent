from __future__ import annotations

from unittest.mock import MagicMock
from uuid6 import uuid7

import pytest

from evaluation.retrieval.models import (
    RetrievalEvaluationCase,
    RetrievalEvaluationInput,
)
from evaluation.retrieval.runners.base import (
    RetrievalRunnerConfigurationError,
    RetrievalRunnerContractError,
)
from evaluation.retrieval.runners.hybrid import (
    HybridRetrievalEvaluationRunner,
)
from packages.knowledge.retrieval.application.retrieve_knowledge import (
    RetrieveKnowledge,
)
from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalFilters,
    RetrievalMethod,
    RetrievalQuery,
    RetrievalResult,
    RetrievalScores,
)
from packages.knowledge.retrieval.profiles import (
    RetrievalProfile,
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


def make_profile(
    *,
    vector_enabled: bool = True,
    lexical_enabled: bool = True,
    reranking_enabled: bool = False,
) -> RetrievalProfile:
    return RetrievalProfile(
        profile_id="evaluation-hybrid",
        vector_enabled=vector_enabled,
        lexical_enabled=lexical_enabled,
        reranking_enabled=reranking_enabled,
        vector_candidate_limit=20,
        lexical_candidate_limit=20,
        fused_candidate_limit=20,
        final_candidate_limit=8,
        rrf_k=60,
    )


def make_retrieve_knowledge(
    *,
    profile: RetrievalProfile | None = None,
) -> MagicMock:
    """
    Mock the production RetrieveKnowledge boundary.

    The mock exposes the real profile property because the hybrid
    evaluation runner validates its pipeline configuration.
    """
    service = MagicMock(
        spec=RetrieveKnowledge
    )

    service.profile = (
        profile
        or make_profile()
    )

    return service


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
    methods: frozenset[RetrievalMethod] | None = None,
    fusion_score: float = 0.032,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid7(),
        document_id=uuid7(),
        version_id=uuid7(),
        chunk_index=chunk_index,
        content=(
            "Refund requests are processed "
            "within several business days."
        ),
        document_title="Refund Policy",
        section_title="Refund Processing",
        methods=(
            methods
            or frozenset(
                {
                    RetrievalMethod.VECTOR,
                    RetrievalMethod.LEXICAL,
                }
            )
        ),
        scores=RetrievalScores(
            vector_distance=0.05,
            vector_similarity=0.95,
            lexical_score=1.8,
            fusion_score=fusion_score,
        ),
        metadata={},
    )


def make_prepared_query(
    *,
    original_query: str = (
        "How long does my refund take?"
    ),
    semantic_query: str = (
        "How long does my refund take?"
    ),
    lexical_query: str = (
        "long refund take processing delay"
    ),
    filters: RetrievalFilters | None = None,
) -> PreparedRetrievalQuery:
    return PreparedRetrievalQuery(
        original_query=original_query,
        semantic_query=semantic_query,
        lexical_queries=(lexical_query,),
        filters=(
            filters
            or RetrievalFilters()
        ),
    )


def make_result(
    *,
    prepared_query:
        PreparedRetrievalQuery | None = None,
    candidates:
        tuple[RetrievalCandidate, ...] = (),
) -> RetrievalResult:
    prepared_query = (
        prepared_query
        or make_prepared_query()
    )

    return RetrievalResult(
        query=RetrievalQuery(
            text=prepared_query.original_query,
            filters=prepared_query.filters,
        ),
        candidates=candidates,
    )


def make_runner(
    *,
    retrieve_knowledge:
        RetrieveKnowledge
        | MagicMock
        | None = None,
) -> HybridRetrievalEvaluationRunner:
    if retrieve_knowledge is None:
        retrieve_knowledge = (
            make_retrieve_knowledge()
        )

    return HybridRetrievalEvaluationRunner(
        query_preparation_service=(
            make_query_preparation_service()
        ),
        retrieve_knowledge=retrieve_knowledge,
    )


# ============================================================================
# Construction
# ============================================================================


class TestHybridRunnerConstruction:
    def test_constructs_with_valid_pipeline(
        self,
    ) -> None:
        service = make_retrieve_knowledge()

        runner = make_runner(
            retrieve_knowledge=service
        )

        assert runner.method == "hybrid"
        assert (
            runner.retrieve_knowledge
            is service
        )

    def test_rejects_invalid_retrieve_knowledge(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalRunnerConfigurationError,
            match="retrieve_knowledge",
        ):
            HybridRetrievalEvaluationRunner(
                query_preparation_service=(
                    make_query_preparation_service()
                ),
                retrieve_knowledge=object(),
            )

    def test_rejects_vector_disabled_profile(
        self,
    ) -> None:
        service = make_retrieve_knowledge(
            profile=make_profile(
                vector_enabled=False
            )
        )

        with pytest.raises(
            RetrievalRunnerConfigurationError,
            match="vector retrieval",
        ):
            make_runner(
                retrieve_knowledge=service
            )

    def test_rejects_lexical_disabled_profile(
        self,
    ) -> None:
        service = make_retrieve_knowledge(
            profile=make_profile(
                lexical_enabled=False
            )
        )

        with pytest.raises(
            RetrievalRunnerConfigurationError,
            match="lexical retrieval",
        ):
            make_runner(
                retrieve_knowledge=service
            )

    def test_rejects_reranking_enabled_profile(
        self,
    ) -> None:
        service = make_retrieve_knowledge(
            profile=make_profile(
                reranking_enabled=True
            )
        )

        with pytest.raises(
            RetrievalRunnerConfigurationError,
            match="reranking",
        ):
            make_runner(
                retrieve_knowledge=service
            )


# ============================================================================
# Retrieval execution
# ============================================================================


class TestHybridRetrievalExecution:
    def test_delegates_to_retrieve_knowledge(
        self,
    ) -> None:
        prepared = make_prepared_query()

        candidate = make_candidate()

        expected = make_result(
            prepared_query=prepared,
            candidates=(candidate,),
        )

        service = make_retrieve_knowledge()
        service.retrieve.return_value = (
            expected
        )

        runner = make_runner(
            retrieve_knowledge=service
        )

        result = runner._execute_retrieval(
            prepared_query=prepared
        )

        service.retrieve.assert_called_once_with(
            prepared_query=prepared
        )

        assert result is expected

    def test_does_not_reimplement_fusion(
        self,
    ) -> None:
        """
        The runner must preserve whatever ranking/provenance the
        production hybrid pipeline returns.
        """
        prepared = make_prepared_query()

        first = make_candidate(
            chunk_index=0,
            fusion_score=0.040,
        )
        second = make_candidate(
            chunk_index=1,
            fusion_score=0.030,
        )
        third = make_candidate(
            chunk_index=2,
            fusion_score=0.020,
        )

        expected = make_result(
            prepared_query=prepared,
            candidates=(
                first,
                second,
                third,
            ),
        )

        service = make_retrieve_knowledge()
        service.retrieve.return_value = (
            expected
        )

        result = make_runner(
            retrieve_knowledge=service
        )._execute_retrieval(
            prepared_query=prepared
        )

        assert result.candidates == (
            first,
            second,
            third,
        )

    def test_preserves_hybrid_candidate_provenance(
        self,
    ) -> None:
        prepared = make_prepared_query()

        candidate = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                    RetrievalMethod.LEXICAL,
                }
            )
        )

        service = make_retrieve_knowledge()
        service.retrieve.return_value = (
            make_result(
                prepared_query=prepared,
                candidates=(candidate,),
            )
        )

        result = make_runner(
            retrieve_knowledge=service
        )._execute_retrieval(
            prepared_query=prepared
        )

        returned = result.candidates[0]

        assert (
            RetrievalMethod.VECTOR
            in returned.methods
        )
        assert (
            RetrievalMethod.LEXICAL
            in returned.methods
        )
        assert (
            returned.scores.fusion_score
            is not None
        )

    def test_empty_result_is_valid(
        self,
    ) -> None:
        prepared = make_prepared_query()

        service = make_retrieve_knowledge()
        service.retrieve.return_value = (
            make_result(
                prepared_query=prepared
            )
        )

        result = make_runner(
            retrieve_knowledge=service
        )._execute_retrieval(
            prepared_query=prepared
        )

        assert result.is_empty
        assert result.candidates == ()

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

    def test_rejects_invalid_service_result(
        self,
    ) -> None:
        service = make_retrieve_knowledge()
        service.retrieve.return_value = (
            object()
        )

        runner = make_runner(
            retrieve_knowledge=service
        )

        with pytest.raises(
            RetrievalRunnerContractError,
            match=(
                "must return a "
                "RetrievalResult"
            ),
        ):
            runner._execute_retrieval(
                prepared_query=(
                    make_prepared_query()
                )
            )

    def test_rejects_wrong_result_query(
        self,
    ) -> None:
        prepared = make_prepared_query(
            original_query=(
                "How long does my refund take?"
            )
        )

        wrong_result = RetrievalResult(
            query=RetrievalQuery(
                text="Different customer query"
            ),
            candidates=(),
        )

        service = make_retrieve_knowledge()
        service.retrieve.return_value = (
            wrong_result
        )

        runner = make_runner(
            retrieve_knowledge=service
        )

        with pytest.raises(
            RetrievalRunnerContractError,
            match="different canonical",
        ):
            runner._execute_retrieval(
                prepared_query=prepared
            )

    def test_rejects_wrong_result_filters(
        self,
    ) -> None:
        filters = RetrievalFilters(
            visibilities=("customer",),
            content_types=("policy",),
            metadata={
                "region": "india",
            },
        )

        prepared = make_prepared_query(
            filters=filters
        )

        wrong_result = RetrievalResult(
            query=RetrievalQuery(
                text=prepared.original_query,
                filters=RetrievalFilters(),
            ),
            candidates=(),
        )

        service = make_retrieve_knowledge()
        service.retrieve.return_value = (
            wrong_result
        )

        runner = make_runner(
            retrieve_knowledge=service
        )

        with pytest.raises(
            RetrievalRunnerContractError,
            match="different canonical",
        ):
            runner._execute_retrieval(
                prepared_query=prepared
            )


# ============================================================================
# Complete runner path
# ============================================================================


class TestHybridRunnerEndToEnd:
    def test_retrieve_prepares_then_executes_hybrid_pipeline(
        self,
    ) -> None:
        service = make_retrieve_knowledge()

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

        candidate = make_candidate()

        expected_query = RetrievalQuery(
            text=case.query,
            filters=RetrievalFilters(),
        )

        service.retrieve.return_value = (
            RetrievalResult(
                query=expected_query,
                candidates=(candidate,),
            )
        )

        runner = make_runner(
            retrieve_knowledge=service
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

        service.retrieve.assert_called_once()

        prepared = (
            service.retrieve
            .call_args
            .kwargs["prepared_query"]
        )

        assert isinstance(
            prepared,
            PreparedRetrievalQuery,
        )

        assert prepared.original_query == (
            case.query
        )

        assert prepared.semantic_query == (
            case.query
        )

        lexical_terms = set(
            prepared.lexical_queries[0].split()
        )

        assert {
            "refund",
            "processing",
            "delay",
        }.issubset(
            lexical_terms
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

        case = make_case(
            retrieval_input=(
                RetrievalEvaluationInput(
                    filters=filters
                )
            )
        )

        service = make_retrieve_knowledge()

        service.retrieve.return_value = (
            RetrievalResult(
                query=RetrievalQuery(
                    text=case.query,
                    filters=filters,
                ),
                candidates=(),
            )
        )

        runner = make_runner(
            retrieve_knowledge=service
        )

        result = runner.retrieve(
            case=case
        )

        prepared = (
            service.retrieve
            .call_args
            .kwargs["prepared_query"]
        )

        assert prepared.filters == filters
        assert result.query.filters == filters

    def test_ground_truth_never_enters_prepared_query(
        self,
    ) -> None:
        case = RetrievalEvaluationCase(
            case_id="hybrid_no_leakage_001",
            query="Where is my money?",
            intent_key="refund_request",
            expected_document_titles=(
                "SECRET REFUND DOCUMENT",
            ),
            expected_section_titles=(
                "SECRET REFUND SECTION",
            ),
            expected_topics=(
                "secret refund topic",
            ),
        )

        service = make_retrieve_knowledge()

        service.retrieve.return_value = (
            RetrievalResult(
                query=RetrievalQuery(
                    text=case.query
                ),
                candidates=(),
            )
        )

        runner = make_runner(
            retrieve_knowledge=service
        )

        runner.retrieve(
            case=case
        )

        prepared = (
            service.retrieve
            .call_args
            .kwargs["prepared_query"]
        )

        searchable_text = " ".join(
            (
                prepared.original_query,
                prepared.semantic_query,
                *prepared.lexical_queries,
            )
        ).casefold()

        assert (
            "secret refund document"
            not in searchable_text
        )
        assert (
            "secret refund section"
            not in searchable_text
        )
        assert (
            "secret refund topic"
            not in searchable_text
        )

    def test_entities_do_not_become_hard_filters(
        self,
    ) -> None:
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

        service = make_retrieve_knowledge()

        service.retrieve.return_value = (
            RetrievalResult(
                query=RetrievalQuery(
                    text=case.query
                ),
                candidates=(),
            )
        )

        runner = make_runner(
            retrieve_knowledge=service
        )

        runner.retrieve(
            case=case
        )

        prepared = (
            service.retrieve
            .call_args
            .kwargs["prepared_query"]
        )

        assert (
            prepared.filters
            == RetrievalFilters()
        )

        assert (
            "ORD-12345"
            not in " ".join(
                prepared.lexical_queries
            )
        )