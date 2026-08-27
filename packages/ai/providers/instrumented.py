from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from time import perf_counter
from typing import TypeVar
from pydantic import BaseModel

from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import LLMProviderError, LLMProviderTimeoutError
from packages.ai.providers.types import LLMResponse, StructuredLLMResponse
from packages.ai.telemetry.recorder import TelemetryRecorder
from packages.database.models.ai.llm_call import LLMCallModel

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

@dataclass(frozen=True, slots=True)
class LLMCallContext:
    """
    Immutable execution context attached to provider calls.

    An InstrumentedLLMProvider instance should be scoped to one logical AI operation/run rather than mutated between concurrent requests.

    Examples of purpose:
        intent_classification
        answer_generation
        query_rewrite
        reranking
        policy_reasoning
    """

    ai_run_id: uuid.UUID
    purpose: str
    prompt_version_id: uuid.UUID | None = None
    temperature: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ai_run_id, uuid.UUID):
            raise TypeError("ai_run_id must be a UUID")

        if not isinstance(self.purpose, str):
            raise TypeError("purpose must be a string")

        normalized_purpose = self.purpose.strip()
        if not normalized_purpose:
            raise ValueError("purpose cannot be empty")

        object.__setattr__(self, "purpose", normalized_purpose)

        if self.prompt_version_id is not None and not isinstance(self.prompt_version_id, uuid.UUID):
            raise TypeError("prompt_version_id must be UUID or None")

        if self.temperature is not None:
            if not isinstance(self.temperature, Decimal):
                raise TypeError("temperature must be Decimal or None")

            if not Decimal("0") <= self.temperature <= Decimal("2"):
                raise ValueError("temperature must be between 0 and 2")


