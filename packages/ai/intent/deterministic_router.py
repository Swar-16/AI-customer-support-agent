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

    _ACKNOWLEDGMENT_ONLY: Final[re.Pattern[str]] = re.compile(
        r"""
        ^\s*
        (?:
            ok
            | okay
            | k
            | alright
            | all\s+right
            | got\s+it
            | understood
            | cool
            | sure
            | noted
            | perfect
            | sounds\s+good
        )
        \s*[!.?]*\s*$
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    _TEST_OR_PING_ONLY: Final[re.Pattern[str]] = re.compile(
        r"""
        ^\s*
        (?:
            test
            | testing
            | test\s*123
            | hello\s*\?+
            | are\s+you\s+there\??
            | is\s+anyone\s+there\??
            | ping
        )
        \s*[!.?]*\s*$
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    _REPEATED_CHAR_SPAM: Final[re.Pattern[str]] = re.compile(r"(.)\1{4,}")
    _CONSONANT_CLUSTER: Final[re.Pattern[str]] = re.compile(
        r"[bcdfghjklmnpqrstvwxz]{6,}",
        flags=re.IGNORECASE,
    )
    _ABNORMALLY_LONG_WORD: Final[re.Pattern[str]] = re.compile(r"\b[a-zA-Z]{35,}\b")

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

        # 1. High-confidence explicit conversational or human requests
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

        if self._ACKNOWLEDGMENT_ONLY.fullmatch(normalized):
            return DeterministicIntentRoute(
                route_kind="acknowledgment",
                intent_result=self._intent_result(reason_summary="The message is a standalone acknowledgment."),
            )

        if self._TEST_OR_PING_ONLY.fullmatch(normalized):
            return DeterministicIntentRoute(
                route_kind="test_or_ping",
                intent_result=self._intent_result(reason_summary="The customer is testing or checking assistant availability."),
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

        # 2. Check for unintelligible spam, keysmashing, or pure symbol noise
        # to avoid burning expensive LLM classification tokens on obvious non-questions.
        if self._is_unintelligible(normalized):
            return DeterministicIntentRoute(
                route_kind="unintelligible",
                intent_result=self._intent_result(
                    intent=IntentType.UNKNOWN,
                    needs_clarification=True,
                    reason_summary="The message contains unintelligible gibberish, keyboard smashing, or unparseable character sequences.",
                ),
            )

        # Long messages are more likely to contain substantive or mixed intent.
        if len(normalized) > self._MAX_ROUTABLE_CHARACTERS:
            return None

        return None

    @classmethod
    def _is_unintelligible(cls, text: str) -> bool:
        """
        Identify obvious gibberish, keyboard smashing, character spam,
        and symbol-only noise that cannot express a legitimate customer support issue.
        """
        alphanumeric = [c for c in text if c.isalnum()]

        # 1. No alphanumeric characters (e.g., "???", "...", "!!!", "$$#@")
        if not alphanumeric:
            return True

        # 2. Single alphanumeric character that is not a recognized word like 'a' or 'i'
        if len(alphanumeric) == 1 and text.strip().lower() not in {"a", "i"}:
            return True

        # 3. Excessive repeated characters (5+ same character in a row, e.g. "aaaaa", "?????")
        if cls._REPEATED_CHAR_SPAM.search(text) is not None:
            return True

        # 4. Words with severe unpronounceable consonant clusters (>= 6 consonants in a row)
        if cls._CONSONANT_CLUSTER.search(text) is not None:
            return True

        # 5. Words with 35+ continuous alphabetical characters
        if cls._ABNORMALLY_LONG_WORD.search(text) is not None:
            return True

        # 6. Overall vowel deficiency in multicharacter text (keyboard mash detection)
        # e.g., "ahcdsvbnm, kczlyvjb efmkcs;..."
        letters = [c for c in text.lower() if "a" <= c <= "z"]
        if len(letters) >= 15:
            vowels = [c for c in letters if c in "aeiouy"]
            if len(vowels) / len(letters) < 0.15:
                return True

        # 7. Words of length >= 6 with zero vowels (including 'y' as vowel)
        words = re.findall(r"\b[a-zA-Z]+\b", text)
        for word in words:
            if len(word) >= 6 and not any(c in "aeiouyAEIOUY" for c in word):
                return True

        return False

    @staticmethod
    def _matches_any(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
        return any(pattern.search(value) is not None for pattern in patterns)

    @staticmethod
    def _intent_result(
        *,
        reason_summary: str,
        intent: IntentType = IntentType.CONVERSATIONAL,
        needs_clarification: bool = False,
        escalation_signals: tuple[EscalationSignal, ...] = (),
    ) -> IntentResult:
        return IntentResult(
            intent=intent,
            confidence=1.0,
            entities=IntentEntities(),
            needs_clarification=needs_clarification,
            escalation_signals=escalation_signals,
            reason_summary=reason_summary,
        )