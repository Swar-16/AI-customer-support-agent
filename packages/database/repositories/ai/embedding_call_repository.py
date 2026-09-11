# AI-customer-support-agent\packages\database\repositories\ai\embedding_call_repository.py
from __future__ import annotations
import uuid
from collections.abc import Sequence
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.ai.embedding_call import EmbeddingCallModel

VALID_EMBEDDING_PURPOSES = frozenset({"query", "document_ingestion", "reindex", "evaluation", "other",})

class EmbeddingCallRepository:
    """
    Persistence adapter for embedding-provider call telemetry.

    It owns lifecycle mutations and queries but never commits.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Writes
    def add(self, call: EmbeddingCallModel) -> None:
        self._validate_call(call)
        self._session.add(call)

    def flush(self) -> None:
        self._session.flush()

    # Lookups
    def get_by_id(self, call_id: uuid.UUID) -> EmbeddingCallModel | None:
        self._validate_uuid(call_id, field_name="call_id")
        statement = (select(EmbeddingCallModel)
                     .where(EmbeddingCallModel.id == call_id)
        )

        return self._session.scalar(statement)

    def get_by_provider_request_id(self, provider_request_id: str) -> EmbeddingCallModel | None:
        normalized = self._normalize_required_text(provider_request_id, field_name="provider_request_id", uppercase=False)
        statement = (select(EmbeddingCallModel)
                     .where(EmbeddingCallModel.provider_request_id == normalized)
        )

        return self._session.scalar(statement)

    def list_for_ai_run(self, ai_run_id: uuid.UUID, *, limit: int = 100) -> Sequence[EmbeddingCallModel]:
        self._validate_uuid(ai_run_id, field_name="ai_run_id")
        self._validate_limit(limit)
        statement = (select(EmbeddingCallModel)
                     .where(EmbeddingCallModel.ai_run_id == ai_run_id)
                     .order_by(EmbeddingCallModel.started_at.asc(),
                               EmbeddingCallModel.id.asc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_for_version(self, version_id: uuid.UUID, *, limit: int = 500) -> Sequence[EmbeddingCallModel]:
        self._validate_uuid(version_id, field_name="version_id")
        self._validate_limit(limit)
        statement = (select(EmbeddingCallModel)
                     .where(EmbeddingCallModel.knowledge_version_id == version_id)
                     .order_by(EmbeddingCallModel.started_at.asc(),
                               EmbeddingCallModel.id.asc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_recent(self, *, purpose: str | None = None, provider: str | None = None, model: str | None = None, status: str | None = None,
                    error_code: str | None = None, started_from: datetime | None = None, started_to: datetime | None = None, limit: int = 100, offset: int = 0,
    ) -> Sequence[EmbeddingCallModel]:
        self._validate_pagination(limit=limit, offset=offset)
        normalized_purpose = self._normalize_optional_purpose(purpose)
        normalized_provider = self._normalize_optional_text(provider, field_name="provider")
        normalized_model = self._normalize_optional_text(model, field_name="model")
        normalized_status = self._normalize_optional_status(status)
        normalized_error_code = self._normalize_optional_text(error_code, field_name="error_code", uppercase=True)
        self._validate_datetime_range(started_from=started_from, started_to=started_to)
        statement = select(EmbeddingCallModel)
        if normalized_purpose is not None:
            statement = statement.where(EmbeddingCallModel.purpose == normalized_purpose)

        if normalized_provider is not None:
            statement = statement.where(EmbeddingCallModel.provider == normalized_provider)

        if normalized_model is not None:
            statement = statement.where(EmbeddingCallModel.model == normalized_model)

        if normalized_status is not None:
            statement = statement.where(EmbeddingCallModel.status == normalized_status)

        if normalized_error_code is not None:
            statement = statement.where(EmbeddingCallModel.error_code == normalized_error_code)

        if started_from is not None:
            statement = statement.where(EmbeddingCallModel.started_at >= started_from)

        if started_to is not None:
            statement = statement.where(EmbeddingCallModel.started_at <= started_to)

        statement = (statement.order_by(EmbeddingCallModel.started_at.desc(),
                                        EmbeddingCallModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Lifecycle mutations
    def mark_succeeded(self, call: EmbeddingCallModel, *, completed_at: datetime, latency_ms: int, dimensions: int, provider_request_id: str | None = None) -> None:
        self._validate_call(call)
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        if isinstance(dimensions, bool) or not isinstance(dimensions, int):
            raise TypeError("dimensions must be an integer")

        if dimensions <= 0:
            raise ValueError("dimensions must be greater than zero")

        call.status = "success"
        call.dimensions = dimensions
        call.latency_ms = latency_ms
        call.provider_request_id = self._normalize_optional_text(provider_request_id, field_name="provider_request_id")
        call.error_code = None
        call.error_message = None
        call.completed_at = completed_at

    def mark_failed(self, call: EmbeddingCallModel, *, completed_at: datetime, latency_ms: int, 
                    error_code: str, error_message: str, provider_request_id: str | None = None) -> None:
        self._validate_call(call)
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        call.status = "failed"
        call.dimensions = None
        call.latency_ms = latency_ms
        call.provider_request_id = self._normalize_optional_text(provider_request_id, field_name="provider_request_id")
        call.error_code = self._normalize_required_text(error_code, field_name="error_code", uppercase=True)
        call.error_message = self._normalize_required_text(error_message, field_name="error_message", uppercase=False)
        call.completed_at = completed_at

    def mark_timeout(self, call: EmbeddingCallModel, *, completed_at: datetime, latency_ms: int, 
                     error_message: str = "Embedding provider request timed out.", provider_request_id: str | None = None) -> None:
        self._validate_call(call)
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        call.status = "timeout"
        call.dimensions = None
        call.latency_ms = latency_ms
        call.provider_request_id = self._normalize_optional_text(provider_request_id, field_name="provider_request_id")
        call.error_code = "TIMEOUT"
        call.error_message = self._normalize_required_text(error_message, field_name="error_message", uppercase=False)
        call.completed_at = completed_at

    # Validation
    @staticmethod
    def _validate_call(call: EmbeddingCallModel) -> None:
        if not isinstance(call, EmbeddingCallModel):
            raise TypeError("call must be an EmbeddingCallModel")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_completion(*, completed_at: datetime, latency_ms: int) -> None:
        if not isinstance(completed_at, datetime):
            raise TypeError("completed_at must be a datetime")

        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")

        if isinstance(latency_ms, bool) or not isinstance(latency_ms, int):
            raise TypeError("latency_ms must be an integer")

        if latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str, uppercase: bool) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        return normalized.upper() if uppercase else normalized

    @classmethod
    def _normalize_optional_text(cls, value: str | None, *, field_name: str, uppercase: bool = False) -> str | None:
        if value is None:
            return None

        return cls._normalize_required_text(value, field_name=field_name, uppercase=uppercase)

    @staticmethod
    def _normalize_optional_purpose(purpose: str | None) -> str | None:
        if purpose is None:
            return None

        if not isinstance(purpose, str):
            raise TypeError("purpose must be a string or None")

        normalized = purpose.strip().lower()
        if normalized not in VALID_EMBEDDING_PURPOSES:
            expected = ", ".join(sorted(VALID_EMBEDDING_PURPOSES))
            raise ValueError(f"purpose must be one of: {expected}")

        return normalized

    @staticmethod
    def _normalize_optional_status(status: str | None) -> str | None:
        if status is None:
            return None

        if not isinstance(status, str):
            raise TypeError("status must be a string or None")

        normalized = status.strip().lower()
        valid = {"started", "success", "failed", "timeout"}
        if normalized not in valid:
            expected = ", ".join(sorted(valid))
            raise ValueError(f"status must be one of: {expected}")

        return normalized

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0 or limit > 1_000:
            raise ValueError("limit must be between 1 and 1000")

    @classmethod
    def _validate_pagination(cls, *, limit: int, offset: int) -> None:
        cls._validate_limit(limit)
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")

        if offset < 0:
            raise ValueError("offset cannot be negative")

    @staticmethod
    def _validate_datetime_range(*, started_from: datetime | None, started_to: datetime | None) -> None:
        for field_name, value in (("started_from", started_from), ("started_to", started_to),):
            if value is None:
                continue

            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime or None")

            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")

        if started_from is not None and started_to is not None and started_from > started_to:
            raise ValueError("started_from cannot be later than started_to")