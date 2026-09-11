# AI-customer-support-agent\packages\application\dashboard\query_traces.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from packages.application.dashboard.models import DashboardPage, DashboardPagination, DashboardTimeRange
from packages.database.repositories.dashboard import DashboardTraceRepository, TraceSummaryRecord
from packages.database.repositories.dashboard.trace_repository import VALID_TRACE_STATUSES
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

class QueryDashboardTracesError(RuntimeError):
    """Base error for dashboard trace queries."""

class DashboardTracePersistenceContractError(QueryDashboardTracesError):
    """Raised when dashboard trace persistence is incorrectly wired."""

@dataclass(frozen=True, slots=True)
class QueryDashboardTracesCommand:
    time_range: DashboardTimeRange
    pagination: DashboardPagination = DashboardPagination()
    trace_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    ai_run_id: uuid.UUID | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.time_range, DashboardTimeRange):
            raise TypeError("time_range must be a DashboardTimeRange")

        if not isinstance(self.pagination, DashboardPagination):
            raise TypeError("pagination must be a DashboardPagination")

        for field_name, value in (("trace_id", self.trace_id), ("conversation_id", self.conversation_id), ("ai_run_id", self.ai_run_id),):
            if value is not None and not isinstance(value, uuid.UUID):
                raise TypeError(f"{field_name} must be a UUID or None")

        if self.status is not None:
            if not isinstance(self.status, str):
                raise TypeError("status must be a string or None")

            normalized_status = self.status.strip().lower()
            if normalized_status not in VALID_TRACE_STATUSES:
                expected = ", ".join(sorted(VALID_TRACE_STATUSES))
                raise ValueError(f"status must be one of: {expected}")

            object.__setattr__(self, "status", normalized_status,)

@dataclass(frozen=True, slots=True)
class DashboardTraceSummary:
    trace_id: uuid.UUID
    first_seen_at: datetime
    last_seen_at: datetime
    status: str
    api_request_count: int
    ai_run_count: int
    failed_api_request_count: int
    failed_ai_run_count: int
    running_ai_run_count: int
    maximum_api_latency_ms: int | None
    maximum_ai_latency_ms: int | None

    @classmethod
    def from_repository(cls, record: TraceSummaryRecord) -> "DashboardTraceSummary":
        if not isinstance(record, TraceSummaryRecord):
            raise TypeError("record must be a TraceSummaryRecord")

        return cls(
            trace_id=record.trace_id,
            first_seen_at=record.first_seen_at,
            last_seen_at=record.last_seen_at,
            status=record.status,
            api_request_count=record.api_request_count,
            ai_run_count=record.ai_run_count,
            failed_api_request_count=record.failed_api_request_count,
            failed_ai_run_count=record.failed_ai_run_count,
            running_ai_run_count=record.running_ai_run_count,
            maximum_api_latency_ms=record.maximum_api_latency_ms,
            maximum_ai_latency_ms=record.maximum_ai_latency_ms,
        )

class QueryDashboardTraces:
    """
    Query the dashboard trace explorer.

    This service validates application input and maps infrastructure read records into application-facing immutable models.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def execute(self, command: QueryDashboardTracesCommand) -> DashboardPage[DashboardTraceSummary]:
        if not isinstance(command, QueryDashboardTracesCommand):
            raise TypeError("command must be a QueryDashboardTracesCommand")

        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            records, total = repository.query_traces(
                started_at=command.time_range.started_at,
                ended_at=command.time_range.ended_at,
                trace_id=command.trace_id,
                conversation_id=command.conversation_id,
                ai_run_id=command.ai_run_id,
                status=command.status,
                limit=command.pagination.limit,
                offset=command.pagination.offset,
            )

            items = tuple(DashboardTraceSummary.from_repository(record) for record in records)
            return DashboardPage(
                items=items,
                total=total,
                limit=command.pagination.limit,
                offset=command.pagination.offset,
            )

    @staticmethod
    def _require_repository(uow: SqlAlchemyUnitOfWork) -> DashboardTraceRepository:
        repository = uow.dashboard_trace

        if repository is None:
            raise DashboardTracePersistenceContractError("DashboardTraceRepository unavailable")

        if not isinstance(repository, DashboardTraceRepository):
            raise DashboardTracePersistenceContractError("dashboard_trace has an invalid repository type")

        return repository