# AI-customer-support-agent\packages\application\tickets\query_tickets.py
from __future__ import annotations
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from packages.database.models.support.ticket import TicketModel
from packages.database.models.support.ticket_comment import TicketCommentModel
from packages.database.repositories.support.ticket_comment_repository import TicketCommentRepository
from packages.database.repositories.support.ticket_repository import TicketRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork,]
AUTHORIZED_REQUESTER_ROLES = frozenset({"customer", "support_agent", "admin",})

class TicketQueryError(RuntimeError):
    """Base application error for ticket queries."""

class TicketDoesNotExistError(TicketQueryError):
    def __init__(self, ticket_id: uuid.UUID) -> None:
        self.ticket_id = ticket_id
        super().__init__(f"Ticket does not exist: {ticket_id}")

class TicketRequesterDoesNotExistError(TicketQueryError):
    def __init__(self, requester_id: uuid.UUID) -> None:
        self.requester_id = requester_id
        super().__init__(f"Requester does not exist: {requester_id}")

class TicketRequesterNotActiveError(TicketQueryError):
    """Raised when a disabled or deleted user requests ticket data."""

class TicketRequesterRoleMismatchError(TicketQueryError):
    """Raised when the declared role does not match persisted user state."""

class TicketAccessDeniedError(TicketQueryError):
    """Raised when a requester cannot access the requested ticket data."""

class TicketQueryContractError(TicketQueryError):
    """Raised when Unit of Work wiring is incomplete."""

@dataclass(frozen=True, slots=True)
class TicketCommentView:
    """Detached ticket-comment representation."""
    comment_id: uuid.UUID
    ticket_id: uuid.UUID
    author_id: uuid.UUID | None
    author_role: str
    visibility: str
    content: str
    metadata: Mapping[str, Any]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class TicketView:
    """
    Detached ticket representation.

    `metadata` is empty for customer-facing queries because administrative metadata may contain internal routing information.
    """
    ticket_id: uuid.UUID
    ticket_number: int
    ticket_reference: str
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    source_message_id: uuid.UUID | None
    escalation_id: uuid.UUID | None
    assigned_agent_id: uuid.UUID | None
    source: str
    subject: str
    description: str
    category: str
    priority: str
    status: str
    resolution_summary: str | None
    metadata: Mapping[str, Any]
    row_version: int
    created_at: datetime
    updated_at: datetime
    assigned_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

@dataclass(frozen=True, slots=True)
class TicketDetail:
    """Ticket together with the comments visible to the requester."""
    ticket: TicketView
    comments: tuple[TicketCommentView, ...]

@dataclass(frozen=True, slots=True)
class GetTicketQuery:
    """Retrieve one ticket for an authenticated requester."""
    ticket_id: uuid.UUID
    requester_id: uuid.UUID
    requester_role: str
    def __post_init__(self) -> None:
        _validate_uuid(self.ticket_id, field_name="ticket_id")
        _validate_uuid(self.requester_id, field_name="requester_id")
        object.__setattr__(self, "requester_role", _normalize_requester_role(self.requester_role))

