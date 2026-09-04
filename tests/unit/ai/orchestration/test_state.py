"""
Unit tests for packages.ai.orchestration.state.

Scope
-----
This module covers:
    - PipelineError:      normalization + immutability
    - RetrievedEvidence:  source-neutral evidence validation + immutability
    - AIState:            construction, field normalization, stage invariants, and every `with_*` / `complete` transition helper.

Notes on test doubles
----------------------
`AIState.intent_result` / `decision_result` are typed as the real
`IntentResult` / `DecisionResult` pydantic models from the intent and
decision packages. This suite only cares about *presence/absence* of
those objects (never their internal fields), so it builds them with
`model_construct()` — the pydantic v2 idiom for producing a real,
type-correct instance without depending on (or hardcoding) that
schema's own required fields. This keeps the suite decoupled from
changes to IntentResult/DecisionResult.

A second, important implementation detail this suite locks in with
explicit tests: `BaseModel.model_copy()` does **not** re-run field or
model validators in pydantic v2. That means the `with_intent`,
`with_decision`, `with_retrieved_evidence`, `with_generated_response`,
`with_error`, and `complete` helpers only get invariant protection
from their own explicit `if ... raise ValueError(...)` guards, *not*
from `validate_stage_invariants`. The invariant validator only fires
on direct construction (`AIState(...)`) or on attribute assignment
(since `validate_assignment=True`). Tests are split along that line
so a regression in either mechanism is caught precisely.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from packages.ai.decision.schemas import DecisionReasonCode, DecisionResult, DecisionType
from packages.ai.intent.schemas import IntentResult
from packages.ai.intent.taxonomy import IntentType
from packages.ai.orchestration.state import AIState, EvidenceSourceType, PipelineError, PipelineStage, RetrievedEvidence
from packages.ai.decision.schemas import DecisionReasonCode, DecisionResult, DecisionType

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ids() -> dict[str, uuid.UUID]:
    """Fresh, independent UUIDs for each identity field."""
    return {
        "ai_run_id": uuid.uuid4(),
        "trace_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "trigger_message_id": uuid.uuid4(),
    }


@pytest.fixture
def base_kwargs(ids: dict[str, uuid.UUID]) -> dict:
    """Minimal valid constructor kwargs for a RECEIVED-stage AIState."""
    return {**ids, "customer_message": "My order hasn't arrived yet."}


@pytest.fixture
def received_state(base_kwargs: dict) -> AIState:
    """A valid, freshly constructed RECEIVED-stage AIState."""
    return AIState(**base_kwargs)


@pytest.fixture
def intent_result() -> IntentResult:
    """A structurally valid, schema-agnostic IntentResult stand-in."""
    return IntentResult(
        intent=IntentType.GENERAL_QUESTION,
        confidence=0.95,
        needs_clarification=False,
        reason_summary="General supported customer question.",
    )


@pytest.fixture
def decision_result() -> DecisionResult:
    """A structurally valid, schema-agnostic DecisionResult stand-in."""
    return DecisionResult(
        decision=DecisionType.ANSWER,
        reason_code=DecisionReasonCode.DIRECT_INFORMATIONAL_RESPONSE,
        reason_summary="Direct response is appropriate.",
        confidence=0.95,
    )


@pytest.fixture
def intent_classified_state(received_state: AIState, intent_result: IntentResult) -> AIState:
    return received_state.with_intent(intent_result)


@pytest.fixture
def decision_made_state(
    intent_classified_state: AIState, decision_result: DecisionResult
) -> AIState:
    return intent_classified_state.with_decision(decision_result)


def make_error(stage: PipelineStage = PipelineStage.RECEIVED) -> PipelineError:
    return PipelineError(code="boom", message="Something went wrong.", stage=stage)


# ---------------------------------------------------------------------------
# PipelineError
# ---------------------------------------------------------------------------


class TestPipelineError:
    def test_code_is_normalized_to_uppercase_and_stripped(self) -> None:
        error = PipelineError(
            code="  not_found  ", message="missing", stage=PipelineStage.RECEIVED
        )
        assert error.code == "NOT_FOUND"

    def test_defaults(self) -> None:
        error = make_error()
        assert error.retryable is False
        assert error.metadata == {}

    @pytest.mark.parametrize("bad_code", ["", "   "])
    def test_empty_code_rejected(self, bad_code: str) -> None:
        with pytest.raises(ValidationError):
            PipelineError(code=bad_code, message="msg", stage=PipelineStage.RECEIVED)

    def test_empty_message_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PipelineError(code="X", message="", stage=PipelineStage.RECEIVED)

    def test_is_frozen(self) -> None:
        error = make_error()
        with pytest.raises(ValidationError):
            error.retryable = True  # type: ignore[misc]

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            PipelineError(
                code="X",
                message="msg",
                stage=PipelineStage.RECEIVED,
                unexpected="nope",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# RetrievedEvidence
# ---------------------------------------------------------------------------


class TestRetrievedEvidence:
    def test_valid_minimal_knowledge_evidence(self) -> None:
        evidence = RetrievedEvidence(
            source_type=EvidenceSourceType.KNOWLEDGE,
            content="Relevant policy text.",
        )

        assert evidence.source_type is EvidenceSourceType.KNOWLEDGE
        assert evidence.content == "Relevant policy text."
        assert evidence.source_id is None
        assert evidence.title is None
        assert evidence.section is None
        assert evidence.relevance_score is None
        assert evidence.metadata == {}

    @pytest.mark.parametrize(
        "source_type",
        [
            EvidenceSourceType.KNOWLEDGE,
            EvidenceSourceType.OPERATIONAL,
            EvidenceSourceType.SYSTEM,
        ],
    )
    def test_all_supported_source_types_are_valid(
        self,
        source_type: EvidenceSourceType,
    ) -> None:
        evidence = RetrievedEvidence(
            source_type=source_type,
            content="Trusted evidence.",
        )

        assert evidence.source_type is source_type

    def test_content_is_stripped(self) -> None:
        evidence = RetrievedEvidence(
            source_type=EvidenceSourceType.KNOWLEDGE,
            content="  Refunds may take several business days.  ",
        )

        assert evidence.content == "Refunds may take several business days."

    @pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
    def test_blank_content_rejected(self, blank: str) -> None:
        with pytest.raises(ValidationError):
            RetrievedEvidence(
                source_type=EvidenceSourceType.KNOWLEDGE,
                content=blank,
            )

    def test_optional_text_fields_are_stripped(self) -> None:
        evidence = RetrievedEvidence(
            source_type=EvidenceSourceType.KNOWLEDGE,
            content="Policy text.",
            source_id="  chunk-123  ",
            title="  Refund Policy  ",
            section="  Processing Time  ",
        )

        assert evidence.source_id == "chunk-123"
        assert evidence.title == "Refund Policy"
        assert evidence.section == "Processing Time"

    @pytest.mark.parametrize(
        "field_name",
        [
            "source_id",
            "title",
            "section",
        ],
    )
    def test_blank_optional_text_normalized_to_none(
        self,
        field_name: str,
    ) -> None:
        evidence = RetrievedEvidence(
            source_type=EvidenceSourceType.KNOWLEDGE,
            content="Policy text.",
            **{field_name: "   "},
        )

        assert getattr(evidence, field_name) is None

    def test_zero_relevance_score_allowed(self) -> None:
        evidence = RetrievedEvidence(
            source_type=EvidenceSourceType.KNOWLEDGE,
            content="Policy text.",
            relevance_score=0.0,
        )

        assert evidence.relevance_score == 0.0

    def test_positive_relevance_score_allowed(self) -> None:
        evidence = RetrievedEvidence(
            source_type=EvidenceSourceType.KNOWLEDGE,
            content="Policy text.",
            relevance_score=0.87,
        )

        assert evidence.relevance_score == pytest.approx(0.87)

    def test_negative_relevance_score_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetrievedEvidence(
                source_type=EvidenceSourceType.KNOWLEDGE,
                content="Policy text.",
                relevance_score=-0.01,
            )

    def test_metadata_is_preserved(self) -> None:
        evidence = RetrievedEvidence(
            source_type=EvidenceSourceType.KNOWLEDGE,
            content="Policy text.",
            metadata={
                "document_id": "doc-123",
                "version_id": "version-456",
            },
        )

        assert evidence.metadata["document_id"] == "doc-123"
        assert evidence.metadata["version_id"] == "version-456"

    def test_is_frozen(self) -> None:
        evidence = RetrievedEvidence(
            source_type=EvidenceSourceType.KNOWLEDGE,
            content="Policy text.",
        )

        with pytest.raises(ValidationError):
            evidence.content = "Changed."  # type: ignore[misc]

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            RetrievedEvidence(
                source_type=EvidenceSourceType.KNOWLEDGE,
                content="Policy text.",
                unknown_field="nope",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# AIState — construction & field normalization
# ---------------------------------------------------------------------------


class TestAIStateConstruction:
    def test_valid_received_state(self, base_kwargs: dict) -> None:
        state = AIState(**base_kwargs)

        assert state.stage is PipelineStage.RECEIVED
        assert state.customer_message == "My order hasn't arrived yet."
        assert state.intent_result is None
        assert state.decision_result is None
        assert state.retrieved_evidence == ()
        assert state.errors == ()
        assert state.generated_response is None
        assert state.completed_at is None
        assert isinstance(state.started_at, datetime)
        assert state.metadata == {}

    def test_started_at_defaults_to_now_utc(self, base_kwargs: dict) -> None:
        before = datetime.now(timezone.utc)
        state = AIState(**base_kwargs)
        after = datetime.now(timezone.utc)

        assert before <= state.started_at <= after

    @pytest.mark.parametrize("blank_message", ["", "   ", "\t\n"])
    def test_empty_customer_message_rejected(
        self, ids: dict[str, uuid.UUID], blank_message: str
    ) -> None:
        with pytest.raises(ValidationError):
            AIState(**ids, customer_message=blank_message)

    def test_customer_message_is_stripped(self, ids: dict[str, uuid.UUID]) -> None:
        state = AIState(**ids, customer_message="  hello there  ")
        assert state.customer_message == "hello there"

    def test_context_is_stripped(self, base_kwargs: dict) -> None:
        state = AIState(**base_kwargs, conversation_context="  prior turns  ")
        assert state.conversation_context == "prior turns"

    def test_blank_context_normalized_to_none(self, base_kwargs: dict) -> None:
        state = AIState(**base_kwargs, conversation_context="    ")
        assert state.conversation_context is None

    def test_context_none_stays_none(self, base_kwargs: dict) -> None:
        state = AIState(**base_kwargs, conversation_context=None)
        assert state.conversation_context is None

    def test_rejects_unknown_fields(self, base_kwargs: dict) -> None:
        with pytest.raises(ValidationError):
            AIState(**base_kwargs, not_a_real_field="oops")  # type: ignore[call-arg]

    def test_customer_message_too_long_rejected(self, ids: dict[str, uuid.UUID]) -> None:
        with pytest.raises(ValidationError):
            AIState(**ids, customer_message="x" * 20_001)


# ---------------------------------------------------------------------------
# AIState — stage invariants (direct construction)
# ---------------------------------------------------------------------------


REQUIRES_INTENT = [
    PipelineStage.INTENT_CLASSIFIED,
    PipelineStage.DECISION_MADE,
    PipelineStage.RETRIEVAL_COMPLETED,
    PipelineStage.RESPONSE_GENERATED,
    PipelineStage.GUARDRAILS_COMPLETED,
    PipelineStage.ACTION_PROPOSED,
    PipelineStage.ACTION_COMPLETED,
    PipelineStage.ESCALATED,
    PipelineStage.COMPLETED,
]

REQUIRES_DECISION = [
    PipelineStage.DECISION_MADE,
    PipelineStage.RETRIEVAL_COMPLETED,
    PipelineStage.RESPONSE_GENERATED,
    PipelineStage.GUARDRAILS_COMPLETED,
    PipelineStage.ACTION_PROPOSED,
    PipelineStage.ACTION_COMPLETED,
    PipelineStage.ESCALATED,
    PipelineStage.COMPLETED,
]


class TestAIStateInvariantsOnDirectConstruction:
    """
    `validate_stage_invariants` only runs on direct construction (and on
    attribute assignment, since `validate_assignment=True`) — NOT through
    `model_copy`. These tests exercise it directly by constructing an
    AIState already sitting at a given stage.
    """

    @pytest.mark.parametrize("stage", REQUIRES_INTENT)
    def test_stage_without_intent_result_rejected(
        self, base_kwargs: dict, stage: PipelineStage
    ) -> None:
        with pytest.raises(ValidationError, match="requires intent_result"):
            AIState(**base_kwargs, stage=stage)

    @pytest.mark.parametrize("stage", REQUIRES_DECISION)
    def test_stage_without_decision_result_rejected(
        self, base_kwargs: dict, stage: PipelineStage, intent_result: IntentResult
    ) -> None:
        with pytest.raises(ValidationError, match="requires decision_result"):
            AIState(**base_kwargs, stage=stage, intent_result=intent_result)

    def test_response_generated_requires_generated_response(
        self,
        base_kwargs: dict,
        intent_result: IntentResult,
        decision_result: DecisionResult,
    ) -> None:
        with pytest.raises(ValidationError, match="RESPONSE_GENERATED requires generated_response"):
            AIState(
                **base_kwargs,
                stage=PipelineStage.RESPONSE_GENERATED,
                intent_result=intent_result,
                decision_result=decision_result,
                generated_response=None,
            )

    def test_response_generated_with_response_is_valid(
        self,
        base_kwargs: dict,
        intent_result: IntentResult,
        decision_result: DecisionResult,
    ) -> None:
        state = AIState(
            **base_kwargs,
            stage=PipelineStage.RESPONSE_GENERATED,
            intent_result=intent_result,
            decision_result=decision_result,
            generated_response="We're looking into it.",
        )
        assert state.generated_response == "We're looking into it."

    def test_completed_requires_completed_at(
        self,
        base_kwargs: dict,
        intent_result: IntentResult,
        decision_result: DecisionResult,
    ) -> None:
        with pytest.raises(ValidationError, match="COMPLETED requires completed_at"):
            AIState(
                **base_kwargs,
                stage=PipelineStage.COMPLETED,
                intent_result=intent_result,
                decision_result=decision_result,
                completed_at=None,
            )

    def test_completed_with_completed_at_is_valid(
        self,
        base_kwargs: dict,
        intent_result: IntentResult,
        decision_result: DecisionResult,
    ) -> None:
        state = AIState(
            **base_kwargs,
            stage=PipelineStage.COMPLETED,
            intent_result=intent_result,
            decision_result=decision_result,
            completed_at=datetime.now(timezone.utc),
        )
        assert state.stage is PipelineStage.COMPLETED

    def test_failed_requires_at_least_one_error(self, base_kwargs: dict) -> None:
        with pytest.raises(ValidationError, match="FAILED state requires at least one error"):
            AIState(**base_kwargs, stage=PipelineStage.FAILED, errors=())

    def test_failed_with_error_is_valid(self, base_kwargs: dict) -> None:
        state = AIState(
            **base_kwargs,
            stage=PipelineStage.FAILED,
            errors=(make_error(),),
        )
        assert state.stage is PipelineStage.FAILED
        assert len(state.errors) == 1

    def test_context_built_has_no_extra_requirements(self, base_kwargs: dict) -> None:
        """CONTEXT_BUILT sits before INTENT_CLASSIFIED and carries no invariant."""
        state = AIState(**base_kwargs, stage=PipelineStage.CONTEXT_BUILT)
        assert state.stage is PipelineStage.CONTEXT_BUILT

    def test_validate_assignment_reruns_invariants(self, received_state: AIState) -> None:
        """`validate_assignment=True` means invariants are re-checked on mutation too."""
        with pytest.raises(ValidationError, match="requires intent_result"):
            received_state.stage = PipelineStage.INTENT_CLASSIFIED
            
    def test_retrieval_completed_allows_empty_evidence(self, base_kwargs: dict, intent_result: IntentResult, decision_result: DecisionResult) -> None:
        state = AIState(
            **base_kwargs,
            stage=PipelineStage.RETRIEVAL_COMPLETED,
            intent_result=intent_result,
            decision_result=decision_result,
            retrieved_evidence=(),
        )

        assert state.stage is PipelineStage.RETRIEVAL_COMPLETED
        assert state.retrieved_evidence == ()


# ---------------------------------------------------------------------------
# AIState — with_intent
# ---------------------------------------------------------------------------


class TestWithIntent:
    def test_transitions_to_intent_classified(
        self, received_state: AIState, intent_result: IntentResult
    ) -> None:
        new_state = received_state.with_intent(intent_result)

        assert new_state.stage is PipelineStage.INTENT_CLASSIFIED
        assert new_state.intent_result is intent_result

    def test_does_not_mutate_original(
        self, received_state: AIState, intent_result: IntentResult
    ) -> None:
        received_state.with_intent(intent_result)

        assert received_state.stage is PipelineStage.RECEIVED
        assert received_state.intent_result is None

    def test_returns_new_instance(
        self, received_state: AIState, intent_result: IntentResult
    ) -> None:
        new_state = received_state.with_intent(intent_result)
        assert new_state is not received_state

    def test_rejects_wrong_type(self, received_state: AIState) -> None:
        """
        `model_copy()` performs no field validation (see module docstring),
        so `with_intent` must guard the input type itself or a bad caller
        can silently corrupt state. This asserts that guard exists.
        """
        with pytest.raises(TypeError):
            received_state.with_intent("not-an-intent")  # type: ignore[arg-type]

# ---------------------------------------------------------------------------
# AIState — with_decision
# ---------------------------------------------------------------------------


class TestWithDecision:
    def test_decision_before_intent_rejected(
        self, received_state: AIState, decision_result: DecisionResult
    ) -> None:
        with pytest.raises(ValueError, match="Cannot add decision before intent classification"):
            received_state.with_decision(decision_result)

    def test_transitions_to_decision_made(
        self, intent_classified_state: AIState, decision_result: DecisionResult
    ) -> None:
        new_state = intent_classified_state.with_decision(decision_result)

        assert new_state.stage is PipelineStage.DECISION_MADE
        assert new_state.decision_result is decision_result
        # Prior stage output must be preserved through the transition.
        assert new_state.intent_result is intent_classified_state.intent_result

    def test_does_not_mutate_original(
        self, intent_classified_state: AIState, decision_result: DecisionResult
    ) -> None:
        intent_classified_state.with_decision(decision_result)

        assert intent_classified_state.stage is PipelineStage.INTENT_CLASSIFIED
        assert intent_classified_state.decision_result is None
        
    def test_rejects_wrong_type(self, intent_classified_state: AIState) -> None:
        """
        Same rationale as `with_intent`'s type-safety test: `model_copy()`
        performs no field validation, so `with_decision` must guard the
        input type itself.
        """
        with pytest.raises(TypeError):
            intent_classified_state.with_decision(12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AIState — with_retrieved_evidence
# ---------------------------------------------------------------------------


class TestWithRetrievalContext:
    class TestWithRetrievedEvidence:
        def test_retrieval_before_decision_rejected(
            self,
            intent_classified_state: AIState,
        ) -> None:
            evidence = (
                RetrievedEvidence(
                    source_type=EvidenceSourceType.KNOWLEDGE,
                    content="Some policy text.",
                ),
            )

            with pytest.raises(
                ValueError,
                match="Cannot attach retrieved evidence before a decision",
            ):
                intent_classified_state.with_retrieved_evidence(evidence)

        def test_transitions_to_retrieval_completed(
            self,
            decision_made_state: AIState,
        ) -> None:
            evidence = (
                RetrievedEvidence(
                    source_type=EvidenceSourceType.KNOWLEDGE,
                    content="Chunk one.",
                    source_id="chunk-1",
                ),
                RetrievedEvidence(
                    source_type=EvidenceSourceType.KNOWLEDGE,
                    content="Chunk two.",
                    source_id="chunk-2",
                ),
            )

            new_state = decision_made_state.with_retrieved_evidence(evidence)

            assert new_state.stage is PipelineStage.RETRIEVAL_COMPLETED
            assert new_state.retrieved_evidence == evidence

        def test_empty_evidence_allowed(
            self,
            decision_made_state: AIState,
        ) -> None:
            new_state = decision_made_state.with_retrieved_evidence(())

            assert new_state.retrieved_evidence == ()
            assert new_state.stage is PipelineStage.RETRIEVAL_COMPLETED

        def test_does_not_mutate_original(
            self,
            decision_made_state: AIState,
        ) -> None:
            evidence = (
                RetrievedEvidence(
                    source_type=EvidenceSourceType.KNOWLEDGE,
                    content="Policy text.",
                ),
            )

            decision_made_state.with_retrieved_evidence(evidence)

            assert decision_made_state.stage is PipelineStage.DECISION_MADE
            assert decision_made_state.retrieved_evidence == ()

        def test_returns_new_instance(
            self,
            decision_made_state: AIState,
        ) -> None:
            evidence = (
                RetrievedEvidence(
                    source_type=EvidenceSourceType.KNOWLEDGE,
                    content="Policy text.",
                ),
            )

            new_state = decision_made_state.with_retrieved_evidence(evidence)

            assert new_state is not decision_made_state

        def test_non_tuple_rejected(
            self,
            decision_made_state: AIState,
        ) -> None:
            evidence = [
                RetrievedEvidence(
                    source_type=EvidenceSourceType.KNOWLEDGE,
                    content="Policy text.",
                )
            ]

            with pytest.raises(
                TypeError,
                match=r"tuple\[RetrievedEvidence",
            ):
                decision_made_state.with_retrieved_evidence(  # type: ignore[arg-type]
                    evidence
                )

        def test_tuple_with_wrong_item_type_rejected(
            self,
            decision_made_state: AIState,
        ) -> None:
            evidence = (
                RetrievedEvidence(
                    source_type=EvidenceSourceType.KNOWLEDGE,
                    content="Valid evidence.",
                ),
                "not-evidence",
            )

            with pytest.raises(
                TypeError,
                match="every item",
            ):
                decision_made_state.with_retrieved_evidence(  # type: ignore[arg-type]
                    evidence
                )

        def test_mixed_evidence_sources_allowed(
            self,
            decision_made_state: AIState,
        ) -> None:
            evidence = (
                RetrievedEvidence(
                    source_type=EvidenceSourceType.KNOWLEDGE,
                    content="Refund processing normally takes several days.",
                ),
                RetrievedEvidence(
                    source_type=EvidenceSourceType.OPERATIONAL,
                    content="Refund transaction is currently processing.",
                    source_id="txn-123",
                ),
            )

            new_state = decision_made_state.with_retrieved_evidence(evidence)

            assert len(new_state.retrieved_evidence) == 2
            assert (
                new_state.retrieved_evidence[0].source_type
                is EvidenceSourceType.KNOWLEDGE
            )
            assert (
                new_state.retrieved_evidence[1].source_type
                is EvidenceSourceType.OPERATIONAL
            )


# ---------------------------------------------------------------------------
# AIState — with_generated_response
# ---------------------------------------------------------------------------


class TestWithGeneratedResponse:
    def test_transitions_to_response_generated(self, decision_made_state: AIState) -> None:
        new_state = decision_made_state.with_generated_response("  Here's an update.  ")

        assert new_state.stage is PipelineStage.RESPONSE_GENERATED
        assert new_state.generated_response == "Here's an update."

    @pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
    def test_blank_response_rejected(self, decision_made_state: AIState, blank: str) -> None:
        with pytest.raises(ValueError, match="Generated response cannot be empty"):
            decision_made_state.with_generated_response(blank)

    def test_generated_response_before_decision_rejected(self, received_state: AIState) -> None:
        with pytest.raises(ValueError, match="Cannot generate response before decision"):
            received_state.with_generated_response("early response")
            
    def test_wrong_response_type_rejected(self, decision_made_state: AIState) -> None:
        with pytest.raises(TypeError, match="response must be a string"):
            decision_made_state.with_generated_response(123)  # type: ignore[arg-type]
            
    def test_does_not_mutate_original(self, decision_made_state: AIState) -> None:
        decision_made_state.with_generated_response("Generated answer.")

        assert decision_made_state.stage is PipelineStage.DECISION_MADE
        assert decision_made_state.generated_response is None


# ---------------------------------------------------------------------------
# AIState — with_error / FAILED
# ---------------------------------------------------------------------------


class TestWithError:
    def test_transitions_to_failed(self, received_state: AIState) -> None:
        error = make_error(stage=PipelineStage.RECEIVED)
        new_state = received_state.with_error(error)

        assert new_state.stage is PipelineStage.FAILED
        assert new_state.completed_at is not None

    def test_failed_state_contains_the_error(self, received_state: AIState) -> None:
        error = make_error(stage=PipelineStage.RECEIVED)
        new_state = received_state.with_error(error)

        assert error in new_state.errors
        assert len(new_state.errors) == 1

    def test_errors_accumulate_across_multiple_calls(self, received_state: AIState) -> None:
        first = make_error(stage=PipelineStage.RECEIVED)
        second = make_error(stage=PipelineStage.INTENT_CLASSIFIED)

        state_after_first = received_state.with_error(first)
        state_after_second = state_after_first.with_error(second)

        assert state_after_second.errors == (first, second)
        # Earlier snapshot must remain untouched (structural immutability).
        assert state_after_first.errors == (first,)

    def test_does_not_mutate_original(self, received_state: AIState) -> None:
        received_state.with_error(make_error())

        assert received_state.stage is PipelineStage.RECEIVED
        assert received_state.errors == ()

    def test_can_fail_from_any_stage(self, decision_made_state: AIState) -> None:
        new_state = decision_made_state.with_error(make_error(PipelineStage.DECISION_MADE))
        assert new_state.stage is PipelineStage.FAILED
        
    def test_wrong_error_type_rejected(self, received_state: AIState) -> None:
        with pytest.raises(TypeError, match="expects a PipelineError"):
            received_state.with_error("boom")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AIState — complete()
# ---------------------------------------------------------------------------


class TestComplete:
    def test_complete_without_intent_rejected(self, received_state: AIState) -> None:
        with pytest.raises(ValueError, match="Cannot complete workflow without intent_result"):
            received_state.complete()

    def test_complete_without_decision_rejected(self, intent_classified_state: AIState) -> None:
        with pytest.raises(ValueError, match="Cannot complete workflow without decision_result"):
            intent_classified_state.complete()

    def test_complete_valid_state(self, decision_made_state: AIState) -> None:
        before = datetime.now(timezone.utc)
        new_state = decision_made_state.complete()
        after = datetime.now(timezone.utc)

        assert new_state.stage is PipelineStage.COMPLETED
        assert new_state.completed_at is not None
        assert before - timedelta(seconds=1) <= new_state.completed_at <= after + timedelta(seconds=1)

    def test_complete_does_not_mutate_original(self, decision_made_state: AIState) -> None:
        decision_made_state.complete()

        assert decision_made_state.stage is PipelineStage.DECISION_MADE
        assert decision_made_state.completed_at is None

    def test_complete_preserves_prior_state(self, decision_made_state: AIState) -> None:
        new_state = decision_made_state.complete()

        assert new_state.intent_result is decision_made_state.intent_result
        assert new_state.decision_result is decision_made_state.decision_result
        assert new_state.customer_message == decision_made_state.customer_message


# ---------------------------------------------------------------------------
# AIState — full happy-path pipeline (integration-style)
# ---------------------------------------------------------------------------


class TestFullPipelineFlow:
    def test_full_happy_path_produces_completed_state(self, received_state: AIState, intent_result: IntentResult, decision_result: DecisionResult) -> None:
        state = received_state
        state = state.with_intent(intent_result)
        state = state.with_decision(decision_result)
        state = state.with_retrieved_evidence(
            (
                RetrievedEvidence(
                    source_type=EvidenceSourceType.KNOWLEDGE,
                    source_id="chunk-123",
                    title="Refund Policy",
                    section="Processing Time",
                    content="Approved refunds are generally processed within several business days.",
                    relevance_score=0.91,
                ),
            )
        )

        state = state.with_generated_response(
            "Approved refunds are generally processed within several business days."
        )

        state = state.complete()

        assert state.stage is PipelineStage.COMPLETED
        assert state.intent_result is intent_result
        assert state.decision_result is decision_result
        assert len(state.retrieved_evidence) == 1
        evidence = state.retrieved_evidence[0]
        assert evidence.source_type is EvidenceSourceType.KNOWLEDGE
        assert evidence.source_id == "chunk-123"
        assert evidence.title == "Refund Policy"
        assert state.generated_response == "Approved refunds are generally processed within several business days."
        assert state.completed_at is not None
        assert state.errors == ()

    def test_original_received_state_is_never_mutated_through_the_chain(
        self,
        received_state: AIState,
        intent_result: IntentResult,
        decision_result: DecisionResult,
    ) -> None:
        original_stage = received_state.stage

        state = received_state.with_intent(intent_result)
        state = state.with_decision(decision_result)
        state.complete()

        assert received_state.stage == original_stage
        assert received_state.intent_result is None
        assert received_state.decision_result is None
        assert received_state.retrieved_evidence == ()