"""
Unit tests for packages.ai.orchestration.orchestrator.

Scope
-----
AIOrchestrator owns workflow coordination only.

The suite therefore verifies:

    customer message
        -> intent classification
        -> deterministic decision
        -> optional AnswerService execution
        -> orchestration-state transitions
        -> observer lifecycle events
        -> conversion of known operational failures into PipelineError

The suite deliberately does NOT test:

    - intent classification internals;
    - decision policy rules;
    - vector / lexical retrieval;
    - embeddings;
    - reranking;
    - prompt construction;
    - grounded generation internals;
    - persistence;
    - SQLAlchemy;
    - retries;
    - business actions.

Those components have their own unit/integration suites.

Testing philosophy
------------------
Collaborators are replaced with controlled test doubles so these tests remain:

    - deterministic;
    - fast;
    - network-free;
    - database-free;
    - focused on orchestration semantics.

Known operational failures should become FAILED AIState snapshots.

Unexpected programming defects should propagate rather than being hidden
behind generic customer-facing pipeline errors.
"""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, call

import pytest

from packages.ai.decision.engine import DecisionEngine
from packages.ai.decision.schemas import (
    DecisionReasonCode,
    DecisionResult,
    DecisionType,
)
from packages.ai.generation.generator import (
    GroundedGenerationError,
    GroundedGenerationProviderError,
    GroundedGenerationTimeoutError,
    InvalidGroundedGenerationResponseError,
)
from packages.ai.generation.models import (
    GroundedGenerationResult,
    GroundingStatus,
)
from packages.ai.intent.classifier import (
    IntentClassificationError,
    IntentClassificationProviderError,
    IntentClassificationTimeoutError,
    IntentClassifier,
    InvalidIntentInputError,
    InvalidIntentResponseError,
)
from packages.ai.intent.schemas import IntentResult
from packages.ai.intent.taxonomy import IntentType
from packages.ai.orchestration.orchestrator import (
    AIOrchestrator,
    AIOrchestratorConfig,
    NullOrchestrationObserver,
)
from packages.ai.orchestration.state import (
    AIState,
    EvidenceSourceType,
    PipelineError,
    PipelineStage,
    RetrievedEvidence,
)
from packages.application.ai.answer_service import (
    AnswerService,
    AnswerServiceError,
    AnswerServiceRequest,
    AnswerServiceResult,
    InvalidRetrievalDecisionError,
    UnsupportedAnswerDecisionError,
    UnsupportedRetrievalKindError,
)


# ===========================================================================
# Test doubles
# ===========================================================================


class StubAnswerService(AnswerService):
    """
    Minimal typed AnswerService double.

    AIOrchestrator validates AnswerService using isinstance(), so using a
    subclass keeps that production invariant active while avoiding
    construction of the real retrieval/generation object graph.

    The real AnswerService has its own dedicated unit tests.
    """

    def __init__(self) -> None:
        self.answer = MagicMock()


class RecordingObserver:
    """
    Observer double satisfying OrchestrationObserver structurally.

    Individual methods remain MagicMocks so lifecycle calls can be asserted
    without coupling the test suite to a logging or telemetry implementation.
    """

    def __init__(self) -> None:
        self.stage_started = MagicMock()
        self.stage_completed = MagicMock()
        self.stage_failed = MagicMock()


# ===========================================================================
# Helpers
# ===========================================================================


def make_ids() -> dict[str, uuid.UUID]:
    return {
        "ai_run_id": uuid.uuid4(),
        "trace_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "trigger_message_id": uuid.uuid4(),
    }


def extract_pipeline_error(
    state: AIState,
) -> PipelineError:
    assert state.stage is PipelineStage.FAILED
    assert state.errors, (
        "FAILED AIState must contain at least one PipelineError"
    )
    return state.errors[-1]


def make_intent(
    *,
    intent: IntentType = IntentType.GENERAL_QUESTION,
) -> IntentResult:
    return IntentResult(
        intent=intent,
        confidence=0.95,
        needs_clarification=False,
        reason_summary="Supported customer request.",
    )


def make_terminal_answer_decision() -> DecisionResult:
    """
    Decision that intentionally stops orchestration at DECISION_MADE.

    ANSWER is useful as the default decision for tests that care only about
    classification/decision coordination and should not enter retrieval.
    """

    return DecisionResult(
        decision=DecisionType.ANSWER,
        reason_code=(
            DecisionReasonCode.DIRECT_INFORMATIONAL_RESPONSE
        ),
        reason_summary=(
            "The workflow can answer without information retrieval."
        ),
        confidence=0.95,
    )


