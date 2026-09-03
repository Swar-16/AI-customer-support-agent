from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping


class IntentType(StrEnum):
    """
    Stable canonical semantic identifiers for supported customer intents.

    These values may be persisted in telemetry, evaluation datasets, dashboards, and historical AI runs.

    Therefore:
        - existing values must not be renamed casually
        - workflow/routing behavior must not be encoded here
        - new intents should represent genuinely distinct customer goals
    """
    REFUND_REQUEST = "refund_request"
    PAYMENT_ISSUE = "payment_issue"
    ORDER_STATUS = "order_status"
    SHIPPING_ISSUE = "shipping_issue"
    CANCELLATION = "cancellation"
    SUBSCRIPTION_ISSUE = "subscription_issue"
    ACCOUNT_ISSUE = "account_issue"
    RETURN_EXCHANGE = "return_exchange"
    PRIVACY_SECURITY = "privacy_security"
    GENERAL_QUESTION = "general_question"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class IntentDefinition:
    """
    Semantic description of one canonical intent.

    IntentDefinition exists only to help semantic classification and evaluation understand what an intent means.

    Those belong to downstream decision/workflow layers.
    """
    intent: IntentType
    description: str
    examples: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.intent, IntentType):
            raise TypeError("intent must be an IntentType instance")

        if not isinstance(self.description, str):
            raise TypeError("description must be a string")

        description = " ".join(self.description.split())
        if not description:
            raise ValueError("description cannot be empty")

        if not isinstance(self.examples, tuple):
            raise TypeError("examples must be a tuple")

        normalized_examples: list[str] = []
        for example in self.examples:
            if not isinstance(example, str):
                raise TypeError("intent examples must contain only strings")

            normalized = " ".join(example.split())
            if not normalized:
                raise ValueError("intent examples cannot contain empty values")

            if normalized not in normalized_examples:
                normalized_examples.append(normalized)

        if not normalized_examples:
            raise ValueError("each intent definition requires at least one example")

        object.__setattr__(self, "description", description)
        object.__setattr__(self, "examples", tuple(normalized_examples))

_INTENT_DEFINITIONS: Final[dict[IntentType, IntentDefinition]] = {
    IntentType.REFUND_REQUEST: IntentDefinition(
        intent=IntentType.REFUND_REQUEST,
        description="The customer is asking about receiving money back, refund eligibility, refund progress, refund timing, or a refund that has not arrived.",
        examples=("I want a refund.", "When will my refund arrive?", "Why have I not received my refund yet?",)
    ),

    IntentType.PAYMENT_ISSUE: IntentDefinition(
        intent=IntentType.PAYMENT_ISSUE,
        description="The customer reports a problem involving a payment, charge, transaction, payment method, duplicate charge, failed payment, or payment processing.",
        examples=("My payment keeps failing.", "I was charged twice.", "Why was my card declined?",)
    ),

    IntentType.ORDER_STATUS: IntentDefinition(
        intent=IntentType.ORDER_STATUS,
        description="The customer wants the current state or progress of a specific order.",
        examples=("Where is my order?", "What is the status of order ORD-123?", "Has my order been processed yet?",)
    ),

    IntentType.SHIPPING_ISSUE: IntentDefinition(
        intent=IntentType.SHIPPING_ISSUE,
        description="The customer has a delivery or shipping-related problem, such as delay, failed delivery, missing delivery, damaged shipment, or shipping-related concern.",
        examples=("My package is late.", "The delivery never arrived.", "My shipment was damaged.",)
    ),

    IntentType.CANCELLATION: IntentDefinition(
        intent=IntentType.CANCELLATION,
        description="The customer wants to cancel, or asks about cancelling, an order, service, subscription, or other supported customer commitment.",
        examples=("I want to cancel my order.", "Can I cancel this?", "How do I cancel my subscription?",)
    ),

    IntentType.SUBSCRIPTION_ISSUE: IntentDefinition(
        intent=IntentType.SUBSCRIPTION_ISSUE,
        description="The customer has a question or problem involving a subscription, plan, renewal, subscription state, or recurring service.",
        examples=("Why did my subscription renew?", "My subscription is not working.", "What happened to my plan?",)
    ),

    IntentType.ACCOUNT_ISSUE: IntentDefinition(
        intent=IntentType.ACCOUNT_ISSUE,
        description="The customer has a problem accessing or managing their account, profile, authentication state, or account settings.",
        examples=("I cannot log in.", "I am locked out of my account.", "I cannot update my account details.",)
    ),

    IntentType.RETURN_EXCHANGE: IntentDefinition(
        intent=IntentType.RETURN_EXCHANGE,
        description="The customer wants to return or exchange a purchased item, or asks about return or exchange eligibility, procedure, conditions, or status.",
        examples=("Can I return this item?", "I want to exchange this for another size.", "How do I send this product back?",)
    ),

    IntentType.PRIVACY_SECURITY: IntentDefinition(
        intent=IntentType.PRIVACY_SECURITY,
        description="The customer raises a privacy, security, suspicious-access, credential, personal-data, or account-compromise concern.",
        examples=("Someone may have accessed my account.", "How is my personal data used?", "I think my account has been compromised.",)
    ),

    IntentType.GENERAL_QUESTION: IntentDefinition(
        intent=IntentType.GENERAL_QUESTION,
        description="The customer asks a supported informational question that does not belong to a more specific canonical intent.",
        examples=("What payment methods do you accept?", "What are your support hours?", "How does your service work?",)
    ),

    IntentType.UNKNOWN: IntentDefinition(
        intent=IntentType.UNKNOWN,
        description="The customer's goal cannot be mapped reliably to one of the supported canonical intents.",
        examples=("I need help with something else.","This does not match any supported request.", "I am not sure how to describe my problem.",)
    ),
}

INTENT_DEFINITIONS: Final[Mapping[IntentType, IntentDefinition]] = MappingProxyType(_INTENT_DEFINITIONS)

def get_intent_definition(intent: IntentType) -> IntentDefinition:
    if not isinstance(intent, IntentType):
        raise TypeError(f"intent must be IntentType, got {type(intent).__name__}")

    return INTENT_DEFINITIONS[intent]


def validate_intent_definitions() -> None:
    """
    Ensure the semantic taxonomy and definition registry cannot drift.

    Adding an IntentType without defining its classification semantics must fail explicitly.
    """
    canonical_intents = set(IntentType)
    defined_intents = set(INTENT_DEFINITIONS)
    missing = canonical_intents - defined_intents
    unexpected = defined_intents - canonical_intents
    if missing or unexpected:
        raise RuntimeError(
            f"Intent definition registry is inconsistent. Missing definitions: {sorted(_intent_name(value) for value in missing)}; "
            f"Unexpected definitions: {sorted(_intent_name(value) for value in unexpected)}"
        )

    for intent, definition in INTENT_DEFINITIONS.items():
        if not isinstance(intent, IntentType):
            raise RuntimeError(f"Intent definition registry contains an invalid key type: {type(intent).__name__}")

        if not isinstance(definition, IntentDefinition):
            raise RuntimeError(f"Definition for {intent.value!r} is not an IntentDefinition")

        if definition.intent is not intent:
            raise RuntimeError(f"Intent definition registry contains a definition/key mismatch for {intent.value!r}")

def _intent_name(value: object) -> str:
    if isinstance(value, IntentType):
        return value.value

    return str(value)

validate_intent_definitions()