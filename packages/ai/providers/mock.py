## Creating this file because
## Need to test AI run, classification, decision, persistence without API Keys

import copy
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import Lock
from __future__ import annotations
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import (
    LLMProviderError,
    LLMProviderResponseError,
    LLMProviderTimeoutError,
)

T = TypeVar("T", bound=BaseModel)

@dataclass(frozen=True, slots=True)
class MockCall:
    """
    Immutable record of a call made to MockLLMProvider.

    Useful for unit tests that need to verify:
    - which prompts were sent
    - which operation was called
    - which response model was requested
    """
    operation: str
    system_prompt: str
    user_prompt: str
    response_model: type[BaseModel] | None = None
    
@dataclass(slots=True)
class MockProviderConfig:
    """
    Runtime behaviour configuration for MockLLMProvider.

    This intentionally supports fault injection so callers can test
    timeout/error paths without depending on a real external provider.
    """

    default_text_response: str = "Mock response"

    latency_seconds: float = 0.0

    fail_next_call: bool = False
    timeout_next_call: bool = False

    strict_structured_responses: bool = True

    def __post_init__(self) -> None:
        if self.latency_seconds < 0:
            raise ValueError("latency_seconds cannot be negative")
        

StructuredResponseResolver = Callable[
    [str, str, type[BaseModel]],
    Mapping[str, Any] | BaseModel,
]

TextResponseResolver = Callable[
    [str, str],
    str,
]

