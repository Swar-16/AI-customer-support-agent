from __future__ import annotations
import pytest

from packages.ai.intent.schemas import IntentResult
from packages.ai.intent.taxonomy import IntentType
from packages.ai.providers.groq import GroqProvider, GroqProviderConfig
from packages.ai.providers.types import StructuredLLMResponse
from packages.config.settings import get_settings

# Integration marker
pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_provider,
]

# Provider fixture
@pytest.fixture(scope="module")
def groq_provider() -> GroqProvider:
    settings = get_settings("development")
    if not settings.groq_api_key:
        pytest.skip("GROQ_API_KEY is not configured")

    return GroqProvider(
        config=GroqProviderConfig(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            timeout_seconds=settings.groq_timeout_seconds,
            max_completion_tokens=settings.groq_max_completion_tokens,
        )
    )

# Live structured-output test
def test_live_structured_intent_classification(groq_provider: GroqProvider) -> None:
    result = groq_provider.generate_structured(
        system_prompt="You are a customer-support intent classifier. Return only the required structured result. The user is reporting a payment problem.",
        user_prompt="I was charged twice for order ORD-123.",
        response_model=IntentResult,
    )

    assert isinstance(result, StructuredLLMResponse)
    assert isinstance(result.output, IntentResult)

    # Do not over-constrain live-model behavior.
    # PAYMENT_ISSUE is expected, but the important contract here is that
    # Groq successfully produced a schema-valid canonical IntentResult.
    assert result.output.intent in set(IntentType)
    assert 0.0 <= result.output.confidence <= 1.0
    assert result.provider == "groq"
    assert result.model
    assert result.metadata.provider_request_id is not None
    assert result.usage.input_tokens >= 0
    assert result.usage.output_tokens >= 0
    assert result.usage.total_tokens >= 0