# AI-customer-support-agent\packages\application\dashboard\query_audit_events.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from packages.application.dashboard.models import DashboardPage, DashboardPagination, DashboardTimeRange
from packages.database.repositories.dashboard.audit_event_repository import DashboardAuditEventRecord, DashboardAuditEventRepository

@dataclass(frozen=True, slots=True)
class QueryDashboardAuditEventsCommand:
    time_range: DashboardTimeRange
    pagination: DashboardPagination
    event_type: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    action: str | None = None
    actor_type: str | None = None
    actor_id: uuid.UUID | None = None
    trace_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    ai_run_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.time_range, DashboardTimeRange):
            raise TypeError("time_range must be a DashboardTimeRange")

        if not isinstance(self.pagination, DashboardPagination):
            raise TypeError("pagination must be a DashboardPagination")

        for field_name, value in (
            ("entity_id", self.entity_id), ("actor_id", self.actor_id), ("trace_id", self.trace_id), ("conversation_id", self.conversation_id), ("ai_run_id", self.ai_run_id)
        ):
            if value is not None and not isinstance(value, uuid.UUID):
                raise TypeError(f"{field_name} must be a UUID or None")

@dataclass(frozen=True, slots=True)
class DashboardAuditEvent:
    id: uuid.UUID
    event_type: str
    entity_type: str
    entity_id: uuid.UUID
    action: str
    actor_type: str
    actor_id: uuid.UUID | None
    trace_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    ai_run_id: uuid.UUID | None
    has_before_state: bool
    has_after_state: bool
    has_reason: bool
    occurred_at: datetime
    recorded_at: datetime

class DashboardAuditEventsUnitOfWork(Protocol):
    dashboard_audit_events: DashboardAuditEventRepository | None

    def __enter__(self) -> "DashboardAuditEventsUnitOfWork":
        ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: Any) -> None:
        ...

DashboardAuditEventsUnitOfWorkFactory = Callable[[], DashboardAuditEventsUnitOfWork]

class QueryDashboardAuditEvents:
    def __init__(self, *, uow_factory: DashboardAuditEventsUnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        self._uow_factory = uow_factory

    def execute(self, command: QueryDashboardAuditEventsCommand) -> DashboardPage[DashboardAuditEvent]:
        if not isinstance(command, QueryDashboardAuditEventsCommand):
            raise TypeError("command must be a QueryDashboardAuditEventsCommand")

        with self._uow_factory() as uow:
            repository = uow.dashboard_audit_events
            if repository is None:
                raise RuntimeError("dashboard_audit_events repository is unavailable")

            records, total = repository.query_audit_events(
                started_at=command.time_range.started_at,
                ended_at=command.time_range.ended_at,
                event_type=command.event_type,
                entity_type=command.entity_type,
                entity_id=command.entity_id,
                action=command.action,
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                trace_id=command.trace_id,
                conversation_id=command.conversation_id,
                ai_run_id=command.ai_run_id,
                limit=command.pagination.limit,
                offset=command.pagination.offset,
            )

        items = tuple(self._map_record(record) for record in records)
        return DashboardPage(items=items, total=total, limit=command.pagination.limit, offset=command.pagination.offset)

    @staticmethod
    def _map_record(record: DashboardAuditEventRecord) -> DashboardAuditEvent:
        return DashboardAuditEvent(
            id=record.id,
            event_type=record.event_type,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            action=record.action,
            actor_type=record.actor_type,
            actor_id=record.actor_id,
            trace_id=record.trace_id,
            conversation_id=record.conversation_id,
            ai_run_id=record.ai_run_id,
            has_before_state=record.has_before_state,
            has_after_state=record.has_after_state,
            has_reason=record.has_reason,
            occurred_at=record.occurred_at,
            recorded_at=record.recorded_at,
        )