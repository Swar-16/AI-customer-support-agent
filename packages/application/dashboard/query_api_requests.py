# AI-customer-support-agent\packages\application\dashboard\query_api_requests.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from packages.application.dashboard.models import DashboardPage, DashboardPagination, DashboardTimeRange
from packages.database.repositories.dashboard.api_request_repository import DashboardAPIRequestRecord, DashboardAPIRequestRepository

@dataclass(frozen=True, slots=True)
class QueryDashboardAPIRequestsCommand:
    time_range: DashboardTimeRange
    pagination: DashboardPagination
    trace_id: uuid.UUID | None = None
    method: str | None = None
    route_template: str | None = None
    status_code: int | None = None
    outcome: str | None = None
    error_code: str | None = None
    actor_user_id: uuid.UUID | None = None
    actor_role: str | None = None
    minimum_latency_ms: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.time_range, DashboardTimeRange):
            raise TypeError("time_range must be a DashboardTimeRange")

        if not isinstance(self.pagination, DashboardPagination):
            raise TypeError("pagination must be a DashboardPagination")

        for field_name, value in (("trace_id", self.trace_id), ("actor_user_id", self.actor_user_id),):
            if value is not None and not isinstance(value, uuid.UUID):
                raise TypeError(f"{field_name} must be a UUID or None")

        if self.status_code is not None:
            if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
                raise TypeError("status_code must be an integer or None")

            if not 100 <= self.status_code <= 599:
                raise ValueError("status_code must be between 100 and 599")

        if self.minimum_latency_ms is not None:
            if isinstance(self.minimum_latency_ms, bool) or not isinstance(self.minimum_latency_ms, int):
                raise TypeError("minimum_latency_ms must be an integer or None")

            if self.minimum_latency_ms < 0:
                raise ValueError("minimum_latency_ms must not be negative")


@dataclass(frozen=True, slots=True)
class DashboardAPIRequest:
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

class DashboardAPIRequestsUnitOfWork(Protocol):
    dashboard_api_requests: DashboardAPIRequestRepository | None

    def __enter__(self) -> "DashboardAPIRequestsUnitOfWork":
        ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: Any) -> None:
        ...

DashboardAPIRequestsUnitOfWorkFactory = Callable[[], DashboardAPIRequestsUnitOfWork]

class QueryDashboardAPIRequests:
    def __init__(self, *, uow_factory: DashboardAPIRequestsUnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        self._uow_factory = uow_factory

    def execute(self, command: QueryDashboardAPIRequestsCommand) -> DashboardPage[DashboardAPIRequest]:
        if not isinstance(command, QueryDashboardAPIRequestsCommand):
            raise TypeError("command must be a QueryDashboardAPIRequestsCommand")

        with self._uow_factory() as uow:
            repository = uow.dashboard_api_requests
            if repository is None:
                raise RuntimeError("dashboard_api_requests repository is unavailable")

            records, total = repository.query_api_requests(
                started_at=command.time_range.started_at,
                ended_at=command.time_range.ended_at,
                trace_id=command.trace_id,
                method=command.method,
                route_template=command.route_template,
                status_code=command.status_code,
                outcome=command.outcome,
                error_code=command.error_code,
                actor_user_id=command.actor_user_id,
                actor_role=command.actor_role,
                minimum_latency_ms=command.minimum_latency_ms,
                limit=command.pagination.limit,
                offset=command.pagination.offset,
            )

        items = tuple(self._map_record(record) for record in records)
        return DashboardPage(items=items, total=total, limit=command.pagination.limit, offset=command.pagination.offset)

    @staticmethod
    def _map_record(record: DashboardAPIRequestRecord) -> DashboardAPIRequest:
        return DashboardAPIRequest(
            id=record.id,
            trace_id=record.trace_id,
            method=record.method,
            route_template=record.route_template,
            status_code=record.status_code,
            outcome=record.outcome,
            error_code=record.error_code,
            actor_user_id=record.actor_user_id,
            actor_role=record.actor_role,
            request_size_bytes=record.request_size_bytes,
            response_size_bytes=record.response_size_bytes,
            latency_ms=record.latency_ms,
            started_at=record.started_at,
            completed_at=record.completed_at,
        )