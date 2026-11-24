# AI-customer-support-agent\tests\unit\ai\providers\test_gemini.py
from __future__ import annotations
import json
from decimal import Decimal
from unittest.mock import MagicMock
import httpx
import pytest
from pydantic import BaseModel, Field

from packages.ai.providers.errors import (
    LLMProviderAuthenticationError,
    LLMProviderError,
    LLMProviderRateLimitError,
    LLMProviderResponseError,
    LLMProviderTimeoutError,
    LLMProviderUnavailableError,
)
from packages.ai.providers.gemini import GeminiProvider, GeminiProviderConfig
from packages.ai.providers.types import LLMResponse, StructuredLLMResponse


class ExampleStructuredResponse(BaseModel):
    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class NestedSchemaResponse(BaseModel):
    class Inner(BaseModel):
        code: str

    inner: Inner
    tags: list[str] = Field(default_factory=list)


def make_gemini_json_response(
    content: str = "hello",
    model: str = "gemini-1.5-flash",
    finish_reason: str = "STOP",
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    cached_tokens: int = 10,
) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": content}],
                },
                "finishReason": finish_reason,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": completion_tokens,
            "cachedContentTokenCount": cached_tokens,
            "totalTokenCount": prompt_tokens + completion_tokens,
        },
    }


def make_mock_client(*, response_data: dict | None = None, status_code: int = 200, headers: dict | None = None):
    client = MagicMock(spec=httpx.Client)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = json.dumps(response_data) if response_data is not None else ""
    resp.json.return_value = response_data if response_data is not None else {}
    resp.headers = headers or {"x-goog-request-id": "req-gemini-test-123"}

    client.post.return_value = resp
    client.get.return_value = resp
    return client


def make_provider(*, client=None, model: str = "gemini-1.5-flash") -> GeminiProvider:
    return GeminiProvider(
        config=GeminiProviderConfig(
            api_key="test-gemini-api-key",
            model=model,
            timeout_seconds=15.0,
            max_completion_tokens=512,
            temperature=Decimal("0"),
        ),
        client=client or make_mock_client(response_data=make_gemini_json_response()),
    )


class TestGeminiProviderConfig:
    def test_valid_config(self) -> None:
        config = GeminiProviderConfig(api_key=" test-key ", model=" gemini-1.5-flash ")
        assert config.api_key == "test-key"
        assert config.model == "gemini-1.5-flash"

    def test_empty_api_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="api_key cannot be empty"):
            GeminiProviderConfig(api_key="   ", model="gemini-1.5-flash")

    def test_empty_model_rejected(self) -> None:
        with pytest.raises(ValueError, match="model cannot be empty"):
            GeminiProviderConfig(api_key="key", model="   ")

    def test_invalid_timeout_rejected(self) -> None:
        with pytest.raises(ValueError, match="timeout_seconds"):
            GeminiProviderConfig(api_key="key", timeout_seconds=0.0)

    def test_invalid_max_completion_tokens_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_completion_tokens"):
            GeminiProviderConfig(api_key="key", max_completion_tokens=0)

    def test_invalid_temperature_rejected(self) -> None:
        with pytest.raises(ValueError, match="temperature"):
            GeminiProviderConfig(api_key="key", temperature=Decimal("2.5"))


class TestGeminiProviderGenerate:
    def test_successful_text_generation(self) -> None:
        data = make_gemini_json_response(content="Test response from Gemini", prompt_tokens=50, completion_tokens=15)
        client = make_mock_client(response_data=data)
        provider = make_provider(client=client)

        result = provider.generate(system_prompt="System instructions", user_prompt="User query")

        assert isinstance(result, LLMResponse)
        assert result.content == "Test response from Gemini"
        assert result.provider == "gemini"
        assert result.model == "gemini-1.5-flash"
        assert result.usage.input_tokens == 50
        assert result.usage.output_tokens == 15
        assert result.usage.cached_input_tokens == 10
        assert result.usage.total_tokens == 65
        assert result.metadata.provider_request_id == "req-gemini-test-123"
        assert result.metadata.finish_reason == "STOP"

    def test_empty_content_raises_response_error(self) -> None:
        data = make_gemini_json_response(content="   ")
        client = make_mock_client(response_data=data)
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderResponseError, match="empty text response"):
            provider.generate(system_prompt="System", user_prompt="User")

    def test_no_candidates_raises_response_error(self) -> None:
        client = make_mock_client(response_data={"candidates": []})
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderResponseError, match="no candidates"):
            provider.generate(system_prompt="System", user_prompt="User")

    def test_prompt_validation(self) -> None:
        provider = make_provider()
        with pytest.raises(ValueError, match="system_prompt"):
            provider.generate(system_prompt="   ", user_prompt="Hello")
        with pytest.raises(ValueError, match="user_prompt"):
            provider.generate(system_prompt="System", user_prompt="   ")


