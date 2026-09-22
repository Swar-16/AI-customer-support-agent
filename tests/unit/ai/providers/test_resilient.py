# AI-customer-support-agent\tests\unit\ai\providers\test_resilient.py
from __future__ import annotations

import pytest

from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import (
    LLMProviderRateLimitError,
    LLMProviderResponseError,
)
from packages.ai.providers.resilient import (
    ProviderRetryConfig,
    ResilientLLMProvider,
)
from packages.ai.providers.types import LLMResponse


class SequencedProvider(LLMProvider):
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return "test"

    @property
    def model_name(self) -> str:
        return "test-model"

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> LLMResponse:
        self.call_count += 1
        outcome = self._outcomes.pop(0)

        if isinstance(outcome, BaseException):
            raise outcome

        assert isinstance(outcome, LLMResponse)
        return outcome

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model,
    ):
        raise NotImplementedError

    def health_check(self) -> bool:
        return True


def successful_response() -> LLMResponse:
    return LLMResponse(
        content="ok",
        provider="test",
        model="test-model",
    )


def test_retries_rate_limit_once_then_succeeds() -> None:
    base = SequencedProvider(
        [
            LLMProviderRateLimitError(
                provider="test",
                metadata={"retry_after_seconds": 0.25},
            ),
            successful_response(),
        ]
    )
    delays: list[float] = []

    provider = ResilientLLMProvider(
        provider=base,
        config=ProviderRetryConfig(
            max_retries=1,
            base_delay_seconds=1,
            maximum_delay_seconds=8,
            jitter_ratio=0,
        ),
        sleep=delays.append,
    )

    result = provider.generate(
        system_prompt="system",
        user_prompt="user",
    )

    assert result.content == "ok"
    assert base.call_count == 2
    assert delays == [0.25]


def test_does_not_retry_invalid_response() -> None:
    error = LLMProviderResponseError(
        provider="test",
        message="Invalid structured response.",
    )
    base = SequencedProvider([error])

    provider = ResilientLLMProvider(
        provider=base,
        config=ProviderRetryConfig(max_retries=1),
        sleep=lambda _: None,
    )

    with pytest.raises(LLMProviderResponseError):
        provider.generate(
            system_prompt="system",
            user_prompt="user",
        )

    assert base.call_count == 1


def test_stops_after_retry_budget_is_exhausted() -> None:
    first = LLMProviderRateLimitError(provider="test")
    second = LLMProviderRateLimitError(provider="test")
    base = SequencedProvider([first, second])
    delays: list[float] = []

    provider = ResilientLLMProvider(
        provider=base,
        config=ProviderRetryConfig(
            max_retries=1,
            base_delay_seconds=0.5,
            maximum_delay_seconds=8,
            jitter_ratio=0,
        ),
        sleep=delays.append,
    )

    with pytest.raises(LLMProviderRateLimitError):
        provider.generate(
            system_prompt="system",
            user_prompt="user",
        )

    assert base.call_count == 2
    assert delays == [0.5]