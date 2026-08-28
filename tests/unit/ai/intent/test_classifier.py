"""
Unit tests for IntentClassifier.

Design notes
------------
- The LLM provider is fully mocked (`create_autospec(LLMProvider)`), so these
  tests never hit a real model/network call.
- Provider responses are represented as `Mock(spec=IntentResult, **fields)`.
  Because the mock is spec'd against the real `IntentResult` class, the
  classifier's `isinstance(result, IntentResult)` guard passes without us
  needing to know how to legally construct a real `IntentResult` instance.
- Tests assert against the PUBLIC contract wherever possible (exceptions
  raised, what gets passed to `provider.generate_structured`, call counts)
  rather than reaching into private methods, so refactors of the classifier's
  internals won't break the suite. `_build_system_prompt`/`_build_user_prompt`
  are only ever exercised indirectly, via the mocked provider's call_args.

Adjust as needed
-----------------
The exact `IntentType` member names used below (`PAYMENT_ISSUE`,
`ORDER_STATUS`, `UNKNOWN`) are assumed based on the classifier module and the
test scenarios requested. Rename them to match your actual
`packages.ai.intent.taxonomy.IntentType` enum if it differs.
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, create_autospec

from packages.ai.intent.classifier import (
    DEFAULT_MAX_MESSAGE_LENGTH,
    IntentClassificationError,
    IntentClassificationProviderError,
    IntentClassificationTimeoutError,
    IntentClassifier,
    IntentClassifierConfig,
    InvalidIntentInputError,
    InvalidIntentResponseError,
)
from packages.ai.intent.schemas import IntentResult
from packages.ai.intent.taxonomy import IntentType
from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import LLMProviderError, LLMProviderResponseError, LLMProviderTimeoutError
from packages.ai.providers.types import StructuredLLMResponse, TokenUsage

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_provider():
    """An autospec'd LLMProvider so unexpected method calls fail loudly."""
    return create_autospec(LLMProvider, instance=True)


@pytest.fixture
def classifier(mock_provider):
    return IntentClassifier(provider=mock_provider)


def make_intent_result(**overrides) -> IntentResult:
    values = {
        "intent": IntentType.GENERAL_QUESTION,
        "confidence": 0.80,
        "reason_summary": "General supported customer question.",
        "needs_clarification": False,
    }

    values.update(overrides)

    return IntentResult(**values)

def make_provider_response(intent: IntentResult | None = None, *, input_tokens: int = 0, output_tokens: int = 0) -> StructuredLLMResponse[IntentResult]:
    return StructuredLLMResponse(
        output=intent or make_intent_result(),
        provider="mock",
        model="mock-llm-v1",
        usage=TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )


def get_call_kwargs(mock_provider) -> dict:
    _, kwargs = mock_provider.generate_structured.call_args
    return kwargs


# ---------------------------------------------------------------------------
# Happy path classifications
# ---------------------------------------------------------------------------


def test_valid_payment_classification(classifier, mock_provider):
    expected = make_intent_result(
        intent=IntentType.PAYMENT_ISSUE,
        confidence=0.94,
        reason_summary="Customer reports being charged twice for one order.",
        needs_clarification=False,
    )
    mock_provider.generate_structured.return_value = make_provider_response(expected)

    result = classifier.classify(
        customer_message="I was charged twice for the same order, please help."
    )

    assert result is expected
    assert result.intent == IntentType.PAYMENT_ISSUE
    assert result.needs_clarification is False
    mock_provider.generate_structured.assert_called_once()


def test_valid_unknown_classification(classifier, mock_provider):
    expected = make_intent_result(
        intent=IntentType.UNKNOWN,
        confidence=0.12,
        reason_summary="Message does not map to any canonical intent.",
        needs_clarification=True,
    )
    mock_provider.generate_structured.return_value = make_provider_response(expected)

    result = classifier.classify(customer_message="asdkjfh random gibberish??")

    assert result.intent == IntentType.UNKNOWN
    assert result.needs_clarification is True


def test_missing_order_id_still_allows_order_status(classifier, mock_provider):
    """
    The classifier must not require an order ID to be present in order to
    return ORDER_STATUS — it should defer to the provider's judgment and
    simply flag needs_clarification when operational detail is missing.
    """
    expected = make_intent_result(
        intent=IntentType.ORDER_STATUS,
        confidence=0.81,
        reason_summary="Customer is asking about order status but gave no order ID.",
        needs_clarification=True,
    )
    mock_provider.generate_structured.return_value = make_provider_response(expected)

    result = classifier.classify(customer_message="Hey, what's going on with my order?")

    assert result.intent == IntentType.ORDER_STATUS
    assert result.needs_clarification is True


