# The orchestrator coordinates stages; it does not implement intent logic, decision rules, persistence, retries, RAG, or business policy itself.
from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from packages.ai.decision.engine import DecisionEngine
from packages.ai.intent.classifier import IntentClassificationError, IntentClassificationProviderError, IntentClassificationTimeoutError, InvalidIntentInputError, InvalidIntentResponseError, IntentClassifier
from packages.ai.orchestration.state import AIState, PipelineError, PipelineStage

# Observer contract
@runtime_checkable
class OrchestrationObserver(Protocol):
    """
    Observer contract for orchestration lifecycle events.

    Implementations may later emit:
      - structured logs
      - OpenTelemetry spans
      - Prometheus metrics
      - persistence events
      - test assertions

    The orchestrator itself does not know HOW observability is implemented.
    """

    def stage_started(self, *, state: AIState, stage: PipelineStage) -> None:
        ...

    def stage_completed(self, *, state: AIState, stage: PipelineStage) -> None:
        ...

    def stage_failed(self, *, state: AIState, stage: PipelineStage, error: PipelineError) -> None:
        ...


class NullOrchestrationObserver:
# No observability backend has been configured, so accept events and safely do nothing.
    """
    Default no-op observer.

    Avoids checks such as:

        if self._observer is not None:

    throughout orchestration code.
    """
    def stage_started(self, *, state: AIState, stage: PipelineStage) -> None:
        pass

    def stage_completed(self, *,state: AIState,stage: PipelineStage) -> None:
        pass

    def stage_failed(self, *, state: AIState, stage: PipelineStage, error: PipelineError) -> None:
        pass


# Configuration
@dataclass(frozen=True, slots=True)
class AIOrchestratorConfig:
    """
    Configuration describing this version of the AI pipeline.

    The pipeline version is persisted with ai.runs so historical runs
    remain reproducible even after orchestration logic evolves.
    """
    pipeline_version: str = "v1"

    def __post_init__(self) -> None:
        if not self.pipeline_version.strip():
            raise ValueError("pipeline_version cannot be empty")


# Orchestrator
class AIOrchestrator:
    """
    Coordinates execution of the customer-support AI pipeline.

    Current V1 flow:
    customer message   ->   IntentClassifier   ->     IntentResult
                                                            ↓
    AIState(stage=DECISION_MADE) <- DecisionResult <- DecisionEngine

    Future stages will extend this pipeline with:
        retrieval
        response generation
        guardrails
        actions
        escalation

    The orchestrator deliberately does NOT:
      - execute SQL
      - know about SQLAlchemy
      - implement LLM provider retries
      - contain classification rules
      - contain decision rules
      - retrieve documents
      - authorize business actions
      - create tickets
    """

    def __init__(self, *, intent_classifier: IntentClassifier, decision_engine: DecisionEngine,
                 observer: OrchestrationObserver | None = None, config: AIOrchestratorConfig | None = None
    ) -> None:
        if intent_classifier is None:
            raise TypeError("intent_classifier cannot be None")

        if decision_engine is None:
            raise TypeError("decision_engine cannot be None")

        self._intent_classifier = intent_classifier
        self._decision_engine = decision_engine
        self._observer = (observer if observer is not None else NullOrchestrationObserver())
        self._config = config or AIOrchestratorConfig()

    
    # Public API
    def process_message(self, *, ai_run_id: uuid.UUID, trace_id: uuid.UUID, conversation_id: uuid.UUID,
                        trigger_message_id: uuid.UUID, customer_message: str, conversation_context: str | None = None
    ) -> AIState:
        """
        Execute the currently implemented orchestration stages.

        The caller is responsible for creating/persisting the AI run
        identifiers before invoking the orchestrator.

        Returns:
            AIState representing either:

                `DECISION_MADE`
            or
                `FAILED`

        Known operational failures are converted into PipelineError objects.

        Unexpected programming/runtime defects are intentionally allowed
        to propagate rather than being silently disguised as user-facing
        AI failures.
        """

        state = AIState(
            ai_run_id=ai_run_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            customer_message=customer_message,
            conversation_context=conversation_context,
            metadata={
                "pipeline_version": self._config.pipeline_version,
            },
        )

        state = self._classify_intent(state)

        if state.stage is PipelineStage.FAILED:
            return state

        state = self._make_decision(state)
        return state


    # Intent classification stage
    def _classify_intent(self, state: AIState) -> AIState:

        self._observer.stage_started(state=state, stage=PipelineStage.INTENT_CLASSIFIED)

        try:
            result = self._intent_classifier.classify(
                customer_message=state.customer_message,
                conversation_context=state.conversation_context,
            )

            next_state = state.with_intent(result)

            self._observer.stage_completed(
                state=next_state,
                stage=PipelineStage.INTENT_CLASSIFIED,
            )

            return next_state

        except InvalidIntentInputError:
            return self._fail(
                state=state,
                stage=PipelineStage.INTENT_CLASSIFIED,
                code="INTENT_INVALID_INPUT",
                message=(
                    "The input could not be processed for "
                    "intent classification."
                ),
                retryable=False,
            )

        except IntentClassificationTimeoutError:
            return self._fail(
                state=state,
                stage=PipelineStage.INTENT_CLASSIFIED,
                code="INTENT_PROVIDER_TIMEOUT",
                message=(
                    "Intent classification timed out."
                ),
                retryable=True,
            )

        except InvalidIntentResponseError:
            return self._fail(
                state=state,
                stage=PipelineStage.INTENT_CLASSIFIED,
                code="INTENT_INVALID_RESPONSE",
                message=(
                    "The intent provider returned an invalid "
                    "structured response."
                ),
                retryable=True,
            )

        except IntentClassificationProviderError:
            return self._fail(
                state=state,
                stage=PipelineStage.INTENT_CLASSIFIED,
                code="INTENT_PROVIDER_FAILURE",
                message=(
                    "The intent classification provider failed."
                ),
                retryable=True,
            )

        except IntentClassificationError:
            return self._fail(
                state=state,
                stage=PipelineStage.INTENT_CLASSIFIED,
                code="INTENT_CLASSIFICATION_FAILURE",
                message=(
                    "Intent classification could not be completed."
                ),
                retryable=False,
            )

    # Decision stage
    def _make_decision(self, state: AIState) -> AIState:

        if state.intent_result is None:
            # This represents a programming/invariant violation,
            # not an expected operational failure.
            raise RuntimeError("Decision stage reached without intent_result")

        self._observer.stage_started(state=state, stage=PipelineStage.DECISION_MADE)

        try:
            result = self._decision_engine.decide(intent_result=state.intent_result)
            next_state = state.with_decision(result)
            self._observer.stage_completed(state=next_state, stage=PipelineStage.DECISION_MADE)
            return next_state

        except (TypeError, ValueError) as exc:
            return self._fail(
                state=state,
                stage=PipelineStage.DECISION_MADE,
                code="DECISION_ENGINE_FAILURE",
                message=(
                    "The system could not determine the next workflow action."
                ),
                retryable=False,
                metadata={
                    "exception_type": type(exc).__name__,
                },
            )


    # Failure handling
    def _fail(self, *, state: AIState, stage: PipelineStage, code: str, message: str,
              retryable: bool, metadata: dict[str, object] | None = None
    ) -> AIState:

        error = PipelineError(
            code=code,
            message=message,
            stage=stage,
            retryable=retryable,
            metadata=dict(metadata or {}),
        )

        failed_state = state.with_error(error)

        self._observer.stage_failed(
            state=failed_state,
            stage=stage,
            error=error,
        )

        return failed_state