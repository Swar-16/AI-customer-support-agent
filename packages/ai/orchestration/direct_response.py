# AI-customer-support-agent\packages\ai\orchestration\direct_response.py
from __future__ import annotations
import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

from packages.ai.decision.schemas import DecisionResult, DecisionType
from packages.ai.intent.schemas import IntentResult
from packages.ai.intent.taxonomy import IntentType

class DirectResponseResolutionError(RuntimeError):
    """Raised when a direct response cannot be resolved safely."""

class DirectResponseKind(StrEnum):
    """
    Stable identifiers for application-controlled direct responses.

    These values may be recorded in sanitized telemetry. They must not contain customer-controlled content.
    """
    GREETING = "greeting"
    CAPABILITIES = "capabilities"
    THANKS = "thanks"
    GOODBYE = "goodbye"
    OUT_OF_SCOPE = "out_of_scope"

@dataclass(frozen=True, slots=True)
class DirectResponse:
    """
    One safe, deterministic customer-facing response.

    `kind` is safe for low-cardinality telemetry. `text` is selected from application-owned templates and never contains customer-controlled text.
    """
    kind: DirectResponseKind
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DirectResponseKind):
            raise TypeError("kind must be a DirectResponseKind.")

        if not isinstance(self.text, str):
            raise TypeError("text must be a string.")

        normalized = " ".join(self.text.split())
        if not normalized:
            raise ValueError("text cannot be blank.")

        object.__setattr__(self, "text", normalized)

_RESPONSE_TEXT: Final[Mapping[DirectResponseKind, str]] = MappingProxyType(
    {
        DirectResponseKind.GREETING: "Hello! How can I help you today?",
        DirectResponseKind.CAPABILITIES: (
            "I can help with questions about refunds, payments, cancellations, subscriptions, shipping, returns, exchanges, "
            "and account support. If your request requires access to private business records or human approval, I can direct it "
            "to the appropriate support team."
        ),
        DirectResponseKind.THANKS: "You're welcome! Let me know if you need help with anything else.",
        DirectResponseKind.GOODBYE: "Goodbye! Feel free to return if you need further support.",
        DirectResponseKind.OUT_OF_SCOPE: (
            "I’m here to help with customer-support questions about refunds, payments, cancellations, subscriptions, shipping, returns, exchanges, and accounts."
        ),
    }
)

# The patterns below only select an application-controlled template.
# No captured customer content is inserted into the resulting response.
_CAPABILITY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\b(?:what|which)\s+(?:can|could|do)\s+you\s+"
        r"(?:help|assist|support)\b"
    ),
    re.compile(r"\bhow\s+can\s+you\s+(?:help|assist|support)\b"),
    re.compile(
        r"\bwhat\s+(?:can|do)\s+you\s+do\b"
    ),
    re.compile(
        r"\bwhat\s+(?:kind|kinds|type|types)\s+of\s+"
        r"(?:help|support|assistance)\b"
    ),
    re.compile(
        r"\bwhat\s+(?:topics|issues|questions)\s+"
        r"(?:can|do)\s+you\s+(?:handle|support|answer)\b"
    ),
    re.compile(
        r"\b(?:show|list|tell)\s+(?:me\s+)?"
        r"(?:your\s+)?(?:capabilities|features)\b"
    ),
    re.compile(r"\bwho\s+are\s+you\b"),
)

_THANKS_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bthanks?\b"),
    re.compile(r"\bthank\s+you\b"),
    re.compile(r"\bmuch\s+appreciated\b"),
    re.compile(r"\bi\s+appreciate\s+(?:it|that|your\s+help)\b"),
)

_GOODBYE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bgoodbye\b"),
    re.compile(r"\bbye(?:\s+bye)?\b"),
    re.compile(r"\bsee\s+you\b"),
    re.compile(r"\btalk\s+to\s+you\s+later\b"),
    re.compile(r"\bhave\s+a\s+(?:good|great|nice)\s+day\b"),
)

_GREETING_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bhello\b"),
    re.compile(r"\bhi\b"),
    re.compile(r"\bhey\b"),
    re.compile(r"\bgreetings\b"),
    re.compile(r"\bgood\s+(?:morning|afternoon|evening)\b"),
    re.compile(r"\bhow\s+are\s+you\b"),
)

