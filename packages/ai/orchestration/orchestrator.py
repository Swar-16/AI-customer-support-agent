# AI-customer-support-agent\packages\ai\orchestration\orchestrator.py
# The orchestrator coordinates pipeline stages. It does not implement intent logic, decision rules,
# persistence, retries, retrieval algorithms, generation prompts, or business policy itself.
from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from packages.ai.decision.engine import DecisionEngine
from packages.ai.decision.schemas import DecisionReasonCode, DecisionType
from packages.ai.generation.generator import GroundedGenerationError, GroundedGenerationProviderError, GroundedGenerationTimeoutError, InvalidGroundedGenerationResponseError
from packages.ai.generation.models import GroundingStatus
from packages.ai.intent.classifier import IntentClassificationError, IntentClassificationProviderError, IntentClassificationTimeoutError
from packages.ai.intent.classifier import InvalidIntentInputError, InvalidIntentResponseError, IntentClassifier
from packages.ai.orchestration.state import AIState, EscalationSource,  GuardrailDisposition, PipelineError, PipelineStage
from packages.application.ai.answer_service import AnswerService, AnswerServiceError, AnswerServiceRequest, InvalidRetrievalDecisionError
from packages.application.ai.answer_service import UnsupportedAnswerDecisionError, UnsupportedRetrievalKindError
from packages.guardrails.evaluator import GuardrailEvaluator
from packages.guardrails.models import GuardrailContext, GuardrailOutcome
from packages.ai.orchestration.direct_response import DirectResponseResolutionError, DirectResponseResolver
from packages.ai.intent.taxonomy import IntentType

_DEFAULT_CLARIFICATION_RESPONSE: Final[str] = (
    "I need a little more information to help with this request. "
    "Please describe what happened, what outcome you expected, and "
    "any error or status message you saw. Do not share passwords, "
    "one-time codes, full payment-card numbers, or other credentials."
)

_UNKNOWN_INTENT_CLARIFICATION_RESPONSE: Final[str] = (
    "I couldn’t determine what support you need from that message. "
    "Please briefly describe the issue—for example, whether it concerns "
    "a payment, refund, return, delivery, subscription, or account."
)

_CLARIFICATION_RESPONSES: Final[dict[str, str]] = {
    "customer_intent": _UNKNOWN_INTENT_CLARIFICATION_RESPONSE,
    "clarification": _DEFAULT_CLARIFICATION_RESPONSE,
    "order_id": (
        "Please provide the order ID whose current status you want to "
        "check. Do not include passwords, one-time codes, or payment-card "
        "details."
    ),
    "order_id_or_transaction_id": (
        "Please provide the relevant order ID or transaction reference "
        "and briefly describe what happened—for example, whether the "
        "payment was declined, duplicated, or is still pending. Do not "
        "share a full payment-card number, password, or one-time code."
    ),
    "subscription_id": (
        "Please provide the subscription reference and describe the "
        "problem—for example, an unexpected renewal, cancellation issue, "
        "or unavailable service. Do not share passwords or payment-card "
        "details."
    ),
}

_INTENT_CLARIFICATION_RESPONSES: Final[dict[IntentType, str]] = {
    IntentType.REFUND_REQUEST: (
        "Please tell me when the refund was requested, what status or "
        "message you currently see, and whether the original payment "
        "method is still active. You may include a non-sensitive order "
        "or transaction reference, but do not share full card details, "
        "passwords, or one-time codes."
    ),
    IntentType.PAYMENT_ISSUE: (
        "Please describe what happened with the payment—for example, "
        "whether it was declined, duplicated, reversed, or remains "
        "pending—and include a non-sensitive order or transaction "
        "reference if available. Do not share full card details, "
        "passwords, or one-time codes."
    ),
    IntentType.ORDER_STATUS: (
        "Please provide the order ID whose status you want to check. "
        "Do not include passwords, one-time codes, or payment-card "
        "details."
    ),
    IntentType.SHIPPING_ISSUE: (
        "Please describe the delivery problem, including the expected "
        "delivery date and the latest tracking status you can see. You "
        "may include the order ID, but do not share credentials or "
        "payment-card details."
    ),
    IntentType.CANCELLATION: (
        "Please tell me what you want to cancel—such as an order or "
        "subscription—and whether you have already attempted the "
        "cancellation. Include a non-sensitive reference if available, "
        "but do not share credentials or payment-card details."
    ),
    IntentType.SUBSCRIPTION_ISSUE: (
        "Please describe the subscription problem—for example, an "
        "unexpected renewal, cancellation issue, billing concern, or "
        "unavailable service—and include the subscription reference if "
        "available. Do not share passwords or payment-card details."
    ),
    IntentType.ACCOUNT_ISSUE: (
        "Please describe the account problem and any safe error message "
        "you see—for example, whether you cannot sign in, the account is "
        "locked, or a setting cannot be changed. Do not share your "
        "password, recovery code, or one-time code."
    ),
    IntentType.RETURN_EXCHANGE: (
        "Please tell me what item you are trying to return or exchange, "
        "when it was delivered, and the rejection reason or status "
        "message you were shown. You may include the order ID, but do "
        "not share credentials or payment-card details."
    ),
    IntentType.GENERAL_QUESTION: (
        "Please rephrase the company, product, service, or policy "
        "information you want to know. You do not need to provide "
        "private account or payment information."
    ),
}

