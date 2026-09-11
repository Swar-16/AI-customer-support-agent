# AI-customer-support-agent\packages\application\audit\query_audit_events.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from packages.application.audit.models import AuditActorType, AuditEventQuery, AuditEventView
from packages.database.models.audit.audit_event import AuditEventModel
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

class AuditEventQueryError(RuntimeError):
    """Base application error for audit-event queries."""

class AuditEventNotFoundError(AuditEventQueryError):
    def __init__(self, event_id: uuid.UUID) -> None:
        self.event_id = event_id
        super().__init__(f"Audit event does not exist: {event_id}")

class AuditQueryPersistenceContractError(AuditEventQueryError):
    """Indicates incomplete Unit of Work wiring or invalid persisted audit data."""

@dataclass(frozen=True, slots=True)
class AuditEventListResult:
    events: tuple[AuditEventView, ...]
    limit: int
    offset: int
    returned_count: int

class GetAuditEvent:
    """Retrieve one immutable audit event by ID."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, event_id: uuid.UUID) -> AuditEventView:
        if not isinstance(event_id, uuid.UUID):
            raise TypeError("event_id must be a UUID")

        with self._uow_factory() as uow:
            repository = _require_repository(uow)
            event = repository.get_by_id(event_id)

            if event is None:
                raise AuditEventNotFoundError(event_id)

            return _to_view(event)

class ListAuditEvents:
    """Return filtered audit events for the dashboard audit explorer."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, query: AuditEventQuery) -> AuditEventListResult:
        if not isinstance(query, AuditEventQuery):
            raise TypeError("query must be an AuditEventQuery")

        with self._uow_factory() as uow:
            repository = _require_repository(uow)
            events = repository.list_recent(
                event_type=query.event_type,
                entity_type=query.entity_type,
                entity_id=query.entity_id,
                action=query.action,
                actor_type=query.actor_type.value if query.actor_type is not None else None,
                actor_id=query.actor_id,
                trace_id=query.trace_id,
                conversation_id=query.conversation_id,
                ai_run_id=query.ai_run_id,
                occurred_from=query.occurred_from,
                occurred_to=query.occurred_to,
                limit=query.limit,
                offset=query.offset,
            )

            views = tuple(_to_view(event) for event in events)

            return AuditEventListResult(events=views, limit=query.limit, offset=query.offset, returned_count=len(views))

class GetEntityAuditHistory:
    """
    Return the ordered mutation history for one business entity.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, *, entity_type: str, entity_id: uuid.UUID, limit: int = 100, offset: int = 0) -> AuditEventListResult:
        with self._uow_factory() as uow:
            repository = _require_repository(uow)
            events = repository.get_entity_history(entity_type=entity_type, entity_id=entity_id, limit=limit, offset=offset)
            views = tuple(_to_view(event) for event in events)

            return AuditEventListResult(events=views, limit=limit, offset=offset, returned_count=len(views))

class GetTraceAuditEvents:
    """Return business events correlated with one distributed trace."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, *, trace_id: uuid.UUID, limit: int = 100) -> tuple[AuditEventView, ...]:
        if not isinstance(trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID")

        with self._uow_factory() as uow:
            repository = _require_repository(uow)
            events = repository.get_by_trace_id(trace_id, limit=limit)

            return tuple(_to_view(event) for event in events)

def _validate_uow_factory(uow_factory: UnitOfWorkFactory) -> UnitOfWorkFactory:
    if uow_factory is None:
        raise TypeError("uow_factory cannot be None")

    if not callable(uow_factory):
        raise TypeError("uow_factory must be callable")

    return uow_factory

def _require_repository(uow: SqlAlchemyUnitOfWork) -> AuditEventRepository:
    if uow.audit_events is None:
        raise AuditQueryPersistenceContractError("AuditEventRepository unavailable")

    return uow.audit_events


def _to_view(event: AuditEventModel) -> AuditEventView:
    if event.id is None:
        raise AuditQueryPersistenceContractError("Persisted audit event has no ID")

    if event.occurred_at is None:
        raise AuditQueryPersistenceContractError("Persisted audit event has no occurred_at")

    if event.recorded_at is None:
        raise AuditQueryPersistenceContractError("Persisted audit event has no recorded_at")

    try:
        actor_type = AuditActorType(event.actor_type)

    except ValueError as exc:
        raise AuditQueryPersistenceContractError("Persisted audit event contains invalid actor_type") from exc

    return AuditEventView(
        id=event.id,
        event_type=event.event_type,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        action=event.action,
        actor_type=actor_type,
        actor_id=event.actor_id,
        trace_id=event.trace_id,
        conversation_id=event.conversation_id,
        ai_run_id=event.ai_run_id,
        before_state=dict(event.before_state) if event.before_state is not None else None,
        after_state=dict(event.after_state) if event.after_state is not None else None,
        reason=event.reason,
        metadata=dict(event.metadata_),
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
    )