def make_knowledge_retrieval_decision() -> DecisionResult:
    return DecisionResult(
        decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=(
            DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED
        ),
        reason_summary=(
            "Grounded knowledge retrieval is required."
        ),
        confidence=0.95,
        metadata={
            "retrieval_kind": "knowledge",
        },
    )


def make_operational_retrieval_decision() -> DecisionResult:
    return DecisionResult(
        decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=(
            DecisionReasonCode.OPERATIONAL_LOOKUP_REQUIRED
        ),
        reason_summary=(
            "Runtime operational information is required."
        ),
        confidence=0.95,
        metadata={
            "retrieval_kind": "operational",
        },
    )


def make_ask_clarification_decision() -> DecisionResult:
    return DecisionResult(
        decision=DecisionType.ASK_CLARIFICATION,
        reason_code=(
            DecisionReasonCode.MISSING_REQUIRED_INFORMATION
        ),
        reason_summary=(
            "Additional information is required."
        ),
        confidence=1.0,
        required_information=("order_id",),
    )


def make_escalation_decision() -> DecisionResult:
    return DecisionResult(
        decision=DecisionType.ESCALATE,
        reason_code=(
            DecisionReasonCode.HUMAN_APPROVAL_REQUIRED
        ),
        reason_summary=(
            "Human review is required."
        ),
        confidence=1.0,
    )


def make_evidence() -> tuple[RetrievedEvidence, ...]:
    return (
        RetrievedEvidence(
            source_type=EvidenceSourceType.KNOWLEDGE,
            source_id="chunk-refund-policy-001",
            title="Refund Policy",
            section="Processing Time",
            content=(
                "Approved refunds are processed within "
                "five business days."
            ),
            relevance_score=0.93,
            metadata={
                "document_id": "refund-policy",
                "chunk_index": 0,
            },
        ),
    )


def make_grounded_generation() -> GroundedGenerationResult:
    return GroundedGenerationResult(
        answer=(
            "Approved refunds are processed within "
            "five business days."
        ),
        grounding_status=GroundingStatus.GROUNDED,
        citations=(),
    )


def make_insufficient_generation() -> GroundedGenerationResult:
    return GroundedGenerationResult(
        answer=(
            "I do not have enough verified information "
            "to answer that accurately."
        ),
        grounding_status=(
            GroundingStatus.INSUFFICIENT_EVIDENCE
        ),
        citations=(),
    )


def make_answer_result() -> AnswerServiceResult:
    return AnswerServiceResult(
        evidence=make_evidence(),
        generation=make_grounded_generation(),
    )


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def intent_classifier() -> MagicMock:
    return MagicMock(
        spec=IntentClassifier,
    )


@pytest.fixture
def decision_engine() -> MagicMock:
    return MagicMock(
        spec=DecisionEngine,
    )


@pytest.fixture
def answer_service() -> StubAnswerService:
    return StubAnswerService()


@pytest.fixture
def observer() -> RecordingObserver:
    return RecordingObserver()


@pytest.fixture
def orchestrator(
    intent_classifier,
    decision_engine,
    observer,
) -> AIOrchestrator:
    """
    Legacy-compatible orchestrator without AnswerService.

    Use this for tests whose decision deliberately does not require retrieval.
    """

    return AIOrchestrator(
        intent_classifier=intent_classifier,
        decision_engine=decision_engine,
        observer=observer,
    )


@pytest.fixture
def grounded_orchestrator(
    intent_classifier,
    decision_engine,
    answer_service,
    observer,
) -> AIOrchestrator:
    """
    Fully composed orchestration boundary for retrieval-path tests.
    """

    return AIOrchestrator(
        intent_classifier=intent_classifier,
        decision_engine=decision_engine,
        answer_service=answer_service,
        observer=observer,
    )


# ===========================================================================
# Constructor
# ===========================================================================


