# AI-customer-support-agent\packages\database\repositories\dashboard\api_request_repository.py
from __future__ import annotations
import uuid
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.database.models.audit.api_request import APIRequestModel

VALID_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD",})
VALID_API_REQUEST_OUTCOMES = frozenset({"success", "client_error", "server_error",})

@dataclass(frozen=True, slots=True)
class DashboardAPIRequestRecord:
    """
    Sanitized dashboard representation of one HTTP request.

    Concrete request paths, client IP addresses, user agents, exception types and unrestricted metadata are deliberately excluded.
    """
    id: uuid.UUID
    trace_id: uuid.UUID
    method: str
    route_template: str | None
    status_code: int
    outcome: str
    error_code: str | None
    actor_user_id: uuid.UUID | None
    actor_role: str | None
    request_size_bytes: int | None
    response_size_bytes: int | None
    latency_ms: int
    started_at: datetime
    completed_at: datetime

class DashboardAPIRequestRepository:
    """
    Read-only repository for the dashboard API-request explorer.

    PostgreSQL performs filtering, counting, ordering and pagination.
    """
    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session instance")

        self._session = session

    def query_api_requests(self, *, started_at: datetime, ended_at: datetime, trace_id: uuid.UUID | None = None, method: str | None = None,
                           route_template: str | None = None, status_code: int | None = None, outcome: str | None = None, error_code: str | None = None,
                           actor_user_id: uuid.UUID | None = None, actor_role: str | None = None, minimum_latency_ms: int | None = None,
                           limit: int = 100, offset: int = 0
    ) -> tuple[tuple[DashboardAPIRequestRecord, ...], int]:
        self._validate_time_range(started_at=started_at, ended_at=ended_at)
        self._validate_pagination(limit=limit, offset=offset)
        for field_name, value in (("trace_id", trace_id), ("actor_user_id", actor_user_id),):
            if value is not None:
                self._validate_uuid(value, field_name=field_name)

        normalized_method = self._normalize_choice(method, field_name="method", valid_values=VALID_HTTP_METHODS, uppercase=True)
        normalized_outcome = self._normalize_choice(outcome, field_name="outcome", valid_values=VALID_API_REQUEST_OUTCOMES, uppercase=False)
        normalized_route = self._normalize_optional_text(route_template, field_name="route_template")
        normalized_error_code = self._normalize_optional_text(error_code, field_name="error_code")
        normalized_actor_role = self._normalize_optional_text(actor_role, field_name="actor_role")
        if status_code is not None:
            self._validate_status_code(status_code)

        if minimum_latency_ms is not None:
            self._validate_non_negative_integer(minimum_latency_ms, field_name="minimum_latency_ms")

        statement = (select(APIRequestModel.id.label("id"),
                            APIRequestModel.trace_id.label("trace_id"),
                            APIRequestModel.method.label("method"),
                            APIRequestModel.route_template.label("route_template"),
                            APIRequestModel.status_code.label("status_code"),
                            APIRequestModel.outcome.label("outcome"),
                            APIRequestModel.error_code.label("error_code"),
                            APIRequestModel.actor_user_id.label("actor_user_id"),
                            APIRequestModel.actor_role.label("actor_role"),
                            APIRequestModel.request_size_bytes.label("request_size_bytes"),
                            APIRequestModel.response_size_bytes.label("response_size_bytes"),
                            APIRequestModel.latency_ms.label("latency_ms"),
                            APIRequestModel.started_at.label("started_at"),
                            APIRequestModel.completed_at.label("completed_at"),
            ).where(APIRequestModel.started_at >= started_at, APIRequestModel.started_at <= ended_at)
        )

        if trace_id is not None:
            statement = statement.where(APIRequestModel.trace_id == trace_id)

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

        if normalized_actor_role is not None:
            statement = statement.where(APIRequestModel.actor_role == normalized_actor_role)

        if minimum_latency_ms is not None:
            statement = statement.where(APIRequestModel.latency_ms >= minimum_latency_ms)

        count_statement = (select(func.count())
                           .select_from(statement.order_by(None).subquery())
        )
        total = int(self._session.scalar(count_statement) or 0)
        statement = (statement.order_by(APIRequestModel.started_at.desc(),
                                        APIRequestModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )
        rows = self._session.execute(statement).all()
        records = tuple(
            DashboardAPIRequestRecord(
                id=row.id,
                trace_id=row.trace_id,
                method=row.method,
                route_template=row.route_template,
                status_code=int(row.status_code),
                outcome=row.outcome,
                error_code=row.error_code,
                actor_user_id=row.actor_user_id,
                actor_role=row.actor_role,
                request_size_bytes=self._optional_int(row.request_size_bytes),
                response_size_bytes=self._optional_int(row.response_size_bytes),
                latency_ms=int(row.latency_ms),
                started_at=row.started_at,
                completed_at=row.completed_at,
            )
            for row in rows
        )

        return records, total

    @staticmethod
    def _optional_int(value: int | None) -> int | None:
        return int(value) if value is not None else None

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_status_code(status_code: int) -> None:
        if isinstance(status_code, bool) or not isinstance(status_code, int):
            raise TypeError("status_code must be an integer")

        if not 100 <= status_code <= 599:
            raise ValueError("status_code must be between 100 and 599")

    @staticmethod
    def _validate_non_negative_integer(value: int, *, field_name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")

        if value < 0:
            raise ValueError(f"{field_name} must not be negative")

    @staticmethod
    def _validate_time_range(*, started_at: datetime, ended_at: datetime) -> None:
        for field_name, value in (("started_at", started_at), ("ended_at", ended_at),):
            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime")

            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")

        if started_at > ended_at:
            raise ValueError("started_at cannot be later than ended_at")

    @staticmethod
    def _validate_pagination(*, limit: int, offset: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if limit > 500:
            raise ValueError("limit must not exceed 500")

        if offset < 0:
            raise ValueError("offset must not be negative")

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        return normalized

    @classmethod
    def _normalize_choice(cls, value: str | None, *, field_name: str, valid_values: frozenset[str], uppercase: bool) -> str | None:
        normalized = cls._normalize_optional_text(value, field_name=field_name)
        if normalized is None:
            return None

        normalized = normalized.upper() if uppercase else normalized.lower()
        if normalized not in valid_values:
            expected = ", ".join(sorted(valid_values))
            raise ValueError(f"{field_name} must be one of: {expected}")

        return normalized