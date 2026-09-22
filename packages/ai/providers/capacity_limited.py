# AI-customer-support-agent\packages\ai\providers\capacity_limited.py
from __future__ import annotations
import threading
import time
from dataclasses import dataclass
from typing import TypeVar
from pydantic import BaseModel

from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import LLMProviderRateLimitError
from packages.ai.providers.types import LLMResponse, StructuredLLMResponse

T = TypeVar("T", bound=BaseModel)

@dataclass(frozen=True, slots=True)
class ProviderCapacityConfig:
    """
    Process-local protection for one shared provider.

    max_concurrency:
        Maximum simultaneous provider calls.

    queue_timeout_seconds:
        Maximum time a request may wait for capacity.

    minimum_start_interval_seconds:
        Minimum spacing between the start of consecutive provider calls.
        This smooths short request bursts but is not a distributed RPM/TPM limiter.
    """
    max_concurrency: int = 2
    queue_timeout_seconds: float = 8.0
    minimum_start_interval_seconds: float = 0.75

    def __post_init__(self) -> None:
        if isinstance(self.max_concurrency, bool) or not isinstance(self.max_concurrency, int):
            raise TypeError("max_concurrency must be an integer")

        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be greater than zero")

        if not isinstance(self.queue_timeout_seconds, (int, float)):
            raise TypeError("queue_timeout_seconds must be numeric")

        if self.queue_timeout_seconds <= 0:
            raise ValueError("queue_timeout_seconds must be greater than zero")

        if not isinstance(self.minimum_start_interval_seconds, (int, float)):
            raise TypeError("minimum_start_interval_seconds must be numeric")

        if self.minimum_start_interval_seconds < 0:
            raise ValueError("minimum_start_interval_seconds cannot be negative")

class CapacityLimitedLLMProvider(LLMProvider):
    """
    Decorate a provider with bounded process-local admission control.

    One long-lived instance must be shared by every request-scoped InstrumentedLLMProvider.
    The semaphore and start-time lock therefore coordinate classification, answer generation, and title generation.

    The wrapper does not retry provider calls. Retry policy will be added as a separate layer so capacity control, retries, and telemetry remain explicit.
    """
    def __init__(self, *, provider: LLMProvider, config: ProviderCapacityConfig | None = None) -> None:
        if not isinstance(provider, LLMProvider):
            raise TypeError("provider must implement LLMProvider")

        self._provider = provider
        self._config = config or ProviderCapacityConfig()
        self._capacity = threading.BoundedSemaphore(value=self._config.max_concurrency)
        self._start_lock = threading.Lock()
        self._next_start_at = 0.0

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    def generate(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        acquired = self._acquire_capacity()
        try:
            self._wait_for_start_slot()
            return self._provider.generate(system_prompt=system_prompt, user_prompt=user_prompt)
        finally:
            if acquired:
                self._capacity.release()

    def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model: type[T]) -> StructuredLLMResponse[T]:
        acquired = self._acquire_capacity()
        try:
            self._wait_for_start_slot()
            return self._provider.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
            )
        finally:
            if acquired:
                self._capacity.release()

    def health_check(self) -> bool:
        # Health checks remain lightweight and should not consume business-call
        # capacity or delay customer requests.
        return self._provider.health_check()

    def _acquire_capacity(self) -> bool:
        acquired = self._capacity.acquire(timeout=float(self._config.queue_timeout_seconds))

        if not acquired:
            raise LLMProviderRateLimitError(
                provider=self.provider_name,
                message="Local provider capacity was unavailable within the configured queue timeout.",
                metadata={
                    "capacity_source": "local",
                    "queue_timeout_seconds": self._config.queue_timeout_seconds,
                    "max_concurrency": self._config.max_concurrency,
                },
            )

        return True

    def _wait_for_start_slot(self) -> None:
        interval = float(self._config.minimum_start_interval_seconds)
        if interval == 0:
            return

        with self._start_lock:
            now = time.monotonic()
            delay = max(0.0, self._next_start_at - now)

            if delay > 0:
                time.sleep(delay)

            started_at = time.monotonic()
            self._next_start_at = started_at + interval