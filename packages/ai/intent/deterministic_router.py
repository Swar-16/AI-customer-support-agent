# AI-customer-support-agent\packages\ai\intent\deterministic_router.py
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Final

from packages.ai.intent.schemas import EscalationSignal, IntentEntities, IntentResult
from packages.ai.intent.taxonomy import IntentType

@dataclass(frozen=True, slots=True)
class DeterministicIntentRoute:
    """
    High-confidence intent result produced without an LLM call.

    `route_kind` is application-controlled, low-cardinality metadata suitable for tests and future telemetry. It never contains customer text.
    """
    route_kind: str
    intent_result: IntentResult

    def __post_init__(self) -> None:
        if not isinstance(self.route_kind, str):
            raise TypeError("route_kind must be a string")

        normalized_kind = self.route_kind.strip()
        if not normalized_kind:
            raise ValueError("route_kind cannot be blank")

        if not isinstance(self.intent_result, IntentResult):
            raise TypeError("intent_result must be an IntentResult")

        object.__setattr__(self, "route_kind", normalized_kind)

class DeterministicIntentRouter:
    """
    Resolve only narrow, high-confidence messages without using an LLM.

    The router intentionally does not classify ordinary business-support messages. Any uncertainty returns None and delegates to IntentClassifier.

    Safe deterministic categories:
        - greeting-only messages;
        - thanks-only messages;
        - goodbye-only messages;
        - support-capability questions;
        - explicit requests for human support.

    It does not pre-route:
        - refunds, returns, payments, subscriptions, orders, or shipping;
        - privacy/security/account-compromise concerns;
        - complaints or dissatisfaction;
        - operational requests;
        - vague or ambiguous messages;
        - arbitrary out-of-scope requests.
    """
    _MAX_ROUTABLE_CHARACTERS: Final[int] = 200
    _GREETING_ONLY: Final[re.Pattern[str]] = re.compile(
        r"""
        ^\s*
        (?:
            hello
            | hi
            | hey
            | greetings
            | good\s+(?:morning|afternoon|evening)
            | how\s+are\s+you
        )
        (?:\s+(?:there|everyone))?
        \s*[!.?]*\s*$
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    _THANKS_ONLY: Final[re.Pattern[str]] = re.compile(
        r"""
        ^\s*
        (?:
            thanks
            | thank\s+you
            | thanks\s+a\s+lot
            | thank\s+you\s+(?:so\s+much|very\s+much)
            | much\s+appreciated
            | i\s+appreciate\s+(?:it|that|your\s+help)
        )
        \s*[!.?]*\s*$
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    _GOODBYE_ONLY: Final[re.Pattern[str]] = re.compile(
        r"""
        ^\s*
        (?:
            goodbye
            | bye
            | bye\s+bye
            | see\s+you
            | talk\s+to\s+you\s+later
            | have\s+a\s+(?:good|great|nice)\s+day
        )
        \s*[!.?]*\s*$
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    _CAPABILITIES_ONLY: Final[tuple[re.Pattern[str], ...]] = (
        re.compile(
            r"^\s*what\s+(?:can|could)\s+you\s+"
            r"(?:help|assist|support)\s+(?:me\s+)?with\s*[?.!]*\s*$",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"^\s*how\s+can\s+you\s+(?:help|assist|support)"
            r"(?:\s+me)?\s*[?.!]*\s*$",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"^\s*what\s+(?:can|do)\s+you\s+do\s*[?.!]*\s*$",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"^\s*what\s+(?:kind|kinds|type|types)\s+of\s+"
            r"(?:help|support|assistance)\s+(?:can|do)\s+you\s+"
            r"(?:provide|offer)\s*[?.!]*\s*$",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:show|list|tell)\s+(?:me\s+)?"
            r"(?:your\s+)?(?:capabilities|features)\s*[?.!]*\s*$",
            flags=re.IGNORECASE,
        ),
    )

    _EXPLICIT_HUMAN_REQUEST: Final[tuple[re.Pattern[str], ...]] = (
        re.compile(
            r"\b(?:connect|transfer|forward|escalate)\s+"
            r"(?:me|this|my\s+(?:case|request|issue))\s+to\s+"
            r"(?:a\s+)?(?:human|person|agent|representative)\b",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:i\s+)?(?:want|need|would\s+like)\s+to\s+"
            r"(?:speak|talk|chat)\s+(?:to|with)\s+"
            r"(?:a\s+)?(?:human|real\s+person|support\s+agent|representative)\b",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:let|have)\s+me\s+(?:speak|talk|chat)\s+"
            r"(?:to|with)\s+(?:a\s+)?"
            r"(?:human|real\s+person|support\s+agent|representative)\b",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:human|live)\s+(?:agent|support|representative)\s+please\b",
            flags=re.IGNORECASE,
        ),
    )

    def route(self, *, customer_message: str) -> DeterministicIntentRoute | None:
        if not isinstance(customer_message, str):
            raise TypeError("customer_message must be a string")

        normalized = " ".join(customer_message.split())
        if not normalized:
            return None

        # Long messages are more likely to contain substantive or mixed intent.
        if len(normalized) > self._MAX_ROUTABLE_CHARACTERS:
            return None

        if self._matches_any(normalized, self._EXPLICIT_HUMAN_REQUEST):
            return DeterministicIntentRoute(
                route_kind="explicit_human_request",
                intent_result=self._intent_result(
                    escalation_signals=(EscalationSignal.EXPLICIT_HUMAN_REQUEST,),
                    reason_summary="The customer explicitly requested assistance from a human support agent.",
                ),
            )

        if self._GREETING_ONLY.fullmatch(normalized):
            return DeterministicIntentRoute(
                route_kind="greeting",
                intent_result=self._intent_result(reason_summary="The message is a standalone greeting."),
            )

        if self._THANKS_ONLY.fullmatch(normalized):
            return DeterministicIntentRoute(
                route_kind="thanks",
                intent_result=self._intent_result(reason_summary="The message is a standalone expression of thanks."),
            )

        if self._GOODBYE_ONLY.fullmatch(normalized):
            return DeterministicIntentRoute(
                route_kind="goodbye",
                intent_result=self._intent_result(reason_summary="The message is a standalone goodbye."),
            )

        if self._matches_any(normalized, self._CAPABILITIES_ONLY):
            return DeterministicIntentRoute(
                route_kind="capabilities",
                intent_result=self._intent_result(reason_summary="The customer is asking which support topics the assistant can help with."),
            )

        return None

    @staticmethod
    def _matches_any(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
        return any(pattern.search(value) is not None for pattern in patterns)

    @staticmethod
    def _intent_result(*, reason_summary: str, escalation_signals: tuple[EscalationSignal, ...] = ()) -> IntentResult:
        return IntentResult(
            intent=IntentType.CONVERSATIONAL,
            confidence=1.0,
            entities=IntentEntities(),
            needs_clarification=False,
            escalation_signals=escalation_signals,
            reason_summary=reason_summary,
        )