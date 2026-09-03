from __future__ import annotations

from unittest.mock import create_autospec
from uuid import uuid4

import pytest

from packages.knowledge.retrieval.application.build_grounding_context import (
    BuildGroundingContext,
)
from packages.knowledge.retrieval.application.retrieve_knowledge import (
    RetrieveKnowledge,
)
from packages.knowledge.retrieval.context.builder import (
    GroundingContextBuilder,
)
from packages.knowledge.retrieval.context.models import (
    GroundingContext,
    GroundingContextBlock,
    GroundingContextBudget,
)
from packages.knowledge.retrieval.errors import (
    GroundingContextBudgetError,
    RetrievalPipelineError,
    VectorSearchError,
)
from packages.knowledge.retrieval.models import (
    RetrievalFilters,
    RetrievalQuery,
    RetrievalResult,
)
from packages.knowledge.retrieval.query.models import (
    PreparedRetrievalQuery,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_prepared_query(
    *,
    original_query: str = "What is the refund policy?",
    semantic_query: str = "What is the refund policy?",
    lexical_query: str = "refund policy",
    filters: RetrievalFilters | None = None,
) -> PreparedRetrievalQuery:
    return PreparedRetrievalQuery(
        original_query=original_query,
        semantic_query=semantic_query,
        lexical_queries=(lexical_query,),
        filters=filters if filters is not None else RetrievalFilters(),
    )


def make_canonical_query(
    prepared_query: PreparedRetrievalQuery,
) -> RetrievalQuery:
    return RetrievalQuery(
        text=prepared_query.original_query,
        filters=prepared_query.filters,
    )


def make_budget(
    *,
    max_tokens: int = 1_000,
    max_blocks: int = 8,
) -> GroundingContextBudget:
    return GroundingContextBudget(
        max_tokens=max_tokens,
        max_blocks=max_blocks,
    )


def make_block(
    *,
    content: str = "Refunds are available within thirty days.",
) -> GroundingContextBlock:
    return GroundingContextBlock(
        chunk_id=uuid4(),
        version_id=uuid4(),
        document_id=uuid4(),
        chunk_index=0,
        content=content,
        document_title="Refund Policy",
        section_title="Eligibility",
        metadata={"language": "en"},
        retrieval_score=0.032,
    )


def make_context(
    *,
    query: RetrievalQuery,
    blocks: tuple[GroundingContextBlock, ...] = (),
    estimated_token_count: int = 0,
    truncated: bool = False,
) -> GroundingContext:
    return GroundingContext(
        query=query,
        blocks=blocks,
        estimated_token_count=estimated_token_count,
        truncated=truncated,
    )


def make_retrieve_knowledge():
    return create_autospec(
        RetrieveKnowledge,
        instance=True,
        spec_set=True,
    )


def make_context_builder():
    return create_autospec(
        GroundingContextBuilder,
        instance=True,
        spec_set=True,
    )


def make_service(
    *,
    retrieve_knowledge=None,
    context_builder=None,
    default_budget: GroundingContextBudget | None = None,
) -> BuildGroundingContext:
    return BuildGroundingContext(
        retrieve_knowledge=(
            retrieve_knowledge
            if retrieve_knowledge is not None
            else make_retrieve_knowledge()
        ),
        context_builder=(
            context_builder
            if context_builder is not None
            else make_context_builder()
        ),
        default_budget=(
            default_budget
            if default_budget is not None
            else make_budget()
        ),
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestBuildGroundingContextConstruction:
    def test_accepts_valid_dependencies(self):
        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        default_budget = make_budget()

        service = BuildGroundingContext(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
            default_budget=default_budget,
        )

        assert service.retrieve_knowledge is retrieve_knowledge
        assert service.context_builder is context_builder
        assert service.default_budget is default_budget

    @pytest.mark.parametrize(
        "retrieve_knowledge",
        [None, object(), "retriever", 123],
    )
    def test_rejects_invalid_retrieve_knowledge(
        self,
        retrieve_knowledge,
    ):
        with pytest.raises(
            TypeError,
            match=(
                "retrieve_knowledge must be a "
                "RetrieveKnowledge instance"
            ),
        ):
            BuildGroundingContext(
                retrieve_knowledge=retrieve_knowledge,  # type: ignore[arg-type]
                context_builder=make_context_builder(),
                default_budget=make_budget(),
            )

    @pytest.mark.parametrize(
        "context_builder",
        [None, object(), "builder", 123],
    )
    def test_rejects_invalid_context_builder(
        self,
        context_builder,
    ):
        with pytest.raises(
            TypeError,
            match=(
                "context_builder must be a "
                "GroundingContextBuilder instance"
            ),
        ):
            BuildGroundingContext(
                retrieve_knowledge=make_retrieve_knowledge(),
                context_builder=context_builder,  # type: ignore[arg-type]
                default_budget=make_budget(),
            )

    @pytest.mark.parametrize(
        "default_budget",
        [None, object(), "budget", 123],
    )
    def test_rejects_invalid_default_budget(
        self,
        default_budget,
    ):
        with pytest.raises(
            TypeError,
            match=(
                "default_budget must be a "
                "GroundingContextBudget instance"
            ),
        ):
            BuildGroundingContext(
                retrieve_knowledge=make_retrieve_knowledge(),
                context_builder=make_context_builder(),
                default_budget=default_budget,  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestBuildGroundingContextInput:
    @pytest.mark.parametrize(
        "prepared_query",
        [None, object(), "refund", 123],
    )
    def test_rejects_invalid_prepared_query(
        self,
        prepared_query,
    ):
        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        with pytest.raises(
            TypeError,
            match=(
                "prepared_query must be a "
                "PreparedRetrievalQuery instance"
            ),
        ):
            service.build(
                prepared_query=prepared_query,  # type: ignore[arg-type]
            )

        retrieve_knowledge.retrieve.assert_not_called()
        context_builder.build.assert_not_called()

    @pytest.mark.parametrize(
        "budget",
        [object(), "budget", 123, True],
    )
    def test_rejects_invalid_override_budget(
        self,
        budget,
    ):
        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        with pytest.raises(
            TypeError,
            match=(
                "budget must be a "
                "GroundingContextBudget instance or None"
            ),
        ):
            service.build(
                prepared_query=make_prepared_query(),
                budget=budget,  # type: ignore[arg-type]
            )

        retrieve_knowledge.retrieve.assert_not_called()
        context_builder.build.assert_not_called()


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


class TestBuildGroundingContextPipeline:
    def test_retrieves_then_builds_context_using_default_budget(self):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        default_budget = make_budget(
            max_tokens=2_000,
            max_blocks=6,
        )

        retrieval_result = RetrievalResult(
            query=canonical_query,
            candidates=(),
        )
        expected_context = make_context(
            query=canonical_query,
        )

        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        retrieve_knowledge.retrieve.return_value = retrieval_result
        context_builder.build.return_value = expected_context

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
            default_budget=default_budget,
        )

        result = service.build(
            prepared_query=prepared_query,
        )

        retrieve_knowledge.retrieve.assert_called_once_with(
            prepared_query=prepared_query,
        )
        context_builder.build.assert_called_once_with(
            retrieval_result=retrieval_result,
            budget=default_budget,
        )
        assert result is expected_context

    def test_uses_explicit_budget_override(self):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        default_budget = make_budget(
            max_tokens=2_000,
            max_blocks=8,
        )
        override_budget = make_budget(
            max_tokens=500,
            max_blocks=3,
        )

        retrieval_result = RetrievalResult(
            query=canonical_query,
            candidates=(),
        )
        expected_context = make_context(
            query=canonical_query,
        )

        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        retrieve_knowledge.retrieve.return_value = retrieval_result
        context_builder.build.return_value = expected_context

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
            default_budget=default_budget,
        )

        result = service.build(
            prepared_query=prepared_query,
            budget=override_budget,
        )

        retrieve_knowledge.retrieve.assert_called_once_with(
            prepared_query=prepared_query,
        )
        context_builder.build.assert_called_once_with(
            retrieval_result=retrieval_result,
            budget=override_budget,
        )
        assert result is expected_context

    def test_explicit_budget_does_not_mutate_default_budget(self):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        default_budget = make_budget(
            max_tokens=2_000,
            max_blocks=8,
        )
        override_budget = make_budget(
            max_tokens=500,
            max_blocks=2,
        )

        retrieval_result = RetrievalResult(
            query=canonical_query,
            candidates=(),
        )

        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        retrieve_knowledge.retrieve.return_value = retrieval_result
        context_builder.build.return_value = make_context(
            query=canonical_query,
        )

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
            default_budget=default_budget,
        )

        service.build(
            prepared_query=prepared_query,
            budget=override_budget,
        )

        assert service.default_budget is default_budget
        assert service.default_budget.max_tokens == 2_000
        assert service.default_budget.max_blocks == 8

    def test_prepared_query_is_not_replaced_by_canonical_query_for_retrieval(
        self,
    ):
        prepared_query = make_prepared_query(
            original_query="How long does my refund take?",
            semantic_query="How long does my refund take?",
            lexical_query="refund duration",
        )
        canonical_query = make_canonical_query(prepared_query)

        retrieval_result = RetrievalResult(
            query=canonical_query,
            candidates=(),
        )

        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        retrieve_knowledge.retrieve.return_value = retrieval_result
        context_builder.build.return_value = make_context(
            query=canonical_query,
        )

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        service.build(
            prepared_query=prepared_query,
        )

        retrieve_knowledge.retrieve.assert_called_once_with(
            prepared_query=prepared_query,
        )


