## Here mocked the Groq SDK client, not GroqProvider, because GroqProvider itself is exactly what we're trying to test.
from __future__ import annotations
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
import groq
import httpx
import pytest
from pydantic import BaseModel, Field

from packages.ai.providers.errors import LLMProviderAuthenticationError, LLMProviderError, LLMProviderRateLimitError
from packages.ai.providers.errors import LLMProviderResponseError, LLMProviderTimeoutError, LLMProviderUnavailableError
from packages.ai.providers.groq import GroqProvider, GroqProviderConfig
from packages.ai.providers.types import LLMResponse, StructuredLLMResponse

# Test response schema
class ExampleStructuredResponse(BaseModel):
    label: str
    confidence: float = Field(ge=0.0, le=1.0)

# Helpers
def make_completion(*, content: str = "hello", model: str = "test-model", request_id: str = "chatcmpl-test-123", finish_reason: str = "stop",
                    prompt_tokens: int = 100, completion_tokens: int = 20, cached_tokens: int = 10
):
    """
    Create a minimal Groq-like completion object.

    We deliberately use SimpleNamespace rather than depending on Groq'sgenerated response model constructors. These tests validate our adapter,
    not Groq SDK internals.
    """

    return SimpleNamespace(
        id=request_id,
        model=model,
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content)
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached_tokens)
        ),
    )


def make_mock_client():
    client = MagicMock()
    # Ensure chained attributes exist explicitly.
    client.chat.completions.create = MagicMock()
    client.models.list = MagicMock()

    return client


def make_provider(*, client=None, strict: bool = False) -> GroqProvider:
    return GroqProvider(
        config=GroqProviderConfig(
            api_key="test-api-key",
            model="test-model",
            timeout_seconds=15.0,
            max_completion_tokens=512,
            temperature=Decimal("0"),
            structured_output_strict=strict,
        ),
        client=client or make_mock_client(),
    )


def make_http_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def make_http_response(status_code: int, *, request_id: str = "req-test-123") -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        request=make_http_request(),
        headers={ "x-request-id": request_id },
    )

# Configuration
class TestGroqProviderConfig:
    def test_valid_config(self) -> None:
        config = GroqProviderConfig(api_key=" key ", model=" test-model ")

        assert config.api_key == "key"
        assert config.model == "test-model"


    def test_empty_api_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="api_key cannot be empty"):
            GroqProviderConfig(api_key="   ", model="test-model")


    def test_empty_model_rejected(self) -> None:
        with pytest.raises(ValueError, match="model cannot be empty"):
            GroqProviderConfig(api_key="key", model="   ")


    def test_non_positive_timeout_rejected(self) -> None:
        with pytest.raises(ValueError):
            GroqProviderConfig(api_key="key", model="model", timeout_seconds=0)


    def test_non_positive_max_tokens_rejected(self) -> None:
        with pytest.raises(ValueError):
            GroqProviderConfig(api_key="key", model="model", max_completion_tokens=0)


    def test_bool_max_tokens_rejected(self) -> None:
        with pytest.raises(TypeError):
            GroqProviderConfig(api_key="key", model="model", max_completion_tokens=True)  # type: ignore[arg-type]


    def test_temperature_must_be_decimal(self) -> None:
        with pytest.raises(TypeError):
            GroqProviderConfig(api_key="key", model="model", temperature=0.2)  # type: ignore[arg-type]


    @pytest.mark.parametrize("temperature", [Decimal("-0.01"), Decimal("2.01")])
    def test_temperature_range_enforced(self, temperature: Decimal) -> None:
        with pytest.raises(ValueError):
            GroqProviderConfig(api_key="key", model="model", temperature=temperature)

# Construction / identity
class TestGroqProviderConstruction:
    def test_provider_identity(self) -> None:
        provider = make_provider()

        assert provider.provider_name == "groq"
        assert provider.model_name == "test-model"


    def test_invalid_config_type_rejected(self) -> None:
        with pytest.raises(TypeError):
            GroqProvider(config="bad-config")  # type: ignore[arg-type]


