# AI-customer-support-agent\packages\ai\conversation_title\sanitizer.py
from __future__ import annotations
import re
import unicodedata
from typing import Final

from packages.ai.conversation_title.models import GENERATED_TITLE_MAX_LENGTH

class ConversationTitleSanitizer:
    """
    Convert an untrusted provider-generated title into safe plain text.

    Returning ``None`` means the candidate must not be persisted. The caller should use the deterministic privacy-conscious fallback instead.

    The sanitizer deliberately rejects candidates containing sensitive identifiers instead of attempting partial redaction.
    Partial redaction can leave enough information to identify a customer, transaction, or credential.
    """
    _TITLE_PREFIX: Final[re.Pattern[str]] = re.compile(r"^\s*(?:conversation\s+)?title\s*:\s*", flags=re.IGNORECASE)
    _MARKDOWN_LINK: Final[re.Pattern[str]] = re.compile(r"\[([^\]]+)]\([^)]+\)")
    _HTML_TAG: Final[re.Pattern[str]] = re.compile(r"<[^>]*>")
    _MARKDOWN_PREFIX: Final[re.Pattern[str]] = re.compile(r"^\s*(?:#{1,6}|[-+*]|\d+[.)])\s+")
    _MARKDOWN_DECORATION: Final[re.Pattern[str]] = re.compile(r"[*_`~]+")
    _WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
    _EMAIL: Final[re.Pattern[str]] = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", flags=re.IGNORECASE)
    _URL: Final[re.Pattern[str]] = re.compile(r"\b(?:https?://|www\.)\S+", flags=re.IGNORECASE)
    _UUID: Final[re.Pattern[str]] = re.compile(
        r"\b[0-9a-f]{8}-"
        r"[0-9a-f]{4}-"
        r"[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-"
        r"[0-9a-f]{12}\b",
        flags=re.IGNORECASE,
    )
    _JWT: Final[re.Pattern[str]] = re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\."
        r"[A-Za-z0-9_-]{8,}\."
        r"[A-Za-z0-9_-]{8,}\b"
    )
    _BEARER_TOKEN: Final[re.Pattern[str]] = re.compile(
        r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}\b",
        flags=re.IGNORECASE,
    )
    _SECRET_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
        r"\b(?:"
        r"password|passwd|passcode|pin|otp|secret|"
        r"api[_ -]?key|access[_ -]?token|refresh[_ -]?token"
        r")\s*(?:is|=|:)\s*\S+",
        flags=re.IGNORECASE,
    )
    _LABELED_CUSTOMER_IDENTIFIER: Final[re.Pattern[str]] = re.compile(
        r"\b(?:"
        r"order|transaction|payment|subscription|account|customer|"
        r"ticket|case|invoice|reference"
        r")"
        r"\s+(?:id|number|no\.?|#)"
        r"\s*(?:is|=|:|#|-)?\s*"
        r"[A-Z0-9][A-Z0-9_-]{3,}\b",
        flags=re.IGNORECASE,
    )
    _CONTEXTUAL_CUSTOMER_IDENTIFIER: Final[
        re.Pattern[str]
    ] = re.compile(
        r"\b(?:"
        r"order|transaction|payment|subscription|account|customer|"
        r"ticket|case|invoice|reference"
        r")"
        r"\s*(?:is|=|:|#|-)?\s*"
        r"(?=[A-Z0-9_-]{5,}\b)"
        r"(?=[A-Z0-9_-]*\d)"
        r"[A-Z0-9][A-Z0-9_-]{4,}\b",
        flags=re.IGNORECASE,
    )
    _PREFIXED_IDENTIFIER: Final[re.Pattern[str]] = re.compile(
        r"\b(?:"
        r"ORD|ORDER|TXN|TRX|PAY|SUB|ACC|TKT|INV|REF"
        r")"
        r"[-_][A-Z0-9_-]*\d[A-Z0-9_-]*\b",
        flags=re.IGNORECASE,
    )
    _CARD_LIKE_NUMBER: Final[re.Pattern[str]] = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
    _LONG_NUMBER: Final[re.Pattern[str]] = re.compile(r"(?<!\d)\d{8,}(?!\d)")
    _PHONE_LIKE_NUMBER: Final[re.Pattern[str]] = re.compile(
        r"(?<!\w)"
        r"(?:\+\d{1,3}[\s().-]?)?"
        r"(?:\d[\s().-]?){9,14}"
        r"\d"
        r"(?!\w)"
    )
    _PROMPT_INJECTION_LANGUAGE: Final[re.Pattern[str]] = re.compile(
        r"\b(?:"
        r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|"
        r"reveal\s+(?:the\s+)?system\s+prompt|"
        r"system\s+prompt|"
        r"developer\s+message|"
        r"hidden\s+instructions|"
        r"act\s+as\s+(?:an?|the)|"
        r"do\s+not\s+follow\s+(?:the\s+)?instructions"
        r")\b",
        flags=re.IGNORECASE,
    )
    _DISALLOWED_STRUCTURE: Final[re.Pattern[str]] = re.compile(r"[{}\[\]<>|]")
    _ENCLOSING_QUOTES: Final[tuple[tuple[str, str], ...]] = (('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"), ("«", "»"),)

    _SENSITIVE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
        _EMAIL, _URL, _UUID, _JWT, _BEARER_TOKEN, _SECRET_ASSIGNMENT, _LABELED_CUSTOMER_IDENTIFIER, _CONTEXTUAL_CUSTOMER_IDENTIFIER,
        _PREFIXED_IDENTIFIER, _CARD_LIKE_NUMBER, _LONG_NUMBER, _PHONE_LIKE_NUMBER,
    )

    def sanitize(self, value: str) -> str | None:
        """
        Return a safe normalized title or ``None``.

        Provider formatting such as quotes, ``Title:`` prefixes, Markdown headings, and emphasis is removed.
        Sensitive or instruction-like output is rejected rather than repaired.
        """
        if not isinstance(value, str):
            raise TypeError("value must be a string")

        candidate = unicodedata.normalize("NFKC", value)
        # Replace Unicode control/format characters with spaces. This blocks invisible direction changes and other misleading title content.
        candidate = "".join(character if not unicodedata.category(character).startswith("C") else " " for character in candidate)
        candidate = self._WHITESPACE.sub(" ", candidate).strip()
        if not candidate:
            return None

        # Scan before removing markup so a URL or identifier cannot be hidden inside a Markdown link.
        if not self._is_safe(candidate):
            return None

        candidate = self._TITLE_PREFIX.sub("", candidate)
        candidate = self._MARKDOWN_PREFIX.sub("", candidate)
        candidate = self._MARKDOWN_LINK.sub(r"\1", candidate)
        candidate = self._HTML_TAG.sub(" ", candidate)
        candidate = self._MARKDOWN_DECORATION.sub("", candidate)
        candidate = self._strip_enclosing_quotes(candidate)
        candidate = self._WHITESPACE.sub(" ", candidate).strip()
        # Remove cosmetic punctuation surrounding the complete title without altering punctuation within meaningful text.
        candidate = candidate.strip(" \t\r\n:;,.!?—–-")
        if not candidate:
            return None

        if len(candidate) > GENERATED_TITLE_MAX_LENGTH:
            return None

        if not self._is_safe(candidate):
            return None

        if self._DISALLOWED_STRUCTURE.search(candidate):
            return None

        # Require at least one letter or number. A punctuation-only provider response must never become a conversation title.
        if not any(character.isalnum() for character in candidate):
            return None

        return candidate

    def _is_safe(self, value: str) -> bool:
        if self._PROMPT_INJECTION_LANGUAGE.search(value):
            return False

        return not any(pattern.search(value) for pattern in self._SENSITIVE_PATTERNS)

    @classmethod
    def _strip_enclosing_quotes(cls, value: str) -> str:
        candidate = value.strip()
        # Providers sometimes wrap structured values in more than one layer of quotes.
        # The bounded loop avoids any accidental infinite cycle.
        for _ in range(3):
            changed = False
            for opening, closing in cls._ENCLOSING_QUOTES:
                if len(candidate) >= 2 and candidate.startswith(opening) and candidate.endswith(closing):
                    candidate = candidate[len(opening): len(candidate) - len(closing)].strip()
                    changed = True
                    break

            if not changed:
                break

        return candidate