class InstrumentedLLMProvider(LLMProvider):
    """
    Decorator around an LLMProvider that records invocation telemetry.

    Responsibilities:
    - create an LLMCallModel before provider execution
    - measure provider-call latency using a monotonic clock
    - persist normalized usage after success
    - persist timeout/failure information
    - preserve the wrapped provider's public response contract

    Explicitly NOT responsible for:
    - committing transactions
    - retry/backoff
    - circuit breaking
    - calculating model pricing
    - intent/domain logic
    - prompt construction
    - swallowing provider failures

    Transaction ownership remains with the surrounding UnitOfWork.
    """

    def __init__(self, *, provider: LLMProvider, recorder: TelemetryRecorder, context: LLMCallContext) -> None:
        if provider is None:
            raise TypeError("provider cannot be None")

        if recorder is None:
            raise TypeError("recorder cannot be None")

        if not isinstance(context, LLMCallContext):
            raise TypeError("context must be an LLMCallContext")

        self._provider = provider
        self._recorder = recorder
        self._context = context
        self._last_call_id: uuid.UUID | None = None


    # Provider identity
    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name
    
    @property
    def last_call_id(self) -> uuid.UUID | None:
        return self._last_call_id


    # Plain-text generation
    def generate(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        self._last_call_id = None ## prevents an old successful call ID from leaking into a later failed invocation.
        call = self._start_call()
        started_perf = perf_counter()

        try:
            response = self._provider.generate(system_prompt=system_prompt, user_prompt=user_prompt)

        except LLMProviderTimeoutError as exc:
            latency_ms = self._elapsed_ms(started_perf)
            self._record_timeout_safely(call=call, exc=exc, latency_ms=latency_ms)
            raise

        except LLMProviderError as exc:
            latency_ms = self._elapsed_ms(started_perf)
            self._record_failure_safely(call=call, exc=exc, latency_ms=latency_ms)
            raise

        except Exception as exc:
            latency_ms = self._elapsed_ms(started_perf)
            self._record_unexpected_failure_safely(call=call, exc=exc, latency_ms=latency_ms)
            # Do not convert programming defects into provider failures.
            raise

        latency_ms = self._elapsed_ms(started_perf)
        self._complete_call(call=call, response=response, latency_ms=latency_ms)
        self._last_call_id = call.id
        return response


    # Structured generation
    def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model: type[T]) -> StructuredLLMResponse[T]:
        self._last_call_id = None ## prevents an old successful call ID from leaking into a later failed invocation.
        call = self._start_call()
        started_perf = perf_counter()

        try:
            response = self._provider.generate_structured(system_prompt=system_prompt, user_prompt=user_prompt, response_model=response_model)
        except LLMProviderTimeoutError as exc:
            latency_ms = self._elapsed_ms(started_perf)
            self._record_timeout_safely(call=call, exc=exc, latency_ms=latency_ms)
            raise

        except LLMProviderError as exc:
            latency_ms = self._elapsed_ms(started_perf)
            self._record_failure_safely(call=call, exc=exc, latency_ms=latency_ms)
            raise

        except Exception as exc:
            latency_ms = self._elapsed_ms(started_perf)
            self._record_unexpected_failure_safely(call=call, exc=exc, latency_ms=latency_ms)
            raise

        latency_ms = self._elapsed_ms(started_perf)
        self._complete_call(call=call, response=response, latency_ms=latency_ms)
        self._last_call_id = call.id
        return response

    # Health
    def health_check(self) -> bool:
        """
        Delegate health checks directly.
        Health checks are deliberately not persisted as business LLM calls.
        """
        return self._provider.health_check()


    # Telemetry lifecycle
    def _start_call(self):
        """
        Create the telemetry row before external provider invocation.

        If this fails, the provider is NOT called. This preserves the
        invariant that an externally executed business LLM call should have
        an auditable DB record.
        """

        return self._recorder.start_llm_call(
            ai_run_id=self._context.ai_run_id,
            purpose=self._context.purpose,
            provider=self.provider_name,
            model=self.model_name,
            started_at=datetime.now(timezone.utc),
            prompt_version_id=self._context.prompt_version_id,
            temperature=self._context.temperature,
        )

    def _complete_call(self, *, call: LLMCallModel, response: LLMResponse | StructuredLLMResponse[BaseModel],latency_ms: int) -> None:
        """
        Persist normalized telemetry from a successful invocation. Does NOT swallow DB failures.

        Telemetry completion errors are deliberately allowed to propagate:
        the provider already succeeded, but failure to persist mandatory
        audit evidence is an infrastructure failure and the surrounding
        UnitOfWork should roll back.
        """

        self._recorder.complete_llm_call(
            call,
            completed_at=datetime.now(timezone.utc),
            latency_ms=latency_ms,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_input_tokens=response.usage.cached_input_tokens,
            estimated_cost_usd=response.estimated_cost_usd,
            provider_request_id=response.metadata.provider_request_id,
        )


    # Failure recording
    def _record_timeout_safely(self, *, call: LLMCallModel, exc: LLMProviderTimeoutError, latency_ms: int) -> None:
        try:
            self._recorder.timeout_llm_call(
                call,
                completed_at=datetime.now(timezone.utc),
                latency_ms=latency_ms,
                error_message=self._safe_error_message(exc),
                provider_request_id=self._extract_request_id(exc),
            )

        except Exception:
            # Preserve the original provider timeout as the externally
            # meaningful failure. The transaction may still be rolled back
            # by the surrounding UoW if persistence is unhealthy.
            logger.exception(
                "failed_to_record_llm_timeout",
                extra={
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "purpose": self._context.purpose,
                    "ai_run_id": str(self._context.ai_run_id),
                },
            )

    def _record_failure_safely(self, *, call: LLMCallModel, exc: LLMProviderError, latency_ms: int) -> None:
        try:
            self._recorder.fail_llm_call(
                call,
                completed_at=datetime.now(timezone.utc),
                latency_ms=latency_ms,
                error_code=getattr(exc, "error_code", None,) or "PROVIDER_ERROR",
                error_message=self._safe_error_message(exc),
                provider_request_id=self._extract_request_id(exc),
            )

        except Exception:
            logger.exception(
                "failed_to_record_llm_failure",
                extra={
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "purpose": self._context.purpose,
                    "ai_run_id": str(self._context.ai_run_id),
                },
            )

    def _record_unexpected_failure_safely(self, *, call: LLMCallModel, exc: Exception, latency_ms: int) -> None:
        try:
            self._recorder.fail_llm_call(
                call,
                completed_at=datetime.now(timezone.utc),
                latency_ms=latency_ms,
                error_code="UNEXPECTED_PROVIDER_EXCEPTION",
                error_message="Unexpected provider implementation failure.",
            )

        except Exception:
            logger.exception(
                "failed_to_record_unexpected_llm_failure",
                extra={
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "purpose": self._context.purpose,
                    "ai_run_id": str(self._context.ai_run_id),
                    "exception_type": type(exc).__name__,
                },
            )


    # Helpers

    @staticmethod
    def _elapsed_ms(started_perf: float) -> int:
        elapsed_seconds = perf_counter() - started_perf
        return max(0, int(round(elapsed_seconds * 1000)))

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        """
        Return a sanitized message appropriate for persistence.

        Provider exception strings may eventually contain sensitive details.
        Prefer normalized error attributes when available.
        """

        message = getattr(exc, "message", None)

        if isinstance(message, str):
            normalized = message.strip()
            if normalized:
                return normalized[:1000]

        return ("LLM provider invocation failed.")

    @staticmethod
    def _extract_request_id(exc: Exception) -> str | None:
        """
        Allow future provider adapters to expose request correlation IDs
        through structured exception metadata without coupling this wrapper
        to Groq/OpenAI/etc.
        """

        metadata = getattr(exc, "metadata", None)

        if not isinstance(metadata, dict):
            return None

        request_id = metadata.get("provider_request_id")
        if not isinstance(request_id, str):
            return None

        normalized = request_id.strip()
        return normalized or None