class TestConstructor:

    def test_rejects_none_intent_classifier(
        self,
        decision_engine,
    ):
        with pytest.raises(
            TypeError,
            match="intent_classifier",
        ):
            AIOrchestrator(
                intent_classifier=None,
                decision_engine=decision_engine,
            )

    def test_rejects_none_decision_engine(
        self,
        intent_classifier,
    ):
        with pytest.raises(
            TypeError,
            match="decision_engine",
        ):
            AIOrchestrator(
                intent_classifier=intent_classifier,
                decision_engine=None,
            )

    def test_answer_service_is_optional(
        self,
        intent_classifier,
        decision_engine,
    ):
        orchestrator = AIOrchestrator(
            intent_classifier=intent_classifier,
            decision_engine=decision_engine,
        )

        assert orchestrator._answer_service is None

    def test_rejects_invalid_answer_service(
        self,
        intent_classifier,
        decision_engine,
    ):
        with pytest.raises(
            TypeError,
            match="answer_service",
        ):
            AIOrchestrator(
                intent_classifier=intent_classifier,
                decision_engine=decision_engine,
                answer_service=object(),
            )

    def test_uses_supplied_answer_service(
        self,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        orchestrator = AIOrchestrator(
            intent_classifier=intent_classifier,
            decision_engine=decision_engine,
            answer_service=answer_service,
        )

        assert (
            orchestrator._answer_service
            is answer_service
        )

    def test_default_observer_is_null_observer(
        self,
        intent_classifier,
        decision_engine,
    ):
        orchestrator = AIOrchestrator(
            intent_classifier=intent_classifier,
            decision_engine=decision_engine,
        )

        assert isinstance(
            orchestrator._observer,
            NullOrchestrationObserver,
        )

    def test_rejects_invalid_config(
        self,
        intent_classifier,
        decision_engine,
    ):
        with pytest.raises(
            TypeError,
            match="config",
        ):
            AIOrchestrator(
                intent_classifier=intent_classifier,
                decision_engine=decision_engine,
                config=object(),
            )


# ===========================================================================
# Configuration
# ===========================================================================


class TestAIOrchestratorConfig:

    def test_default_pipeline_version_is_v1(self):
        assert (
            AIOrchestratorConfig().pipeline_version
            == "v1"
        )

    def test_accepts_custom_pipeline_version(self):
        config = AIOrchestratorConfig(
            pipeline_version="v2",
        )

        assert config.pipeline_version == "v2"

    def test_pipeline_version_is_normalized(self):
        config = AIOrchestratorConfig(
            pipeline_version="  v7-experimental  ",
        )

        assert (
            config.pipeline_version
            == "v7-experimental"
        )

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "\n",
            "\t",
        ],
    )
    def test_rejects_blank_pipeline_version(
        self,
        value,
    ):
        with pytest.raises(
            ValueError,
            match="pipeline_version",
        ):
            AIOrchestratorConfig(
                pipeline_version=value,
            )

    def test_rejects_non_string_pipeline_version(self):
        with pytest.raises(
            TypeError,
            match="pipeline_version",
        ):
            AIOrchestratorConfig(
                pipeline_version=123,
            )

    def test_config_is_frozen(self):
        config = AIOrchestratorConfig()

        with pytest.raises(FrozenInstanceError):
            config.pipeline_version = "v9"


# ===========================================================================
# Initial state / request propagation
# ===========================================================================


