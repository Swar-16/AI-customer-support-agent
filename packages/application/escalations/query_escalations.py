# AI-customer-support-agent\packages\application\escalations\query_escalations.py
from __future__ import annotations
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from packages.database.models.support.escalation import EscalationModel
from packages.database.repositories.support.escalation_repository import EscalationRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork,]

class EscalationQueryError(RuntimeError):
    """Base application error for escalation queries."""

class EscalationDoesNotExistError(EscalationQueryError):
    """Raised when an escalation cannot be found."""
    def __init__(self, escalation_id: uuid.UUID) -> None:
        self.escalation_id = escalation_id

        super().__init__(f"Escalation does not exist: {escalation_id}")

class EscalationQueryContractError(EscalationQueryError):
    """Raised when Unit of Work or persistence wiring is incomplete."""

@dataclass(frozen=True, slots=True)
class EscalationView:
    """
    Detached application view of one escalation.

    No ORM instance escapes the Unit of Work.
    """
    escalation_id: uuid.UUID
    conversation_id: uuid.UUID
    ai_run_id: uuid.UUID | None
    trigger_message_id: uuid.UUID | None
    source: str
    reason_code: str
    reason_summary: str | None
    priority: str
    status: str
    handoff_summary: str | None
    metadata: Mapping[str, Any]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class GetEscalationQuery:
    """Query for one escalation by ID."""
    escalation_id: uuid.UUID

    def __post_init__(self) -> None:
        if not isinstance(self.escalation_id, uuid.UUID):
            raise TypeError("escalation_id must be a UUID")

@dataclass(frozen=True, slots=True)
class ListConversationEscalationsQuery:
    """Query for escalation history belonging to one conversation."""
    conversation_id: uuid.UUID
    limit: int = 100

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, uuid.UUID):
            raise TypeError("conversation_id must be a UUID")

        self._validate_limit(self.limit)

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if limit > 200:
            raise ValueError("limit must not exceed 200")

@dataclass(frozen=True, slots=True)
class ListEscalationsQuery:
    """
    Query for the operations escalation queue.

    `active_only=True` returns only open/in-review escalations using priority-first queue ordering.

    `active_only=False` returns recent records and permits an exact status and reason-code filter.
    """
    active_only: bool = False
    status: str | None = None
    priority: str | None = None
    reason_code: str | None = None
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.active_only, bool):
            raise TypeError("active_only must be a boolean")

        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer")

        if self.limit <= 0:
            raise ValueError("limit must be greater than zero")

        # The service fetches limit + 1 to determine has_more. Keeping this at 200 remains safely below the repository's maximum limit of 500.
        if self.limit > 200:
            raise ValueError("limit must not exceed 200")

        if isinstance(self.offset, bool) or not isinstance(self.offset, int):
            raise TypeError("offset must be an integer")

        if self.offset < 0:
            raise ValueError("offset must not be negative")

        normalized_status = self._normalize_optional_text(self.status, field_name="status")
        normalized_priority = self._normalize_optional_text(self.priority, field_name="priority")
        normalized_reason_code = self._normalize_optional_text(self.reason_code, field_name="reason_code")
        if self.active_only:
            if normalized_status is not None:
                raise ValueError("status cannot be supplied when active_only=True")

            if normalized_reason_code is not None:
                raise ValueError("reason_code cannot be supplied when active_only=True")

        object.__setattr__(self, "status", normalized_status)
        object.__setattr__(self, "priority", normalized_priority)
        object.__setattr__(self, "reason_code", normalized_reason_code)

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip().lower()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        return normalized

@dataclass(frozen=True, slots=True)
class EscalationPage:
    """Offset-based escalation result page for the MVP dashboard."""
    items: tuple[EscalationView, ...]
    limit: int
    offset: int
    has_more: bool

    @property
    def count(self) -> int:
        return len(self.items)

class GetEscalation:
    """Retrieve one escalation using its ID."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, query: GetEscalationQuery) -> EscalationView:
        if not isinstance(query, GetEscalationQuery):
            raise TypeError("query must be a GetEscalationQuery")

        with self._uow_factory() as uow:
            repository = _require_repository(uow)
            escalation = repository.get_by_id(query.escalation_id)

            if escalation is None:
                raise EscalationDoesNotExistError(query.escalation_id)

            # No commit is needed for this read-only Unit of Work.
            return _to_view(escalation)

class ListConversationEscalations:
    """Retrieve escalation history for one conversation."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, query: ListConversationEscalationsQuery) -> tuple[EscalationView, ...]:
        if not isinstance(query, ListConversationEscalationsQuery):
            raise TypeError("query must be a ListConversationEscalationsQuery")

        with self._uow_factory() as uow:
            repository = _require_repository(uow)
            escalations = repository.get_by_conversation(query.conversation_id, limit=query.limit)

            return _to_views(escalations)

class ListEscalations:
    """Retrieve the dashboard escalation queue or recent history."""

    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, query: ListEscalationsQuery) -> EscalationPage:
        if not isinstance(query, ListEscalationsQuery):
            raise TypeError("query must be a ListEscalationsQuery")

        fetch_limit = query.limit + 1
        with self._uow_factory() as uow:
            repository = _require_repository(uow)

            if query.active_only:
                records = repository.list_active(priority=query.priority, limit=fetch_limit, offset=query.offset)
            else:
                records = repository.list_recent(status=query.status, priority=query.priority, reason_code=query.reason_code, limit=fetch_limit, offset=query.offset)

            has_more = len(records) > query.limit
            visible_records = records[: query.limit]

            return EscalationPage(
                items=_to_views(visible_records),
                limit=query.limit,
                offset=query.offset,
                has_more=has_more,
            )

def _validate_uow_factory(uow_factory: UnitOfWorkFactory) -> UnitOfWorkFactory:
    if uow_factory is None:
        raise TypeError("uow_factory cannot be None")

    if not callable(uow_factory):
        raise TypeError("uow_factory must be callable")

    return uow_factory

def _require_repository(uow: SqlAlchemyUnitOfWork) -> EscalationRepository:
    if uow.escalations is None:
        raise EscalationQueryContractError("EscalationRepository unavailable")

    return uow.escalations

def _to_views(escalations: Sequence[EscalationModel]) -> tuple[EscalationView, ...]:
    return tuple(_to_view(escalation) for escalation in escalations)

def _to_view(escalation: EscalationModel) -> EscalationView:
    if escalation.id is None:
        raise EscalationQueryContractError("Persisted escalation has no ID")

    return EscalationView(
        escalation_id=escalation.id,
        conversation_id=escalation.conversation_id,
        ai_run_id=escalation.ai_run_id,
        trigger_message_id=escalation.trigger_message_id,
        source=escalation.source,
        reason_code=escalation.reason_code,
        reason_summary=escalation.reason_summary,
        priority=escalation.priority,
        status=escalation.status,
        handoff_summary=escalation.handoff_summary,
        metadata=dict(escalation.metadata_),
        created_at=escalation.created_at,
        updated_at=escalation.updated_at,
        resolved_at=escalation.resolved_at,
    )