# Text generation
class TestGroqTextGeneration:
    def test_text_generation_returns_normalized_response(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.return_value = make_completion(
                content="Hello customer",
                model="actual-model",
                prompt_tokens=120,
                completion_tokens=30,
                cached_tokens=20,
        )

        provider = make_provider(client=client)

        result = provider.generate(system_prompt="system", user_prompt="hello")

        assert isinstance(result, LLMResponse)
        assert result.content == "Hello customer"
        assert result.provider == "groq"
        assert result.model == "actual-model"
        assert result.usage.input_tokens == 120
        assert result.usage.output_tokens == 30
        assert result.usage.cached_input_tokens == 20
        assert result.usage.total_tokens == 150
        assert result.metadata.provider_request_id == "chatcmpl-test-123"
        assert result.metadata.finish_reason == "stop"
        assert result.estimated_cost_usd is None


    def test_text_generation_passes_expected_arguments(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.return_value = make_completion()

        provider = GroqProvider(
            config=GroqProviderConfig(
                api_key="key",
                model="llama-test",
                timeout_seconds=10,
                max_completion_tokens=321,
                temperature=Decimal("0.25"),
            ),
            client=client,
        )

        provider.generate(system_prompt="system instructions", user_prompt="customer message")

        kwargs = client.chat.completions.create.call_args.kwargs

        assert kwargs["model"] == "llama-test"
        assert kwargs["temperature"] == 0.25
        assert kwargs["max_completion_tokens"] == 321
        assert kwargs["messages"] == [
            {
                "role": "system",
                "content": "system instructions",
            },
            {
                "role": "user",
                "content": "customer message",
            },
        ]


    def test_empty_text_response_rejected(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.return_value = make_completion(content="   ")
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderResponseError):
            provider.generate(
                system_prompt="system",
                user_prompt="user",
            )


    def test_no_choices_rejected(self) -> None:
        client = make_mock_client()
        completion = make_completion()
        completion.choices = []
        client.chat.completions.create.return_value = completion
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderResponseError, match="no choices"):
            provider.generate(system_prompt="system", user_prompt="user")


# Structured generation
class TestGroqStructuredGeneration:
    def test_valid_json_is_parsed_and_validated(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.return_value = make_completion(
            content='{"label":"payment_issue","confidence":0.95}'
        )

        provider = make_provider(client=client)
        result = provider.generate_structured(
            system_prompt="system",
            user_prompt="classify",
            response_model=ExampleStructuredResponse,
        )

        assert isinstance(result, StructuredLLMResponse)
        assert isinstance(result.output, ExampleStructuredResponse)
        assert result.output.label == "payment_issue"
        assert result.output.confidence == 0.95


    def test_structured_request_sends_json_schema(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.return_value = make_completion(content='{"label":"x","confidence":0.5}')
        provider = make_provider(client=client, strict=False)

        provider.generate_structured(
            system_prompt="system",
            user_prompt="classify",
            response_model=ExampleStructuredResponse
        )

        kwargs = client.chat.completions.create.call_args.kwargs
        response_format = kwargs["response_format"]

        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is False

        schema = response_format["json_schema"]["schema"]
        assert "properties" in schema
        assert "label" in schema["properties"]
        assert "confidence" in schema["properties"]


    def test_strict_flag_is_propagated(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.return_value = make_completion(content='{"label":"x", "confidence":0.5}')
        provider = make_provider(client=client, strict=True)

        provider.generate_structured(
            system_prompt="system",
            user_prompt="classify",
            response_model=ExampleStructuredResponse,
        )

        response_format = client.chat.completions.create.call_args.kwargs["response_format"]

        assert response_format["json_schema"]["strict"] is True

    def test_malformed_json_rejected(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.return_value = make_completion(content="{this is not json")
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderResponseError, match="malformed JSON"):
            provider.generate_structured(
                system_prompt="system",
                user_prompt="classify",
                response_model=ExampleStructuredResponse
            )


    def test_schema_invalid_payload_rejected(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.return_value = make_completion(content='{"label":"payment_issue", "confidence":7.5}')
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderResponseError, match="did not satisfy"):
            provider.generate_structured(
                system_prompt="system",
                user_prompt="classify",
                response_model=ExampleStructuredResponse
            )

    def test_invalid_response_model_rejected_before_sdk_call(self) -> None:
        client = make_mock_client()
        provider = make_provider(client=client)

        with pytest.raises(TypeError):
            provider.generate_structured(
                system_prompt="system",
                user_prompt="classify",
                response_model=dict,  # type: ignore[arg-type]
            )

        client.chat.completions.create.assert_not_called()

# Usage normalization
class TestGroqUsageNormalization:
    def test_missing_usage_becomes_zero_usage(self) -> None:
        client = make_mock_client()
        completion = make_completion()
        completion.usage = None
        client.chat.completions.create.return_value = completion
        provider = make_provider(client=client)
        result = provider.generate(system_prompt="system", user_prompt="hello")

        assert result.usage.input_tokens == 0
        assert result.usage.output_tokens == 0
        assert result.usage.total_tokens == 0


    def test_missing_cache_details_defaults_to_zero(self) -> None:
        client = make_mock_client()
        completion = make_completion()
        completion.usage.prompt_tokens_details = None
        client.chat.completions.create.return_value = completion
        provider = make_provider(client=client)
        result = provider.generate(system_prompt="system", user_prompt="hello")

        assert result.usage.cached_input_tokens == 0


# Error translation
class TestGroqErrorTranslation:
    def test_timeout_translated(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.side_effect = groq.APITimeoutError(request=make_http_request())
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderTimeoutError) as exc_info:
            provider.generate(system_prompt="system", user_prompt="hello")

        assert exc_info.value.retryable is True
        assert exc_info.value.error_code == "TIMEOUT"

    def test_rate_limit_translated(self) -> None:
        client = make_mock_client()
        response = make_http_response(429)
        client.chat.completions.create.side_effect = groq.RateLimitError("rate limited", response=response, body=None)
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderRateLimitError) as exc_info:
            provider.generate(system_prompt="system", user_prompt="hello")

        assert exc_info.value.retryable is True
        assert exc_info.value.metadata["http_status_code"] == 429
        assert exc_info.value.metadata["provider_request_id"] == "req-test-123"

    def test_authentication_error_translated(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.side_effect = (groq.AuthenticationError("invalid key", response=make_http_response(401), body=None))
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderAuthenticationError) as exc_info:
            provider.generate(system_prompt="system", user_prompt="hello")

        assert exc_info.value.retryable is False


    def test_permission_error_translated_as_auth_failure(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.side_effect = groq.PermissionDeniedError("forbidden", response=make_http_response(403), body=None)
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderAuthenticationError):
            provider.generate(system_prompt="system", user_prompt="hello")

    def test_connection_error_translated(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.side_effect = groq.APIConnectionError(request=make_http_request())
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderUnavailableError) as exc_info:
            provider.generate(system_prompt="system", user_prompt="hello")

        assert exc_info.value.retryable is True


    def test_internal_server_error_translated(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.side_effect = groq.InternalServerError("server failure", response=make_http_response(500), body=None)
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderUnavailableError):
            provider.generate(system_prompt="system", user_prompt="hello")


    @pytest.mark.parametrize(("sdk_exception", "status_code",), [(groq.BadRequestError, 400,), (groq.UnprocessableEntityError, 422,)])
    def test_invalid_request_translated_to_response_error(self, sdk_exception, status_code: int) -> None:
        client = make_mock_client()
        client.chat.completions.create.side_effect = sdk_exception("invalid request", response=make_http_response(status_code), body=None)
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderResponseError):
            provider.generate_structured(
                system_prompt="system",
                user_prompt="hello",
                response_model=ExampleStructuredResponse,
            )


    def test_generic_api_error_translated(self) -> None:
        client = make_mock_client()

        # APIStatusError is a convenient generic APIError subclass for
        # exercising the fallback branch without matching a more specific
        # exception first.
        client.chat.completions.create.side_effect = groq.APIStatusError("unexpected API status", response=make_http_response(418), body=None)
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate(system_prompt="system", user_prompt="hello")

        assert exc_info.value.error_code == "GROQ_API_ERROR"


    def test_unexpected_programming_error_is_not_mislabeled(self) -> None:
        client = make_mock_client()
        client.chat.completions.create.side_effect = ValueError("adapter bug")
        provider = make_provider(client=client)

        with pytest.raises(ValueError,match="adapter bug"):
            provider.generate(system_prompt="system", user_prompt="hello")
            

# Input validation
class TestGroqInputValidation:
    @pytest.mark.parametrize("system_prompt", ["", "   ", "\n\t"])
    def test_blank_system_prompt_rejected(self, system_prompt: str) -> None:
        client = make_mock_client()
        provider = make_provider(client=client)

        with pytest.raises(ValueError):
            provider.generate(system_prompt=system_prompt, user_prompt="hello")

        client.chat.completions.create.assert_not_called()


    @pytest.mark.parametrize("user_prompt", ["", "   ", "\n\t"])
    def test_blank_user_prompt_rejected(self, user_prompt: str) -> None:
        client = make_mock_client()
        provider = make_provider(client=client)

        with pytest.raises(ValueError):
            provider.generate(system_prompt="system", user_prompt=user_prompt)

        client.chat.completions.create.assert_not_called()

    def test_non_string_prompt_rejected(self) -> None:
        provider = make_provider()

        with pytest.raises(TypeError):
            provider.generate(system_prompt=123, user_prompt="hello")


# Health check
class TestGroqHealthCheck:
    def test_healthy_provider_returns_true(self) -> None:
        client = make_mock_client()
        client.models.list.return_value = SimpleNamespace(data=[])
        provider = make_provider(client=client)

        assert provider.health_check() is True
        client.models.list.assert_called_once_with()


    def test_api_failure_returns_false(self) -> None:
        client = make_mock_client()
        client.models.list.side_effect = groq.AuthenticationError("bad key", response=make_http_response(401), body=None)
        provider = make_provider(client=client)

        assert provider.health_check() is False


    def test_unexpected_health_check_error_returns_false(self) -> None:
        client = make_mock_client()
        client.models.list.side_effect = RuntimeError("unexpected")
        provider = make_provider(client=client)

        assert provider.health_check() is False