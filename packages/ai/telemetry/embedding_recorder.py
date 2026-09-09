# AI-customer-support-agent\packages\ai\telemetry\embedding_recorder.py
from __future__ import annotations
import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self

from packages.database.models.ai.embedding_call import EmbeddingCallModel
from packages.database.repositories.ai.embedding_call_repository import EmbeddingCallRepository, VALID_EMBEDDING_PURPOSES

logger = logging.getLogger(__name__)

class EmbeddingTelemetryUnitOfWork(Protocol):
    """
    Minimal transaction contract required by embedding telemetry.

    Both SqlAlchemyUnitOfWork and SQLAlchemyKnowledgeUnitOfWork satisfy this protocol.
    """
    @property
    def embedding_calls(self) -> EmbeddingCallRepository:
        ...

    def __enter__(self) -> Self:
        ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        ...

    def commit(self) -> None:
        ...

EmbeddingTelemetryUnitOfWorkFactory = Callable[[], EmbeddingTelemetryUnitOfWork]

class EmbeddingTelemetryRecorder:
    """
    Best-effort persistence for embedding-provider telemetry.

    Each lifecycle operation uses a fresh transaction. Consequently:

    - the STARTED record is committed before provider execution;
    - provider failures can still be recorded;
    - telemetry persistence is independent from knowledge-artifact writes;
    - telemetry failure never causes the embedding operation itself to fail.

    Raw input text, document content, query text, and vectors must never be supplied through metadata or error messages.
    """
    def __init__(self, *, uow_factory: EmbeddingTelemetryUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def start_call(self, *, purpose: str, provider: str, model: str, input_count: int, total_input_characters: int, started_at: datetime,
                   ai_run_id: uuid.UUID | None = None, trace_id: uuid.UUID | None = None, knowledge_version_id: uuid.UUID | None = None,
                   provider_revision: str | None = None, request_fingerprint: str | None = None, metadata: dict[str, Any] | None = None
    ) -> uuid.UUID | None:
        """
        Persist and commit a STARTED embedding-call record.

        None is returned if telemetry storage fails. The provider call should still proceed in that case.
        """
        normalized_purpose = self._normalize_purpose(purpose)
        normalized_provider = self._normalize_required_text(provider, field_name="provider", maximum_length=100)
        normalized_model = self._normalize_required_text(model, field_name="model", maximum_length=200)
        normalized_revision = self._normalize_optional_text(provider_revision, field_name="provider_revision", maximum_length=200)
        normalized_fingerprint = self._normalize_optional_text(request_fingerprint, field_name="request_fingerprint", maximum_length=64)
        self._validate_positive_integer(input_count, field_name="input_count")
        self._validate_non_negative_integer(total_input_characters, field_name="total_input_characters")
        self._validate_aware_datetime(started_at, field_name="started_at")
        self._validate_optional_uuid(ai_run_id, field_name="ai_run_id")
        self._validate_optional_uuid(trace_id, field_name="trace_id")
        self._validate_optional_uuid(knowledge_version_id, field_name="knowledge_version_id")
        safe_metadata = self._copy_metadata(metadata)
        call = EmbeddingCallModel(
            ai_run_id=ai_run_id, trace_id=trace_id, knowledge_version_id=knowledge_version_id, purpose=normalized_purpose, 
            provider=normalized_provider, model=normalized_model, provider_revision=normalized_revision, input_count=input_count,
            total_input_characters=total_input_characters, request_fingerprint=normalized_fingerprint, dimensions=None, latency_ms=None,
            status="started", provider_request_id=None, error_code=None, error_message=None, metadata_=safe_metadata, started_at=started_at,
            completed_at=None,
        )

        try:
            with self._uow_factory() as uow:
                uow.embedding_calls.add(call)
                uow.embedding_calls.flush()
                call_id = call.id
                uow.commit()

            return call_id

        except Exception:
            logger.exception(
                "embedding_telemetry_start_persistence_failed",
                extra={
                    "purpose": normalized_purpose,
                    "provider": normalized_provider,
                    "model": normalized_model,
                },
            )
            return None

    def complete_call(self, call_id: uuid.UUID | None, *, completed_at: datetime, latency_ms: int, dimensions: int, provider_request_id: str | None = None) -> None:
        """Best-effort transition from STARTED to SUCCESS."""
        if call_id is None:
            return

        self._validate_uuid(call_id, field_name="call_id")
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        self._validate_positive_integer(dimensions, field_name="dimensions")

        try:
            with self._uow_factory() as uow:
                call = uow.embedding_calls.get_by_id(call_id)
                if call is None:
                    self._log_missing_call(call_id)
                    return

                uow.embedding_calls.mark_succeeded(
                    call, completed_at=completed_at, latency_ms=latency_ms, dimensions=dimensions, provider_request_id=provider_request_id
                )
                uow.commit()

        except Exception:
            logger.exception("embedding_telemetry_completion_persistence_failed", extra={"embedding_call_id": str(call_id)})

    def fail_call(self, call_id: uuid.UUID | None, *, completed_at: datetime, latency_ms: int, error_code: str, error_message: str, provider_request_id: str | None = None) -> None:
        """
        Best-effort transition from STARTED to FAILED.

        error_message must be a sanitized operational summary. Never pass the raw provider response, request body, input text, or document content.
        """
        if call_id is None:
            return

        self._validate_uuid(call_id, field_name="call_id")
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        safe_error_code = self._normalize_required_text(error_code, field_name="error_code", maximum_length=100).upper()
        safe_error_message = self._normalize_required_text(error_message, field_name="error_message", maximum_length=2_000)

        try:
            with self._uow_factory() as uow:
                call = uow.embedding_calls.get_by_id(call_id)
                if call is None:
                    self._log_missing_call(call_id)
                    return

                uow.embedding_calls.mark_failed(
                    call, completed_at=completed_at, latency_ms=latency_ms, error_code=safe_error_code, error_message=safe_error_message,
                    provider_request_id=provider_request_id,
                )
                uow.commit()

        except Exception:
            logger.exception("embedding_telemetry_failure_persistence_failed", extra={"embedding_call_id": str(call_id)})

    def timeout_call(self, call_id: uuid.UUID | None, *, completed_at: datetime, latency_ms: int, provider_request_id: str | None = None) -> None:
        """Best-effort transition from STARTED to TIMEOUT."""
        if call_id is None:
            return

        self._validate_uuid(call_id, field_name="call_id")
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)

        try:
            with self._uow_factory() as uow:
                call = uow.embedding_calls.get_by_id(call_id)
                if call is None:
                    self._log_missing_call(call_id)
                    return

                uow.embedding_calls.mark_timeout(
                    call, completed_at=completed_at, latency_ms=latency_ms, error_message="Embedding provider request timed out.", provider_request_id=provider_request_id,
                )
                uow.commit()

        except Exception:
            logger.exception("embedding_telemetry_timeout_persistence_failed", extra={"embedding_call_id": str(call_id)})

    @staticmethod
    def _log_missing_call(call_id: uuid.UUID) -> None:
        logger.warning("embedding_telemetry_call_not_found", extra={"embedding_call_id": str(call_id)})

    @staticmethod
    def _copy_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        if metadata is None:
            return {}

        if not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary or None")

        return dict(metadata)

    @staticmethod
    def _normalize_purpose(purpose: str) -> str:
        if not isinstance(purpose, str):
            raise TypeError("purpose must be a string")

        normalized = purpose.strip().lower()
        if normalized not in VALID_EMBEDDING_PURPOSES:
            expected = ", ".join(sorted(VALID_EMBEDDING_PURPOSES))
            raise ValueError(f"purpose must be one of: {expected}")

        return normalized

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

    @classmethod
    def _normalize_optional_text(cls, value: str | None, *, field_name: str, maximum_length: int) -> str | None:
        if value is None:
            return None

        return cls._normalize_required_text(value, field_name=field_name, maximum_length=maximum_length)

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

    @classmethod
    def _validate_completion(cls, *, completed_at: datetime, latency_ms: int) -> None:
        cls._validate_aware_datetime(completed_at, field_name="completed_at")
        cls._validate_non_negative_integer(latency_ms, field_name="latency_ms")

    @staticmethod
    def _validate_positive_integer(value: int, *, field_name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")

        if value <= 0:
            raise ValueError(f"{field_name} must be greater than zero")

    @staticmethod
    def _validate_non_negative_integer(value: int, *, field_name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")

        if value < 0:
            raise ValueError(f"{field_name} cannot be negative")