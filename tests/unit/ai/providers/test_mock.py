from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from packages.ai.providers.errors import (
    LLMProviderError,
    LLMProviderResponseError,
    LLMProviderTimeoutError,
)
from packages.ai.providers.mock import (
    MockLLMProvider,
    MockProviderConfig,
)


# ---------------------------------------------------------------------------
# Test schemas
# ---------------------------------------------------------------------------


class ExampleStructuredResponse(BaseModel):
    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class DefaultOnlyResponse(BaseModel):
    label: str = "default"
    confidence: float = 0.5


# ---------------------------------------------------------------------------
# Construction / configuration
# ---------------------------------------------------------------------------


class TestMockProviderConfiguration:
    def test_default_provider_metadata(self) -> None:
        provider = MockLLMProvider()

        assert provider.provider_name == "mock"
        assert provider.model_name == "mock-llm-v1"


    def test_negative_latency_rejected(self) -> None:
        with pytest.raises(
            ValueError,
            match="latency_seconds cannot be negative",
        ):
            MockProviderConfig(
                latency_seconds=-0.1
            )


    def test_initial_call_count_is_zero(self) -> None:
        provider = MockLLMProvider()

        assert provider.call_count == 0
        assert provider.calls == ()


# ---------------------------------------------------------------------------
# Plain-text generation
# ---------------------------------------------------------------------------


class TestTextGeneration:
    def test_returns_default_text_response(self) -> None:
        provider = MockLLMProvider()

        result = provider.generate(
            system_prompt="You are a test model.",
            user_prompt="hello",
        )

        assert result == "Mock response"


    def test_returns_configured_text_response(self) -> None:
        provider = MockLLMProvider(
            text_responses={
                "hello": "configured response",
            }
        )

        result = provider.generate(
            system_prompt="system",
            user_prompt="hello",
        )

        assert result == "configured response"


    def test_custom_default_response(self) -> None:
        provider = MockLLMProvider(
            config=MockProviderConfig(
                default_text_response="fallback"
            )
        )

        result = provider.generate(
            system_prompt="system",
            user_prompt="unknown prompt",
        )

        assert result == "fallback"


    def test_text_resolver_has_priority_over_fixture(self) -> None:
        def resolver(
            system_prompt: str,
            user_prompt: str,
        ) -> str:
            return f"resolved:{user_prompt}"

        provider = MockLLMProvider(
            text_responses={
                "hello": "fixture",
            },
            text_resolver=resolver,
        )

        result = provider.generate(
            system_prompt="system",
            user_prompt="hello",
        )

        assert result == "resolved:hello"


    def test_empty_text_response_rejected(self) -> None:
        provider = MockLLMProvider(
            text_responses={
                "hello": "   ",
            }
        )

        with pytest.raises(
            LLMProviderResponseError
        ):
            provider.generate(
                system_prompt="system",
                user_prompt="hello",
            )


    def test_non_string_text_response_rejected(self) -> None:
        def resolver(
            system_prompt: str,
            user_prompt: str,
        ) -> Any:
            return 42

        provider = MockLLMProvider(
            text_resolver=resolver,  # type: ignore[arg-type]
        )

        with pytest.raises(
            LLMProviderResponseError
        ):
            provider.generate(
                system_prompt="system",
                user_prompt="hello",
            )


    def test_text_resolver_exception_wrapped(self) -> None:
        def resolver(
            system_prompt: str,
            user_prompt: str,
        ) -> str:
            raise ValueError("resolver bug")

        provider = MockLLMProvider(
            text_resolver=resolver,
        )

        with pytest.raises(
            LLMProviderError
        ) as exc_info:
            provider.generate(
                system_prompt="system",
                user_prompt="hello",
            )

        assert (
            "Mock text response resolver failed"
            in str(exc_info.value)
        )


# ---------------------------------------------------------------------------
# Structured generation
# ---------------------------------------------------------------------------


