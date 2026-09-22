# AI-customer-support-agent\tests\unit\ai\providers\test_capacity_limited.py
from __future__ import annotations

import threading
import time

import pytest

from packages.ai.providers.base import LLMProvider
from packages.ai.providers.capacity_limited import (
    CapacityLimitedLLMProvider,
    ProviderCapacityConfig,
)
from packages.ai.providers.errors import LLMProviderRateLimitError
from packages.ai.providers.types import LLMResponse


class BlockingProvider(LLMProvider):
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return "blocking"

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
        self.entered.set()
        self.release.wait(timeout=2)

        return LLMResponse(
            content="ok",
            provider=self.provider_name,
            model=self.model_name,
        )

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


def test_rejects_when_local_queue_timeout_expires() -> None:
    base = BlockingProvider()
    provider = CapacityLimitedLLMProvider(
        provider=base,
        config=ProviderCapacityConfig(
            max_concurrency=1,
            queue_timeout_seconds=0.05,
            minimum_start_interval_seconds=0,
        ),
    )

    first_error: list[BaseException] = []

    def first_call() -> None:
        try:
            provider.generate(
                system_prompt="system",
                user_prompt="user",
            )
        except BaseException as exc:
            first_error.append(exc)

    thread = threading.Thread(target=first_call)
    thread.start()

    assert base.entered.wait(timeout=1)

    with pytest.raises(LLMProviderRateLimitError) as captured:
        provider.generate(
            system_prompt="system",
            user_prompt="second",
        )

    assert captured.value.retryable is True
    assert captured.value.error_code == "RATE_LIMITED"
    assert captured.value.metadata["capacity_source"] == "local"

    base.release.set()
    thread.join(timeout=1)

    assert thread.is_alive() is False
    assert first_error == []
    assert base.call_count == 1


def test_health_check_does_not_consume_capacity() -> None:
    base = BlockingProvider()
    provider = CapacityLimitedLLMProvider(
        provider=base,
        config=ProviderCapacityConfig(
            max_concurrency=1,
            queue_timeout_seconds=0.05,
            minimum_start_interval_seconds=0,
        ),
    )

    assert provider.health_check() is True


def test_validates_configuration() -> None:
    with pytest.raises(ValueError):
        ProviderCapacityConfig(max_concurrency=0)

    with pytest.raises(ValueError):
        ProviderCapacityConfig(queue_timeout_seconds=0)

    with pytest.raises(ValueError):
        ProviderCapacityConfig(minimum_start_interval_seconds=-1)