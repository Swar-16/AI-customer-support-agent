# AI-customer-support-agent\packages\ai\conversation_title\fallback.py
from __future__ import annotations
import re
from typing import Final

from packages.ai.conversation_title.models import ConversationTitleResult, ConversationTitleSource

class ConversationTitleFallback:
    """
    Produce a deterministic privacy-conscious conversation title.

    The fallback deliberately uses allowlisted category titles instead of truncating the customer's original message.
    Direct truncation could place names, order IDs, account details, credentials, or other sensitive content in navigation elements and logs.

    A confirmed canonical intent is preferred when available. Keyword matching is used only when the intent is absent or unknown.
    """
    DEFAULT_TITLE: Final[str] = "Support request"
    _INTENT_TITLES: Final[dict[str, str]] = {
        "greeting": "General support",
        "general": "General support question",
        "general_inquiry": "General support question",
        "help": "General support question",
        "faq": "General information request",

        "return": "Return and exchange help",
        "returns": "Return and exchange help",
        "return_exchange": "Return and exchange help",
        "refund": "Refund assistance",
        "refund_request": "Refund assistance",

        "order": "Order assistance",
        "order_status": "Order status request",
        "shipping": "Shipping assistance",
        "delivery": "Delivery assistance",
        "delivery_issue": "Delivery assistance",

        "payment": "Payment assistance",
        "payment_issue": "Payment assistance",
        "billing": "Billing assistance",
        "billing_issue": "Billing assistance",
        "duplicate_charge": "Duplicate charge assistance",

        "subscription": "Subscription assistance",
        "subscription_issue": "Subscription assistance",
        "cancellation": "Cancellation assistance",

        "account": "Account assistance",
        "account_access": "Account access help",
        "account_issue": "Account assistance",
        "account_security": "Account security help",
        "security_issue": "Account security help",
        "credential_compromise": "Account security help",

        "technical": "Technical support",
        "technical_issue": "Technical support",
        "product": "Product information",
        "product_information": "Product information",

        "complaint": "Customer service concern",
        "human_support": "Human support request",
        "escalation": "Human support request",
    }
    _CATEGORY_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
        (
            re.compile(
                r"\b(?:"
                r"stolen|hacked|compromised|unauthori[sz]ed|"
                r"phishing|fraud|scam|password|passcode|credential|"
                r"cannot\s+(?:log\s*in|sign\s*in)|"
                r"can't\s+(?:log\s*in|sign\s*in)|"
                r"locked\s+out"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Account security help",
        ),
        (
            re.compile(
                r"\b(?:"
                r"charged\s+(?:twice|multiple\s+times)|"
                r"duplicate\s+charge|double\s+charge"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Duplicate charge assistance",
        ),
        (
            re.compile(
                r"\b(?:"
                r"refund|refunded|money\s+back|reimbursement"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Refund assistance",
        ),
        (
            re.compile(
                r"\b(?:"
                r"return(?:s|ed|ing)?|"
                r"exchange(?:s|d|ing)?|"
                r"replacement"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Return and exchange help",
        ),
        (
            re.compile(
                r"\b(?:"
                r"payment|billing|charged|charge|invoice|"
                r"transaction|card\s+declined"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Payment assistance",
        ),
        (
            re.compile(
                r"\b(?:"
                r"where\s+is\s+(?:my\s+)?order|"
                r"order\s+status|track(?:ing)?\s+(?:my\s+)?order|"
                r"shipment\s+status"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Order status request",
        ),
        (
            re.compile(
                r"\b(?:"
                r"shipping|shipment|delivery|delivered|"
                r"courier|package|parcel"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Delivery assistance",
        ),
        (
            re.compile(
                r"\b(?:"
                r"order|purchase"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Order assistance",
        ),
        (
            re.compile(
                r"\b(?:"
                r"subscription|subscribe|renewal|renew|"
                r"cancel\s+(?:my\s+)?(?:plan|subscription)|"
                r"membership"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Subscription assistance",
        ),
        (
            re.compile(
                r"\b(?:"
                r"account|profile|sign\s+in|log\s+in|login"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Account assistance",
        ),
        (
            re.compile(
                r"\b(?:"
                r"error|bug|broken|not\s+working|"
                r"technical|"
                r"crash(?:es|ed|ing)?|"
                r"failed\s+to|unable\s+to"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Technical support",
        ),
        (
            re.compile(
                r"\b(?:"
                r"product|feature|features|pricing|price|"
                r"availability|available|how\s+does"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Product information",
        ),
        (
            re.compile(
                r"\b(?:"
                r"complaint|unhappy|disappointed|poor\s+service|"
                r"bad\s+experience"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Customer service concern",
        ),
        (
            re.compile(
                r"\b(?:"
                r"human|support\s+agent|customer\s+service|"
                r"representative|speak\s+to\s+someone"
                r")\b",
                flags=re.IGNORECASE,
            ),
            "Human support request",
        ),
    )
    _GREETING_ONLY: Final[re.Pattern[str]] = re.compile(
        r"^\s*(?:"
        r"hi|hello|hey|good\s+morning|good\s+afternoon|"
        r"good\s+evening|greetings"
        r")(?:\s+(?:there|team|support))?"
        r"[\s!,.?]*$",
        flags=re.IGNORECASE,
    )
    _GENERAL_HELP: Final[re.Pattern[str]] = re.compile(
        r"\b(?:"
        r"what\s+(?:can|could)\s+you\s+(?:do|help\s+with)|"
        r"how\s+can\s+you\s+help|"
        r"what\s+(?:kind|type)s?\s+of\s+help|"
        r"need\s+help|help\s+me"
        r")\b",
        flags=re.IGNORECASE,
    )

    def generate(self, *, customer_message: str, intent: str | None = None) -> ConversationTitleResult:
        if not isinstance(customer_message, str):
            raise TypeError("customer_message must be a string")

        if intent is not None and not isinstance(intent, str):
            raise TypeError("intent must be a string or None")

        normalized_message = " ".join(customer_message.split())
        normalized_intent = self._normalize_intent(intent) if intent is not None else None
        title = self._title_from_intent(normalized_intent)
        if title is None:
            title = self._title_from_message(normalized_message)

        return ConversationTitleResult(title=title, source=ConversationTitleSource.FALLBACK)

    def _title_from_intent(self, intent: str | None) -> str | None:
        if intent is None:
            return None

        return self._INTENT_TITLES.get(intent)

    def _title_from_message(self, customer_message: str) -> str:
        if not customer_message:
            return self.DEFAULT_TITLE
        # Specific support categories take precedence over greeting text.
        # For example, "Hello, I need a refund" remains refund assistance.
        for pattern, title in self._CATEGORY_PATTERNS:
            if pattern.search(customer_message):
                return title

        if self._GENERAL_HELP.search(customer_message):
            return "General support question"

        if self._GREETING_ONLY.fullmatch(customer_message):
            return "General support"

        return self.DEFAULT_TITLE

    @staticmethod
    def _normalize_intent(intent: str) -> str | None:
        normalized = intent.strip().lower()
        if not normalized:
            return None

        normalized = re.sub(r"[\s-]+", "_", normalized)
        return normalized