# ---------------------------------------------------------------------------
# Empty retrieval
# ---------------------------------------------------------------------------


class TestBuildGroundingContextEmpty:
    def test_empty_retrieval_still_flows_through_context_builder(self):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        retrieval_result = RetrievalResult(
            query=canonical_query,
            candidates=(),
        )
        empty_context = make_context(
            query=canonical_query,
        )

        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        retrieve_knowledge.retrieve.return_value = retrieval_result
        context_builder.build.return_value = empty_context

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        result = service.build(
            prepared_query=prepared_query,
        )

        retrieve_knowledge.retrieve.assert_called_once_with(
            prepared_query=prepared_query,
        )
        context_builder.build.assert_called_once_with(
            retrieval_result=retrieval_result,
            budget=service.default_budget,
        )
        assert result is empty_context
        assert result.is_empty
        assert result.blocks == ()
        assert result.estimated_token_count == 0

    def test_application_service_does_not_short_circuit_empty_retrieval(
        self,
    ):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        retrieval_result = RetrievalResult(
            query=canonical_query,
            candidates=(),
        )

        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        retrieve_knowledge.retrieve.return_value = retrieval_result
        context_builder.build.return_value = make_context(
            query=canonical_query,
        )

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        service.build(
            prepared_query=prepared_query,
        )

        context_builder.build.assert_called_once_with(
            retrieval_result=retrieval_result,
            budget=service.default_budget,
        )


