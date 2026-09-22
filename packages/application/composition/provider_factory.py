# AI-customer-support-agent\packages\application\composition\provider_factory.py
from __future__ import annotations
from decimal import Decimal

from packages.ai.providers.base import LLMProvider
from packages.ai.providers.groq import GroqProvider, GroqProviderConfig
from packages.ai.providers.mock import MockLLMProvider
from packages.ai.providers.capacity_limited import CapacityLimitedLLMProvider, ProviderCapacityConfig
from packages.ai.providers.resilient import ResilientLLMProvider, ProviderRetryConfig
from packages.config.settings import Settings

class ProviderConfigurationError(RuntimeError):
    """
    Raised when application provider configuration is invalid.
    """


def create_llm_provider(*, settings: Settings) -> LLMProvider:
    """
    Construct the application's base LLM provider.

    This is a composition concern, not an AI-domain concern.

    The returned provider is intentionally uninstrumented. 
    Request-scoped InstrumentedLLMProvider instances are created later by AIPipelineFactory.
    """

    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")

    provider_name = settings.llm_provider.strip().lower()
    if provider_name == "groq":
        groq_provider = _create_groq_provider(settings=settings)

        capacity_limited_provider = CapacityLimitedLLMProvider(
            provider=groq_provider,
            config=ProviderCapacityConfig(
                max_concurrency=settings.ai_provider_max_concurrency,
                queue_timeout_seconds=settings.ai_provider_queue_timeout_seconds,
                minimum_start_interval_seconds=settings.ai_provider_minimum_start_interval_seconds,
            ),
        )

        return ResilientLLMProvider(
            provider=capacity_limited_provider,
            config=ProviderRetryConfig(
                max_retries=settings.ai_provider_max_retries,
                base_delay_seconds=settings.ai_provider_retry_base_delay_seconds,
                maximum_delay_seconds=settings.ai_provider_retry_maximum_delay_seconds,
                jitter_ratio=settings.ai_provider_retry_jitter_ratio,
            ),
        )

    if provider_name == "mock":
        return MockLLMProvider()

    raise ProviderConfigurationError(f"Unsupported LLM provider: {settings.llm_provider!r}")


def _create_groq_provider(*, settings: Settings) -> GroqProvider:
    api_key = settings.groq_api_key
    if api_key is None or not api_key.strip():
        raise ProviderConfigurationError("GROQ_API_KEY is required when LLM_PROVIDER=groq")

    return GroqProvider(
        config=GroqProviderConfig(
            api_key=api_key,
            model=settings.groq_model,
            timeout_seconds=settings.groq_timeout_seconds,
            max_completion_tokens=settings.groq_max_completion_tokens,
            temperature=Decimal(str(settings.groq_temperature)),
        )
    )