class MockLLMProvider(LLMProvider):
    """
    Deterministic test implementation of LLMProvider.

    Responsibilities:
    - return predictable text responses
    - return validated structured responses
    - record calls for assertions
    - simulate latency
    - simulate provider failures
    - simulate timeouts

    This provider performs no network calls.

    It is intended for:
    - unit tests
    - integration tests
    - local development
    - deterministic evaluation pipelines
    """

    PROVIDER_NAME = "mock"
    MODEL_NAME = "mock-llm-v1"

    def __init__(self, *, config: MockProviderConfig | None = None,
                 text_responses: Mapping[str, str] | None = None,
                 structured_responses: Mapping[str, Mapping[str, Any] | BaseModel,] | None = None,
                 text_resolver: TextResponseResolver | None = None,
                 structured_resolver: StructuredResponseResolver | None = None,
    ) -> None:
        self._config = config or MockProviderConfig()

        # Defensive copy prevents tests from accidentally mutating
        # provider state after construction.
        self._text_responses = dict(text_responses or {})
        self._structured_responses = copy.deepcopy(
            dict(structured_responses or {})
        )

        self._text_resolver = text_resolver
        self._structured_resolver = structured_resolver

        self._calls: list[MockCall] = []

        # Tests may execute concurrently.
        self._lock = Lock()

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    @property
    def model_name(self) -> str:
        return self.MODEL_NAME

    @property
    def calls(self) -> tuple[MockCall, ...]:
        """
        Return an immutable snapshot of recorded calls.
        """

        with self._lock:
            return tuple(self._calls)

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self._calls)

    def reset(self) -> None:
        """
        Clear recorded calls and transient fault flags.

        Helpful when reusing a provider instance across tests.
        """

        with self._lock:
            self._calls.clear()

            self._config.fail_next_call = False
            self._config.timeout_next_call = False

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        """
        Produce a deterministic plain-text response.
        """
        self._validate_prompts( system_prompt=system_prompt, user_prompt=user_prompt)

        self._record_call(operation="generate", system_prompt=system_prompt, user_prompt=user_prompt)

        self._apply_fault_injection()
        self._simulate_latency()

        try:
            if self._text_resolver is not None:
                response = self._text_resolver(
                    system_prompt,
                    user_prompt,
                )

            else:
                response = self._text_responses.get(
                    user_prompt,
                    self._config.default_text_response,
                )

        except LLMProviderError:
            raise

        except Exception as exc:
            raise LLMProviderError(
                provider=self.PROVIDER_NAME,
                message="Mock text response resolver failed.",
            ) from exc

        if not isinstance(response, str):
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message=(
                    "Mock text resolver returned a non-string response."
                ),
            )

        if not response.strip():
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message="Mock provider returned an empty response.",
            )

        return response

    def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model: type[T]) -> T:
        """
        Produce a deterministic response validated against a Pydantic model.
        """
        self._validate_prompts(system_prompt=system_prompt, user_prompt=user_prompt)

        if not isinstance(response_model, type) or not issubclass(response_model, BaseModel,):
            raise TypeError("response_model must be a Pydantic BaseModel subclass")

        self._record_call(
            operation="generate_structured",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
        )

        self._apply_fault_injection()
        self._simulate_latency()

        try:
            raw_response = self._resolve_structured_response(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
            )

            if isinstance(raw_response, response_model):
                # Defensive copy ensures callers cannot mutate provider fixture.
                return raw_response.model_copy(deep=True)

            if isinstance(raw_response, BaseModel):
                raw_response = raw_response.model_dump()

            return response_model.model_validate(
                copy.deepcopy(raw_response)
            )

        except ValidationError as exc:
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message=(
                    f"Mock structured response failed validation "
                    f"for {response_model.__name__}."
                ),
            ) from exc

        except LLMProviderError:
            raise

        except Exception as exc:
            raise LLMProviderError(
                provider=self.PROVIDER_NAME,
                message="Mock structured response resolver failed.",
            ) from exc

    def health_check(self) -> bool:
        """
        Mock provider is always locally available.

        Deliberately does not consume fail_next_call/timeout_next_call,
        because health checks should not mutate normal test behaviour.
        """

        return True

    def queue_failure(self) -> None:
        """
        Cause the next provider invocation to fail.
        """

        with self._lock:
            self._config.fail_next_call = True

    def queue_timeout(self) -> None:
        """
        Cause the next provider invocation to raise a timeout.
        """

        with self._lock:
            self._config.timeout_next_call = True

    def _resolve_structured_response(self, *, system_prompt: str, user_prompt: str, response_model: type[T]) -> Mapping[str, Any] | BaseModel:
        if self._structured_resolver is not None:
            return self._structured_resolver(
                system_prompt,
                user_prompt,
                response_model,
            )

        if user_prompt in self._structured_responses:
            return copy.deepcopy(
                self._structured_responses[user_prompt]
            )

        if self._config.strict_structured_responses:
            raise LLMProviderResponseError(
                provider=self.PROVIDER_NAME,
                message=(
                    "No mock structured response configured for "
                    f"user prompt: {user_prompt!r}"
                ),
            )

        # Non-strict mode is useful only for schemas whose fields
        # all have defaults.
        return {}

    def _record_call(self, *, operation: str, system_prompt: str, user_prompt: str, response_model: type[BaseModel] | None = None) -> None:
        call = MockCall(
            operation=operation,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
        )

        with self._lock:
            self._calls.append(call)

    def _apply_fault_injection(self) -> None:
        with self._lock:
            if self._config.timeout_next_call:
                self._config.timeout_next_call = False

                raise LLMProviderTimeoutError(
                    provider=self.PROVIDER_NAME,
                    message="Simulated mock provider timeout.",
                )

            if self._config.fail_next_call:
                self._config.fail_next_call = False

                raise LLMProviderError(
                    provider=self.PROVIDER_NAME,
                    message="Simulated mock provider failure.",
                )

    def _simulate_latency(self) -> None:
        if self._config.latency_seconds > 0:
            time.sleep(self._config.latency_seconds)

    @staticmethod
    def _validate_prompts(*, system_prompt: str, user_prompt: str) -> None:
        if not isinstance(system_prompt, str):
            raise TypeError("system_prompt must be a string")

        if not isinstance(user_prompt, str):
            raise TypeError("user_prompt must be a string")

        if not system_prompt.strip():
            raise ValueError("system_prompt cannot be empty")

        if not user_prompt.strip():
            raise ValueError("user_prompt cannot be empty")