@dataclass(frozen=True, slots=True)
class ListTicketsQuery:
    """
    Retrieve customer-owned tickets or an agent/admin queue.

    Customer behavior:
    - results are always restricted to requester_id;
    - assignment filters are prohibited;
    - internal metadata is excluded.

    Agent/admin behavior:
    - active_only=True returns priority-ordered work;
    - active_only=False returns recent ticket history.
    """
    requester_id: uuid.UUID
    requester_role: str
    active_only: bool = False
    status: str | None = None
    priority: str | None = None
    category: str | None = None
    assigned_agent_id: uuid.UUID | None = None
    unassigned_only: bool = False
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        _validate_uuid(self.requester_id, field_name="requester_id")
        requester_role = _normalize_requester_role(self.requester_role)
        if not isinstance(self.active_only, bool):
            raise TypeError("active_only must be a boolean")

        if not isinstance(self.unassigned_only, bool):
            raise TypeError("unassigned_only must be a boolean")

        if self.assigned_agent_id is not None:
            _validate_uuid(self.assigned_agent_id, field_name="assigned_agent_id")

        if self.assigned_agent_id is not None and self.unassigned_only:
            raise ValueError("assigned_agent_id and unassigned_only=True cannot be combined")

        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer")

        if self.limit <= 0:
            raise ValueError("limit must be greater than zero")

        if self.limit > 200:
            raise ValueError("limit must not exceed 200")

        if isinstance(self.offset, bool) or not isinstance(self.offset, int):
            raise TypeError("offset must be an integer")

        if self.offset < 0:
            raise ValueError("offset must not be negative")

        status = _normalize_optional_text(self.status, field_name="status")
        priority = _normalize_optional_text(self.priority, field_name="priority")
        category = _normalize_optional_text(self.category, field_name="category")
        if self.active_only and status is not None:
            raise ValueError("status cannot be supplied when active_only=True")

        if requester_role == "customer":
            if self.assigned_agent_id is not None:
                raise TicketAccessDeniedError("Customers cannot filter tickets by assigned agent")

            if self.unassigned_only:
                raise TicketAccessDeniedError("Customers cannot request the unassigned support queue")

            if self.active_only:
                raise TicketAccessDeniedError("Customers cannot request the support work queue")

            if priority is not None:
                raise TicketAccessDeniedError("Customers cannot filter tickets by internal priority")

            if category is not None:
                raise TicketAccessDeniedError("Customers cannot filter tickets by internal category")

        object.__setattr__(self, "requester_role", requester_role)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "priority", priority)
        object.__setattr__(self, "category", category)

@dataclass(frozen=True, slots=True)
class TicketPage:
    """Offset-based ticket result page."""
    items: tuple[TicketView, ...]
    limit: int
    offset: int
    has_more: bool

    @property
    def count(self) -> int:
        return len(self.items)