class TestStructuredGeneration:
    def test_returns_valid_structured_fixture(self) -> None:
        provider = MockLLMProvider(
            structured_responses={
                "classify": {
                    "label": "payment_issue",
                    "confidence": 0.95,
                }
            }
        )

        result = provider.generate_structured(
            system_prompt="system",
            user_prompt="classify",
            response_model=ExampleStructuredResponse,
        )

        assert isinstance(
            result,
            ExampleStructuredResponse,
        )

        assert result.label == "payment_issue"
        assert result.confidence == 0.95


    def test_existing_pydantic_model_is_returned_as_copy(
        self,
    ) -> None:
        fixture = ExampleStructuredResponse(
            label="refund_request",
            confidence=0.9,
        )

        provider = MockLLMProvider(
            structured_responses={
                "classify": fixture,
            }
        )

        result = provider.generate_structured(
            system_prompt="system",
            user_prompt="classify",
            response_model=ExampleStructuredResponse,
        )

        assert result == fixture
        assert result is not fixture


    def test_other_basemodel_is_converted_through_dump(
        self,
    ) -> None:
        class OtherModel(BaseModel):
            label: str
            confidence: float

        fixture = OtherModel(
            label="order_status",
            confidence=0.8,
        )

        provider = MockLLMProvider(
            structured_responses={
                "classify": fixture,
            }
        )

        result = provider.generate_structured(
            system_prompt="system",
            user_prompt="classify",
            response_model=ExampleStructuredResponse,
        )

        assert result.label == "order_status"
        assert result.confidence == 0.8


    def test_structured_resolver_used_when_configured(
        self,
    ) -> None:
        def resolver(
            system_prompt: str,
            user_prompt: str,
            response_model: type[BaseModel],
        ) -> dict[str, Any]:
            return {
                "label": "resolved",
                "confidence": 0.77,
            }

        provider = MockLLMProvider(
            structured_responses={
                "classify": {
                    "label": "fixture",
                    "confidence": 0.5,
                }
            },
            structured_resolver=resolver,
        )

        result = provider.generate_structured(
            system_prompt="system",
            user_prompt="classify",
            response_model=ExampleStructuredResponse,
        )

        assert result.label == "resolved"
        assert result.confidence == 0.77


    def test_missing_structured_fixture_fails_in_strict_mode(
        self,
    ) -> None:
        provider = MockLLMProvider()

        with pytest.raises(
            LLMProviderResponseError
        ) as exc_info:
            provider.generate_structured(
                system_prompt="system",
                user_prompt="missing",
                response_model=ExampleStructuredResponse,
            )

        assert (
            "No mock structured response configured"
            in str(exc_info.value)
        )


    def test_non_strict_mode_allows_default_only_schema(
        self,
    ) -> None:
        provider = MockLLMProvider(
            config=MockProviderConfig(
                strict_structured_responses=False
            )
        )

        result = provider.generate_structured(
            system_prompt="system",
            user_prompt="missing",
            response_model=DefaultOnlyResponse,
        )

        assert result.label == "default"
        assert result.confidence == 0.5


    def test_non_strict_mode_still_fails_required_schema(
        self,
    ) -> None:
        provider = MockLLMProvider(
            config=MockProviderConfig(
                strict_structured_responses=False
            )
        )

        with pytest.raises(
            LLMProviderResponseError
        ):
            provider.generate_structured(
                system_prompt="system",
                user_prompt="missing",
                response_model=ExampleStructuredResponse,
            )


    def test_invalid_structured_fixture_is_wrapped(
        self,
    ) -> None:
        provider = MockLLMProvider(
            structured_responses={
                "classify": {
                    "label": "payment_issue",
                    "confidence": 4.2,
                }
            }
        )

        with pytest.raises(
            LLMProviderResponseError
        ) as exc_info:
            provider.generate_structured(
                system_prompt="system",
                user_prompt="classify",
                response_model=ExampleStructuredResponse,
            )

        assert (
            "failed validation"
            in str(exc_info.value)
        )


    def test_invalid_response_model_type_rejected(
        self,
    ) -> None:
        provider = MockLLMProvider()

        with pytest.raises(TypeError):
            provider.generate_structured(
                system_prompt="system",
                user_prompt="classify",
                response_model=dict,  # type: ignore[arg-type]
            )


    def test_structured_resolver_exception_wrapped(
        self,
    ) -> None:
        def resolver(
            system_prompt: str,
            user_prompt: str,
            response_model: type[BaseModel],
        ) -> dict[str, Any]:
            raise RuntimeError("resolver crashed")

        provider = MockLLMProvider(
            structured_resolver=resolver,
        )

        with pytest.raises(
            LLMProviderError
        ) as exc_info:
            provider.generate_structured(
                system_prompt="system",
                user_prompt="classify",
                response_model=ExampleStructuredResponse,
            )

        assert (
            "Mock structured response resolver failed"
            in str(exc_info.value)
        )


