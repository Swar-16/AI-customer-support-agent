# AI-customer-support-agent\packages\ai\orchestration\orchestrator.py
# The orchestrator coordinates pipeline stages. It does not implement intent logic, decision rules,
# persistence, retries, retrieval algorithms, generation prompts, or business policy itself.
from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from packages.ai.decision.engine import DecisionEngine
from packages.ai.decision.schemas import DecisionType
from packages.ai.generation.generator import GroundedGenerationError, GroundedGenerationProviderError, GroundedGenerationTimeoutError, InvalidGroundedGenerationResponseError
from packages.ai.intent.classifier import IntentClassificationError, IntentClassificationProviderError, IntentClassificationTimeoutError
from packages.ai.intent.classifier import InvalidIntentInputError, InvalidIntentResponseError, IntentClassifier
from packages.ai.orchestration.state import AIState, EscalationSource, PipelineError, PipelineStage
from packages.application.ai.answer_service import AnswerService, AnswerServiceError, AnswerServiceRequest, InvalidRetrievalDecisionError
from packages.application.ai.answer_service import UnsupportedAnswerDecisionError, UnsupportedRetrievalKindError
from packages.guardrails.evaluator import GuardrailEvaluator
from packages.guardrails.models import GuardrailContext, GuardrailOutcome
from packages.ai.orchestration.direct_response import DirectResponseResolutionError, DirectResponseResolver

_DEFAULT_CLARIFICATION_RESPONSE: Final[str] = "Could you provide a little more detail so I can help you correctly?"

_CLARIFICATION_RESPONSES: Final[dict[str, str]] = {
    "customer_intent": "Could you tell me what you need help with?",
    "clarification": _DEFAULT_CLARIFICATION_RESPONSE,
    "order_id": "Could you provide the order ID so I can help with this request?",
    "order_id_or_transaction_id": "Could you provide the order ID or transaction ID so I can help with this request?",
    "subscription_id": "Could you provide the subscription ID so I can help with this request?",
}


# Observer contract
@runtime_checkable
class OrchestrationObserver(Protocol):
    """
    Observer contract for orchestration lifecycle events.

    Implementations may emit:
        - structured logs;
        - OpenTelemetry spans;
        - Prometheus metrics;
        - persistence events;
        - test assertions.

    The orchestrator does not know how observability is implemented.
    """
    def stage_started(self, *, state: AIState, stage: PipelineStage) -> None:
        ...

    def stage_completed(self, *, state: AIState, stage: PipelineStage) -> None:
        ...

    def stage_failed(self, *, state: AIState, stage: PipelineStage, error: PipelineError) -> None:
        ...

class NullOrchestrationObserver:
    """
    Default no-op observer.

    Avoids repeated observer-is-not-None checks throughout orchestration.
    """
    def stage_started(self, *, state: AIState, stage: PipelineStage) -> None:
        pass

    def stage_completed(self, *, state: AIState, stage: PipelineStage) -> None:
        pass

    def stage_failed(self, *, state: AIState, stage: PipelineStage, error: PipelineError) -> None:
        pass

# Configuration
@dataclass(frozen=True, slots=True)
class AIOrchestratorConfig:
    """
    Configuration describing this version of the AI pipeline.

    The pipeline version is persisted with ai.runs so historical runs remain attributable to the orchestration version that produced them.
    """
    pipeline_version: str = "v1"

    def __post_init__(self) -> None:
        if not isinstance(self.pipeline_version, str):
            raise TypeError("pipeline_version must be a string")

        normalized = self.pipeline_version.strip()
        if not normalized:
            raise ValueError("pipeline_version cannot be empty")

        object.__setattr__(self, "pipeline_version", normalized)

