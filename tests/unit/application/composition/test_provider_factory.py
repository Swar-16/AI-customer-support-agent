from __future__ import annotations
import pytest

from packages.ai.providers.groq import GroqProvider
from packages.ai.providers.mock import MockLLMProvider
from packages.application.composition.provider_factory import ProviderConfigurationError, create_llm_provider
from packages.config.settings import Settings


def make_settings(**overrides) -> Settings:
    values = {
        # Required application/database settings
        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "support_ai_test",
        "database_user": "support_ai_test_user",
        "database_password": "test-db-password",

        # Provider settings
        "llm_provider": "mock",
        "groq_api_key": None,
        "groq_model": "openai/gpt-oss-20b",
        "groq_timeout_seconds": 30.0,
        "groq_max_completion_tokens": 1024,
        "groq_temperature": 0.0,
    }

    values.update(overrides)
    return Settings( _env_file=None, **values)

def test_mock_provider_selected() -> None:
    settings = make_settings(llm_provider="mock")
    provider = create_llm_provider(settings=settings)

    assert isinstance(provider, MockLLMProvider)

def test_provider_name_is_case_insensitive() -> None:
    settings = make_settings(llm_provider="  MoCk  ")
    provider = create_llm_provider(settings=settings)

    assert isinstance(provider, MockLLMProvider)

def test_groq_provider_selected() -> None:
    settings = make_settings(llm_provider="groq", groq_api_key="test-groq-key")
    provider = create_llm_provider(settings=settings)

    assert isinstance(provider, GroqProvider)
    assert provider.provider_name == "groq"
    assert provider.model_name == "openai/gpt-oss-20b"

def test_missing_groq_api_key_rejected() -> None:
    settings = make_settings(llm_provider="groq", groq_api_key=None)

    with pytest.raises(ProviderConfigurationError, match="GROQ_API_KEY"):
        create_llm_provider(settings=settings)

def test_blank_groq_api_key_rejected() -> None:
    settings = make_settings(llm_provider="groq", groq_api_key="   ")

    with pytest.raises(ProviderConfigurationError, match="GROQ_API_KEY"):
        create_llm_provider(settings=settings)


def test_unsupported_provider_rejected() -> None:
    settings = make_settings(llm_provider="unknown-provider")

    with pytest.raises(ProviderConfigurationError, match="Unsupported LLM provider"):
        create_llm_provider(settings=settings)


def test_non_settings_object_rejected() -> None:
    with pytest.raises(TypeError):
        create_llm_provider(settings="bad-settings")


def test_groq_configuration_is_forwarded() -> None:
    settings = make_settings(
        llm_provider="groq",
        groq_api_key="test-key",
        groq_model="custom-model",
        groq_timeout_seconds=12.5,
        groq_max_completion_tokens=777,
        groq_temperature=0.25,
    )

    provider = create_llm_provider(settings=settings)

    assert isinstance(provider, GroqProvider)
    assert provider.model_name == "custom-model"