# ---------------------------------------------------------------------------
# Fault injection
# ---------------------------------------------------------------------------


class TestFaultInjection:
    def test_queue_failure_affects_next_call(self) -> None:
        provider = MockLLMProvider()

        provider.queue_failure()

        with pytest.raises(
            LLMProviderError
        ):
            provider.generate(
                system_prompt="system",
                user_prompt="first",
            )


    def test_failure_only_affects_one_call(self) -> None:
        provider = MockLLMProvider()

        provider.queue_failure()

        with pytest.raises(
            LLMProviderError
        ):
            provider.generate(
                system_prompt="system",
                user_prompt="first",
            )

        result = provider.generate(
            system_prompt="system",
            user_prompt="second",
        )

        assert result == "Mock response"


    def test_queue_timeout_affects_next_call(self) -> None:
        provider = MockLLMProvider()

        provider.queue_timeout()

        with pytest.raises(
            LLMProviderTimeoutError
        ) as exc_info:
            provider.generate(
                system_prompt="system",
                user_prompt="first",
            )

        assert exc_info.value.retryable is True


    def test_timeout_only_affects_one_call(self) -> None:
        provider = MockLLMProvider()

        provider.queue_timeout()

        with pytest.raises(
            LLMProviderTimeoutError
        ):
            provider.generate(
                system_prompt="system",
                user_prompt="first",
            )

        result = provider.generate(
            system_prompt="system",
            user_prompt="second",
        )

        assert result == "Mock response"


    def test_timeout_has_priority_over_failure(
        self,
    ) -> None:
        provider = MockLLMProvider()

        provider.queue_failure()
        provider.queue_timeout()

        with pytest.raises(
            LLMProviderTimeoutError
        ):
            provider.generate(
                system_prompt="system",
                user_prompt="first",
            )

        # Failure flag should still remain queued.
        with pytest.raises(
            LLMProviderError
        ):
            provider.generate(
                system_prompt="system",
                user_prompt="second",
            )


# ---------------------------------------------------------------------------
# Prompt validation
# ---------------------------------------------------------------------------