# ---------------------------------------------------------------------------
# Input validation (must fail BEFORE the provider is ever called)
# ---------------------------------------------------------------------------


def test_empty_message_rejected_before_provider_call(classifier, mock_provider):
    with pytest.raises(InvalidIntentInputError):
        classifier.classify(customer_message="")

    mock_provider.generate_structured.assert_not_called()


def test_whitespace_only_message_rejected(classifier, mock_provider):
    with pytest.raises(InvalidIntentInputError):
        classifier.classify(customer_message="   \n\t   ")

    mock_provider.generate_structured.assert_not_called()


def test_non_string_message_rejected(classifier, mock_provider):
    with pytest.raises(InvalidIntentInputError):
        classifier.classify(customer_message=12345)  # type: ignore[arg-type]

    mock_provider.generate_structured.assert_not_called()


def test_oversized_message_rejected(mock_provider):
    config = IntentClassifierConfig(max_message_length=10)
    small_classifier = IntentClassifier(provider=mock_provider, config=config)

    with pytest.raises(InvalidIntentInputError):
        small_classifier.classify(
            customer_message="this message is definitely too long for the limit"
        )

    mock_provider.generate_structured.assert_not_called()


def test_message_at_default_limit_boundary_is_accepted(classifier, mock_provider):
    """A message exactly at the configured max length should NOT be rejected."""
    mock_provider.generate_structured.return_value = make_provider_response()
    boundary_message = "a" * DEFAULT_MAX_MESSAGE_LENGTH

    classifier.classify(customer_message=boundary_message)

    mock_provider.generate_structured.assert_called_once()
    
def test_message_over_default_limit_is_rejected(classifier, mock_provider):
    message = "a" * (DEFAULT_MAX_MESSAGE_LENGTH + 1)

    with pytest.raises(InvalidIntentInputError):
        classifier.classify(customer_message=message)

    mock_provider.generate_structured.assert_not_called()


# ---------------------------------------------------------------------------
# Context normalization
# ---------------------------------------------------------------------------


def test_none_context_renders_as_no_context_placeholder(classifier, mock_provider):
    mock_provider.generate_structured.return_value = make_provider_response()

    classifier.classify(customer_message="Where is my order?", conversation_context=None)

    user_prompt = get_call_kwargs(mock_provider)["user_prompt"]
    assert "No conversation context provided." in user_prompt
    assert "<conversation_context>" not in user_prompt


def test_whitespace_only_context_normalizes_to_none(classifier, mock_provider):
    mock_provider.generate_structured.return_value = make_provider_response()

    classifier.classify(
        customer_message="Where is my order?",
        conversation_context="    \n  ",
    )

    user_prompt = get_call_kwargs(mock_provider)["user_prompt"]
    assert "No conversation context provided." in user_prompt
    assert "<conversation_context>" not in user_prompt


def test_context_is_stripped_and_wrapped_when_present(classifier, mock_provider):
    mock_provider.generate_structured.return_value = make_provider_response()

    classifier.classify(
        customer_message="Where is my order?",
        conversation_context="   Customer previously asked about a refund.   ",
    )

    user_prompt = get_call_kwargs(mock_provider)["user_prompt"]
    assert "<conversation_context>" in user_prompt
    assert "Customer previously asked about a refund." in user_prompt
    # Ensure it was stripped, not just wrapped with leading/trailing whitespace intact.
    assert "<conversation_context>\n   Customer" not in user_prompt


def test_non_string_context_rejected(classifier, mock_provider):
    with pytest.raises(InvalidIntentInputError):
        classifier.classify(customer_message="Hello", conversation_context=42)  # type: ignore[arg-type]

    mock_provider.generate_structured.assert_not_called()


# ---------------------------------------------------------------------------
# Provider failure translation
# ---------------------------------------------------------------------------


def test_provider_timeout_translated_correctly(classifier, mock_provider):
    mock_provider.generate_structured.side_effect = (
        LLMProviderTimeoutError(
            provider="mock",
            message="timed out"
        )
    )

    with pytest.raises(IntentClassificationTimeoutError):
        classifier.classify(customer_message="Hello, are you there?")


def test_provider_generic_failure_translated_correctly(classifier, mock_provider):
    mock_provider.generate_structured.side_effect = (
        LLMProviderError(
            provider="mock",
            message="upstream 500"
        )
    )

    with pytest.raises(IntentClassificationProviderError):
        classifier.classify(customer_message="Hello, are you there?")


