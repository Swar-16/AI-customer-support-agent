# AI-customer-support-agent\packages\database\repositories\audit\api_request_repository.py
from __future__ import annotations
import uuid
from collections.abc import Sequence
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.audit.api_request import APIRequestModel

VALID_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD",})
VALID_API_REQUEST_OUTCOMES = frozenset({"success", "client_error", "server_error",})


class APIRequestRepository:
    """
    Persistence adapter for durable HTTP request records.

    The repository owns query construction only. It does not:

    - commit transactions;
    - decide what request data is safe to record;
    - extract actor identity;
    - calculate latency;
    - expose raw HTTP objects.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, request_record: APIRequestModel) -> None:
        """
        Stage a request record in the current transaction.

        This method does not flush or commit.
        """
        self._validate_request_instance(request_record)
        self._session.add(request_record)

    def flush(self) -> None:
        """Flush pending records without committing."""
        self._session.flush()

    # Primary lookups
    def get_by_id(self, request_id: uuid.UUID) -> APIRequestModel | None:
        self._validate_uuid(request_id, field_name="request_id")
        statement = (select(APIRequestModel)
                     .where(APIRequestModel.id == request_id)
        )

        return self._session.scalar(statement)

    def get_by_trace_id(self, trace_id: uuid.UUID, *, limit: int = 100) -> Sequence[APIRequestModel]:
        """
        Return HTTP requests belonging to one trace in chronological order.

        A trace ID is not assumed to be unique because a caller may reuse one correlation ID across several related HTTP requests.
        """
        self._validate_uuid(trace_id, field_name="trace_id")
        self._validate_limit(limit)
        statement = (select(APIRequestModel)
                     .where(APIRequestModel.trace_id == trace_id)
                     .order_by(APIRequestModel.started_at.asc(),
                               APIRequestModel.id.asc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Dashboard queries
    def list_recent(self, *, method: str | None = None, route_template: str | None = None, status_code: int | None = None,
                    outcome: str | None = None, error_code: str | None = None, actor_user_id: uuid.UUID | None = None, 
                    trace_id: uuid.UUID | None = None, minimum_latency_ms: int | None = None, started_from: datetime | None = None,
                    started_to: datetime | None = None, limit: int = 100, offset: int = 0) -> Sequence[APIRequestModel]:
        """
        Return filtered API traffic ordered newest first.

        This is the primary API-request table query for the MVP dashboard. Aggregate metrics should be
        implemented separately rather than calculated from a paginated result.
        """
        self._validate_pagination(limit=limit, offset=offset)
        normalized_method = self._normalize_optional_method(method)
        normalized_route = self._normalize_optional_text(route_template, field_name="route_template", lowercase=False)
        normalized_outcome = self._normalize_optional_outcome(outcome)
        normalized_error_code = self._normalize_optional_text(error_code, field_name="error_code", lowercase=False)
        if status_code is not None:
            self._validate_status_code(status_code)

        if actor_user_id is not None:
            self._validate_uuid(actor_user_id, field_name="actor_user_id")

        if trace_id is not None:
            self._validate_uuid(trace_id, field_name="trace_id")

        if minimum_latency_ms is not None:
            self._validate_non_negative_integer(minimum_latency_ms, field_name="minimum_latency_ms")

        self._validate_datetime_range(started_from=started_from, started_to=started_to)
        statement = select(APIRequestModel)
        if normalized_method is not None:
            statement = statement.where(APIRequestModel.method == normalized_method)

        if normalized_route is not None:
            statement = statement.where(APIRequestModel.route_template == normalized_route)

        if status_code is not None:
            statement = statement.where(APIRequestModel.status_code == status_code)

        if normalized_outcome is not None:
            statement = statement.where(APIRequestModel.outcome == normalized_outcome)

        if normalized_error_code is not None:
            statement = statement.where(APIRequestModel.error_code == normalized_error_code)

        if actor_user_id is not None:
            statement = statement.where(APIRequestModel.actor_user_id == actor_user_id)

        if trace_id is not None:
            statement = statement.where(APIRequestModel.trace_id == trace_id)

        if minimum_latency_ms is not None:
            statement = statement.where(APIRequestModel.latency_ms >= minimum_latency_ms)

        if started_from is not None:
            statement = statement.where(APIRequestModel.started_at >= started_from)

        if started_to is not None:
            statement = statement.where(APIRequestModel.started_at <= started_to)

        statement = (statement.order_by(APIRequestModel.started_at.desc(),
                                        APIRequestModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Validation helpers
    @staticmethod
    def _validate_request_instance(request_record: APIRequestModel) -> None:
        if not isinstance(request_record, APIRequestModel):
            raise TypeError("request_record must be an APIRequestModel")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_status_code(status_code: int) -> None:
        if isinstance(status_code, bool) or not isinstance(status_code, int):
            raise TypeError("status_code must be an integer")

        if status_code < 100 or status_code > 599:
            raise ValueError("status_code must be between 100 and 599")

    @staticmethod
    def _validate_non_negative_integer(value: int, *, field_name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")

        if value < 0:
            raise ValueError(f"{field_name} cannot be negative")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if limit > 500:
            raise ValueError("limit must not exceed 500")

    @classmethod
    def _validate_pagination(cls, *, limit: int, offset: int) -> None:
        cls._validate_limit(limit)
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")

        if offset < 0:
            raise ValueError("offset must not be negative")

    @staticmethod
    def _normalize_optional_method(method: str | None) -> str | None:
        if method is None:
            return None

        if not isinstance(method, str):
            raise TypeError("method must be a string or None")

        normalized = method.strip().upper()
        if not normalized:
            raise ValueError("method cannot be blank")

        if normalized not in VALID_HTTP_METHODS:
            expected = ", ".join(sorted(VALID_HTTP_METHODS))
            raise ValueError(f"method must be one of: {expected}")

        return normalized

    @staticmethod
    def _normalize_optional_outcome(outcome: str | None) -> str | None:
        if outcome is None:
            return None

        if not isinstance(outcome, str):
            raise TypeError("outcome must be a string or None")

        normalized = outcome.strip().lower()
        if not normalized:
            raise ValueError("outcome cannot be blank")

        if normalized not in VALID_API_REQUEST_OUTCOMES:
            expected = ", ".join(sorted(VALID_API_REQUEST_OUTCOMES))
            raise ValueError(f"outcome must be one of: {expected}")

        return normalized

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str, lowercase: bool) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        if lowercase:
            return normalized.lower()

        return normalized

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