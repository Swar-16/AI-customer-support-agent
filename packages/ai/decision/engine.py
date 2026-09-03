from __future__ import annotations
from dataclasses import dataclass

from packages.ai.decision.policies import IntentDecisionPolicy, RetrievalKind, get_intent_decision_policy
from packages.ai.decision.schemas import DecisionReasonCode, DecisionResult, DecisionType
from packages.ai.intent.schemas import IntentResult
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

            1. unknown intent
            2. insufficient classification confidence
            3. classifier-detected missing information
            4. canonical intent decision policy

        Safety/clarification gates therefore always take precedence over the normal routing policy.
        """

        if not isinstance(intent_result, IntentResult):
            raise TypeError("intent_result must be an IntentResult instance")

        # 1. Genuine unknown intent
        if intent_result.intent is IntentType.UNKNOWN:
            return DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.UNKNOWN_INTENT,
                reason_summary="The customer's intent cannot be determined reliably.",
                confidence=intent_result.confidence,
                required_information=("customer_intent",),
            )

        # 2. Classification confidence is too low for safe routing
        if intent_result.confidence < self._config.low_confidence_threshold:
            return DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.LOW_INTENT_CONFIDENCE,
                reason_summary="Intent confidence is below the configured routing threshold.",
                confidence=intent_result.confidence,
                required_information=("clarification",),
            )

        # 3. Intent is understood, but required information is missing
        if intent_result.needs_clarification:
            missing_information = self._infer_missing_information(intent_result)
            return DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.MISSING_REQUIRED_INFORMATION,
                reason_summary="The intent is understood but additional information is required before processing can continue.",
                confidence=intent_result.confidence,
                required_information=missing_information,
            )

        # 4. Resolve declarative routing policy
        policy = get_intent_decision_policy(intent_result.intent)

        return self._decision_from_policy(
            intent_result=intent_result,
            policy=policy,
        )

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
    def _infer_missing_information(intent_result: IntentResult) -> tuple[str, ...]:
        """
        Infer missing information from the currently supported semantic contracts.

        This remains intentionally conservative.

        Unlike default routing, missing-information requirements can be contextual.
        They should therefore NOT be encoded as simple static fields in IntentDecisionPolicy.

        This method will later be replaced by a dedicated requirement/rule resolver when operational workflows are implemented.
        """
        entities = intent_result.entities
        if intent_result.intent is IntentType.ORDER_STATUS:
            if entities.order_id is None:
                return ("order_id",)

        if intent_result.intent is IntentType.PAYMENT_ISSUE:
            if entities.order_id is None and entities.transaction_id is None:
                return ("order_id_or_transaction_id",)

        if intent_result.intent is IntentType.SUBSCRIPTION_ISSUE:
            if entities.subscription_id is None:
                return ("subscription_id",)

        if intent_result.intent is IntentType.ACCOUNT_ISSUE:
            # Authenticated identity may provide account context later. Therefore we deliberately do not require account_id here.
            return ("clarification",)

        return ("clarification",)