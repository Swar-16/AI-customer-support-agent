# AI-customer-support-agent\packages\ai\providers\resilient.py
from __future__ import annotations
import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar
from pydantic import BaseModel

from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import LLMProviderRateLimitError, LLMProviderTimeoutError, LLMProviderUnavailableError
from packages.ai.providers.types import LLMResponse, StructuredLLMResponse

TModel = TypeVar("TModel", bound=BaseModel)
TResult = TypeVar("TResult")
SleepFunction = Callable[[float], None]
RandomFunction = Callable[[], float]

@dataclass(frozen=True, slots=True)
class ProviderRetryConfig:
    """
    Conservative retry policy for transient provider failures.

    max_retries counts additional attempts after the initial attempt. Therefore max_retries=1 permits at most two total provider attempts.
    """
    max_retries: int = 1
    base_delay_seconds: float = 0.75
    maximum_delay_seconds: float = 8.0
    jitter_ratio: float = 0.20

    def __post_init__(self) -> None:
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int):
            raise TypeError("max_retries must be an integer")

        if not 0 <= self.max_retries <= 3:
            raise ValueError("max_retries must be between 0 and 3")

        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds cannot be negative")

        if self.maximum_delay_seconds <= 0:
            raise ValueError("maximum_delay_seconds must be greater than zero")

        if self.base_delay_seconds > self.maximum_delay_seconds:
            raise ValueError("base_delay_seconds cannot exceed maximum_delay_seconds")

        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")

class ResilientLLMProvider(LLMProvider):
    """
    Retry only failures that are explicitly transient.

    This wrapper must sit outside CapacityLimitedLLMProvider. Each retry then reacquires provider capacity,
    and the backoff sleep does not occupy a semaphore slot.

    Deliberately not retried:
        - invalid structured output;
        - authentication/permission failure;
        - bad request or rejected schema;
        - customer-input validation;
        - programming errors;
        - every generic non-retryable LLMProviderError.
    """
    def __init__(self, *, provider: LLMProvider, config: ProviderRetryConfig | None = None, sleep: SleepFunction = time.sleep, random_value: RandomFunction = random.random) -> None:
        if not isinstance(provider, LLMProvider):
            raise TypeError("provider must implement LLMProvider")

        if not callable(sleep):
            raise TypeError("sleep must be callable")

        if not callable(random_value):
            raise TypeError("random_value must be callable")

        self._provider = provider
        self._config = config or ProviderRetryConfig()
        self._sleep = sleep
        self._random_value = random_value

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    def generate(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        return self._execute(operation=lambda: self._provider.generate(system_prompt=system_prompt, user_prompt=user_prompt))

    def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model: type[TModel]) -> StructuredLLMResponse[TModel]:
        return self._execute(
            operation=lambda: self._provider.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
            ),
        )

    def health_check(self) -> bool:
        # Health checks must remain lightweight and must not silently retry.
        return self._provider.health_check()

    def _execute(self, *, operation: Callable[[], TResult]) -> TResult:
        retry_number = 0

        while True:
            try:
                return operation()

            except (LLMProviderRateLimitError, LLMProviderTimeoutError, LLMProviderUnavailableError,) as exc:
                if retry_number >= self._config.max_retries:
                    raise

                delay = self._retry_delay(retry_number=retry_number, error=exc)
                retry_number += 1
                if delay > 0:
                    self._sleep(delay)

    def _retry_delay(self, *, retry_number: int, error: Exception) -> float:
        retry_after = self._retry_after_seconds(error)
        if retry_after is not None:
            base_delay = retry_after
            
        else:
            base_delay = (self._config.base_delay_seconds * (2 ** retry_number))

        bounded_delay = min(max(0.0, base_delay), self._config.maximum_delay_seconds)
        if bounded_delay == 0 or self._config.jitter_ratio == 0:
            return bounded_delay

        random_value = float(self._random_value())
        random_value = min(max(random_value, 0.0), 1.0)
        # Symmetric multiplicative jitter:
        # random=0 -> 1-jitter_ratio
        # random=1 -> 1+jitter_ratio
        multiplier = (1.0 - self._config.jitter_ratio + (2.0 * self._config.jitter_ratio * random_value))

        return bounded_delay * multiplier

    @staticmethod
    def _retry_after_seconds(error: Exception) -> float | None:
        metadata = getattr(error, "metadata", None)
        if not isinstance(metadata, dict):
            return None

        value = metadata.get("retry_after_seconds")
        if isinstance(value, bool):
            return None

        if isinstance(value, (int, float)):
            return max(0.0, float(value))

        if isinstance(value, str):
            try:
                return max(0.0, float(value.strip()))
            
            except ValueError:
                return None

        return None