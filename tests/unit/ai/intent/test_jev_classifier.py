from __future__ import annotations
import json
from unittest.mock import MagicMock, Mock

import pytest
from typesafe_sdk import ChoiceAnswer, NoulAnswer, SystemOneResponse, Usage, TypeSafeError

from packages.ai.intent.classifier import IntentClassifier, InvalidIntentInputError
from packages.ai.intent.jev_classifier import JevIntentClassifier, extract_entities_from_text
from packages.ai.intent.schemas import EscalationSignal, IntentEntities, IntentResult
from packages.ai.intent.taxonomy import IntentType
from packages.ai.providers.types import StructuredLLMResponse, TokenUsage


def make_fallback_result(
    intent: IntentType = IntentType.REFUND_REQUEST,
    confidence: float = 0.95,
) -> IntentResult:
    return IntentResult(
        intent=intent,
        confidence=confidence,
        entities=IntentEntities(order_id="ORD-FALLBACK"),
        needs_clarification=False,
        reason_summary="Fallback LLM classification.",
    )


def make_fallback_response(result: IntentResult) -> StructuredLLMResponse[IntentResult]:
    return StructuredLLMResponse(
        output=result,
        provider="gemini",
        model="gemini-1.5-flash",
        usage=TokenUsage(input_tokens=100, output_tokens=25),
    )


class TestEntityExtraction:
    def test_extracts_order_id(self) -> None:
        entities = extract_entities_from_text("Where is my order ORD-998877?")
        assert entities.order_id == "ORD-998877"

        entities2 = extract_entities_from_text("Check order #12345 please")
        assert entities2.order_id == "12345"

    def test_extracts_transaction_id(self) -> None:
        entities = extract_entities_from_text("Payment failed for transaction: txn_987654")
        assert entities.transaction_id == "txn_987654"

    def test_extracts_subscription_id(self) -> None:
        entities = extract_entities_from_text("Cancel sub_monthly_premium immediately")
        assert entities.subscription_id == "sub_monthly_premium"

    def test_extracts_account_id(self) -> None:
        entities = extract_entities_from_text("My account is acc_user_12345")
        assert entities.account_id == "acc_user_12345"

    def test_extracts_no_entities_when_none_present(self) -> None:
        entities = extract_entities_from_text("Hello, how are you today?")
        assert entities.order_id is None
        assert entities.transaction_id is None
        assert entities.subscription_id is None
        assert entities.account_id is None


class TestJevIntentClassifierInit:
    def test_rejects_none_fallback_classifier(self) -> None:
        with pytest.raises(TypeError, match="fallback_classifier cannot be None"):
            JevIntentClassifier(fallback_classifier=None)  # type: ignore[arg-type]

    def test_inactive_without_api_key(self) -> None:
        fallback = Mock(spec=IntentClassifier)
        fallback._provider = Mock()
        classifier = JevIntentClassifier(fallback_classifier=fallback, typesafe_api_key=None)
        assert not classifier.is_jev_active

    def test_active_with_api_key(self) -> None:
        fallback = Mock(spec=IntentClassifier)
        fallback._provider = Mock()
        classifier = JevIntentClassifier(fallback_classifier=fallback, typesafe_api_key="test-typesafe-key")
        assert classifier.is_jev_active


