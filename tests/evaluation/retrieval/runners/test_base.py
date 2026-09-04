from __future__ import annotations

from types import MappingProxyType

import pytest

from evaluation.retrieval.runners.base import (
    BaseRetrievalEvaluationRunner,
    EvaluationRetrievalContext,
    RetrievalRunnerContractError,
    RetrievalRunnerExecutionError,
    RetrievalRunnerInputError,
)
from packages.knowledge.retrieval.models import (
    RetrievalFilters,
    RetrievalQuery,
    RetrievalResult,
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
from evaluation.retrieval.models import (
    RetrievalEvaluationCase,
    RetrievalEvaluationInput,
)


def make_query_preparation_service(
) -> RetrievalQueryPreparationService:
    return RetrievalQueryPreparationService(
        builder=DeterministicRetrievalQueryBuilder(),
    )


def make_case(
    *,
    case_id: str = "refund_001",
    query: str = "How long does my refund take?",
    intent_key: str | None = "refund_request",
    retrieval_input:
        RetrievalEvaluationInput | None = None,
    metadata: dict[str, str] | None = None,
) -> RetrievalEvaluationCase:
    return RetrievalEvaluationCase(
        case_id=case_id,
        query=query,
        intent_key=intent_key,
        expected_document_titles=(
            "Refund Policy",
        ),
        retrieval_input=(
            retrieval_input
            or RetrievalEvaluationInput()
        ),
        metadata=metadata or {},
    )


def make_result(
    *,
    query: str = "How long does my refund take?",
) -> RetrievalResult:
    return RetrievalResult(
        query=RetrievalQuery(
            text=query,
        ),
        candidates=(),
    )


class RecordingRunner(
    BaseRetrievalEvaluationRunner
):
    def __init__(
        self,
        *,
        query_preparation_service:
            RetrievalQueryPreparationService,
        result: RetrievalResult | None = None,
    ) -> None:
        super().__init__(
            query_preparation_service=(
                query_preparation_service
            )
        )

        self.result = (
            result
            if result is not None
            else make_result()
        )

        self.prepared_queries: list[
            PreparedRetrievalQuery
        ] = []

    @property
    def method(self) -> str:
        return "test"

    def _execute_retrieval(
        self,
        *,
        prepared_query: PreparedRetrievalQuery,
    ) -> RetrievalResult:
        self.prepared_queries.append(
            prepared_query
        )

        return self.result


class RaisingRunner(
    BaseRetrievalEvaluationRunner
):
    @property
    def method(self) -> str:
        return "raising"

    def _execute_retrieval(
        self,
        *,
        prepared_query: PreparedRetrievalQuery,
    ) -> RetrievalResult:
        raise RuntimeError(
            "retrieval backend unavailable"
        )


class InvalidResultRunner(
    BaseRetrievalEvaluationRunner
):
    @property
    def method(self) -> str:
        return "invalid"

    def _execute_retrieval(
        self,
        *,
        prepared_query: PreparedRetrievalQuery,
    ):
        return object()


class TestEvaluationRetrievalContext:
    def test_accepts_valid_context(
        self,
    ) -> None:
        filters = RetrievalFilters()

        context = EvaluationRetrievalContext(
            customer_message=(
                "How long does my refund take?"
            ),
            intent_key="refund_request",
            entities={
                "issue_type": "refund delay",
            },
            filters=filters,
            conversation_context=(
                "The customer previously asked "
                "about a completed refund."
            ),
        )

        assert context.customer_message == (
            "How long does my refund take?"
        )
        assert context.intent_key == (
            "refund_request"
        )
        assert context.entities == {
            "issue_type": "refund delay",
        }
        assert context.filters is filters
        assert context.conversation_context == (
            "The customer previously asked "
            "about a completed refund."
        )

    def test_normalizes_strings(
        self,
    ) -> None:
        context = EvaluationRetrievalContext(
            customer_message="  Refund timing?  ",
            intent_key="  refund_request  ",
            entities={
                " issue_type ": " refund delay ",
            },
            filters=RetrievalFilters(),
            conversation_context=(
                "  Previous refund discussion.  "
            ),
        )

        assert context.customer_message == (
            "Refund timing?"
        )
        assert context.intent_key == (
            "refund_request"
        )
        assert context.entities == {
            "issue_type": "refund delay",
        }
        assert context.conversation_context == (
            "Previous refund discussion."
        )

    def test_empty_optional_strings_become_none(
        self,
    ) -> None:
        context = EvaluationRetrievalContext(
            customer_message="Refund timing?",
            intent_key="   ",
            entities={},
            filters=RetrievalFilters(),
            conversation_context="   ",
        )

        assert context.intent_key is None
        assert context.conversation_context is None

    def test_drops_empty_entity_entries(
        self,
    ) -> None:
        context = EvaluationRetrievalContext(
            customer_message="Refund timing?",
            intent_key="refund_request",
            entities={
                "issue_type": "refund delay",
                "empty_value": "   ",
                "   ": "ignored",
            },
            filters=RetrievalFilters(),
        )

        assert dict(context.entities) == {
            "issue_type": "refund delay",
        }

    def test_entities_are_immutable(
        self,
    ) -> None:
        context = EvaluationRetrievalContext(
            customer_message="Refund timing?",
            intent_key="refund_request",
            entities={
                "issue_type": "refund delay",
            },
            filters=RetrievalFilters(),
        )

        assert isinstance(
            context.entities,
            MappingProxyType,
        )

        with pytest.raises(TypeError):
            context.entities[
                "issue_type"
            ] = "changed"  # type: ignore[index]

    def test_entities_are_defensively_copied(
        self,
    ) -> None:
        source = {
            "issue_type": "refund delay",
        }

        context = EvaluationRetrievalContext(
            customer_message="Refund timing?",
            intent_key="refund_request",
            entities=source,
            filters=RetrievalFilters(),
        )

        source["issue_type"] = "changed"

        assert context.entities[
            "issue_type"
        ] == "refund delay"

    def test_rejects_empty_customer_message(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalRunnerInputError,
            match=(
                "customer_message must not be empty"
            ),
        ):
            EvaluationRetrievalContext(
                customer_message="   ",
                intent_key=None,
                entities={},
                filters=RetrievalFilters(),
            )

    def test_rejects_non_string_customer_message(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalRunnerInputError,
            match=(
                "customer_message must be a string"
            ),
        ):
            EvaluationRetrievalContext(
                customer_message=123,  # type: ignore[arg-type]
                intent_key=None,
                entities={},
                filters=RetrievalFilters(),
            )

    def test_rejects_non_string_intent(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalRunnerInputError,
            match=(
                "intent_key must be a string or None"
            ),
        ):
            EvaluationRetrievalContext(
                customer_message="Refund timing?",
                intent_key=123,  # type: ignore[arg-type]
                entities={},
                filters=RetrievalFilters(),
            )

    def test_rejects_non_mapping_entities(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalRunnerInputError,
            match="entities must be a mapping",
        ):
            EvaluationRetrievalContext(
                customer_message="Refund timing?",
                intent_key=None,
                entities=[],  # type: ignore[arg-type]
                filters=RetrievalFilters(),
            )

    @pytest.mark.parametrize(
        "entities",
        [
            {
                123: "refund",
            },
            {
                "issue_type": 123,
            },
        ],
    )
    def test_rejects_non_string_entity_entries(
        self,
        entities: object,
    ) -> None:
        with pytest.raises(
            RetrievalRunnerInputError,
            match=(
                "entities must contain string keys "
                "and string values"
            ),
        ):
            EvaluationRetrievalContext(
                customer_message="Refund timing?",
                intent_key=None,
                entities=entities,  # type: ignore[arg-type]
                filters=RetrievalFilters(),
            )

    def test_rejects_invalid_filters(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalRunnerInputError,
            match=(
                "filters must be a "
                "RetrievalFilters instance"
            ),
        ):
            EvaluationRetrievalContext(
                customer_message="Refund timing?",
                intent_key=None,
                entities={},
                filters=object(),  # type: ignore[arg-type]
            )

    def test_rejects_invalid_conversation_context(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalRunnerInputError,
            match=(
                "conversation_context must be "
                "a string or None"
            ),
        ):
            EvaluationRetrievalContext(
                customer_message="Refund timing?",
                intent_key=None,
                entities={},
                filters=RetrievalFilters(),
                conversation_context=123,  # type: ignore[arg-type]
            )


class TestBaseRunnerContextExtraction:
    def test_builds_context_from_case(
        self,
    ) -> None:
        filters = RetrievalFilters()

        case = make_case(
            retrieval_input=RetrievalEvaluationInput(
                entities={
                    "issue_type": "refund delay",
                },
                filters=filters,
                conversation_context=(
                    "Customer already requested "
                    "the refund."
                ),
            )
        )

        runner = RecordingRunner(
            query_preparation_service=(
                make_query_preparation_service()
            )
        )

        context = (
            runner._build_evaluation_context(
                case=case,
            )
        )

        assert context.customer_message == (
            case.query
        )
        assert context.intent_key == (
            case.intent_key
        )
        assert context.entities == {
            "issue_type": "refund delay",
        }
        assert context.filters is filters
        assert context.conversation_context == (
            "Customer already requested "
            "the refund."
        )

    def test_ground_truth_does_not_enter_context(
        self,
    ) -> None:
        case = RetrievalEvaluationCase(
            case_id="no_leakage_001",
            query="Where is my refund?",
            intent_key="refund_request",
            expected_document_titles=(
                "SECRET CORRECT DOCUMENT",
            ),
            expected_section_titles=(
                "SECRET CORRECT SECTION",
            ),
            expected_topics=(
                "secret correct topic",
            ),
        )

        runner = RecordingRunner(
            query_preparation_service=(
                make_query_preparation_service()
            )
        )

        context = (
            runner._build_evaluation_context(
                case=case,
            )
        )

        serialized_input = " ".join(
            [
                context.customer_message,
                context.intent_key or "",
                " ".join(
                    context.entities.values()
                ),
                (
                    context.conversation_context
                    or ""
                ),
            ]
        ).casefold()

        assert (
            "secret correct document"
            not in serialized_input
        )
        assert (
            "secret correct section"
            not in serialized_input
        )
        assert (
            "secret correct topic"
            not in serialized_input
        )

    def test_defaults_to_empty_entities_and_filters(
        self,
    ) -> None:
        runner = RecordingRunner(
            query_preparation_service=(
                make_query_preparation_service()
            )
        )

        context = (
            runner._build_evaluation_context(
                case=make_case()
            )
        )

        assert dict(
            context.entities
        ) == {}
        assert context.filters == (
            RetrievalFilters()
        )
        assert context.conversation_context is None
        
    def test_retrieval_input_rejects_invalid_entities(self) -> None:
        with pytest.raises(
            TypeError,
            match="entity keys and values must be strings",
        ):
            RetrievalEvaluationInput(
                entities={
                    "issue_type": 123,
                }
            )


    def test_retrieval_input_rejects_invalid_filters(self) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "filters must be a "
                "RetrievalFilters instance"
            ),
        ):
            RetrievalEvaluationInput(
                filters={},  # type: ignore[arg-type]
            )


    def test_retrieval_input_normalizes_context(self) -> None:
        value = RetrievalEvaluationInput(
            conversation_context=(
                "  Previous refund discussion.  "
            )
        )

        assert value.conversation_context == (
            "Previous refund discussion."
        )


    def test_retrieval_input_entities_are_immutable(self) -> None:
        source = {
            "issue_type": "refund delay",
        }

        value = RetrievalEvaluationInput(
            entities=source
        )

        source["issue_type"] = "changed"

        assert value.entities[
            "issue_type"
        ] == "refund delay"

        with pytest.raises(TypeError):
            value.entities[
                "issue_type"
            ] = "changed"  # type: ignore[index]