def test_malformed_structured_output_via_provider_error(classifier, mock_provider):
    """Provider signals it could not produce a schema-conformant response."""
    mock_provider.generate_structured.side_effect = (
        LLMProviderResponseError(
            provider="mock",
            message="response failed schema validation"
        )
    )

    with pytest.raises(InvalidIntentResponseError):
        classifier.classify(customer_message="Hello, are you there?")


def test_malformed_structured_output_via_wrong_return_type(classifier, mock_provider):
    """
    Defensive check: even if the provider claims success but hands back
    something that isn't an IntentResult, the classifier must not leak it.
    """
    mock_provider.generate_structured.return_value = {"intent": "UNKNOWN"}

    with pytest.raises(InvalidIntentResponseError):
        classifier.classify(customer_message="Hello, are you there?")


def test_unexpected_exception_is_wrapped_not_swallowed(classifier, mock_provider):
    """
    An implementation defect (e.g. a bug in the provider) should still
    surface as a classifier-level error rather than crashing with an
    unrelated, unhandled exception type or silently becoming UNKNOWN.
    """
    mock_provider.generate_structured.side_effect = ValueError("unexpected bug")

    with pytest.raises(IntentClassificationError):
        classifier.classify(customer_message="Hello, are you there?")


# ---------------------------------------------------------------------------
# Provider invocation contract
# ---------------------------------------------------------------------------


def test_provider_invoked_exactly_once_per_classification(classifier, mock_provider):
    mock_provider.generate_structured.return_value = make_provider_response()

    classifier.classify(customer_message="Hi there")
    assert mock_provider.generate_structured.call_count == 1

    classifier.classify(customer_message="Hi again")
    assert mock_provider.generate_structured.call_count == 2


def test_provider_called_with_response_model_intent_result(classifier, mock_provider):
    mock_provider.generate_structured.return_value = make_provider_response()

    classifier.classify(customer_message="Hi there")

    kwargs = get_call_kwargs(mock_provider)
    assert kwargs["response_model"] is IntentResult


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_prompt_contains_every_canonical_intent(classifier, mock_provider):
    mock_provider.generate_structured.return_value = make_provider_response()

    classifier.classify(customer_message="Test message for taxonomy coverage")

    system_prompt = get_call_kwargs(mock_provider)["system_prompt"]
    for intent in IntentType:
        assert intent.value in system_prompt, f"{intent.value} missing from system prompt"


def test_customer_message_is_delimited_in_user_prompt(classifier, mock_provider):
    mock_provider.generate_structured.return_value = make_provider_response()

    classifier.classify(customer_message="Refund my last order please")

    user_prompt = get_call_kwargs(mock_provider)["user_prompt"]
    assert "<customer_message>" in user_prompt
    assert "Refund my last order please" in user_prompt
    assert "</customer_message>" in user_prompt


# ---------------------------------------------------------------------------
# Constructor / config validation (bonus coverage)
# ---------------------------------------------------------------------------


def test_constructor_rejects_none_provider():
    with pytest.raises(TypeError):
        IntentClassifier(provider=None)  # type: ignore[arg-type]


def test_config_rejects_non_positive_max_message_length():
    with pytest.raises(ValueError):
        IntentClassifierConfig(max_message_length=0)


def test_config_rejects_negative_max_examples_per_intent():
    with pytest.raises(ValueError):
        IntentClassifierConfig(max_examples_per_intent=-1)
        

# ---------------------------------------------------------------------------
# Full provider response contract
# ---------------------------------------------------------------------------


def test_classify_with_response_preserves_provider_response(classifier, mock_provider):
    intent = make_intent_result(intent=IntentType.PAYMENT_ISSUE, confidence=0.92)
    provider_response = make_provider_response(intent, input_tokens=100, output_tokens=25)
    mock_provider.generate_structured.return_value = provider_response
    result = classifier.classify_with_response(customer_message="I was charged twice.")

    assert result is provider_response
    assert result.output is intent

    assert result.provider == "mock"
    assert result.model == "mock-llm-v1"

    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 25
    assert result.usage.total_tokens == 125
    
def test_classify_returns_only_intent_result(classifier, mock_provider):
    intent = make_intent_result()
    mock_provider.generate_structured.return_value = make_provider_response(intent)
    result = classifier.classify(customer_message="hello")

    assert result is intent
    assert isinstance(result, IntentResult)