class TestJevIntentClassifierExecution:
    @pytest.fixture
    def mock_fallback(self) -> Mock:
        fallback = Mock(spec=IntentClassifier)
        fallback._provider = Mock()
        fallback.classify_with_response.return_value = make_fallback_response(make_fallback_result())
        return fallback

    @pytest.fixture
    def mock_client(self) -> Mock:
        return Mock()

    def test_falls_back_when_client_is_none(self, mock_fallback: Mock) -> None:
        classifier = JevIntentClassifier(fallback_classifier=mock_fallback, client=None)
        response = classifier.classify_with_response(customer_message="I want my money back for order ORD-123")

        mock_fallback.classify_with_response.assert_called_once()
        assert response.output.entities.order_id == "ORD-FALLBACK"
        assert response.model == "gemini-1.5-flash"

    def test_successful_jev_classification(self, mock_fallback: Mock, mock_client: Mock) -> None:
        jev_response = SystemOneResponse(
            model="jev-latest",
            usage=Usage(input_tokens=42, output_tokens=0),
            answers={
                "intent": ChoiceAnswer(
                    type="choice",
                    choice="refund_request",
                    confidence=0.96,
                    probabilities={"refund_request": 0.96, "payment_issue": 0.04},
                ),
                "needs_clarification": NoulAnswer(type="noul", noul=0.1),
                "explicit_human_request": NoulAnswer(type="noul", noul=0.05),
                "severe_customer_dissatisfaction": NoulAnswer(type="noul", noul=0.08),
            },
        )
        mock_client.system_one.return_value = jev_response

        classifier = JevIntentClassifier(
            fallback_classifier=mock_fallback,
            client=mock_client,
            confidence_threshold=0.70,
        )

        response = classifier.classify_with_response(
            customer_message="I need a refund for order ORD-778899 please"
        )

        mock_fallback.classify_with_response.assert_not_called()
        assert response.output.intent is IntentType.REFUND_REQUEST
        assert response.output.confidence == 0.96
        assert response.output.entities.order_id == "ORD-778899"
        assert not response.output.needs_clarification
        assert response.output.escalation_signals == ()
        assert response.usage.output_tokens == 0
        assert response.usage.input_tokens == 42
        assert response.provider == "typesafe"
        assert response.model == "jev-latest"

    def test_falls_back_when_confidence_below_threshold(
        self, mock_fallback: Mock, mock_client: Mock
    ) -> None:
        jev_response = SystemOneResponse(
            model="jev-latest",
            usage=Usage(input_tokens=30, output_tokens=0),
            answers={
                "intent": ChoiceAnswer(
                    type="choice",
                    choice="general_question",
                    confidence=0.55,
                    probabilities={"general_question": 0.55, "out_of_scope": 0.45},
                ),
                "needs_clarification": NoulAnswer(type="noul", noul=0.3),
                "explicit_human_request": NoulAnswer(type="noul", noul=0.1),
                "severe_customer_dissatisfaction": NoulAnswer(type="noul", noul=0.1),
            },
        )
        mock_client.system_one.return_value = jev_response

        classifier = JevIntentClassifier(
            fallback_classifier=mock_fallback,
            client=mock_client,
            confidence_threshold=0.70,
        )

        response = classifier.classify_with_response(
            customer_message="Maybe something about hours?"
        )

        # Fallback was called because 0.55 < 0.70 threshold
        mock_fallback.classify_with_response.assert_called_once()
        assert response.model == "gemini-1.5-flash"

    def test_falls_back_on_typesafe_api_error(
        self, mock_fallback: Mock, mock_client: Mock
    ) -> None:
        mock_client.system_one.side_effect = TypeSafeError("API connection error")

        classifier = JevIntentClassifier(
            fallback_classifier=mock_fallback,
            client=mock_client,
        )

        response = classifier.classify_with_response(
            customer_message="Where is order ORD-1111?"
        )

        mock_fallback.classify_with_response.assert_called_once()
        assert response.model == "gemini-1.5-flash"

    def test_detects_escalation_signals_from_noul_answers(
        self, mock_fallback: Mock, mock_client: Mock
    ) -> None:
        jev_response = SystemOneResponse(
            model="jev-latest",
            usage=Usage(input_tokens=50, output_tokens=0),
            answers={
                "intent": ChoiceAnswer(
                    type="choice",
                    choice="account_issue",
                    confidence=0.92,
                    probabilities={"account_issue": 0.92},
                ),
                "needs_clarification": NoulAnswer(type="noul", noul=0.2),
                "explicit_human_request": NoulAnswer(type="noul", noul=0.85),
                "severe_customer_dissatisfaction": NoulAnswer(type="noul", noul=0.90),
            },
        )
        mock_client.system_one.return_value = jev_response

        classifier = JevIntentClassifier(
            fallback_classifier=mock_fallback,
            client=mock_client,
        )

        response = classifier.classify_with_response(
            customer_message="I demand to speak to a real person right now! I am furious!"
        )

        assert EscalationSignal.EXPLICIT_HUMAN_REQUEST in response.output.escalation_signals
        assert EscalationSignal.SEVERE_CUSTOMER_DISSATISFACTION in response.output.escalation_signals

    def test_enforces_needs_clarification_on_unknown_intent(
        self, mock_fallback: Mock, mock_client: Mock
    ) -> None:
        jev_response = SystemOneResponse(
            model="jev-latest",
            usage=Usage(input_tokens=20, output_tokens=0),
            answers={
                "intent": ChoiceAnswer(
                    type="choice",
                    choice="unknown",
                    confidence=0.88,
                    probabilities={"unknown": 0.88},
                ),
                "needs_clarification": NoulAnswer(type="noul", noul=0.1),  # even if false
                "explicit_human_request": NoulAnswer(type="noul", noul=0.1),
                "severe_customer_dissatisfaction": NoulAnswer(type="noul", noul=0.1),
            },
        )
        mock_client.system_one.return_value = jev_response

        classifier = JevIntentClassifier(
            fallback_classifier=mock_fallback,
            client=mock_client,
        )

        response = classifier.classify_with_response(
            customer_message="asdf ghjkl zxcvb"
        )

        assert response.output.intent is IntentType.UNKNOWN
        assert response.output.needs_clarification is True

    def test_rejects_empty_message(self, mock_fallback: Mock) -> None:
        classifier = JevIntentClassifier(fallback_classifier=mock_fallback)
        with pytest.raises(InvalidIntentInputError, match="customer_message cannot be empty"):
            classifier.classify(customer_message="   ")