class GetTicket:
    """Retrieve a ticket and requester-visible comment history."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, query: GetTicketQuery) -> TicketDetail:
        if not isinstance(query, GetTicketQuery):
            raise TypeError("query must be a GetTicketQuery")

        with self._uow_factory() as uow:
            tickets, comments = _require_repositories(uow)
            _validate_requester(requester_id=query.requester_id, requester_role=query.requester_role, uow=uow)
            ticket = tickets.get_by_id(query.ticket_id)
            if ticket is None:
                raise TicketDoesNotExistError(query.ticket_id)

            _authorize_ticket_access(ticket=ticket, requester_id=query.requester_id, requester_role=query.requester_role)
            include_internal = query.requester_role in {"support_agent", "admin"}
            comment_records = comments.list_for_ticket(ticket.id, include_internal=include_internal, limit=500)

            return TicketDetail(
                ticket=_to_ticket_view(ticket, include_metadata=include_internal),
                comments=tuple(_to_comment_view(comment, include_metadata=include_internal) for comment in comment_records)
            )

class ListTickets:
    """Retrieve a customer ticket list or operations queue."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, query: ListTicketsQuery) -> TicketPage:
        if not isinstance(query, ListTicketsQuery):
            raise TypeError("query must be a ListTicketsQuery")

        fetch_limit = query.limit + 1
        with self._uow_factory() as uow:
            tickets, _ = _require_repositories(uow)
            _validate_requester(requester_id=query.requester_id, requester_role=query.requester_role, uow=uow)
            include_metadata = query.requester_role in {"support_agent", "admin"}
            if query.requester_role == "customer":
                records = tickets.list_for_customer(query.requester_id, status=query.status, limit=fetch_limit, offset=query.offset)

            elif query.active_only:
                records = tickets.list_active_queue(
                    priority=query.priority,
                    category=query.category,
                    assigned_agent_id=query.assigned_agent_id,
                    unassigned_only=query.unassigned_only,
                    limit=fetch_limit,
                    offset=query.offset,
                )

            else:
                records = tickets.list_recent(
                    status=query.status,
                    priority=query.priority,
                    category=query.category,
                    assigned_agent_id=query.assigned_agent_id,
                    unassigned_only=query.unassigned_only,
                    limit=fetch_limit,
                    offset=query.offset,
                )

            has_more = len(records) > query.limit
            visible_records = records[:query.limit]

            return TicketPage(
                items=tuple(_to_ticket_view(ticket, include_metadata=include_metadata) for ticket in visible_records),
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

def _require_repositories(uow: SqlAlchemyUnitOfWork) -> tuple[TicketRepository, TicketCommentRepository,]:
    if uow.session is None:
        raise TicketQueryContractError("Active SQLAlchemy Session unavailable")

    if uow.tickets is None:
        raise TicketQueryContractError("TicketRepository unavailable")

    if uow.ticket_comments is None:
        raise TicketQueryContractError("TicketCommentRepository unavailable")

    if uow.users is None:
        raise TicketQueryContractError("UserRepository unavailable")

    return (uow.tickets, uow.ticket_comments,)

def _validate_requester(*, requester_id: uuid.UUID, requester_role: str, uow: SqlAlchemyUnitOfWork) -> None:
    if uow.users is None:
        raise TicketQueryContractError("UserRepository unavailable")

    requester = uow.users.get_by_id(requester_id)
    if requester is None:
        raise TicketRequesterDoesNotExistError(requester_id)

    if requester.status != "active":
        raise TicketRequesterNotActiveError(f"Requester {requester_id} is not active: status={requester.status!r}")

    if requester.role != requester_role:
        raise TicketRequesterRoleMismatchError(f"Declared requester role {requester_role!r} does not match persisted role {requester.role!r}")

def _authorize_ticket_access(*, ticket: TicketModel, requester_id: uuid.UUID, requester_role: str) -> None:
    if requester_role in {"support_agent", "admin",}:
        return

    if requester_role == "customer" and ticket.customer_id == requester_id:
        return

    raise TicketAccessDeniedError(f"Requester {requester_id} cannot access ticket {ticket.id}")

def _to_ticket_view(ticket: TicketModel, *, include_metadata: bool) -> TicketView:
    if ticket.id is None:
        raise TicketQueryContractError("Persisted ticket has no ID")

    if ticket.ticket_number is None:
        raise TicketQueryContractError("Persisted ticket has no ticket number")

    metadata = dict(ticket.metadata_) if include_metadata else {}
    return TicketView(
        ticket_id=ticket.id,
        ticket_number=ticket.ticket_number,
        ticket_reference=f"TKT-{ticket.ticket_number:08d}",
        conversation_id=ticket.conversation_id,
        customer_id=ticket.customer_id,
        source_message_id=ticket.source_message_id,
        escalation_id=ticket.escalation_id,
        assigned_agent_id=ticket.assigned_agent_id,
        source=ticket.source,
        subject=ticket.subject,
        description=ticket.description,
        category=ticket.category,
        priority=ticket.priority,
        status=ticket.status,
        resolution_summary=ticket.resolution_summary,
        metadata=metadata,
        row_version=ticket.row_version,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        assigned_at=ticket.assigned_at,
        resolved_at=ticket.resolved_at,
        closed_at=ticket.closed_at,
    )

def _to_comment_view(comment: TicketCommentModel, *, include_metadata: bool) -> TicketCommentView:
    if comment.id is None:
        raise TicketQueryContractError("Persisted ticket comment has no ID")

    metadata = dict(comment.metadata_) if include_metadata else {}
    return TicketCommentView(
        comment_id=comment.id,
        ticket_id=comment.ticket_id,
        author_id=comment.author_id,
        author_role=comment.author_role,
        visibility=comment.visibility,
        content=comment.content,
        metadata=metadata,
        created_at=comment.created_at,
    )

def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
    if not isinstance(value, uuid.UUID):
        raise TypeError(f"{field_name} must be a UUID")

def _normalize_requester_role(role: str) -> str:
    if not isinstance(role, str):
        raise TypeError("requester_role must be a string")

    normalized = role.strip().lower()
    if normalized not in AUTHORIZED_REQUESTER_ROLES:
        expected = ", ".join(sorted(AUTHORIZED_REQUESTER_ROLES))
        raise ValueError(f"requester_role must be one of: {expected}")

    return normalized

def _normalize_optional_text(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")

    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} cannot be blank")

    return normalized