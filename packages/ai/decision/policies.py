from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

from packages.ai.decision.schemas import DecisionReasonCode, DecisionType
from packages.ai.intent.taxonomy import IntentType


class RetrievalKind(StrEnum):
    """
    Broad source category used when a decision requires information retrieval.

    KNOWLEDGE:
        Versioned customer-support knowledge such as policies, FAQs, procedures, guides, and reference material.

    OPERATIONAL:
        Runtime business data such as order status, payment state, subscription state, or account information.

    The enum deliberately describes *where information comes from* rather than naming concrete providers or repositories.
    """
    KNOWLEDGE = "knowledge"
    OPERATIONAL = "operational"

class DecisionPriority(StrEnum):
    """
    Stable workflow-priority vocabulary.

    Priority is routing metadata only. It must never by itself authorize sensitive actions or bypass business/security policies.
    """
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass(frozen=True, slots=True)
class IntentDecisionPolicy:
    """
    Declarative default routing policy for one canonical customer intent.

    This object answers:

        "Once an intent has been classified reliably, what is the default workflow direction for that intent?"

    Runtime circumstances may still override this default policy.

    For example:
        PAYMENT_ISSUE may normally require knowledge retrieval, while a particular subtype may later require an operational payment lookup.

    Such context-dependent rules belong in the decision-policy evaluation layer, not in this static definition.
    """
    intent: IntentType
    default_decision: DecisionType
    reason_code: DecisionReasonCode
    retrieval_kind: RetrievalKind | None = None
    potentially_actionable: bool = False
    default_priority: DecisionPriority = DecisionPriority.NORMAL

    def __post_init__(self) -> None:
        if not isinstance(self.intent, IntentType):
            raise TypeError("intent must be an IntentType instance")

        if not isinstance(self.default_decision, DecisionType):
            raise TypeError("default_decision must be a DecisionType instance")

        if not isinstance(self.reason_code, DecisionReasonCode):
            raise TypeError("reason_code must be a DecisionReasonCode instance")

        if self.retrieval_kind is not None and not isinstance(self.retrieval_kind, RetrievalKind):
            raise TypeError("retrieval_kind must be a RetrievalKind instance or None")

        if not isinstance(self.potentially_actionable, bool):
            raise TypeError("potentially_actionable must be a boolean")

        if not isinstance(self.default_priority, DecisionPriority):
            raise TypeError("default_priority must be a DecisionPriority instance")

        self._validate_retrieval_semantics()

    def _validate_retrieval_semantics(self) -> None:
        """
        Prevent impossible policy configurations.

        A retrieval source is meaningful only for RETRIEVE_INFORMATION.
        Likewise, RETRIEVE_INFORMATION must identify the broad source from which information is expected.
        """
        if self.default_decision is DecisionType.RETRIEVE_INFORMATION:
            if self.retrieval_kind is None:
                raise ValueError("RETRIEVE_INFORMATION policy requires retrieval_kind")
            return

        if self.retrieval_kind is not None:
            raise ValueError("retrieval_kind may only be populated when default_decision is RETRIEVE_INFORMATION")

_INTENT_DECISION_POLICIES: Final[dict[IntentType, IntentDecisionPolicy]] = {
    IntentType.REFUND_REQUEST: IntentDecisionPolicy(
        intent=IntentType.REFUND_REQUEST,
        default_decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
        retrieval_kind=RetrievalKind.KNOWLEDGE,
        potentially_actionable=True,
    ),

    IntentType.PAYMENT_ISSUE: IntentDecisionPolicy(
        intent=IntentType.PAYMENT_ISSUE,
        default_decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
        retrieval_kind=RetrievalKind.KNOWLEDGE,
        potentially_actionable=True,
    ),

    IntentType.ORDER_STATUS: IntentDecisionPolicy(
        intent=IntentType.ORDER_STATUS,
        default_decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=DecisionReasonCode.OPERATIONAL_LOOKUP_REQUIRED,
        retrieval_kind=RetrievalKind.OPERATIONAL,
        potentially_actionable=True,
    ),

    IntentType.SHIPPING_ISSUE: IntentDecisionPolicy(
        intent=IntentType.SHIPPING_ISSUE,
        default_decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
        retrieval_kind=RetrievalKind.KNOWLEDGE,
        potentially_actionable=True,
    ),

    IntentType.CANCELLATION: IntentDecisionPolicy(
        intent=IntentType.CANCELLATION,
        default_decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
        retrieval_kind=RetrievalKind.KNOWLEDGE,
        potentially_actionable=True,
    ),

    IntentType.SUBSCRIPTION_ISSUE: IntentDecisionPolicy(
        intent=IntentType.SUBSCRIPTION_ISSUE,
        default_decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
        retrieval_kind=RetrievalKind.KNOWLEDGE,
        potentially_actionable=True,
    ),

    IntentType.ACCOUNT_ISSUE: IntentDecisionPolicy(
        intent=IntentType.ACCOUNT_ISSUE,
        default_decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
        retrieval_kind=RetrievalKind.KNOWLEDGE,
        potentially_actionable=True,
        default_priority=DecisionPriority.HIGH,
    ),
    
    IntentType.RETURN_EXCHANGE: IntentDecisionPolicy(
        intent=IntentType.RETURN_EXCHANGE,
        default_decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
        retrieval_kind=RetrievalKind.KNOWLEDGE,
        potentially_actionable=True,
    ),

    IntentType.PRIVACY_SECURITY: IntentDecisionPolicy(
        intent=IntentType.PRIVACY_SECURITY,
        default_decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
        retrieval_kind=RetrievalKind.KNOWLEDGE,
        potentially_actionable=False,
        default_priority=DecisionPriority.HIGH,
    ),

    IntentType.GENERAL_QUESTION: IntentDecisionPolicy(
        intent=IntentType.GENERAL_QUESTION,
        default_decision=DecisionType.RETRIEVE_INFORMATION,
        reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
        retrieval_kind=RetrievalKind.KNOWLEDGE,
        potentially_actionable=False,
    ),

    IntentType.UNKNOWN: IntentDecisionPolicy(
        intent=IntentType.UNKNOWN,
        default_decision=DecisionType.ASK_CLARIFICATION,
        reason_code=DecisionReasonCode.UNKNOWN_INTENT,
        potentially_actionable=False,
    ),
}

