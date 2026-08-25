from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

## Using StrEnum instead of Enums
## convenient for Pydantic, JSON, PostgreSQL, logs, evaluation files, and prompts.
## Only high level intent mentioned (No Overlapping Intents)
class IntentType(StrEnum):
    """
    Canonical customer-intent taxonomy.

    These values are persisted, evaluated, surfaced in dashboards,
    and referenced by routing/policy logic. Treat them as stable API
    identifiers: renaming an enum value is a schema/evaluation change,
    not a cosmetic refactor.
    """
    ## Transaction / money related
    REFUND_REQUEST = "refund_request"
    PAYMENT_ISSUE = "payment_issue"

    ## Order / fulfilment related
    ORDER_STATUS = "order_status"
    SHIPPING_ISSUE = "shipping_issue"

    ## Account / subscription lifecycle
    CANCELLATION = "cancellation"
    SUBSCRIPTION_ISSUE = "subscription_issue"
    ACCOUNT_ISSUE = "account_issue"

    ## Informational / fallback
    GENERAL_QUESTION = "general_question"
    UNKNOWN = "unknown"
    

@dataclass(frozen=True, slots=True)
class IntentDefinition:
    """
    Human- and machine-readable metadata describing one intent.

    The enum value is the stable identifier.
    This definition provides semantic guidance for prompts, evaluation,
    routing, admin tooling, and documentation.
    """
    intent: IntentType
    
    display_name: str
    description: str

    positive_examples: tuple[str, ...]
    negative_examples: tuple[str, ...]

    requires_policy_retrieval: bool
    potentially_actionable: bool

    default_priority: str = "normal"
    

_INTENT_DEFINITIONS: Final[dict[IntentType, IntentDefinition]] = {
    IntentType.REFUND_REQUEST: IntentDefinition(
        intent=IntentType.REFUND_REQUEST,
        display_name="Refund Request",
        description=(
            "The customer is asking whether money can be returned, requesting a refund, or discussing refund eligibility."
        ),
        positive_examples=(
            "Can I get a refund?",
            "I want my money back.",
            "Please refund this order.",
            "Am I eligible for a refund?",
        ),
        negative_examples=(
            "Why was my payment declined?",
            "Where is my order?",
        ),
        requires_policy_retrieval=True,
        potentially_actionable=True,
    ),

    IntentType.PAYMENT_ISSUE: IntentDefinition(
        intent=IntentType.PAYMENT_ISSUE,
        display_name="Payment Issue",
        description=(
            "The customer is reporting a problem with a charge, payment, transaction, billing event, payment method, or duplicate charge."
        ),
        positive_examples=(
            "I was charged twice.",
            "My payment failed.",
            "Why was my card declined?",
            "I don't recognize this charge.",
        ),
        negative_examples=(
            "I want a refund.",
            "Can I cancel my subscription?",
        ),
        requires_policy_retrieval=True,
        potentially_actionable=True,
    ),

    IntentType.ORDER_STATUS: IntentDefinition(
        intent=IntentType.ORDER_STATUS,
        display_name="Order Status",
        description=(
            "The customer wants to know the current state, progress or location of an existing order."
        ),
        positive_examples=(
            "Where is my order?",
            "Has my order shipped yet?",
            "What's happening with order 1234?",
        ),
        negative_examples=(
            "How long does shipping usually take?",
            "I want to cancel my order.",
        ),
        requires_policy_retrieval=False,
        potentially_actionable=True,
    ),

    IntentType.SHIPPING_ISSUE: IntentDefinition(
        intent=IntentType.SHIPPING_ISSUE,
        display_name="Shipping Issue",
        description=(
            "The customer is asking about shipping policy or reporting delivery, shipment, delay, loss, or fulfilment problems."
        ),
        positive_examples=(
            "My package is delayed.",
            "Do you ship internationally?",
            "My package never arrived.",
            "How long does shipping take?",
        ),
        negative_examples=(
            "Where exactly is order 1234 right now?",
            "I need a refund.",
        ),
        requires_policy_retrieval=True,
        potentially_actionable=True,
    ),

    IntentType.CANCELLATION: IntentDefinition(
        intent=IntentType.CANCELLATION,
        display_name="Cancellation",
        description=(
            "The customer wants to cancel an order, service, or other eligible customer commitment."
        ),
        positive_examples=(
            "Cancel my order.",
            "Can I cancel this purchase?",
            "I no longer want this order.",
        ),
        negative_examples=(
            "Cancel my monthly subscription.",
            "Can I get a refund?",
        ),
        requires_policy_retrieval=True,
        potentially_actionable=True,
    ),

    IntentType.SUBSCRIPTION_ISSUE: IntentDefinition(
        intent=IntentType.SUBSCRIPTION_ISSUE,
        display_name="Subscription Issue",
        description=(
            "The customer is asking about subscription status, renewal, billing, cancellation, upgrade, downgrade, or subscription policy."
        ),
        positive_examples=(
            "How do I cancel my subscription?",
            "Why did my subscription renew?",
            "Can I change my plan?",
            "When does my subscription expire?",
        ),
        negative_examples=(
            "Cancel my physical order.",
            "My card payment failed.",
        ),
        requires_policy_retrieval=True,
        potentially_actionable=True,
    ),

    IntentType.ACCOUNT_ISSUE: IntentDefinition(
        intent=IntentType.ACCOUNT_ISSUE,
        display_name="Account Issue",
        description=(
            "The customer is asking about account access, authentication, profile settings, account security, or account-related policy."
        ),
        positive_examples=(
            "I can't log in.",
            "How do I change my email address?",
            "My account is locked.",
            "Someone may have accessed my account.",
        ),
        negative_examples=(
            "Where is my package?",
            "I want a refund.",
        ),
        requires_policy_retrieval=True,
        potentially_actionable=True,
        default_priority="high",
    ),

    IntentType.GENERAL_QUESTION: IntentDefinition(
        intent=IntentType.GENERAL_QUESTION,
        display_name="General Question",
        description=(
            "The customer is asking a supported informational question that does not clearly belong to another specific intent."
        ),
        positive_examples=(
            "How does your service work?",
            "What support options do you offer?",
        ),
        negative_examples=(
            "Refund my payment.",
            "My account is compromised.",
        ),
        requires_policy_retrieval=True,
        potentially_actionable=False,
    ),

    IntentType.UNKNOWN: IntentDefinition(
        intent=IntentType.UNKNOWN,
        display_name="Unknown",
        description=(
            "The request cannot be classified reliably, is outside the supported taxonomy or lacks enough information to determine intent."
        ),
        positive_examples=(
            "How's the weather today or tomorrow?",
            "I have a problem in my life.",
            "Tell me today's football score.",
        ),
        negative_examples=(
            "I want a refund.",
            "Where is my order?",
        ),
        requires_policy_retrieval=False,
        potentially_actionable=False,
    ),
}

