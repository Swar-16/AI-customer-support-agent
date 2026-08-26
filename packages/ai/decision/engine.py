from __future__ import annotations
from dataclasses import dataclass

from packages.ai.decision.schemas import DecisionReasonCode, DecisionResult, DecisionType
from packages.ai.intent.schemas import IntentResult
from packages.ai.intent.taxonomy import INTENT_DEFINITIONS, IntentType


@dataclass(frozen=True, slots=True)
class DecisionEngineConfig:
    """
    Configuration for deterministic routing.

    Thresholds are deliberately configurable because they should
    eventually be derived from evaluation rather than hard-coded forever.
    """

    low_confidence_threshold: float = 0.60

    def __post_init__(self) -> None:
        if not 0.0 <= self.low_confidence_threshold <= 1.0:
            raise ValueError("low_confidence_threshold must be between 0 and 1")


class DecisionEngine:
    """
    Convert validated semantic understanding into a controlled
    system-level next-step decision.

    This layer is deterministic.

    It does NOT:
      - call an LLM
      - retrieve knowledge
      - execute actions
      - authorize refunds/cancellations
      - create tickets
      - write to the database

    Those responsibilities belong to downstream orchestration,
    policy, action, and persistence layers.
    """

    def __init__(self, *, config: DecisionEngineConfig | None = None) -> None:
        self._config = config or DecisionEngineConfig()

    def decide(self, *, intent_result: IntentResult) -> DecisionResult:
        if not isinstance(intent_result, IntentResult):
            raise TypeError("intent_result must be an IntentResult instance")

        # 1. Genuine unknown intent.
        if intent_result.intent is IntentType.UNKNOWN:
            return DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.UNKNOWN_INTENT,
                reason_summary=(
                    "The customer's intent cannot be determined reliably."
                ),
                confidence=intent_result.confidence,
                required_information=("customer_intent",),
            )

        # 2. Confidence is too low for reliable routing.
        if (
            intent_result.confidence
            < self._config.low_confidence_threshold
        ):
            return DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.LOW_INTENT_CONFIDENCE,
                reason_summary=(
                    "Intent confidence is below the configured routing threshold."
                ),
                confidence=intent_result.confidence,
                required_information=("clarification",),
            )

        # 3. Known intent, but information is missing.
        if intent_result.needs_clarification:
            missing = self._infer_missing_information(intent_result)

            return DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=(
                    DecisionReasonCode.MISSING_REQUIRED_INFORMATION
                ),
                reason_summary=(
                    "The intent is understood but additional information is required before processing can continue."
                ),
                confidence=intent_result.confidence,
                required_information=missing,
            )

        # 4. Certain operational intents require external lookup.
        if intent_result.intent is IntentType.ORDER_STATUS:
            return DecisionResult(
                decision=DecisionType.RETRIEVE_INFORMATION,
                reason_code=(
                    DecisionReasonCode.OPERATIONAL_LOOKUP_REQUIRED
                ),
                reason_summary=(
                    "Order status requires retrieval from an operational order source."
                ),
                confidence=intent_result.confidence,
                metadata={
                    "retrieval_kind": "operational",
                },
            )

        # 5. Policy-backed intents should use grounded retrieval.
        definition = INTENT_DEFINITIONS[intent_result.intent]

        if definition.requires_policy_retrieval:
            return DecisionResult(
                decision=DecisionType.RETRIEVE_INFORMATION,
                reason_code=(
                    DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED
                ),
                reason_summary=(
                    "The request requires a response grounded in the applicable customer-support policy."
                ),
                confidence=intent_result.confidence,
                metadata={
                    "retrieval_kind": "policy",
                    "intent": intent_result.intent.value,
                },
            )

        # 6. Safe informational fallback.
        return DecisionResult(
            decision=DecisionType.ANSWER,
            reason_code=(
                DecisionReasonCode.DIRECT_INFORMATIONAL_RESPONSE
            ),
            reason_summary=(
                "The request can proceed to response generation without additional retrieval or business action."
            ),
            confidence=intent_result.confidence,
        )

    @staticmethod
    def _infer_missing_information(intent_result: IntentResult) -> tuple[str, ...]:
        """
        Infer missing operational information from intent/entities.

        Keep this deliberately conservative. This does not authorize
        any business action; it only identifies information needed
        to continue the workflow.
        """

        entities = intent_result.entities

        if intent_result.intent is IntentType.ORDER_STATUS:
            if entities.order_id is None:
                return ("order_id",)

        if intent_result.intent is IntentType.PAYMENT_ISSUE:
            if (
                entities.order_id is None
                and entities.transaction_id is None
            ):
                return ("order_id_or_transaction_id",)

        if intent_result.intent is IntentType.SUBSCRIPTION_ISSUE:
            if entities.subscription_id is None:
                return ("subscription_id",)

        if intent_result.intent is IntentType.ACCOUNT_ISSUE:
            # Do not automatically demand account_id because the
            # authenticated user identity may provide it later.
            return ("clarification",)

        return ("clarification",)