INTENT_DECISION_POLICIES: Final[Mapping[IntentType, IntentDecisionPolicy]] = MappingProxyType(_INTENT_DECISION_POLICIES)

def get_intent_decision_policy(intent: IntentType) -> IntentDecisionPolicy:
    """
    Return the default routing policy for a canonical intent.

    Raises:
        TypeError:
            If intent is not an IntentType.

        KeyError:
            If the policy registry is incomplete.
    """

    if not isinstance(intent, IntentType):
        raise TypeError(f"intent must be IntentType, got {type(intent).__name__}")

    return INTENT_DECISION_POLICIES[intent]

def get_knowledge_retrieval_intents() -> frozenset[IntentType]:
    """
    Return intents whose default workflow uses published knowledge.
    """
    return frozenset(
        intent for intent, policy in INTENT_DECISION_POLICIES.items()
        if policy.default_decision is DecisionType.RETRIEVE_INFORMATION and policy.retrieval_kind is RetrievalKind.KNOWLEDGE
    )

def get_operational_retrieval_intents() -> frozenset[IntentType]:
    """
    Return intents whose default workflow uses operational business data.
    """
    return frozenset(
        intent for intent, policy in INTENT_DECISION_POLICIES.items()
        if policy.default_decision is DecisionType.RETRIEVE_INFORMATION and policy.retrieval_kind is RetrievalKind.OPERATIONAL
    )

def get_actionable_intents() -> frozenset[IntentType]:
    """
    Return intents which may eventually lead to a business action.

    This is descriptive routing metadata only.

    Membership here never grants authorization to perform the action.
    """

    return frozenset(
        intent for intent, policy in INTENT_DECISION_POLICIES.items()
        if policy.potentially_actionable
    )

def validate_intent_decision_policies() -> None:
    """
    Fail fast when IntentType and the routing registry drift apart.

    Adding a new canonical IntentType without specifying its routing policy is therefore an explicit application error rather than a silent fallback.
    """
    canonical_intents = set(IntentType)
    configured_intents = set(INTENT_DECISION_POLICIES)
    missing = canonical_intents - configured_intents
    unexpected = configured_intents - canonical_intents
    if missing or unexpected:
        raise RuntimeError(
            f"Intent decision-policy registry is inconsistent. Missing policies: {sorted(_intent_name(value) for value in missing)}; "
            f"Unexpected policies: {sorted(_intent_name(value) for value in unexpected)}"
        )

    for intent, policy in INTENT_DECISION_POLICIES.items():
        if not isinstance(intent, IntentType):
            raise RuntimeError(f"Intent decision-policy registry contains an invalid key type: {type(intent).__name__}")

        if not isinstance(policy, IntentDecisionPolicy):
            raise RuntimeError(f"Policy for {intent.value!r} is not an IntentDecisionPolicy")

        if policy.intent is not intent:
            raise RuntimeError(f"Intent decision-policy registry contains a policy/key mismatch for {intent.value!r}")

def _intent_name(value: object) -> str:
    if isinstance(value, IntentType):
        return value.value

    return str(value)

validate_intent_decision_policies()