# Orchestrator
class AIOrchestrator:
    """
    Coordinates execution of the customer-support AI pipeline.

    Current V1 flow:

        customer message
              |
              v
        IntentClassifier
              |
              v
        IntentResult
              |
              v
        DecisionEngine
              |
              v
        DecisionResult
              |
              +--> ANSWER
              |      |
              |      +--> deterministic direct response
              |
              +--> RETRIEVE_INFORMATION
              |      |
              |      +--> AnswerService
              |
              +--> ASK_CLARIFICATION
              |      |
              |      +--> deterministic clarification response
              |
              +--> ESCALATE
                      |
                      +--> human-review disposition

     Response-producing paths
              |
              v
        RESPONSE_GENERATED
              |
              v
        GuardrailEvaluator
              |
              +--> GUARDRAILS_COMPLETED
              +--> ESCALATED
              +--> FAILED


    AnswerService owns the implementation boundary for retrieval and grounded generation. The orchestrator therefore does not know about:

        - embeddings;
        - vector search;
        - lexical search;
        - RRF;
        - reranking;
        - knowledge chunks;
        - grounding-context internals;
        - generation prompts.

    Future stages may extend this pipeline with:
        - guardrails;
        - operational tools;
        - actions;
        - escalation.
    """
    def __init__(self, *, intent_classifier: IntentClassifier, decision_engine: DecisionEngine, answer_service: AnswerService | None = None,
                 direct_response_resolver: DirectResponseResolver | None = None, guardrail_evaluator: GuardrailEvaluator | None = None,
                 observer: OrchestrationObserver | None = None, config: AIOrchestratorConfig | None = None
    ) -> None:
        if intent_classifier is None:
            raise TypeError("intent_classifier cannot be None")

        if decision_engine is None:
            raise TypeError("decision_engine cannot be None")

        if answer_service is not None and not isinstance(answer_service, AnswerService):
            raise TypeError("answer_service must be an AnswerService instance or None")
        
        if direct_response_resolver is not None and not isinstance(direct_response_resolver, DirectResponseResolver):
            raise TypeError("direct_response_resolver must be a DirectResponseResolver instance or None")
        
        if guardrail_evaluator is not None and not isinstance(guardrail_evaluator, GuardrailEvaluator):
            raise TypeError("guardrail_evaluator must be a GuardrailEvaluator instance or None")

        if observer is not None and not isinstance(observer, OrchestrationObserver):
            raise TypeError("observer must satisfy OrchestrationObserver")

        if config is not None and not isinstance(config, AIOrchestratorConfig):
            raise TypeError("config must be an AIOrchestratorConfig instance or None")

        self._intent_classifier = intent_classifier
        self._decision_engine = decision_engine
        self._answer_service = answer_service
        self._direct_response_resolver = direct_response_resolver if direct_response_resolver is not None else DirectResponseResolver()
        self._guardrail_evaluator = guardrail_evaluator
        self._observer = observer if observer is not None else NullOrchestrationObserver()
        self._config = config if config is not None else AIOrchestratorConfig()

    # Public API
    def process_message(self, *, ai_run_id: uuid.UUID, trace_id: uuid.UUID, conversation_id: uuid.UUID, trigger_message_id: uuid.UUID,
                        customer_message: str, conversation_context: str | None = None) -> AIState:
        """
        Execute the currently implemented orchestration stages.

        The caller owns persistence and creates/persists run identifiers before invoking this orchestrator.

        Every decision is converted into an explicit terminal disposition:

            - an approved customer response;
            - an escalation request; or
            - a typed FAILED state.

        Known operational failures are converted into PipelineError instances and represented by a FAILED AIState.

        Unexpected programming/invariant defects intentionally propagate rather than being disguised as recoverable AI failures.
        """
        state = AIState(
            ai_run_id=ai_run_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            customer_message=customer_message,
            conversation_context=conversation_context,
            metadata={"pipeline_version": self._config.pipeline_version,},
        )

        state = self._classify_intent(state)
        if state.stage is PipelineStage.FAILED:
            return state

        state = self._make_decision(state)
        if state.stage is PipelineStage.FAILED:
            return state

        return self._execute_decision(state)

    # Intent classification
    def _classify_intent(self, state: AIState) -> AIState:
        self._observer.stage_started(state=state, stage=PipelineStage.INTENT_CLASSIFIED)
        try:
            result = self._intent_classifier.classify(customer_message=state.customer_message, conversation_context=state.conversation_context)
            next_state = state.with_intent(result)
            self._observer.stage_completed(state=next_state, stage=PipelineStage.INTENT_CLASSIFIED)

            return next_state

        except InvalidIntentInputError:
            return self._fail(
                state=state,
                stage=PipelineStage.INTENT_CLASSIFIED,
                code="INTENT_INVALID_INPUT",
                message="The input could not be processed for intent classification.",
                retryable=False,
            )

        except IntentClassificationTimeoutError:
            return self._fail(
                state=state,
                stage=PipelineStage.INTENT_CLASSIFIED,
                code="INTENT_PROVIDER_TIMEOUT",
                message="Intent classification timed out.",
                retryable=True,
            )

        except InvalidIntentResponseError:
            return self._fail(
                state=state,
                stage=PipelineStage.INTENT_CLASSIFIED,
                code="INTENT_INVALID_RESPONSE",
                message="The intent provider returned an invalid structured response.",
                retryable=True,
            )

        except IntentClassificationProviderError:
            return self._fail(
                state=state,
                stage=PipelineStage.INTENT_CLASSIFIED,
                code="INTENT_PROVIDER_FAILURE",
                message="The intent classification provider failed.",
                retryable=True,
            )

        except IntentClassificationError:
            return self._fail(
                state=state,
                stage=PipelineStage.INTENT_CLASSIFIED,
                code="INTENT_CLASSIFICATION_FAILURE",
                message="Intent classification could not be completed.",
                retryable=False,
            )

    # Decision
    def _make_decision(self, state: AIState) -> AIState:
        if state.intent_result is None:
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
                message="The system could not determine the next workflow action.",
                retryable=False,
                metadata={"exception_type": type(exc).__name__,},
            )

    # Decision execution
    def _execute_decision(self, state: AIState) -> AIState:
        """
        Execute workflows currently supported by this pipeline version.

        Knowledge retrieval is implemented through AnswerService.

        Unsupported decisions fail explicitly rather than escaping as a false-success DECISION_MADE state.
        """
        if state.decision_result is None:
            raise RuntimeError("Decision execution reached without decision_result")

        decision = state.decision_result.decision
        
        if decision is DecisionType.ANSWER:
            return self._answer_directly(state)
        
        if decision is DecisionType.RETRIEVE_INFORMATION:
            return self._retrieve_and_generate(state)

        if decision is DecisionType.ASK_CLARIFICATION:
            return self._request_clarification(state)

        if decision is DecisionType.ESCALATE:
            return self._escalate_from_decision(state)

        return self._fail(
            state=state,
            stage=PipelineStage.DECISION_MADE,
            code="DECISION_WORKFLOW_UNSUPPORTED",
            message="The selected workflow is not implemented by this pipeline version.",
            retryable=False,
            metadata={"decision": decision.value},
        )

    def _answer_directly(self, state: AIState) -> AIState:
        """
        Produce an application-controlled direct response.

        This workflow is limited to intents explicitly supported by DirectResponseResolver.
        It performs no knowledge retrieval, provider generation, operational lookup, or business action.

        The selected response still passes through the normal response-generation lifecycle and guardrails before it becomes eligible for persistence.
        """
        intent_result = state.intent_result
        if intent_result is None:
            raise RuntimeError("Direct-answer workflow reached without intent_result")

        decision_result = state.decision_result
        if decision_result is None:
            raise RuntimeError("Direct-answer workflow reached without decision_result")

        if decision_result.decision is not DecisionType.ANSWER:
            raise RuntimeError("Direct-answer workflow requires an ANSWER decision")

        try:
            direct_response = self._direct_response_resolver.resolve(
                customer_message=state.customer_message, intent_result=intent_result, decision_result=decision_result
            )

        except DirectResponseResolutionError as exc:
            return self._fail(
                state=state,
                stage=PipelineStage.RESPONSE_GENERATED,
                code="DIRECT_RESPONSE_UNAVAILABLE",
                message="A safe direct customer response could not be resolved.",
                retryable=False,
                metadata={
                    "exception_type": type(exc).__name__,
                    "intent": intent_result.intent.value,
                    "decision": decision_result.decision.value,
                },
            )

        generated_state = self._complete_generation(state=state, answer=direct_response.text)

        return self._evaluate_guardrails(generated_state)

    def _request_clarification(self, state: AIState) -> AIState:
        """Create an allowlisted clarification response without another provider call."""
        decision = state.decision_result
        if decision is None:
            raise RuntimeError("Clarification reached without decision_result")

        if decision.decision is not DecisionType.ASK_CLARIFICATION:
            raise RuntimeError("Clarification requires an ASK_CLARIFICATION decision")

        response = self._resolve_clarification_response(
            required_information=decision.required_information,
        )
        generated_state = self._complete_generation(
            state=state,
            answer=response,
        )

        return self._evaluate_guardrails(generated_state)

    @staticmethod
    def _resolve_clarification_response(*, required_information: tuple[str, ...]) -> str:
        """
        Resolve only application-controlled response text.

        Unknown requirement keys deliberately fall back to generic wording;
        internal routing vocabulary is never interpolated into customer text.
        """
        if len(required_information) != 1:
            return _DEFAULT_CLARIFICATION_RESPONSE

        return _CLARIFICATION_RESPONSES.get(required_information[0], _DEFAULT_CLARIFICATION_RESPONSE)
    
    def _escalate_from_decision(self, state: AIState) -> AIState:
        """
        Transition a deterministic DecisionEngine escalation into human review.

        This records the orchestration disposition only. Creating the persistent escalation record/ticket belongs to the application layer.
        """
        if state.decision_result is None:
            raise RuntimeError("Decision escalation reached without decision_result")

        self._observer.stage_started(state=state, stage=PipelineStage.ESCALATED)
        next_state = state.with_escalation(source=EscalationSource.DECISION, reason_code=state.decision_result.reason_code.value)
        self._observer.stage_completed(state=next_state, stage=PipelineStage.ESCALATED)

        return next_state
    
    def _escalate_from_guardrail(self, *, state: AIState, reason_code: str) -> AIState:
        """
        Transition a guardrail rejection requiring human review into ESCALATED.

        The generated response remains internal diagnostic state. Reaching ESCALATED does not authorize that candidate for customer persistence.
        """
        self._observer.stage_started(state=state, stage=PipelineStage.ESCALATED)
        next_state = state.with_escalation(source=EscalationSource.GUARDRAIL, reason_code=reason_code)
        self._observer.stage_completed(state=next_state, stage=PipelineStage.ESCALATED)

        return next_state

    # Retrieval + grounded generation
    def _retrieve_and_generate(self, state: AIState) -> AIState:
        """
        Execute the application-level retrieval + generation workflow.

        AnswerService performs retrieval, evidence mapping, and grounded generation atomically from the orchestrator's perspective.

        AIState transitions are still performed here because orchestration owns pipeline lifecycle state.
        """
        if state.intent_result is None:
            raise RuntimeError("Retrieval stage reached without intent_result")

        if state.decision_result is None:
            raise RuntimeError("Retrieval stage reached without decision_result")

        if self._answer_service is None:
            return self._fail(
                state=state,
                stage=PipelineStage.RETRIEVAL_COMPLETED,
                code="ANSWER_SERVICE_UNAVAILABLE",
                message="The answer workflow is not configured for this pipeline.",
                retryable=False,
            )

        self._observer.stage_started(state=state, stage=PipelineStage.RETRIEVAL_COMPLETED)

        try:
            result = self._answer_service.answer(
                request=AnswerServiceRequest(
                    customer_message=state.customer_message,
                    intent_result=state.intent_result,
                    decision_result=state.decision_result,
                    conversation_context=state.conversation_context,
                )
            )

            retrieved_state = state.with_retrieved_evidence(result.evidence)
            self._observer.stage_completed(state=retrieved_state, stage=PipelineStage.RETRIEVAL_COMPLETED)
            generated_state = self._complete_generation(state=retrieved_state, answer=result.generation.answer)

            return self._evaluate_guardrails(generated_state)

        except UnsupportedRetrievalKindError as exc:
            return self._fail(
                state=state,
                stage=PipelineStage.RETRIEVAL_COMPLETED,
                code="RETRIEVAL_KIND_UNSUPPORTED",
                message="The requested retrieval source is not supported by this pipeline version.",
                retryable=False,
                metadata={"exception_type": type(exc).__name__,},
            )

        except (InvalidRetrievalDecisionError, UnsupportedAnswerDecisionError,) as exc:
            return self._fail(
                state=state,
                stage=PipelineStage.RETRIEVAL_COMPLETED,
                code="RETRIEVAL_DECISION_INVALID",
                message="The retrieval decision could not be executed.",
                retryable=False,
                metadata={"exception_type": type(exc).__name__,},
            )

        except GroundedGenerationTimeoutError as exc:
            return self._fail(
                state=state,
                stage=PipelineStage.RESPONSE_GENERATED,
                code="GENERATION_PROVIDER_TIMEOUT",
                message="Grounded response generation timed out.",
                retryable=True,
                metadata={"exception_type": type(exc).__name__,},
            )

        except GroundedGenerationProviderError as exc:
            return self._fail(
                state=state,
                stage=PipelineStage.RESPONSE_GENERATED,
                code="GENERATION_PROVIDER_FAILURE",
                message="The response generation provider failed.",
                retryable=True,
                metadata={"exception_type": type(exc).__name__,},
            )

        except InvalidGroundedGenerationResponseError as exc:
            return self._fail(
                state=state,
                stage=PipelineStage.RESPONSE_GENERATED,
                code="GENERATION_INVALID_RESPONSE",
                message="The response generator returned an invalid grounded response.",
                retryable=True,
                metadata={"exception_type": type(exc).__name__,},
            )

        except GroundedGenerationError as exc:
            return self._fail(
                state=state,
                stage=PipelineStage.RESPONSE_GENERATED,
                code="GENERATION_FAILURE",
                message="Grounded response generation could not be completed.",
                retryable=False,
                metadata={"exception_type": type(exc).__name__,},
            )

        except AnswerServiceError as exc:
            return self._fail(
                state=state,
                stage=PipelineStage.RETRIEVAL_COMPLETED,
                code="ANSWER_WORKFLOW_FAILURE",
                message="The grounded answer workflow could not be completed.",
                retryable=False,
                metadata={"exception_type": type(exc).__name__,},
            )

    def _complete_generation(self, *, state: AIState, answer: str) -> AIState:
        """
        Apply the generation lifecycle transition.

        Generation itself already occurred inside AnswerService. This method records that result in generic orchestration
        state and emits the corresponding lifecycle event.
        """
        self._observer.stage_started(state=state, stage=PipelineStage.RESPONSE_GENERATED)
        next_state = state.with_generated_response(answer)
        self._observer.stage_completed(state=next_state, stage=PipelineStage.RESPONSE_GENERATED)

        return next_state
    
    def _evaluate_guardrails(self, state: AIState) -> AIState:
        """
        Evaluate the generated response before it may be treated as an approved customer-facing response.

        Guardrail policy violations are normal workflow outcomes rather than evaluator exceptions.

        Until dedicated refusal and escalation workflows are implemented, rejected responses are converted into controlled FAILED
        states. This prevents an unsafe generated candidate from being treated as a successful customer response.
        """
        if state.stage is not PipelineStage.RESPONSE_GENERATED:
            raise RuntimeError("Guardrail evaluation reached before response generation")

        if state.decision_result is None:
            raise RuntimeError("Guardrail evaluation reached without decision_result")

        if state.generated_response is None:
            raise RuntimeError("Guardrail evaluation reached without generated_response")

        # Transitional compatibility:
        # existing pipelines that have not yet been composed with guardrails retain their previous RESPONSE_GENERATED behavior.
        if self._guardrail_evaluator is None:
            return state

        self._observer.stage_started(state=state, stage=PipelineStage.GUARDRAILS_COMPLETED)
        context = GuardrailContext(
            customer_message=state.customer_message,
            decision=state.decision_result,
            generated_response=state.generated_response,
            retrieved_evidence=state.retrieved_evidence,
        )

        result = self._guardrail_evaluator.evaluate(context)
        if result.outcome is GuardrailOutcome.PASS:
            next_state = state.with_guardrails_completed()
            self._observer.stage_completed(state=next_state, stage=PipelineStage.GUARDRAILS_COMPLETED)

            return next_state
        
        if result.outcome is GuardrailOutcome.ESCALATE:
            return self._escalate_from_guardrail(state=state, reason_code=result.reason_code.value)

        # REFUSE does not yet have its own customer-response workflow.
        # Keep it fail-closed rather than exposing the rejected candidate.
        return self._fail(
            state=state,
            stage=PipelineStage.GUARDRAILS_COMPLETED,
            code="GUARDRAIL_REFUSED_RESPONSE",
            message="The generated response was refused by customer-response guardrails.",
            retryable=False,
            metadata={
                "guardrail_outcome": result.outcome.value,
                "guardrail_reason_code": result.reason_code.value,
                "guardrail_policy_id": result.policy_id,
            },
        )

    # Failure handling
    def _fail(self, *, state: AIState, stage: PipelineStage, code: str, message: str, retryable: bool, metadata: dict[str, object] | None = None) -> AIState:
        error = PipelineError(
            code=code,
            message=message,
            stage=stage,
            retryable=retryable,
            metadata=dict(metadata or {}),
        )

        failed_state = state.with_error(error)
        self._observer.stage_failed(state=failed_state, stage=stage, error=error)

        return failed_state