class TestGeminiProviderGenerateStructured:
    def test_successful_structured_generation(self) -> None:
        data = make_gemini_json_response(
            content=json.dumps({"label": "order_status", "confidence": 0.95}),
        )
        client = make_mock_client(response_data=data)
        provider = make_provider(client=client)

        result = provider.generate_structured(
            system_prompt="System instructions",
            user_prompt="Where is my order?",
            response_model=ExampleStructuredResponse,
        )

        assert isinstance(result, StructuredLLMResponse)
        assert isinstance(result.output, ExampleStructuredResponse)
        assert result.output.label == "order_status"
        assert result.output.confidence == 0.95
        assert result.provider == "gemini"

    def test_malformed_json_raises_response_error(self) -> None:
        data = make_gemini_json_response(content="{not-valid-json}")
        client = make_mock_client(response_data=data)
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderResponseError, match="malformed JSON"):
            provider.generate_structured(
                system_prompt="System",
                user_prompt="User",
                response_model=ExampleStructuredResponse,
            )

    def test_schema_mismatch_raises_response_error(self) -> None:
        data = make_gemini_json_response(content=json.dumps({"wrong_field": 123}))
        client = make_mock_client(response_data=data)
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderResponseError, match="did not satisfy"):
            provider.generate_structured(
                system_prompt="System",
                user_prompt="User",
                response_model=ExampleStructuredResponse,
            )

    def test_non_basemodel_rejected(self) -> None:
        provider = make_provider()
        with pytest.raises(TypeError, match="BaseModel"):
            provider.generate_structured(
                system_prompt="System",
                user_prompt="User",
                response_model=dict,  # type: ignore[arg-type]
            )

    def test_clean_schema_inlines_defs_and_strips_title(self) -> None:
        schema = NestedSchemaResponse.model_json_schema()
        cleaned = GeminiProvider._clean_schema_for_gemini(schema)

        assert "$defs" not in cleaned
        assert "definitions" not in cleaned
        assert "title" not in cleaned
        # Inner should be inlined
        assert "inner" in cleaned["properties"]
        assert "properties" in cleaned["properties"]["inner"]
        assert "code" in cleaned["properties"]["inner"]["properties"]


class TestGeminiProviderErrorTranslation:
    def test_rate_limit_translation_429(self) -> None:
        client = MagicMock(spec=httpx.Client)
        resp = httpx.Response(
            status_code=429,
            headers={"retry-after": "5", "x-goog-request-id": "req-429"},
            text="Quota exceeded",
            request=httpx.Request("POST", "https://example.com"),
        )
        client.post.return_value = resp
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderRateLimitError) as exc_info:
            provider.generate(system_prompt="System", user_prompt="User")

        assert exc_info.value.retryable is True
        assert exc_info.value.metadata.get("retry_after_seconds") == 5.0

    def test_auth_error_translation_401(self) -> None:
        client = MagicMock(spec=httpx.Client)
        resp = httpx.Response(
            status_code=401,
            text="API key invalid",
            request=httpx.Request("POST", "https://example.com"),
        )
        client.post.return_value = resp
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderAuthenticationError) as exc_info:
            provider.generate(system_prompt="System", user_prompt="User")

        assert exc_info.value.retryable is False

    def test_unavailable_error_translation_503(self) -> None:
        client = MagicMock(spec=httpx.Client)
        resp = httpx.Response(
            status_code=503,
            text="Service unavailable",
            request=httpx.Request("POST", "https://example.com"),
        )
        client.post.return_value = resp
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderUnavailableError) as exc_info:
            provider.generate(system_prompt="System", user_prompt="User")

        assert exc_info.value.retryable is True

    def test_bad_request_translation_400(self) -> None:
        client = MagicMock(spec=httpx.Client)
        resp = httpx.Response(
            status_code=400,
            text="Invalid model parameter",
            request=httpx.Request("POST", "https://example.com"),
        )
        client.post.return_value = resp
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderResponseError):
            provider.generate(system_prompt="System", user_prompt="User")

    def test_timeout_translation(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.post.side_effect = httpx.ReadTimeout("Request timed out")
        provider = make_provider(client=client)

        with pytest.raises(LLMProviderTimeoutError) as exc_info:
            provider.generate(system_prompt="System", user_prompt="User")

        assert exc_info.value.retryable is True


class TestGeminiProviderHealthCheck:
    def test_health_check_success(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = httpx.Response(
            status_code=200,
            request=httpx.Request("GET", "https://example.com"),
        )
        provider = make_provider(client=client)

        assert provider.health_check() is True

    def test_health_check_failure_on_500(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = httpx.Response(
            status_code=500,
            request=httpx.Request("GET", "https://example.com"),
        )
        provider = make_provider(client=client)

        assert provider.health_check() is False

    def test_health_check_failure_on_exception(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = httpx.ConnectError("Connection failed")
        provider = make_provider(client=client)

        assert provider.health_check() is False


class TestGeminiSchemaSanitization:
    def test_collapses_nullable_anyof_unions_for_gemini_openapi_compatibility(self) -> None:
        from packages.ai.generation.models import GroundedGenerationResult
        from packages.ai.intent.schemas import IntentResult

        for model_cls in (GroundedGenerationResult, IntentResult):
            cleaned = GeminiProvider._clean_schema_for_gemini(model_cls.model_json_schema())
            serialized = json.dumps(cleaned)
            assert '"anyOf"' not in serialized
            assert '"$defs"' not in serialized
            assert '"additionalProperties"' not in serialized

        citation_props = GeminiProvider._clean_schema_for_gemini(
            GroundedGenerationResult.model_json_schema()
        )["properties"]["citations"]["items"]["properties"]
        assert citation_props["section"]["type"] == "string"
        assert citation_props["section"]["nullable"] is True