# ---------------------------------------------------------------------------
# Context result
# ---------------------------------------------------------------------------


class TestBuildGroundingContextResult:
    def test_returns_context_builder_result_unchanged(self):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        block = make_block()

        retrieval_result = RetrievalResult(
            query=canonical_query,
            candidates=(),
        )
        context = make_context(
            query=canonical_query,
            blocks=(block,),
            estimated_token_count=42,
            truncated=True,
        )

        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        retrieve_knowledge.retrieve.return_value = retrieval_result
        context_builder.build.return_value = context

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        result = service.build(
            prepared_query=prepared_query,
        )

        assert result is context
        assert result.blocks == (block,)
        assert result.estimated_token_count == 42
        assert result.truncated is True

    def test_rejects_context_for_different_query(self):
        prepared_query = make_prepared_query(
            original_query="What is the refund policy?",
        )
        canonical_query = make_canonical_query(prepared_query)
        different_query = RetrievalQuery(
            text="Where is my order?",
            filters=prepared_query.filters,
        )

        retrieval_result = RetrievalResult(
            query=canonical_query,
            candidates=(),
        )

        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        retrieve_knowledge.retrieve.return_value = retrieval_result
        context_builder.build.return_value = make_context(
            query=different_query,
        )

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        with pytest.raises(
            RetrievalPipelineError,
            match="different retrieval query",
        ):
            service.build(
                prepared_query=prepared_query,
            )


