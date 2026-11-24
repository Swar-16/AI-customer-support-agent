# AI-customer-support-agent\packages\ai\intent\jev_classifier.py
from __future__ import annotations
import json
import logging
import re
from decimal import Decimal
from typing import Final, Mapping

from typesafe_sdk import Choice, ChoiceAnswer, Noul, NoulAnswer, SystemOneResponse, TypeSafeClient
from typesafe_sdk import TypeSafeError

from packages.ai.intent.classifier import IntentClassifier, IntentClassifierConfig
from packages.ai.intent.schemas import EscalationSignal, IntentEntities, IntentResult
from packages.ai.intent.taxonomy import INTENT_DEFINITIONS, IntentType
from packages.ai.providers.types import ProviderMetadata, StructuredLLMResponse, TokenUsage

logger = logging.getLogger(__name__)

# Precompiled regex patterns for common customer identifiers
_ORDER_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(ORD-[A-Za-z0-9-]{3,20})\b|\b(order_[A-Za-z0-9_-]{3,30})\b|\b(?:order|ord)(?:\s*(?:is|id|number|#|:|=|-)\s*|\s+)([A-Za-z0-9_-]{3,30})\b",
    re.IGNORECASE,
)
_TRANSACTION_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(TXN-[A-Za-z0-9-]{3,20})\b|\b(txn_[A-Za-z0-9_-]{3,30})\b|\b(?:transaction|txn|tx)(?:\s*(?:is|id|number|#|:|=|-)\s*|\s+)([A-Za-z0-9_-]{3,30})\b",
    re.IGNORECASE,
)
_SUBSCRIPTION_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(SUB-[A-Za-z0-9-]{3,20})\b|\b(sub_[A-Za-z0-9_-]{3,30})\b|\b(?:subscription|sub)(?:\s*(?:is|id|number|#|:|=|-)\s*|\s+)([A-Za-z0-9_-]{3,30})\b",
    re.IGNORECASE,
)
_ACCOUNT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(ACC-[A-Za-z0-9-]{3,20})\b|\b(acc_[A-Za-z0-9_-]{3,30})\b|\b(?:account|acc)(?:\s*(?:is|id|number|#|:|=|-)\s*|\s+)([A-Za-z0-9_-]{3,30})\b",
    re.IGNORECASE,
)


def _extract_first_matching_group(match: re.Match[str] | None) -> str | None:
    if not match:
        return None
    for group in match.groups():
        if group:
            cleaned = group.strip()
            if cleaned:
                return cleaned
    return None


def extract_entities_from_text(text: str) -> IntentEntities:
    """Extract common business entities from customer text using conservative regexes."""
    order_id = _extract_first_matching_group(_ORDER_ID_PATTERN.search(text))
    transaction_id = _extract_first_matching_group(_TRANSACTION_ID_PATTERN.search(text))
    subscription_id = _extract_first_matching_group(_SUBSCRIPTION_ID_PATTERN.search(text))
    account_id = _extract_first_matching_group(_ACCOUNT_ID_PATTERN.search(text))

    return IntentEntities(
        order_id=order_id,
        transaction_id=transaction_id,
        subscription_id=subscription_id,
        account_id=account_id,
    )


class JevIntentClassifier(IntentClassifier):
    """
    High-speed, zero-output-token intent classifier powered by TypeSafe AI's Jev model.

    Jev is a non-autoregressive System One decision model that classifies text into
    structured probabilities without generating tokens. This reduces token consumption
    to zero output tokens and slashes latency.

    If Jev confidence is below the configured threshold, or if an API key is not
    configured, or if an unexpected transport/API error occurs, this classifier
    transparently falls back to the provided fallback LLM classifier (Gemini).
    """

    def __init__(
        self,
        *,
        fallback_classifier: IntentClassifier,
        typesafe_api_key: str | None = None,
        model: str = "jev-latest",
        confidence_threshold: float = 0.70,
        config: IntentClassifierConfig | None = None,
        client: TypeSafeClient | None = None,
    ) -> None:
        if fallback_classifier is None:
            raise TypeError("fallback_classifier cannot be None")

        super().__init__(provider=fallback_classifier._provider, config=config)
        self._fallback_classifier = fallback_classifier
        raw_key = typesafe_api_key.strip() if typesafe_api_key and typesafe_api_key.strip() else None
        is_placeholder = raw_key is not None and ("YOUR_" in raw_key.upper() or "PLACEHOLDER" in raw_key.upper())
        self._typesafe_api_key = None if is_placeholder else raw_key
        self._model = model
        self._confidence_threshold = confidence_threshold

        if client is not None:
            self._client = client
        elif self._typesafe_api_key:
            self._client = TypeSafeClient(api_key=self._typesafe_api_key)
        else:
            self._client = None

        # Build Jev Choice criteria once from canonical intent definitions
        self._criteria: Mapping[str, str] = {
            intent_def.intent.value: intent_def.description
            for intent_def in INTENT_DEFINITIONS.values()
        }

    @property
    def is_jev_active(self) -> bool:
        """Return True if Jev client is initialized with an active API key."""
        return self._client is not None

    def classify_with_response(
        self,
        *,
        customer_message: str,
        conversation_context: str | None = None,
    ) -> StructuredLLMResponse[IntentResult]:
        """
        Classify customer message using Jev System One model, falling back to LLM if needed.
        """
        normalized_message = self._validate_and_normalize_message(customer_message)
        normalized_context = self._normalize_context(conversation_context)

        # 1. Fallback directly if Jev client is not configured
        if self._client is None:
            return self._fallback_classifier.classify_with_response(
                customer_message=normalized_message,
                conversation_context=normalized_context,
            )

        # 2. Attempt Jev evaluation
        try:
            return self._evaluate_with_jev(
                customer_message=normalized_message,
                conversation_context=normalized_context,
            )
        except Exception as exc:
            logger.warning(
                "Jev intent classification failed (%s: %s). Falling back to LLM provider.",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return self._fallback_classifier.classify_with_response(
                customer_message=normalized_message,
                conversation_context=normalized_context,
            )

    def _evaluate_with_jev(
        self,
        *,
        customer_message: str,
        conversation_context: str | None,
    ) -> StructuredLLMResponse[IntentResult]:
        """Execute Jev System One question-answering evaluation."""
        state_parts = [f"Customer Message: {customer_message}"]
        if conversation_context:
            state_parts.append(f"Conversation Context:\n{conversation_context}")
        state = "\n\n".join(state_parts)

        questions = {
            "intent": Choice(
                instructions="Classify the core customer intent into exactly one supported canonical category based on their request.",
                criteria=self._criteria,
            ),
            "needs_clarification": Noul(
                instructions="Does this customer message lack critical details required to act on it, or is it too ambiguous or incomplete?",
            ),
            "explicit_human_request": Noul(
                instructions="Does the customer explicitly demand to speak or transfer to a human agent, supervisor, or real person?",
            ),
            "severe_customer_dissatisfaction": Noul(
                instructions="Does the customer express extreme anger, threats of legal action/regulatory complaint, or severe escalation-worthy distress?",
            ),
        }

        response: SystemOneResponse = self._client.system_one(
            state=state,
            questions=questions,
            model=self._model,
        )

        # 3. Parse intent choice
        intent_answer = response.answers.get("intent")
        if not isinstance(intent_answer, ChoiceAnswer) or not intent_answer.choice:
            logger.info("Jev returned non-choice intent answer; falling back to LLM.")
            return self._fallback_classifier.classify_with_response(
                customer_message=customer_message,
                conversation_context=conversation_context,
            )

        selected_choice = intent_answer.choice
        confidence = float(intent_answer.confidence or 0.0)

        # Check confidence against threshold
        if confidence < self._confidence_threshold:
            logger.info(
                "Jev intent confidence (%.3f) below threshold (%.3f); falling back to LLM.",
                confidence,
                self._confidence_threshold,
            )
            return self._fallback_classifier.classify_with_response(
                customer_message=customer_message,
                conversation_context=conversation_context,
            )

        try:
            intent_type = IntentType(selected_choice)
        except ValueError:
            logger.warning("Jev returned unrecognized intent '%s'; falling back to LLM.", selected_choice)
            return self._fallback_classifier.classify_with_response(
                customer_message=customer_message,
                conversation_context=conversation_context,
            )

        # 4. Parse needs_clarification
        clarification_answer = response.answers.get("needs_clarification")
        needs_clarification = False
        if isinstance(clarification_answer, NoulAnswer) and clarification_answer.noul is not None:
            needs_clarification = clarification_answer.noul >= 0.5

        if intent_type is IntentType.UNKNOWN:
            needs_clarification = True

        # 5. Parse escalation signals
        escalation_signals: list[EscalationSignal] = []
        human_answer = response.answers.get("explicit_human_request")
        if isinstance(human_answer, NoulAnswer) and human_answer.noul is not None and human_answer.noul >= 0.6:
            escalation_signals.append(EscalationSignal.EXPLICIT_HUMAN_REQUEST)

        dissat_answer = response.answers.get("severe_customer_dissatisfaction")
        if isinstance(dissat_answer, NoulAnswer) and dissat_answer.noul is not None and dissat_answer.noul >= 0.6:
            escalation_signals.append(EscalationSignal.SEVERE_CUSTOMER_DISSATISFACTION)

        # 6. Extract entities
        entities = extract_entities_from_text(customer_message)

        # 7. Build IntentResult
        result = IntentResult(
            intent=intent_type,
            confidence=round(confidence, 4),
            entities=entities,
            needs_clarification=needs_clarification,
            escalation_signals=tuple(escalation_signals),
            reason_summary=f"Classified by Jev System One model ({self._model}).",
        )

        input_tokens = response.usage.input_tokens if response.usage else 0

        return StructuredLLMResponse(
            output=result,
            provider="typesafe",
            model=self._model,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=0,
            ),
            metadata=ProviderMetadata(
                provider_request_id=None,
                finish_reason="stop",
                raw_model_name=self._model,
            ),
            estimated_cost_usd=Decimal("0.0"),
        )
