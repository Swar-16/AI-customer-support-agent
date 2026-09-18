# AI-customer-support-agent\packages\ai\telemetry\llm_call_recorder.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from types import TracebackType
from typing import Protocol, Self

from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.repositories.ai.llm_call_repository import LLMCallRepository

class LLMTelemetryUnitOfWork(Protocol):
    """
    Minimal transaction contract required by LLM-call telemetry.

    Each factory invocation must return a fresh Unit of Work.
    """
    llm_calls: LLMCallRepository | None

    def __enter__(self) -> Self:
        ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        ...

    def commit(self) -> None:
        ...

LLMTelemetryUnitOfWorkFactory = Callable[[], LLMTelemetryUnitOfWork,]

class LLMCallTelemetryRecorder:
    """
    Persist LLM-call telemetry through short, independent transactions.

    Lifecycle:

        start transaction
            -> insert status="started"
            -> commit
        close transaction

        execute external provider with no telemetry transaction open

        completion transaction
            -> reload the call
            -> mark success/failure/timeout
            -> commit
        close transaction

    Customer messages, prompts, generated content, authentication data, and raw provider error responses must never be supplied to this recorder.
    """
    def __init__(self, *, uow_factory: LLMTelemetryUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def start_llm_call(self, *, ai_run_id: uuid.UUID, purpose: str, provider: str, model: str, started_at: datetime, 
                       prompt_version_id: uuid.UUID | None = None, temperature: Decimal | None = None,
    ) -> uuid.UUID:
        """
        Persist the STARTED record before invoking the provider.

        Unlike optional operational logging, this telemetry is mandatory.
        Persistence failures therefore propagate and prevent an untracked provider call.
        """
        self._validate_uuid(ai_run_id, field_name="ai_run_id")
        self._validate_optional_uuid(prompt_version_id, field_name="prompt_version_id")
        self._validate_aware_datetime(started_at, field_name="started_at")
        normalized_purpose = self._normalize_required_text(purpose, field_name="purpose", maximum_length=100)
        normalized_provider = self._normalize_required_text(provider, field_name="provider", maximum_length=100)
        normalized_model = self._normalize_required_text(model, field_name="model", maximum_length=200)
        if temperature is not None:
            if not isinstance(temperature, Decimal):
                raise TypeError("temperature must be a Decimal or None")

            if not Decimal("0") <= temperature <= Decimal("2"):
                raise ValueError("temperature must be between 0 and 2")

        call = LLMCallModel(
            ai_run_id=ai_run_id,
            prompt_version_id=prompt_version_id,
            purpose=normalized_purpose,
            provider=normalized_provider,
            model=normalized_model,
            temperature=temperature,
            status="started",
            started_at=started_at,
        )

        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            repository.add(call)
            repository.flush()

            call_id = call.id
            if call_id is None:
                raise RuntimeError("LLM call ID was not generated after flush")

            uow.commit()

        return call_id

    def complete_llm_call(self, call_id: uuid.UUID, *, completed_at: datetime, latency_ms: int, input_tokens: int, output_tokens: int,
                          cached_input_tokens: int = 0, estimated_cost_usd: Decimal | None = None, provider_request_id: str | None = None,
                          
    ) -> None:
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        self._validate_nonnegative_integer(input_tokens, field_name="input_tokens")
        self._validate_nonnegative_integer(output_tokens, field_name="output_tokens")
        self._validate_nonnegative_integer(cached_input_tokens, field_name="cached_input_tokens")

        if estimated_cost_usd is not None and estimated_cost_usd < 0:
            raise ValueError("estimated_cost_usd cannot be negative")

        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            call = self._get_started_call(repository=repository, call_id=call_id)
            repository.mark_succeeded(
                call,
                completed_at=completed_at,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
                estimated_cost_usd=estimated_cost_usd,
                provider_request_id=provider_request_id,
            )
            uow.commit()

    def fail_llm_call(self, call_id: uuid.UUID, *, completed_at: datetime, latency_ms: int, error_code: str, error_message: str, provider_request_id: str | None = None) -> None:
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        normalized_code = self._normalize_required_text(error_code, field_name="error_code", maximum_length=100)
        normalized_message = self._normalize_required_text(error_message, field_name="error_message", maximum_length=1000)

        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            call = self._get_started_call(repository=repository, call_id=call_id)
            repository.mark_failed(
                call,
                completed_at=completed_at,
                latency_ms=latency_ms,
                error_code=normalized_code,
                error_message=normalized_message,
                provider_request_id=provider_request_id,
            )
            uow.commit()

    def timeout_llm_call(self, call_id: uuid.UUID, *, completed_at: datetime, latency_ms: int,
                         error_message: str = "LLM provider request timed out.", provider_request_id: str | None = None
    ) -> None:
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        normalized_message = self._normalize_required_text(error_message, field_name="error_message", maximum_length=1000)

        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            call = self._get_started_call(repository=repository, call_id=call_id)
            repository.mark_timeout(
                call,
                completed_at=completed_at,
                latency_ms=latency_ms,
                error_message=normalized_message,
                provider_request_id=provider_request_id,
            )
            uow.commit()

    @staticmethod
    def _require_repository(uow: LLMTelemetryUnitOfWork) -> LLMCallRepository:
        repository = uow.llm_calls
        if repository is None:
            raise RuntimeError("LLM-call repository is unavailable in the telemetry Unit of Work")

        if not isinstance(repository, LLMCallRepository):
            raise TypeError("uow.llm_calls must be an LLMCallRepository")

        return repository

    @classmethod
    def _get_started_call(cls, *, repository: LLMCallRepository, call_id: uuid.UUID) -> LLMCallModel:
        cls._validate_uuid(call_id, field_name="call_id")
        call = repository.get_by_id(call_id)
        if call is None:
            raise RuntimeError(f"LLM telemetry call does not exist: {call_id}")

        if call.status != "started":
            raise RuntimeError(f"LLM telemetry call is already finalized: {call_id} ({call.status})")

        return call

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str, maximum_length: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        if len(normalized) > maximum_length:
            raise ValueError(f"{field_name} cannot exceed {maximum_length} characters")

        return normalized

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @classmethod
    def _validate_optional_uuid(cls, value: uuid.UUID | None, *, field_name: str) -> None:
        if value is not None:
            cls._validate_uuid(value, field_name=field_name)

    @staticmethod
    def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")

    @staticmethod
    def _validate_nonnegative_integer(value: int, *, field_name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")

        if value < 0:
            raise ValueError(f"{field_name} cannot be negative")

    @classmethod
    def _validate_completion(cls, *, completed_at: datetime, latency_ms: int) -> None:
        cls._validate_aware_datetime(completed_at, field_name="completed_at")
        cls._validate_nonnegative_integer(latency_ms, field_name="latency_ms")