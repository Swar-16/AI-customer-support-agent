# AI-customer-support-agent\packages\database\repositories\ai\reranker_call_repository.py
from __future__ import annotations
import uuid
from collections.abc import Sequence
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.ai.reranker_call import RerankerCallModel


class RerankerCallRepository:
    """
    Persistence adapter for reranker execution telemetry.

    It manages call lifecycle state but never commits.
    """

    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Writes
    def add(self, call: RerankerCallModel) -> None:
        self._validate_call(call)
        self._session.add(call)

    def flush(self) -> None:
        self._session.flush()

    # Lookups
    def get_by_id(self, call_id: uuid.UUID) -> RerankerCallModel | None:
        self._validate_uuid(call_id, field_name="call_id")

        statement = (select(RerankerCallModel)
                     .where(RerankerCallModel.id == call_id)
        )

        return self._session.scalar(statement)

    def get_by_provider_request_id(self, provider_request_id: str) -> RerankerCallModel | None:
        normalized = self._normalize_required_text(provider_request_id, field_name="provider_request_id", uppercase=False)
        statement = (select(RerankerCallModel)
                     .where(RerankerCallModel.provider_request_id == normalized)
        )

        return self._session.scalar(statement)

    def list_for_retrieval_run(self, retrieval_run_id: uuid.UUID, *, limit: int = 100) -> Sequence[RerankerCallModel]:
        self._validate_uuid(retrieval_run_id, field_name="retrieval_run_id")
        self._validate_limit(limit)
        statement = (select(RerankerCallModel)
                     .where(RerankerCallModel.retrieval_run_id == retrieval_run_id)
                     .order_by(RerankerCallModel.started_at.asc(),
                               RerankerCallModel.id.asc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_for_trace(self, trace_id: uuid.UUID, *, limit: int = 100) -> Sequence[RerankerCallModel]:
        self._validate_uuid(trace_id, field_name="trace_id")
        self._validate_limit(limit)
        statement = (select(RerankerCallModel)
                     .where(RerankerCallModel.trace_id == trace_id)
                     .order_by(RerankerCallModel.started_at.asc(),
                               RerankerCallModel.id.asc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_recent(self, *, reranker_id: str | None = None, provider: str | None = None, model: str | None = None, 
                    status: str | None = None, error_code: str | None = None, started_from: datetime | None = None, 
                    started_to: datetime | None = None, limit: int = 100, offset: int = 0,
    ) -> Sequence[RerankerCallModel]:
        self._validate_pagination(limit=limit, offset=offset)
        normalized_reranker_id = self._normalize_optional_text(reranker_id, field_name="reranker_id")
        normalized_provider = self._normalize_optional_text(provider, field_name="provider")
        normalized_model = self._normalize_optional_text(model, field_name="model")
        normalized_status = self._normalize_optional_status(status)
        normalized_error_code = self._normalize_optional_text(error_code, field_name="error_code", uppercase=True)
        self._validate_datetime_range(started_from=started_from, started_to=started_to)
        statement = select(RerankerCallModel)
        if normalized_reranker_id is not None:
            statement = statement.where(RerankerCallModel.reranker_id == normalized_reranker_id)

        if normalized_provider is not None:
            statement = statement.where(RerankerCallModel.provider == normalized_provider)

        if normalized_model is not None:
            statement = statement.where(RerankerCallModel.model == normalized_model)

        if normalized_status is not None:
            statement = statement.where(RerankerCallModel.status == normalized_status)

        if normalized_error_code is not None:
            statement = statement.where(RerankerCallModel.error_code == normalized_error_code)

        if started_from is not None:
            statement = statement.where(RerankerCallModel.started_at >= started_from)

        if started_to is not None:
            statement = statement.where(RerankerCallModel.started_at <= started_to)

        statement = (statement.order_by(RerankerCallModel.started_at.desc(),
                                        RerankerCallModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Lifecycle updates
    def mark_succeeded(self, call: RerankerCallModel, *, completed_at: datetime, latency_ms: int, output_candidate_count: int, provider_request_id: str | None = None) -> None:
        self._validate_call(call)
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        self._validate_output_count(call=call, output_candidate_count=output_candidate_count)
        call.status = "success"
        call.output_candidate_count = output_candidate_count
        call.latency_ms = latency_ms
        call.provider_request_id = self._normalize_optional_text(provider_request_id, field_name="provider_request_id")
        call.error_code = None
        call.error_message = None
        call.completed_at = completed_at

    def mark_failed(self, call: RerankerCallModel, *, completed_at: datetime, latency_ms: int, error_code: str, error_message: str, provider_request_id: str | None = None) -> None:
        self._validate_call(call)
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        call.status = "failed"
        call.output_candidate_count = 0
        call.latency_ms = latency_ms
        call.provider_request_id = self._normalize_optional_text(provider_request_id, field_name="provider_request_id")
        call.error_code = self._normalize_required_text(error_code, field_name="error_code", uppercase=True)
        call.error_message = self._normalize_required_text(error_message, field_name="error_message", uppercase=False)
        call.completed_at = completed_at

    def mark_timeout(self, call: RerankerCallModel, *, completed_at: datetime, latency_ms: int,
                     error_message: str = "Reranker request timed out.", provider_request_id: str | None = None) -> None:
        self._validate_call(call)
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        call.status = "timeout"
        call.output_candidate_count = 0
        call.latency_ms = latency_ms
        call.provider_request_id = self._normalize_optional_text(provider_request_id, field_name="provider_request_id")
        call.error_code = "TIMEOUT"
        call.error_message = self._normalize_required_text(error_message, field_name="error_message", uppercase=False)
        call.completed_at = completed_at

    # Validation helpers
    @staticmethod
    def _validate_call(call: RerankerCallModel) -> None:
        if not isinstance(call, RerankerCallModel):
            raise TypeError("call must be a RerankerCallModel")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_output_count(*, call: RerankerCallModel, output_candidate_count: int) -> None:
        if isinstance(output_candidate_count, bool) or not isinstance(output_candidate_count, int):
            raise TypeError("output_candidate_count must be an integer")

        if output_candidate_count < 0:
            raise ValueError("output_candidate_count cannot be negative")

        if output_candidate_count > call.input_candidate_count:
            raise ValueError("output_candidate_count cannot exceed input_candidate_count")

        if output_candidate_count > call.requested_limit:
            raise ValueError("output_candidate_count cannot exceed requested_limit")

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