INTENT_DEFINITIONS: Final = MappingProxyType(_INTENT_DEFINITIONS)

def get_intent_definition(intent: IntentType) -> IntentDefinition:
    """
    Return metadata for a canonical intent.

    Raises:
        TypeError:
            If the caller does not provide IntentType.
        KeyError:
            If taxonomy metadata is incomplete.
    """
    if not isinstance(intent, IntentType):
        raise TypeError(f"intent must be IntentType, got {type(intent).__name__}")

    return INTENT_DEFINITIONS[intent]

def get_all_intents() -> tuple[IntentType, ...]:
    """
    Return every supported canonical intent.
    """
    return tuple(IntentType)

def get_actionable_intents() -> frozenset[IntentType]:
    """
    Return intents that may eventually lead to business actions.

    This does not mean the AI is authorized to execute those actions.
    Authorization remains the responsibility of the policy/action layer.
    """
    return frozenset(intent for intent, definition in INTENT_DEFINITIONS.items() if definition.potentially_actionable)

def get_retrieval_intents() -> frozenset[IntentType]:
    """
    Return intents whose default handling requires knowledge retrieval.

    This is routing metadata only. Runtime orchestration may override this
    depending on available context or deterministic business data.
    """
    return frozenset(intent for intent, definition in INTENT_DEFINITIONS.items() if definition.requires_policy_retrieval)

def validate_taxonomy() -> None:
    """
    Fail fast if taxonomy definitions drift away from IntentType.
    """

    enum_values = set(IntentType)
    definition_values = set(INTENT_DEFINITIONS)

    missing = enum_values - definition_values
    unexpected = definition_values - enum_values

    if missing or unexpected:
        raise RuntimeError(
            "Intent taxonomy is inconsistent. "
            f"Missing definitions: {sorted(item.value for item in missing)}; "
            f"Unexpected definitions: "
            f"{sorted(item.value for item in unexpected)}"
        )

    for intent, definition in INTENT_DEFINITIONS.items():
        if definition.intent is not intent:
            raise RuntimeError(f"Intent definition mismatch for {intent.value}")

        if not definition.display_name.strip():
            raise RuntimeError(f"Missing display name for {intent.value}")

        if not definition.description.strip():
            raise RuntimeError(f"Missing description for {intent.value}")

        if not definition.positive_examples:
            raise RuntimeError(f"No positive examples configured for {intent.value}")


validate_taxonomy()