# ---------------------------------------------------------------------------
# Failure propagation
# ---------------------------------------------------------------------------


class TestBuildGroundingContextFailures:
    def test_retrieval_failure_propagates_unchanged(self):
        prepared_query = make_prepared_query()
        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        error = VectorSearchError(
            "vector retrieval failed",
        )
        retrieve_knowledge.retrieve.side_effect = error

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        with pytest.raises(
            VectorSearchError,
            match="vector retrieval failed",
        ) as exc_info:
            service.build(
                prepared_query=prepared_query,
            )

        assert exc_info.value is error
        context_builder.build.assert_not_called()

    def test_context_builder_failure_propagates_unchanged(self):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        retrieval_result = RetrievalResult(
            query=canonical_query,
            candidates=(),
        )

        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        retrieve_knowledge.retrieve.return_value = retrieval_result

        error = GroundingContextBudgetError(
            "context budget failed",
        )
        context_builder.build.side_effect = error

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        with pytest.raises(
            GroundingContextBudgetError,
            match="context budget failed",
        ) as exc_info:
            service.build(
                prepared_query=prepared_query,
            )

        assert exc_info.value is error

    def test_unexpected_retrieval_exception_is_not_swallowed(self):
        prepared_query = make_prepared_query()
        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        error = RuntimeError(
            "programming defect",
        )
        retrieve_knowledge.retrieve.side_effect = error

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        with pytest.raises(
            RuntimeError,
            match="programming defect",
        ) as exc_info:
            service.build(
                prepared_query=prepared_query,
            )

        assert exc_info.value is error
        context_builder.build.assert_not_called()

    def test_unexpected_context_builder_exception_is_not_swallowed(self):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        retrieval_result = RetrievalResult(
            query=canonical_query,
            candidates=(),
        )

        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        retrieve_knowledge.retrieve.return_value = retrieval_result

        error = RuntimeError(
            "builder programming defect",
        )
        context_builder.build.side_effect = error

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        with pytest.raises(
            RuntimeError,
            match="builder programming defect",
        ) as exc_info:
            service.build(
                prepared_query=prepared_query,
            )

        assert exc_info.value is error


# ---------------------------------------------------------------------------
# Call ordering / object identity
# ---------------------------------------------------------------------------


class TestBuildGroundingContextCallOrdering:
    def test_context_builder_receives_exact_retrieval_result(self):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        retrieval_result = RetrievalResult(
            query=canonical_query,
            candidates=(),
        )

        retrieve_knowledge = make_retrieve_knowledge()
        context_builder = make_context_builder()
        retrieve_knowledge.retrieve.return_value = retrieval_result
        context_builder.build.return_value = make_context(
            query=canonical_query,
        )

        service = make_service(
            retrieve_knowledge=retrieve_knowledge,
            context_builder=context_builder,
        )

        service.build(
            prepared_query=prepared_query,
        )

        passed_result = (
            context_builder
            .build
            .call_args
            .kwargs["retrieval_result"]
        )

        assert passed_result is retrieval_result