class DirectResponseResolver:
    """
    Resolve direct-answer decisions without invoking an LLM.

    Supported intents:

    `CONVERSATIONAL`
        Greetings, capability questions, thanks, and goodbyes.

    `OUT_OF_SCOPE`
        Requests that do not belong to the customer-support domain.

    The latest customer message is treated only as untrusted classification input for choosing an allowlisted response.
    It is never copied into the returned response.

    Supported policy questions remain outside this resolver and must use the knowledge-retrieval workflow.
    """
    _SUPPORTED_INTENTS: Final[frozenset[IntentType]] = frozenset({IntentType.CONVERSATIONAL, IntentType.OUT_OF_SCOPE,})

    def resolve(self, *, customer_message: str, intent_result: IntentResult, decision_result: DecisionResult) -> DirectResponse:
        self._validate_inputs(customer_message=customer_message, intent_result=intent_result, decision_result=decision_result)
        if intent_result.intent is IntentType.OUT_OF_SCOPE:
            return self._response(DirectResponseKind.OUT_OF_SCOPE)

        normalized_message = self._normalize_for_matching(customer_message)
        kind = self._resolve_conversational_kind(normalized_message)

        return self._response(kind)

    @classmethod
    def _validate_inputs(cls, *, customer_message: str, intent_result: IntentResult, decision_result: DecisionResult) -> None:
        if not isinstance(customer_message, str):
            raise TypeError("customer_message must be a string.")

        if not customer_message.strip():
            raise DirectResponseResolutionError("A direct response cannot be resolved for a blank message.")

        if not isinstance(intent_result, IntentResult):
            raise TypeError("intent_result must be an IntentResult instance.")

        if not isinstance(decision_result, DecisionResult):
            raise TypeError("decision_result must be a DecisionResult instance.")

        if decision_result.decision is not DecisionType.ANSWER:
            raise DirectResponseResolutionError("Direct responses require an ANSWER decision.")

        if intent_result.intent not in cls._SUPPORTED_INTENTS:
            raise DirectResponseResolutionError("The classified intent is not eligible for a direct response.")

        if intent_result.needs_clarification:
            raise DirectResponseResolutionError("An intent requiring clarification cannot use a direct response.")

    @staticmethod
    def _normalize_for_matching(message: str) -> str:
        """
        Produce a conservative representation used only for template selection.

        Unicode letters and numbers are preserved. Punctuation and control characters become spaces.
        """
        normalized = message.casefold()
        normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
        normalized = re.sub(r"_+", " ", normalized)
        normalized = " ".join(normalized.split())
        if not normalized:
            raise DirectResponseResolutionError("The message contains no usable conversational text.")

        return normalized

    @classmethod
    def _resolve_conversational_kind(cls, normalized_message: str) -> DirectResponseKind:
        # Capability questions take precedence because messages such as
        # "Hello, what can you help me with?" contain both a greeting and a capability request.
        if cls._matches_any(normalized_message, _CAPABILITY_PATTERNS):
            return DirectResponseKind.CAPABILITIES

        # A closing message such as "Thanks, goodbye" is better represented
        # as a goodbye because it concludes the interaction.
        if cls._matches_any(normalized_message, _GOODBYE_PATTERNS):
            return DirectResponseKind.GOODBYE

        if cls._matches_any(normalized_message, _THANKS_PATTERNS):
            return DirectResponseKind.THANKS

        if cls._matches_any(normalized_message, _GREETING_PATTERNS):
            return DirectResponseKind.GREETING

        # Classification has already established that this is conversational.
        # A generic greeting is safer than reflecting unknown model-produced subtypes or customer-controlled text.
        return DirectResponseKind.GREETING

    @staticmethod
    def _matches_any(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
        return any(pattern.search(value) is not None for pattern in patterns)

    @staticmethod
    def _response(kind: DirectResponseKind) -> DirectResponse:
        try:
            text = _RESPONSE_TEXT[kind]
            
        except KeyError as exc:
            raise DirectResponseResolutionError(f"No direct-response template is configured for {kind.value!r}.") from exc

        return DirectResponse(kind=kind, text=text)