class TestInitialState:

    def test_identifiers_are_propagated(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        ids = make_ids()

        state = orchestrator.process_message(
            **ids,
            customer_message="hello",
        )

        assert state.ai_run_id == ids["ai_run_id"]
        assert state.trace_id == ids["trace_id"]
        assert (
            state.conversation_id
            == ids["conversation_id"]
        )
        assert (
            state.trigger_message_id
            == ids["trigger_message_id"]
        )

    def test_customer_message_is_preserved(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="  hello customer support  ",
        )

        # AIState owns normalization.
        assert (
            state.customer_message
            == "hello customer support"
        )

    def test_default_pipeline_version_is_recorded(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        assert (
            state.metadata["pipeline_version"]
            == "v1"
        )

    def test_custom_pipeline_version_is_recorded(
        self,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        orchestrator = AIOrchestrator(
            intent_classifier=intent_classifier,
            decision_engine=decision_engine,
            config=AIOrchestratorConfig(
                pipeline_version="v42",
            ),
        )

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        assert (
            state.metadata["pipeline_version"]
            == "v42"
        )


# ===========================================================================
# Intent classification
# ===========================================================================


class TestIntentClassification:

    def test_classifier_receives_message_and_context(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        orchestrator.process_message(
            **make_ids(),
            customer_message="Where is my refund?",
            conversation_context=(
                "The customer previously asked about "
                "refund processing."
            ),
        )

        intent_classifier.classify.assert_called_once_with(
            customer_message="Where is my refund?",
            conversation_context=(
                "The customer previously asked about "
                "refund processing."
            ),
        )

    def test_context_defaults_to_none(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        intent_classifier.classify.assert_called_once_with(
            customer_message="hello",
            conversation_context=None,
        )

    def test_intent_result_is_written_to_state(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent = make_intent()

        intent_classifier.classify.return_value = intent
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        assert state.intent_result is intent


# ===========================================================================
# Intent failure mapping
# ===========================================================================


INTENT_FAILURE_CASES = [
    pytest.param(
        InvalidIntentInputError("bad input"),
        "INTENT_INVALID_INPUT",
        False,
        id="invalid-input",
    ),
    pytest.param(
        IntentClassificationTimeoutError("timeout"),
        "INTENT_PROVIDER_TIMEOUT",
        True,
        id="provider-timeout",
    ),
    pytest.param(
        InvalidIntentResponseError("invalid"),
        "INTENT_INVALID_RESPONSE",
        True,
        id="invalid-response",
    ),
    pytest.param(
        IntentClassificationProviderError("provider"),
        "INTENT_PROVIDER_FAILURE",
        True,
        id="provider-failure",
    ),
    pytest.param(
        IntentClassificationError("generic"),
        "INTENT_CLASSIFICATION_FAILURE",
        False,
        id="generic-classification-failure",
    ),
]


class TestIntentFailures:

    @pytest.mark.parametrize(
        "exception, expected_code, expected_retryable",
        INTENT_FAILURE_CASES,
    )
    def test_known_failure_maps_to_pipeline_error(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
        exception,
        expected_code,
        expected_retryable,
    ):
        intent_classifier.classify.side_effect = exception

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        error = extract_pipeline_error(state)

        assert error.code == expected_code
        assert (
            error.retryable
            is expected_retryable
        )
        assert (
            error.stage
            is PipelineStage.INTENT_CLASSIFIED
        )

        decision_engine.decide.assert_not_called()

    def test_failed_intent_has_no_intent_result(
        self,
        orchestrator,
        intent_classifier,
    ):
        intent_classifier.classify.side_effect = (
            InvalidIntentResponseError("invalid")
        )

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        assert state.intent_result is None
        assert state.decision_result is None

    def test_unexpected_classifier_exception_propagates(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.side_effect = RuntimeError(
            "programming defect"
        )

        with pytest.raises(
            RuntimeError,
            match="programming defect",
        ):
            orchestrator.process_message(
                **make_ids(),
                customer_message="hello",
            )

        decision_engine.decide.assert_not_called()


# ===========================================================================
# Decision stage
# ===========================================================================


class TestDecisionStage:

    def test_decision_engine_receives_classifier_result(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent = make_intent()

        intent_classifier.classify.return_value = intent
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        decision_engine.decide.assert_called_once_with(
            intent_result=intent,
        )

    def test_terminal_decision_is_written_to_state(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent = make_intent()
        decision = make_terminal_answer_decision()

        intent_classifier.classify.return_value = intent
        decision_engine.decide.return_value = decision

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        assert state.intent_result is intent
        assert state.decision_result is decision
        assert (
            state.stage
            is PipelineStage.DECISION_MADE
        )

    @pytest.mark.parametrize(
        "decision",
        [
            pytest.param(
                make_terminal_answer_decision(),
                id="answer",
            ),
            pytest.param(
                make_ask_clarification_decision(),
                id="clarification",
            ),
            pytest.param(
                make_escalation_decision(),
                id="escalation",
            ),
        ],
    )
    def test_non_retrieval_decisions_stop_at_decision_made(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
        decision,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = decision

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        assert (
            state.stage
            is PipelineStage.DECISION_MADE
        )

        answer_service.answer.assert_not_called()

    @pytest.mark.parametrize(
        "exception",
        [
            TypeError("bad decision shape"),
            ValueError("unknown intent"),
        ],
    )
    def test_known_decision_failure_becomes_pipeline_error(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
        exception,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.side_effect = exception

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        error = extract_pipeline_error(state)

        assert error.code == "DECISION_ENGINE_FAILURE"
        assert error.retryable is False
        assert (
            error.stage
            is PipelineStage.DECISION_MADE
        )
        assert (
            error.metadata["exception_type"]
            == type(exception).__name__
        )

        # Classification succeeded before decision failed.
        assert state.intent_result is not None

    def test_unexpected_decision_exception_propagates(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.side_effect = KeyError(
            "programming defect"
        )

        with pytest.raises(KeyError):
            orchestrator.process_message(
                **make_ids(),
                customer_message="hello",
            )


# ===========================================================================
# Invariant guards
# ===========================================================================


class TestInvariantGuards:

    def test_decision_stage_rejects_missing_intent(
        self,
        orchestrator,
        decision_engine,
    ):
        state = AIState(
            **make_ids(),
            customer_message="hello",
            conversation_context=None,
            metadata={},
        )

        with pytest.raises(
            RuntimeError,
            match="intent_result",
        ):
            orchestrator._make_decision(state)

        decision_engine.decide.assert_not_called()

    def test_decision_execution_rejects_missing_decision(
        self,
        orchestrator,
    ):
        state = AIState(
            **make_ids(),
            customer_message="hello",
            conversation_context=None,
            metadata={},
        )

        state = state.with_intent(
            make_intent()
        )

        with pytest.raises(
            RuntimeError,
            match="decision_result",
        ):
            orchestrator._execute_decision(state)


# ===========================================================================
# Knowledge retrieval + grounded generation
# ===========================================================================


class TestKnowledgeRetrieval:

    def test_retrieval_decision_calls_answer_service_once(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        intent = make_intent(
            intent=IntentType.REFUND_REQUEST,
        )
        decision = make_knowledge_retrieval_decision()

        intent_classifier.classify.return_value = intent
        decision_engine.decide.return_value = decision
        answer_service.answer.return_value = (
            make_answer_result()
        )

        grounded_orchestrator.process_message(
            **make_ids(),
            customer_message=(
                "How long does an approved refund take?"
            ),
        )

        answer_service.answer.assert_called_once()

    def test_answer_service_receives_typed_request(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        intent = make_intent(
            intent=IntentType.REFUND_REQUEST,
        )
        decision = make_knowledge_retrieval_decision()

        intent_classifier.classify.return_value = intent
        decision_engine.decide.return_value = decision
        answer_service.answer.return_value = (
            make_answer_result()
        )

        grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="How long does my refund take?",
            conversation_context=(
                "The customer previously requested a refund."
            ),
        )

        request = (
            answer_service
            .answer
            .call_args
            .kwargs["request"]
        )

        assert isinstance(
            request,
            AnswerServiceRequest,
        )

        assert (
            request.customer_message
            == "How long does my refund take?"
        )
        assert request.intent_result is intent
        assert request.decision_result is decision
        assert request.conversation_context == (
            "The customer previously requested a refund."
        )

    def test_retrieved_evidence_is_written_to_state(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        evidence = make_evidence()

        intent_classifier.classify.return_value = (
            make_intent(
                intent=IntentType.REFUND_REQUEST,
            )
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )
        answer_service.answer.return_value = (
            AnswerServiceResult(
                evidence=evidence,
                generation=make_grounded_generation(),
            )
        )

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="Explain refund timing.",
        )

        assert state.retrieved_evidence == evidence

    def test_generated_response_is_written_to_state(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        result = make_answer_result()

        intent_classifier.classify.return_value = (
            make_intent(
                intent=IntentType.REFUND_REQUEST,
            )
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )
        answer_service.answer.return_value = result

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="Explain refund timing.",
        )

        assert (
            state.generated_response
            == result.generation.answer
        )

    def test_successful_grounded_path_finishes_at_response_generated(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        intent_classifier.classify.return_value = (
            make_intent(
                intent=IntentType.REFUND_REQUEST,
            )
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )
        answer_service.answer.return_value = (
            make_answer_result()
        )

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="Explain refund timing.",
        )

        assert (
            state.stage
            is PipelineStage.RESPONSE_GENERATED
        )
        assert state.intent_result is not None
        assert state.decision_result is not None
        assert state.retrieved_evidence
        assert state.generated_response is not None
        assert state.errors == ()

    def test_empty_evidence_is_valid_semantic_result(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        generation = make_insufficient_generation()

        intent_classifier.classify.return_value = (
            make_intent(
                intent=IntentType.GENERAL_QUESTION,
            )
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )

        answer_service.answer.return_value = (
            AnswerServiceResult(
                evidence=(),
                generation=generation,
            )
        )

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message=(
                "What is the policy for an unsupported case?"
            ),
        )

        assert state.retrieved_evidence == ()
        assert (
            state.generated_response
            == generation.answer
        )
        assert (
            state.stage
            is PipelineStage.RESPONSE_GENERATED
        )
        assert state.errors == ()


# ===========================================================================
# Missing AnswerService
# ===========================================================================


class TestMissingAnswerService:

    def test_retrieval_without_answer_service_fails_cleanly(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent(
                intent=IntentType.REFUND_REQUEST,
            )
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="What is the refund policy?",
        )

        error = extract_pipeline_error(state)

        assert (
            error.code
            == "ANSWER_SERVICE_UNAVAILABLE"
        )
        assert (
            error.stage
            is PipelineStage.RETRIEVAL_COMPLETED
        )
        assert error.retryable is False

    def test_missing_service_does_not_fake_retrieval_output(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent(
                intent=IntentType.REFUND_REQUEST,
            )
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="refund?",
        )

        assert state.retrieved_evidence == ()
        assert state.generated_response is None


# ===========================================================================
# Unsupported operational retrieval
# ===========================================================================


class TestOperationalRetrieval:

    def test_operational_retrieval_is_not_misrouted_as_knowledge(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        intent_classifier.classify.return_value = (
            make_intent(
                intent=IntentType.ORDER_STATUS,
            )
        )
        decision_engine.decide.return_value = (
            make_operational_retrieval_decision()
        )

        answer_service.answer.side_effect = (
            UnsupportedRetrievalKindError(
                "Operational retrieval is unsupported."
            )
        )

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="Where is order ORD-123?",
        )

        error = extract_pipeline_error(state)

        assert (
            error.code
            == "RETRIEVAL_KIND_UNSUPPORTED"
        )
        assert (
            error.stage
            is PipelineStage.RETRIEVAL_COMPLETED
        )
        assert error.retryable is False

        answer_service.answer.assert_called_once()

    def test_operational_failure_does_not_create_fake_evidence(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        intent_classifier.classify.return_value = (
            make_intent(
                intent=IntentType.ORDER_STATUS,
            )
        )
        decision_engine.decide.return_value = (
            make_operational_retrieval_decision()
        )
        answer_service.answer.side_effect = (
            UnsupportedRetrievalKindError(
                "unsupported"
            )
        )

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="Where is ORD-123?",
        )

        assert state.retrieved_evidence == ()
        assert state.generated_response is None


# ===========================================================================
# Retrieval-decision failures
# ===========================================================================


class TestRetrievalDecisionFailures:

    @pytest.mark.parametrize(
        "exception",
        [
            pytest.param(
                InvalidRetrievalDecisionError(
                    "invalid retrieval decision"
                ),
                id="invalid-retrieval-decision",
            ),
            pytest.param(
                UnsupportedAnswerDecisionError(
                    "unsupported answer decision"
                ),
                id="unsupported-answer-decision",
            ),
        ],
    )
    def test_invalid_retrieval_decision_fails_non_retryable(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
        exception,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )
        answer_service.answer.side_effect = exception

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="Explain the policy.",
        )

        error = extract_pipeline_error(state)

        assert (
            error.code
            == "RETRIEVAL_DECISION_INVALID"
        )
        assert (
            error.stage
            is PipelineStage.RETRIEVAL_COMPLETED
        )
        assert error.retryable is False
        assert (
            error.metadata["exception_type"]
            == type(exception).__name__
        )


# ===========================================================================
# Generation failure mapping
# ===========================================================================


GENERATION_FAILURE_CASES = [
    pytest.param(
        GroundedGenerationTimeoutError("timeout"),
        "GENERATION_PROVIDER_TIMEOUT",
        True,
        id="provider-timeout",
    ),
    pytest.param(
        GroundedGenerationProviderError(
            "provider failed"
        ),
        "GENERATION_PROVIDER_FAILURE",
        True,
        id="provider-failure",
    ),
    pytest.param(
        InvalidGroundedGenerationResponseError(
            "invalid response"
        ),
        "GENERATION_INVALID_RESPONSE",
        True,
        id="invalid-response",
    ),
    pytest.param(
        GroundedGenerationError(
            "generation failed"
        ),
        "GENERATION_FAILURE",
        False,
        id="generic-generation-failure",
    ),
]


class TestGenerationFailures:

    @pytest.mark.parametrize(
        (
            "exception",
            "expected_code",
            "expected_retryable",
        ),
        GENERATION_FAILURE_CASES,
    )
    def test_known_generation_failure_maps_to_pipeline_error(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
        exception,
        expected_code,
        expected_retryable,
    ):
        intent_classifier.classify.return_value = (
            make_intent(
                intent=IntentType.REFUND_REQUEST,
            )
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )
        answer_service.answer.side_effect = exception

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="Explain refund timing.",
        )

        error = extract_pipeline_error(state)

        assert error.code == expected_code
        assert (
            error.retryable
            is expected_retryable
        )
        assert (
            error.stage
            is PipelineStage.RESPONSE_GENERATED
        )
        assert (
            error.metadata["exception_type"]
            == type(exception).__name__
        )

    def test_generation_failure_does_not_fake_generated_response(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )
        answer_service.answer.side_effect = (
            GroundedGenerationProviderError(
                "provider failed"
            )
        )

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="policy?",
        )

        assert state.generated_response is None


# ===========================================================================
# Generic AnswerService failure
# ===========================================================================


class TestAnswerServiceFailure:

    def test_known_answer_service_failure_is_mapped(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )

        answer_service.answer.side_effect = (
            AnswerServiceError(
                "answer workflow failed"
            )
        )

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="policy?",
        )

        error = extract_pipeline_error(state)

        assert error.code == "ANSWER_WORKFLOW_FAILURE"
        assert (
            error.stage
            is PipelineStage.RETRIEVAL_COMPLETED
        )
        assert error.retryable is False

    def test_unexpected_answer_service_exception_propagates(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )

        answer_service.answer.side_effect = KeyError(
            "unexpected programming defect"
        )

        with pytest.raises(
            KeyError,
            match="unexpected programming defect",
        ):
            grounded_orchestrator.process_message(
                **make_ids(),
                customer_message="policy?",
            )


# ===========================================================================
# Observer lifecycle
# ===========================================================================


class TestObserverLifecycle:

    def test_terminal_path_emits_intent_then_decision(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
        observer,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        started = [
            event.kwargs["stage"]
            for event
            in observer.stage_started.call_args_list
        ]

        completed = [
            event.kwargs["stage"]
            for event
            in observer.stage_completed.call_args_list
        ]

        assert started == [
            PipelineStage.INTENT_CLASSIFIED,
            PipelineStage.DECISION_MADE,
        ]

        assert completed == [
            PipelineStage.INTENT_CLASSIFIED,
            PipelineStage.DECISION_MADE,
        ]

        observer.stage_failed.assert_not_called()

    def test_grounded_path_emits_complete_stage_sequence(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
        observer,
    ):
        intent_classifier.classify.return_value = (
            make_intent(
                intent=IntentType.REFUND_REQUEST,
            )
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )
        answer_service.answer.return_value = (
            make_answer_result()
        )

        grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="Explain refund timing.",
        )

        expected = [
            PipelineStage.INTENT_CLASSIFIED,
            PipelineStage.DECISION_MADE,
            PipelineStage.RETRIEVAL_COMPLETED,
            PipelineStage.RESPONSE_GENERATED,
        ]

        started = [
            event.kwargs["stage"]
            for event
            in observer.stage_started.call_args_list
        ]

        completed = [
            event.kwargs["stage"]
            for event
            in observer.stage_completed.call_args_list
        ]

        assert started == expected
        assert completed == expected

        observer.stage_failed.assert_not_called()

    def test_intent_failure_notifies_failed_once(
        self,
        orchestrator,
        intent_classifier,
        observer,
    ):
        intent_classifier.classify.side_effect = (
            IntentClassificationTimeoutError(
                "timeout"
            )
        )

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        error = extract_pipeline_error(state)

        observer.stage_failed.assert_called_once_with(
            state=state,
            stage=PipelineStage.INTENT_CLASSIFIED,
            error=error,
        )

    def test_decision_stage_never_starts_after_intent_failure(
        self,
        orchestrator,
        intent_classifier,
        observer,
    ):
        intent_classifier.classify.side_effect = (
            InvalidIntentInputError("invalid")
        )

        orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        started = [
            event.kwargs["stage"]
            for event
            in observer.stage_started.call_args_list
        ]

        assert (
            PipelineStage.DECISION_MADE
            not in started
        )

    def test_generation_failure_notifies_response_stage_failure(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
        observer,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )
        answer_service.answer.side_effect = (
            GroundedGenerationTimeoutError(
                "timeout"
            )
        )

        state = grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="policy?",
        )

        error = extract_pipeline_error(state)

        observer.stage_failed.assert_called_once_with(
            state=state,
            stage=PipelineStage.RESPONSE_GENERATED,
            error=error,
        )

    def test_null_observer_is_safe(
        self,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        orchestrator = AIOrchestrator(
            intent_classifier=intent_classifier,
            decision_engine=decision_engine,
        )

        state = orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        assert (
            state.stage
            is PipelineStage.DECISION_MADE
        )


# ===========================================================================
# Ordering
# ===========================================================================


class TestExecutionOrdering:

    def test_decision_is_not_called_before_classifier(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        manager = MagicMock()

        manager.attach_mock(
            intent_classifier.classify,
            "classify",
        )
        manager.attach_mock(
            decision_engine.decide,
            "decide",
        )

        orchestrator.process_message(
            **make_ids(),
            customer_message="hello",
        )

        assert [
            item[0]
            for item
            in manager.mock_calls
        ] == [
            "classify",
            "decide",
        ]

    def test_answer_service_runs_only_after_decision(
        self,
        grounded_orchestrator,
        intent_classifier,
        decision_engine,
        answer_service,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_knowledge_retrieval_decision()
        )
        answer_service.answer.return_value = (
            make_answer_result()
        )

        manager = MagicMock()

        manager.attach_mock(
            intent_classifier.classify,
            "classify",
        )
        manager.attach_mock(
            decision_engine.decide,
            "decide",
        )
        manager.attach_mock(
            answer_service.answer,
            "answer",
        )

        grounded_orchestrator.process_message(
            **make_ids(),
            customer_message="refund?",
        )

        names = [
            item[0]
            for item
            in manager.mock_calls
        ]

        assert names == [
            "classify",
            "decide",
            "answer",
        ]


# ===========================================================================
# Stateless reuse
# ===========================================================================


class TestStatelessReuse:

    def test_orchestrator_can_process_multiple_independent_requests(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.return_value = (
            make_intent()
        )
        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        first_ids = make_ids()
        second_ids = make_ids()

        first = orchestrator.process_message(
            **first_ids,
            customer_message="first",
        )

        second = orchestrator.process_message(
            **second_ids,
            customer_message="second",
        )

        assert first.ai_run_id != second.ai_run_id
        assert first.customer_message == "first"
        assert second.customer_message == "second"

        assert (
            intent_classifier.classify.call_args_list
            == [
                call(
                    customer_message="first",
                    conversation_context=None,
                ),
                call(
                    customer_message="second",
                    conversation_context=None,
                ),
            ]
        )

    def test_failed_request_does_not_poison_next_request(
        self,
        orchestrator,
        intent_classifier,
        decision_engine,
    ):
        intent_classifier.classify.side_effect = [
            IntentClassificationTimeoutError(
                "first request failed"
            ),
            make_intent(),
        ]

        decision_engine.decide.return_value = (
            make_terminal_answer_decision()
        )

        first = orchestrator.process_message(
            **make_ids(),
            customer_message="first",
        )

        second = orchestrator.process_message(
            **make_ids(),
            customer_message="second",
        )

        assert first.stage is PipelineStage.FAILED
        assert (
            second.stage
            is PipelineStage.DECISION_MADE
        )


# ===========================================================================
# Null observer contract
# ===========================================================================


class TestNullObserver:

    def test_methods_are_safe_noops(self):
        observer = NullOrchestrationObserver()

        state = MagicMock()
        error = MagicMock()

        observer.stage_started(
            state=state,
            stage=PipelineStage.INTENT_CLASSIFIED,
        )

        observer.stage_completed(
            state=state,
            stage=PipelineStage.INTENT_CLASSIFIED,
        )

        observer.stage_failed(
            state=state,
            stage=PipelineStage.INTENT_CLASSIFIED,
            error=error,
        )


# ===========================================================================
# Property-based smoke test
#
# Hypothesis remains optional. Its absence must NOT cause the entire
# orchestrator suite to be skipped.
# ===========================================================================


try:
    from hypothesis import given
    from hypothesis import strategies as st

    HYPOTHESIS_AVAILABLE = True

except ImportError:
    HYPOTHESIS_AVAILABLE = False


if HYPOTHESIS_AVAILABLE:

    class TestPropertyBasedOrchestration:

        @given(
            message=st.text(
                min_size=1,
                max_size=500,
            ).filter(
                lambda value: bool(value.strip())
            )
        )
        def test_arbitrary_nonblank_messages_do_not_break_terminal_path(
            self,
            message,
        ):
            intent_classifier = MagicMock(
                spec=IntentClassifier,
            )
            decision_engine = MagicMock(
                spec=DecisionEngine,
            )

            intent_classifier.classify.return_value = (
                make_intent()
            )
            decision_engine.decide.return_value = (
                make_terminal_answer_decision()
            )

            orchestrator = AIOrchestrator(
                intent_classifier=intent_classifier,
                decision_engine=decision_engine,
            )

            state = orchestrator.process_message(
                **make_ids(),
                customer_message=message,
            )

            assert (
                state.stage
                is PipelineStage.DECISION_MADE
            )
            assert (
                state.customer_message
                == message.strip()
            )

else:

    class TestPropertyBasedOrchestration:

        @pytest.mark.skip(
            reason="hypothesis is not installed"
        )
        def test_hypothesis_not_installed(self):
            pass