class TestPromptValidation:
    @pytest.mark.parametrize(
        "system_prompt",
        ["", "   ", "\n\t"],
    )
    def test_empty_system_prompt_rejected(
        self,
        system_prompt: str,
    ) -> None:
        provider = MockLLMProvider()

        with pytest.raises(ValueError):
            provider.generate(
                system_prompt=system_prompt,
                user_prompt="hello",
            )

        assert provider.call_count == 0


    @pytest.mark.parametrize(
        "user_prompt",
        ["", "   ", "\n\t"],
    )
    def test_empty_user_prompt_rejected(
        self,
        user_prompt: str,
    ) -> None:
        provider = MockLLMProvider()

        with pytest.raises(ValueError):
            provider.generate(
                system_prompt="system",
                user_prompt=user_prompt,
            )

        assert provider.call_count == 0


    def test_non_string_system_prompt_rejected(
        self,
    ) -> None:
        provider = MockLLMProvider()

        with pytest.raises(TypeError):
            provider.generate(
                system_prompt=123,  # type: ignore[arg-type]
                user_prompt="hello",
            )


    def test_non_string_user_prompt_rejected(
        self,
    ) -> None:
        provider = MockLLMProvider()

        with pytest.raises(TypeError):
            provider.generate(
                system_prompt="system",
                user_prompt=123,  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Call recording
# ---------------------------------------------------------------------------


class TestCallRecording:
    def test_generate_records_call(self) -> None:
        provider = MockLLMProvider()

        provider.generate(
            system_prompt="system",
            user_prompt="hello",
        )

        assert provider.call_count == 1

        recorded = provider.calls[0]

        assert recorded.operation == "generate"
        assert recorded.system_prompt == "system"
        assert recorded.user_prompt == "hello"
        assert recorded.response_model is None


    def test_generate_structured_records_response_model(
        self,
    ) -> None:
        provider = MockLLMProvider(
            structured_responses={
                "classify": {
                    "label": "x",
                    "confidence": 0.5,
                }
            }
        )

        provider.generate_structured(
            system_prompt="system",
            user_prompt="classify",
            response_model=ExampleStructuredResponse,
        )

        recorded = provider.calls[0]

        assert recorded.operation == "generate_structured"
        assert (
            recorded.response_model
            is ExampleStructuredResponse
        )


    def test_calls_returns_immutable_snapshot(self) -> None:
        provider = MockLLMProvider()

        provider.generate(
            system_prompt="system",
            user_prompt="hello",
        )

        snapshot = provider.calls

        assert isinstance(snapshot, tuple)

        provider.generate(
            system_prompt="system",
            user_prompt="again",
        )

        assert len(snapshot) == 1
        assert provider.call_count == 2


    def test_failed_call_is_still_recorded(self) -> None:
        provider = MockLLMProvider()

        provider.queue_timeout()

        with pytest.raises(
            LLMProviderTimeoutError
        ):
            provider.generate(
                system_prompt="system",
                user_prompt="hello",
            )

        assert provider.call_count == 1
        
    def test_configured_latency_is_recorded() -> None:
        provider = MockLLMProvider(
            config=MockProviderConfig(
                latency_seconds=0.01
            )
        )

        provider.generate(system_prompt="system", user_prompt="hello")
        assert provider.calls[0].simulated_latency_seconds == 0.01


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_call_history(self) -> None:
        provider = MockLLMProvider()

        provider.generate(
            system_prompt="system",
            user_prompt="hello",
        )

        assert provider.call_count == 1

        provider.reset()

        assert provider.call_count == 0
        assert provider.calls == ()


    def test_reset_clears_queued_failure(self) -> None:
        provider = MockLLMProvider()

        provider.queue_failure()
        provider.reset()

        result = provider.generate(
            system_prompt="system",
            user_prompt="hello",
        )

        assert result == "Mock response"


    def test_reset_clears_queued_timeout(self) -> None:
        provider = MockLLMProvider()

        provider.queue_timeout()
        provider.reset()

        result = provider.generate(
            system_prompt="system",
            user_prompt="hello",
        )

        assert result == "Mock response"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_health_check_returns_true(self) -> None:
        provider = MockLLMProvider()

        assert provider.health_check() is True


    def test_health_check_does_not_consume_timeout(
        self,
    ) -> None:
        provider = MockLLMProvider()

        provider.queue_timeout()

        assert provider.health_check() is True

        with pytest.raises(
            LLMProviderTimeoutError
        ):
            provider.generate(
                system_prompt="system",
                user_prompt="hello",
            )


    def test_health_check_does_not_consume_failure(
        self,
    ) -> None:
        provider = MockLLMProvider()

        provider.queue_failure()

        assert provider.health_check() is True

        with pytest.raises(
            LLMProviderError
        ):
            provider.generate(
                system_prompt="system",
                user_prompt="hello",
            )