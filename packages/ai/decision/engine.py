# AI-customer-support-agent\packages\ai\decision\engine.py
from __future__ import annotations
from dataclasses import dataclass

from packages.ai.decision.policies import IntentDecisionPolicy, RetrievalKind, get_intent_decision_policy
from packages.ai.decision.schemas import DecisionReasonCode, DecisionResult, DecisionType
from packages.ai.intent.schemas import EscalationSignal, IntentResult
from packages.ai.intent.taxonomy import IntentType


@dataclass(frozen=True, slots=True)
class DecisionEngineConfig:
    """
    Configuration for deterministic routing.

    Thresholds are deliberately configurable because they should eventually be calibrated from 
    evaluation data rather than treated as permanent constants.
    """
    low_confidence_threshold: float = 0.60

    def __post_init__(self) -> None:
        if isinstance(self.low_confidence_threshold, bool):
            raise TypeError("low_confidence_threshold must be numeric")

        if not isinstance(self.low_confidence_threshold, (int, float)):
            raise TypeError("low_confidence_threshold must be numeric")

        if not 0.0 <= float(self.low_confidence_threshold) <= 1.0:
            raise ValueError("low_confidence_threshold must be between 0 and 1")

class DecisionEngine:
    """
    Convert validated semantic understanding into a controlled system-level next-step decision.

    The engine is deterministic.

    Responsibilities:
        - enforce confidence/clarification safety gates
        - resolve the default workflow policy for a canonical intent
        - translate that policy into DecisionResult
        - identify currently known missing information conservatively

    Intent-specific default routing belongs in the decision-policy registry rather than in this engine.
    """
    def __init__(self, *, config: DecisionEngineConfig | None = None) -> None:
        self._config = config or DecisionEngineConfig()

    def decide(self, *, intent_result: IntentResult) -> DecisionResult:
        """
        Determine the next workflow step for a validated IntentResult.

        Evaluation order matters:

            1. explicit human-support request
            2. severe unresolved customer dissatisfaction
            3. security-sensitive intent
            4. unknown intent
            5. insufficient classification confidence
            6. deterministically required workflow information
            7. canonical intent decision policy
            8. classifier-detected clarification requirement for workflows that cannot safely proceed without additional information

        Explicit human handoff and safety-sensitive escalation therefore take precedence over clarification and ordinary intent routing.

        Sufficiently confident knowledge-backed requests are allowed to retrieve published guidance even when the classifier marks the
        customer-specific case as incomplete. Retrieval does not authorize an operational lookup or business action.
        """
        if not isinstance(intent_result, IntentResult):
            raise TypeError("intent_result must be an IntentResult instance")

        # 1-2. Explicit allowlisted escalation signals take precedence over ambiguity, confidence, missing identifiers, and normal intent policy.
        signal_decision = self._decision_from_escalation_signals(intent_result)
        if signal_decision is not None:
            return signal_decision

        # 3. Security-sensitive requests are escalated conservatively even when
        # classification confidence is imperfect or additional operational information is unavailable.
        if intent_result.intent is IntentType.PRIVACY_SECURITY:
            return self._decision_from_policy(intent_result=intent_result, policy=get_intent_decision_policy(IntentType.PRIVACY_SECURITY))

        # 4. Genuine unknown support intent.
        if intent_result.intent is IntentType.UNKNOWN:
            return DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.UNKNOWN_INTENT,
                reason_summary="The customer's support intent cannot be determined reliably.",
                confidence=intent_result.confidence,
                required_information=("customer_intent",),
            )

        # 5. Classification confidence is too low for safe normal routing.
        if intent_result.confidence < self._config.low_confidence_threshold:
            return DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.LOW_INTENT_CONFIDENCE,
                reason_summary="Intent confidence is below the configured routing threshold.",
                confidence=intent_result.confidence,
                required_information=("clarification",),
            )

        # 6. Enforce mandatory workflow information independently of the classifier's needs_clarification flag.
        mandatory_missing_information = self._resolve_mandatory_missing_information(intent_result)
        if mandatory_missing_information:
            return DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.MISSING_REQUIRED_INFORMATION,
                reason_summary="The request is missing information required by the selected support workflow.",
                confidence=intent_result.confidence,
                required_information=mandatory_missing_information,
            )

        # 7. Resolve the declarative workflow policy before interpreting the classifier's generic clarification flag.
        policy = get_intent_decision_policy(intent_result.intent)

        # Published knowledge can provide useful policy, procedural, and troubleshooting guidance without accessing a customer-specific
        # business record or performing an action.

        # Therefore, a sufficiently confident knowledge-backed intent may proceed to retrieval even when the classifier believes
        # that more information would be useful for resolving the customer's exact case. The generated answer must still remain
        # grounded and clearly avoid claiming access to operational state.
        if self._can_proceed_with_knowledge_guidance(policy):
            return self._decision_from_policy(intent_result=intent_result, policy=policy)

        # 8. Other workflows may genuinely require additional information before they can proceed.
        if intent_result.needs_clarification:
            missing_information = self._infer_missing_information(intent_result)
            return DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.MISSING_REQUIRED_INFORMATION,
                reason_summary="The intent is understood but additional information is required before processing can continue.",
                confidence=intent_result.confidence,
                required_information=missing_information,
            )

        return self._decision_from_policy(intent_result=intent_result, policy=policy)
    
    @staticmethod
    def _decision_from_escalation_signals(intent_result: IntentResult) -> DecisionResult | None:
        """
        Translate allowlisted classifier signals into deterministic escalation.

        Signal precedence is deliberate:

        1. an explicit request for a human;
        2. severe unresolved dissatisfaction.

        When both are present, the explicit customer request is the clearest reason for the handoff.
        """
        signals = frozenset(intent_result.escalation_signals)
        if EscalationSignal.EXPLICIT_HUMAN_REQUEST in signals:
            return DecisionResult(
                decision=DecisionType.ESCALATE,
                reason_code=DecisionReasonCode.CUSTOMER_REQUESTED_HUMAN,
                reason_summary="The customer explicitly requested assistance from a human support agent.",
                confidence=intent_result.confidence,
                metadata={
                    "escalation_signal": EscalationSignal.EXPLICIT_HUMAN_REQUEST.value,
                    "priority": "normal",
                },
            )

        if EscalationSignal.SEVERE_CUSTOMER_DISSATISFACTION in signals:
            return DecisionResult(
                decision=DecisionType.ESCALATE,
                reason_code=DecisionReasonCode.SEVERE_CUSTOMER_DISSATISFACTION,
                reason_summary="The customer described severe unresolved dissatisfaction requiring human review.",
                confidence=intent_result.confidence,
                metadata={
                    "escalation_signal": EscalationSignal.SEVERE_CUSTOMER_DISSATISFACTION.value,
                    "priority": "high",
                },
            )

        return None

    @staticmethod
    def _can_proceed_with_knowledge_guidance(policy: IntentDecisionPolicy) -> bool:
        """
        Return whether the workflow can safely retrieve published guidance.

        This does not authorize:

        - access to private operational records;
        - customer-specific status claims;
        - business actions;
        - bypassing grounding or response guardrails.

        It only permits the retrieval pipeline to look for verified informational guidance.
        """
        if not isinstance(policy, IntentDecisionPolicy):
            raise TypeError("policy must be an IntentDecisionPolicy instance")

        return policy.default_decision is DecisionType.RETRIEVE_INFORMATION and policy.retrieval_kind is RetrievalKind.KNOWLEDGE

    @staticmethod
    def _decision_from_policy(*, intent_result: IntentResult, policy: IntentDecisionPolicy) -> DecisionResult:
        """
        Translate one validated default intent policy into DecisionResult.

        This method deliberately contains no branching on IntentType.

        New intents therefore require:
            - taxonomy definition
            - decision policy

        but do not require changes to this routing engine.
        """
        metadata: dict[str, object] = {
            "intent": intent_result.intent.value,
            "priority": policy.default_priority.value,
            "potentially_actionable": policy.potentially_actionable,
        }

        if policy.retrieval_kind is not None:
            metadata["retrieval_kind"] = policy.retrieval_kind.value

        reason_summary = DecisionEngine._default_policy_reason_summary(policy)

        return DecisionResult(
            decision=policy.default_decision,
            reason_code=policy.reason_code,
            reason_summary=reason_summary,
            confidence=intent_result.confidence,
            metadata=metadata,
        )

    @staticmethod
    def _default_policy_reason_summary(policy: IntentDecisionPolicy) -> str:
        """
        Produce a stable audit-friendly explanation for a default policy.

        These summaries explain routing only. Business logic and authorization must never depend on this prose.
        """
        if policy.default_decision is DecisionType.RETRIEVE_INFORMATION:
            if policy.retrieval_kind is RetrievalKind.KNOWLEDGE:
                return "The request requires a response grounded in published customer-support knowledge."

            if policy.retrieval_kind is RetrievalKind.OPERATIONAL:
                return "The request requires information from an operational business-data source."

        if policy.default_decision is DecisionType.ANSWER:
            return "The request can proceed to response generation without additional retrieval or business action."

        if policy.default_decision is DecisionType.PERFORM_ACTION:
            return "The request requires evaluation by the business action workflow."

        if policy.default_decision is DecisionType.ESCALATE:
            return "The request requires escalation to an appropriate human workflow."

        if policy.default_decision is DecisionType.ASK_CLARIFICATION:
            # UNKNOWN and other early clarification scenarios are normally intercepted before reaching policy routing.
            # This branch remains defensive for future policy configurations.
            return "Additional customer information is required before the workflow can continue."

        raise RuntimeError(f"Unsupported default decision policy: {policy.default_decision!r}")

    @staticmethod
    def _resolve_mandatory_missing_information(intent_result: IntentResult) -> tuple[str, ...]:
        """
        Resolve information that a workflow always requires.

        These requirements are deterministic application rules. They must be enforced even if the probabilistic classifier returns needs_clarification=False.

        Only requirements that are universally necessary for the current workflow belong here.
        Do not require identifiers merely because they might be useful.

        For the MVP, order-status handling cannot proceed without an explicit order identifier.
        Once that identifier is available, the request is escalated because no trusted operational order-data source is configured.
        """
        if not isinstance(intent_result, IntentResult):
            raise TypeError("intent_result must be an IntentResult instance")

        if intent_result.intent is IntentType.ORDER_STATUS and intent_result.entities.order_id is None:
            return ("order_id",)

        return ()

    @staticmethod
    def _infer_missing_information(intent_result: IntentResult) -> tuple[str, ...]:
        """
        Resolve additional information for workflows that cannot safely proceed through published-knowledge retrieval.

        Universally mandatory inputs belong in `_resolve_mandatory_missing_information`.

        Knowledge-backed workflows are handled before this method is reached, because they may provide 
        useful general guidance without customer-specific identifiers.
        """
        if not isinstance(intent_result, IntentResult):
            raise TypeError("intent_result must be an IntentResult instance")

        if intent_result.intent is IntentType.ORDER_STATUS:
            return ("order_id",)

        return ("clarification",)