class TestQueryPreparation:
    def test_uses_real_query_preparation_service(
        self,
    ) -> None:
        runner = RecordingRunner(
            query_preparation_service=(
                make_query_preparation_service()
            )
        )

        case = make_case(
            query=(
                "How long does my refund take?"
            ),
            retrieval_input=RetrievalEvaluationInput(
                entities={
                    "issue_type": (
                        "refund processing delay"
                    ),
                }
            )
        )

        runner.retrieve(
            case=case
        )

        assert len(
            runner.prepared_queries
        ) == 1

        prepared = (
            runner.prepared_queries[0]
        )

        assert isinstance(
            prepared,
            PreparedRetrievalQuery,
        )

        assert prepared.original_query == (
            "How long does my refund take?"
        )

        assert prepared.semantic_query == (
            "How long does my refund take?"
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

    def test_ground_truth_does_not_enter_prepared_query(
        self,
    ) -> None:
        runner = RecordingRunner(
            query_preparation_service=(
                make_query_preparation_service()
            )
        )

        case = RetrievalEvaluationCase(
            case_id="no_leakage_002",
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

        prepared = (
            runner.prepared_queries[0]
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
            "secret timeline section"
            not in searchable_text
        )
        assert (
            "secret refund topic"
            not in searchable_text
        )


class TestRetrievalExecution:
    def test_returns_strategy_result(
        self,
    ) -> None:
        expected = make_result()

        runner = RecordingRunner(
            query_preparation_service=(
                make_query_preparation_service()
            ),
            result=expected,
        )

        result = runner.retrieve(
            case=make_case()
        )

        assert result is expected

    def test_passes_prepared_query_to_strategy(
        self,
    ) -> None:
        runner = RecordingRunner(
            query_preparation_service=(
                make_query_preparation_service()
            )
        )

        runner.retrieve(
            case=make_case(
                query="Refund processing delay",
            )
        )

        assert len(
            runner.prepared_queries
        ) == 1

        prepared = (
            runner.prepared_queries[0]
        )

        assert prepared.original_query == (
            "Refund processing delay"
        )

    def test_wraps_unexpected_strategy_failure(
        self,
    ) -> None:
        runner = RaisingRunner(
            query_preparation_service=(
                make_query_preparation_service()
            )
        )

        with pytest.raises(
            RetrievalRunnerExecutionError,
            match=(
                "Retrieval evaluation runner "
                "failed for case 'refund_001' "
                "using method 'raising'"
            ),
        ) as exc_info:
            runner.retrieve(
                case=make_case()
            )

        assert isinstance(
            exc_info.value.__cause__,
            RuntimeError,
        )

    def test_rejects_invalid_strategy_result(
        self,
    ) -> None:
        runner = InvalidResultRunner(
            query_preparation_service=(
                make_query_preparation_service()
            )
        )

        with pytest.raises(
            RetrievalRunnerContractError,
            match=(
                "_execute_retrieval must return "
                "a RetrievalResult instance"
            ),
        ):
            runner.retrieve(
                case=make_case()
            )

    def test_rejects_invalid_case(
        self,
    ) -> None:
        runner = RecordingRunner(
            query_preparation_service=(
                make_query_preparation_service()
            )
        )

        with pytest.raises(
            RetrievalRunnerInputError,
            match=(
                "case must be a "
                "RetrievalEvaluationCase instance"
            ),
        ):
            runner.retrieve(
                case=object()  # type: ignore[arg-type]
            )