_DEFAULT_GUARDRAIL_REFUSAL_RESPONSE: Final[str] = (
    "I’m unable to help with that request. I can assist with supported customer-service questions about refunds, payments, cancellations, "
    "subscriptions, shipping, returns, exchanges, and accounts."
)

_DEFAULT_ESCALATION_NOTICE: Final[str] = (
    "I couldn’t complete this request safely through automated support, "
    "so I requested human review. Your message has been saved for the "
    "support team. Please do not send passwords, one-time codes, full "
    "payment-card numbers, or other credentials."
)

_KNOWLEDGE_GAP_ESCALATION_NOTICE: Final[str] = (
    "I couldn’t find enough verified information to answer this request "
    "reliably, so I requested human review. Your message has been saved "
    "for the support team. Please do not send passwords, one-time codes, "
    "full payment-card numbers, or other credentials."
)

_GUARDRAIL_ESCALATION_NOTICE: Final[str] = (
    "I’m unable to provide the proposed automated response safely, so I "
    "requested human review. Your message has been saved for the support "
    "team. Please do not send passwords, one-time codes, full "
    "payment-card numbers, or other credentials."
)

_ESCALATION_NOTICES: Final[dict[DecisionReasonCode, str]] = {
    DecisionReasonCode.CUSTOMER_REQUESTED_HUMAN: (
        "I requested human support for this conversation. Your message "
        "has been saved, and a support agent can review the available "
        "conversation history. Please do not send passwords, one-time "
        "codes, full payment-card numbers, or other credentials."
    ),
    DecisionReasonCode.SEVERE_CUSTOMER_DISSATISFACTION: (
        "I’m sorry this issue has remained unresolved. I requested human "
        "review so a support agent can examine the conversation and the "
        "problem you reported. Please do not send passwords, one-time "
        "codes, full payment-card numbers, or other credentials."
    ),
    DecisionReasonCode.SECURITY_SENSITIVE_REQUEST: (
        "I requested urgent human review because this may involve account "
        "security. Until it is reviewed, do not share passwords or "
        "one-time codes, change your password through the official "
        "account-security or recovery page, and secure the email account "
        "connected to your profile."
    ),
    DecisionReasonCode.OPERATIONAL_LOOKUP_UNAVAILABLE: (
        "I can’t access the private operational record needed to confirm "
        "the current status of this request, so I requested human review. "
        "Your message and the available reference have been saved for the "
        "support team."
    ),
    DecisionReasonCode.HUMAN_APPROVAL_REQUIRED: (
        "This request requires authorization from a human support agent, "
        "so I requested human review. No business action has been "
        "completed yet."
    ),
    DecisionReasonCode.POLICY_CONFLICT: (
        "The available support guidance does not provide a clear, "
        "consistent answer for this case, so I requested human review. "
        "No business action has been completed yet."
    ),
    DecisionReasonCode.KNOWLEDGE_UNAVAILABLE: _KNOWLEDGE_GAP_ESCALATION_NOTICE,
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
            intent=state.intent_result.intent if state.intent_result is not None else None,
            required_information=decision.required_information,
        )
        generated_state = self._complete_generation(
            state=state,
            answer=response,
        )

        return self._evaluate_guardrails(generated_state)

    @staticmethod
    def _resolve_clarification_response(*, intent: IntentType | None, required_information: tuple[str, ...]) -> str:
        """
        Resolve a safe, application-controlled clarification response.

        Explicit requirement keys take precedence. When the decision layer only provides the generic ``clarification`` key,
        the canonical intent is used to request useful, bounded information.

        Customer-controlled text and model-generated reason summaries are never interpolated into the response.
        """
        if not isinstance(required_information, tuple):
            raise TypeError("required_information must be a tuple")

        if intent is not None and not isinstance(intent, IntentType):
            raise TypeError("intent must be an IntentType instance or None")

        # UNKNOWN means the customer's support goal could not be established.
        # Do not pretend that a specific identifier is sufficient.
        if intent is IntentType.UNKNOWN:
            return _UNKNOWN_INTENT_CLARIFICATION_RESPONSE

        # A single specific deterministic requirement is authoritative.
        if len(required_information) == 1:
            requirement = required_information[0]

            if requirement != "clarification":
                response = _CLARIFICATION_RESPONSES.get(requirement)
                if response is not None:
                    return response

        # The decision layer knows the workflow but could not express a more
        # specific structured requirement. Use an allowlisted intent response.
        if intent is not None:
            response = _INTENT_CLARIFICATION_RESPONSES.get(intent)
            if response is not None:
                return response

        # Unknown future requirement keys fail safely to bounded generic text.
        return _DEFAULT_CLARIFICATION_RESPONSE

    @staticmethod
    def _resolve_escalation_notice(*, reason_code: DecisionReasonCode) -> str:
        """
        Resolve safe application-controlled escalation text.

        The response is selected only from allowlisted structured reason codes. Customer text, model output,
        provider errors, and internal reason summaries are never interpolated.
        """
        if not isinstance(reason_code, DecisionReasonCode):
            raise TypeError("reason_code must be a DecisionReasonCode instance")

        return _ESCALATION_NOTICES.get(reason_code, _DEFAULT_ESCALATION_NOTICE)
    
    def _escalate_from_knowledge_gap(self, state: AIState) -> AIState:
        """
        Escalate when published knowledge cannot support a reliable answer.

        The provider-generated insufficient-evidence candidate remains internal.
        A separate application-controlled customer notice is attached to the escalation and may be persisted safely.

        This is a normal human-review disposition, not an infrastructure failure.
        """
        if state.stage is not PipelineStage.RESPONSE_GENERATED:
            raise RuntimeError("Knowledge-gap escalation requires a generated result")

        if state.intent_result is None:
            raise RuntimeError("Knowledge-gap escalation reached without intent_result")

        if state.decision_result is None:
            raise RuntimeError("Knowledge-gap escalation reached without decision_result")

        if state.decision_result.decision is not DecisionType.RETRIEVE_INFORMATION:
            raise RuntimeError("Knowledge-gap escalation requires a RETRIEVE_INFORMATION decision")

        self._observer.stage_started(state=state, stage=PipelineStage.ESCALATED)
        escalated_state = state.with_escalation(
            source=EscalationSource.SYSTEM,
            reason_code=DecisionReasonCode.KNOWLEDGE_UNAVAILABLE.value,
            customer_notice=_KNOWLEDGE_GAP_ESCALATION_NOTICE,
        )
        self._observer.stage_completed(state=escalated_state, stage=PipelineStage.ESCALATED)

        return escalated_state
    
    def _escalate_from_decision(self, state: AIState) -> AIState:
        """
        Transition a deterministic DecisionEngine escalation into human review.

        This records the orchestration disposition and attaches safe, application-controlled customer-facing text.
        Creating the persistent escalation record belongs to the application layer.

        This method does not claim that a ticket was created, an agent has already reviewed the request, or any business action was completed.
        """
        if state.decision_result is None:
            raise RuntimeError("Decision escalation reached without decision_result")

        self._observer.stage_started(state=state, stage=PipelineStage.ESCALATED)
        reason_code = state.decision_result.reason_code
        customer_notice = self._resolve_escalation_notice(reason_code=reason_code)
        next_state = state.with_escalation(source=EscalationSource.DECISION, reason_code=reason_code.value, customer_notice=customer_notice)
        self._observer.stage_completed(state=next_state, stage=PipelineStage.ESCALATED)

        return next_state
    
    def _escalate_from_guardrail(self, *, state: AIState, reason_code: str, policy_id: str | None) -> AIState:
        """
        Transition a guardrail rejection into human review.

        The rejected generated candidate remains internal and is never authorized for customer-message persistence.

        Only sanitized guardrail identifiers are retained in orchestration state.
        """
        if state.stage is not PipelineStage.RESPONSE_GENERATED:
            raise RuntimeError("Guardrail escalation requires a generated candidate")

        if not isinstance(reason_code, str):
            raise TypeError("reason_code must be a string")

        if not reason_code.strip():
            raise ValueError("reason_code cannot be blank")

        if policy_id is not None:
            if not isinstance(policy_id, str):
                raise TypeError("policy_id must be a string or None")

            if not policy_id.strip():
                raise ValueError("policy_id cannot be blank when provided")

        # Guardrail evaluation itself completed successfully. Its result redirected the workflow rather than producing a pipeline failure.
        escalated_state = state.with_guardrail_escalation(
            escalation_reason_code=reason_code,
            guardrail_reason_code=reason_code,
            customer_notice=_GUARDRAIL_ESCALATION_NOTICE,
            policy_id=policy_id,
        )
        # The guardrail stage completed normally with an ESCALATE disposition.
        # Use the annotated immutable state so structured telemetry receives the disposition and reason.
        self._observer.stage_completed(state=escalated_state, stage=PipelineStage.GUARDRAILS_COMPLETED)
        self._observer.stage_started(state=escalated_state, stage=PipelineStage.ESCALATED)
        self._observer.stage_completed(state=escalated_state, stage=PipelineStage.ESCALATED)

        return escalated_state

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
            grounding_status = result.generation.grounding_status
            if grounding_status is GroundingStatus.INSUFFICIENT_EVIDENCE:
                return self._escalate_from_knowledge_gap(generated_state)

            if grounding_status is GroundingStatus.NOT_REQUIRED:
                return self._fail(
                    state=generated_state,
                    stage=PipelineStage.RESPONSE_GENERATED,
                    code="GROUNDING_STATUS_INVALID",
                    message="A knowledge-retrieval workflow returned an incompatible grounding status.",
                    retryable=False,
                    metadata={"grounding_status": grounding_status.value,},
                )

            if grounding_status is not GroundingStatus.GROUNDED:
                return self._fail(
                    state=generated_state,
                    stage=PipelineStage.RESPONSE_GENERATED,
                    code="GROUNDING_STATUS_UNSUPPORTED",
                    message="The generation workflow returned an unsupported grounding status.",
                    retryable=False,
                    metadata={"grounding_status": str(grounding_status),},
                )

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

        Guardrail dispositions are handled as follows:

        - PASS authorizes the generated response.
        - ESCALATE preserves the candidate internally and requests human review.
        - REFUSE discards the candidate and substitutes an application-controlled
        customer refusal.
        - Unknown outcomes fail closed.
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
            next_state = state.with_guardrails_completed(
                disposition=GuardrailDisposition.PASS,
                reason_code=result.reason_code.value,
                policy_id=result.policy_id,
            )
            self._observer.stage_completed(state=next_state, stage=PipelineStage.GUARDRAILS_COMPLETED)

            return next_state
        
        if result.outcome is GuardrailOutcome.ESCALATE:
            return self._escalate_from_guardrail(state=state, reason_code=result.reason_code.value, policy_id=result.policy_id)

        if result.outcome is GuardrailOutcome.REFUSE:
            return self._complete_safe_refusal(
                state=state,
                reason_code=result.reason_code.value,
                policy_id=result.policy_id,
            )

        return self._fail(
            state=state,
            stage=PipelineStage.GUARDRAILS_COMPLETED,
            code="GUARDRAIL_OUTCOME_UNSUPPORTED",
            message="The guardrail evaluator returned an unsupported disposition.",
            retryable=False,
            metadata={"guardrail_outcome": str(result.outcome),},
        )
    
    def _complete_safe_refusal(self, *, state: AIState, reason_code: str, policy_id: str | None) -> AIState:
        """
        Replace a rejected generated candidate with an application-controlled refusal response.

        The original candidate must never be returned or persisted. The refusal text is owned by the application and contains
        no customer-controlled, provider-controlled, or policy-diagnostic content.
        """
        if state.stage is not PipelineStage.RESPONSE_GENERATED:
            raise RuntimeError("Safe refusal requires a generated candidate")

        if not isinstance(reason_code, str):
            raise TypeError("reason_code must be a string")

        if not reason_code.strip():
            raise ValueError("reason_code cannot be blank")

        if policy_id is not None:
            if not isinstance(policy_id, str):
                raise TypeError("policy_id must be a string or None")

            if not policy_id.strip():
                raise ValueError("policy_id cannot be blank when provided")

        # with_generated_response() returns a new immutable state. It replaces
        # the rejected candidate instead of mutating or exposing it.
        refusal_state = state.with_generated_response(
            _DEFAULT_GUARDRAIL_REFUSAL_RESPONSE
        )

        completed_state = refusal_state.with_guardrails_completed(
            disposition=GuardrailDisposition.REFUSE,
            reason_code=reason_code,
            policy_id=policy_id,
        )

        self._observer.stage_completed(
            state=completed_state,
            stage=PipelineStage.GUARDRAILS_COMPLETED,
        )

        return completed_state

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