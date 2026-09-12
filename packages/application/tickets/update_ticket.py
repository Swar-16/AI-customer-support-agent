# AI-customer-support-agent\packages\application\tickets\update_ticket.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final
from sqlalchemy.orm.exc import StaleDataError
from typing import Any

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.database.models.support.ticket import TicketModel
from packages.database.repositories.support.ticket_repository import TicketRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork,]
Clock = Callable[[], datetime]
VALID_TICKET_STATUSES: Final[frozenset[str]] = frozenset({"open", "in_progress", "waiting_for_customer", "resolved", "closed", "reopened",})
VALID_TICKET_PRIORITIES: Final[frozenset[str]] = frozenset({"low", "normal", "high", "urgent",})
VALID_TICKET_CATEGORIES: Final[frozenset[str]] = frozenset({"billing", "refund", "order", "account", "technical", "security", "product", "general", "other",})
ALLOWED_TICKET_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "open": frozenset({"in_progress", "waiting_for_customer", "resolved",}),
    "in_progress": frozenset({"waiting_for_customer", "resolved",}),
    "waiting_for_customer": frozenset({"in_progress", "resolved",}),
    "resolved": frozenset({"closed", "reopened",}),
    "closed": frozenset({"reopened",}),
    "reopened": frozenset({"in_progress", "waiting_for_customer", "resolved",}),
}
MAX_RESOLUTION_SUMMARY_LENGTH: Final[int] = 5_000
TICKET_UPDATE_ROLES: Final[frozenset[AuthRole]] = frozenset({AuthRole.SUPPORT_AGENT, AuthRole.ADMIN,})

class UpdateTicketError(RuntimeError):
    """Base application error for ticket mutations."""

class TicketDoesNotExistError(UpdateTicketError):
    def __init__(self, ticket_id: uuid.UUID) -> None:
        self.ticket_id = ticket_id
        super().__init__(f"Ticket does not exist: {ticket_id}")
        
class TicketUpdateAccessDeniedError(UpdateTicketError):
    """Raised when the authenticated principal cannot update tickets."""

class InvalidTicketTransitionError(UpdateTicketError):
    def __init__(self, *, ticket_id: uuid.UUID, current_status: str, target_status: str) -> None:
        self.ticket_id = ticket_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(f"Invalid ticket transition for {ticket_id}: {current_status!r} -> {target_status!r}")

class TicketAgentDoesNotExistError(UpdateTicketError):
    def __init__(self, agent_id: uuid.UUID) -> None:
        self.agent_id = agent_id
        super().__init__(f"Support agent does not exist: {agent_id}")

class TicketAgentNotAssignableError(UpdateTicketError):
    """Raised when a user cannot be assigned support work."""

class TicketConcurrencyError(UpdateTicketError):
    """Raised when the caller updates a stale ticket version."""
    def __init__(self, *, ticket_id: uuid.UUID, expected_version: int, actual_version: int | None = None) -> None:
        self.ticket_id = ticket_id
        self.expected_version = expected_version
        self.actual_version = actual_version

        detail = f", actual version is {actual_version}" if actual_version is not None else ""
        super().__init__(f"Ticket {ticket_id} was modified concurrently; expected version {expected_version}{detail}")

class ClosedTicketMutationError(UpdateTicketError):
    """Raised when a closed ticket is changed without reopening it."""

class TicketPersistenceContractError(UpdateTicketError):
    """Raised when Unit of Work wiring is incomplete."""

@dataclass(frozen=True, slots=True)
class UpdateTicketCommand:
    """
    Controlled ticket mutation.

    `expected_row_version` is required for optimistic concurrency.

    Assignment semantics:
    - assigned_agent_id=<UUID> assigns/reassigns;
    - unassign=True removes the current assignee;
    - neither leaves assignment unchanged.

    Resolution semantics:
    - target_status="resolved" requires resolution_summary;
    - reopening clears resolution and closure information;
    - closing is permitted only from resolved and retains its resolution.
    """
    ticket_id: uuid.UUID
    expected_row_version: int
    principal: AuthenticatedPrincipal
    trace_id: uuid.UUID
    target_status: str | None = None
    priority: str | None = None
    category: str | None = None
    assigned_agent_id: uuid.UUID | None = None
    unassign: bool = False
    resolution_summary: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ticket_id, uuid.UUID):
            raise TypeError("ticket_id must be a UUID")
        
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if self.principal.role not in TICKET_UPDATE_ROLES:
            raise TicketUpdateAccessDeniedError("Only support agents and administrators may update tickets")

        if not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID")

        if isinstance(self.expected_row_version, bool) or not isinstance(self.expected_row_version, int):
            raise TypeError("expected_row_version must be an integer")

        if self.expected_row_version <= 0:
            raise ValueError("expected_row_version must be greater than zero")

        if not isinstance(self.unassign, bool):
            raise TypeError("unassign must be a boolean")

        if self.assigned_agent_id is not None:
            if not isinstance(self.assigned_agent_id, uuid.UUID):
                raise TypeError("assigned_agent_id must be a UUID or None")

        if self.assigned_agent_id is not None and self.unassign:
            raise ValueError("assigned_agent_id and unassign=True cannot be combined")

        target_status = self._normalize_optional_choice(self.target_status, field_name="target_status", valid_values=VALID_TICKET_STATUSES)
        priority = self._normalize_optional_choice(self.priority, field_name="priority", valid_values=VALID_TICKET_PRIORITIES)
        category = self._normalize_optional_choice(self.category, field_name="category", valid_values=VALID_TICKET_CATEGORIES)
        resolution_summary = self._normalize_optional_text(self.resolution_summary, field_name="resolution_summary", max_length=MAX_RESOLUTION_SUMMARY_LENGTH)
        if target_status == "resolved" and resolution_summary is None:
            raise ValueError("resolution_summary is required when target_status='resolved'")

        if target_status != "resolved" and resolution_summary is not None:
            raise ValueError("resolution_summary may only be supplied when target_status='resolved'")

        has_mutation = any((target_status is not None, priority is not None, category is not None, self.assigned_agent_id is not None, self.unassign,))
        if not has_mutation:
            raise ValueError("At least one ticket mutation must be requested")

        object.__setattr__(self, "target_status", target_status)
        object.__setattr__(self, "priority", priority)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "resolution_summary", resolution_summary)

    @staticmethod
    def _normalize_optional_choice(value: str | None, *, field_name: str, valid_values: frozenset[str]) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip().lower()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        if normalized not in valid_values:
            expected = ", ".join(sorted(valid_values))

            raise ValueError(f"{field_name} must be one of: {expected}")

        return normalized

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str, max_length: int) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = " ".join(value.split())
        if not normalized:
            return None

        if len(normalized) > max_length:
            raise ValueError(f"{field_name} exceeds {max_length} characters")

        return normalized


@dataclass(frozen=True, slots=True)
class UpdateTicketResult:
    """Detached ticket state returned after commit."""
    ticket_id: uuid.UUID
    ticket_number: int
    ticket_reference: str
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    previous_status: str
    current_status: str
    priority: str
    category: str
    assigned_agent_id: uuid.UUID | None
    resolution_summary: str | None
    row_version: int
    assigned_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    updated_at: datetime
    changed: bool

class UpdateTicket:
    """
    Apply a controlled ticket mutation.

    A row lock protects lifecycle validation, while row_version protects clients from overwriting a state they did not retrieve.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock | None = None) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable or None")

        self._uow_factory = uow_factory
        self._clock = clock if clock is not None else self._utc_now

    def execute(self, command: UpdateTicketCommand) -> UpdateTicketResult:
        if not isinstance(command, UpdateTicketCommand):
            raise TypeError("command must be an UpdateTicketCommand")

        try:
            with self._uow_factory() as uow:
                ticket_repository, audit_repository = self._require_repositories(uow)
                ticket = ticket_repository.get_by_id_for_update(command.ticket_id)
                if ticket is None:
                    raise TicketDoesNotExistError(command.ticket_id)

                if ticket.row_version != command.expected_row_version:
                    raise TicketConcurrencyError(
                        ticket_id=ticket.id,
                        expected_version=command.expected_row_version,
                        actual_version=ticket.row_version,
                    )

                self._validate_closed_ticket_mutation(ticket=ticket, command=command)
                before_state = self._audit_state(ticket)
                occurred_at = self._clock()
                self._validate_clock_value(occurred_at)
                previous_status = ticket.status
                changed = self._apply_mutations(ticket=ticket, command=command, occurred_at=occurred_at, uow=uow)
                if changed:
                    ticket.updated_at = occurred_at
                    uow.flush()

                    AuditRecorder(repository=audit_repository).record(
                        RecordAuditEventCommand(
                            event_type="ticket.updated",
                            entity_type="ticket",
                            entity_id=ticket.id,
                            action="updated",
                            actor=AuditActor(actor_type=self._audit_actor_type(command.principal.role), actor_id=command.principal.user_id),
                            trace_id=command.trace_id,
                            conversation_id=ticket.conversation_id,
                            before_state=before_state,
                            after_state=self._audit_state(ticket),
                            metadata={
                                "ticket_number": ticket.ticket_number,
                                "expected_row_version": command.expected_row_version,
                            },
                            occurred_at=occurred_at,
                        )
                    )

                result = self._to_result(ticket=ticket, previous_status=previous_status, changed=changed)
                uow.commit()
                return result

        except StaleDataError as exc:
            raise TicketConcurrencyError(ticket_id=command.ticket_id, expected_version=command.expected_row_version) from exc

    @staticmethod
    def _apply_mutations(*, ticket: TicketModel, command: UpdateTicketCommand, occurred_at: datetime, uow: SqlAlchemyUnitOfWork) -> bool:
        changed = False
        if command.priority is not None and command.priority != ticket.priority:
            ticket.priority = command.priority
            changed = True

        if command.category is not None and command.category != ticket.category:
            ticket.category = command.category
            changed = True

        if command.assigned_agent_id is not None:
            UpdateTicket._validate_agent(agent_id=command.assigned_agent_id, uow=uow)
            if ticket.assigned_agent_id != command.assigned_agent_id:
                ticket.assigned_agent_id = command.assigned_agent_id
                ticket.assigned_at = occurred_at
                changed = True

        elif command.unassign:
            if ticket.assigned_agent_id is not None:
                ticket.assigned_agent_id = None
                # Preserve assigned_at as historical information. The database constraint intentionally permits this.
                changed = True

        if command.target_status is not None and command.target_status != ticket.status:
            UpdateTicket._validate_transition(
                ticket_id=ticket.id,
                current_status=ticket.status,
                target_status=command.target_status,
            )

            UpdateTicket._apply_status_transition(
                ticket=ticket,
                target_status=command.target_status,
                resolution_summary=command.resolution_summary,
                occurred_at=occurred_at,
            )

            changed = True

        return changed

    @staticmethod
    def _validate_agent(*, agent_id: uuid.UUID, uow: SqlAlchemyUnitOfWork) -> None:
        if uow.users is None:
            raise TicketPersistenceContractError("UserRepository unavailable")

        agent = uow.users.get_by_id(agent_id)
        if agent is None:
            raise TicketAgentDoesNotExistError(agent_id)

        if agent.status != "active":
            raise TicketAgentNotAssignableError(f"User {agent_id} is not active: status={agent.status!r}")

        if agent.role not in {"support_agent", "admin",}:
            raise TicketAgentNotAssignableError(f"User {agent_id} cannot be assigned tickets: role={agent.role!r}")

    @staticmethod
    def _validate_transition(*, ticket_id: uuid.UUID, current_status: str, target_status: str) -> None:
        allowed_targets = ALLOWED_TICKET_TRANSITIONS.get(current_status)
        if allowed_targets is None or target_status not in allowed_targets:
            raise InvalidTicketTransitionError(
                ticket_id=ticket_id,
                current_status=current_status,
                target_status=target_status,
            )

    @staticmethod
    def _apply_status_transition(*, ticket: TicketModel, target_status: str, resolution_summary: str | None, occurred_at: datetime) -> None:
        current_status = ticket.status
        if target_status == "resolved":
            if resolution_summary is None:
                raise TicketPersistenceContractError("Resolved transition has no resolution summary")

            ticket.status = "resolved"
            ticket.resolution_summary = resolution_summary
            ticket.resolved_at = occurred_at
            ticket.closed_at = None
            return

        if target_status == "closed":
            if current_status != "resolved":
                raise TicketPersistenceContractError("Only a resolved ticket can be closed")

            if ticket.resolved_at is None or ticket.resolution_summary is None:
                raise TicketPersistenceContractError("Resolved ticket is missing resolution information")

            ticket.status = "closed"
            ticket.closed_at = occurred_at
            return

        if target_status == "reopened":
            ticket.status = "reopened"
            ticket.resolution_summary = None
            ticket.resolved_at = None
            ticket.closed_at = None
            return

        ticket.status = target_status
        ticket.resolution_summary = None
        ticket.resolved_at = None
        ticket.closed_at = None

    @staticmethod
    def _validate_closed_ticket_mutation(*, ticket: TicketModel, command: UpdateTicketCommand) -> None:
        if ticket.status != "closed":
            return

        if command.target_status != "reopened":
            raise ClosedTicketMutationError(f"Closed ticket {ticket.id} must be reopened before it can be modified")

        # Reopening may be combined with assignment, priority, or category updates in the same atomic command.

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> tuple[TicketRepository, AuditEventRepository]:
        if uow.session is None:
            raise TicketPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.tickets is None:
            raise TicketPersistenceContractError("TicketRepository unavailable")

        if uow.users is None:
            raise TicketPersistenceContractError("UserRepository unavailable")

        if uow.audit_events is None:
            raise TicketPersistenceContractError("AuditEventRepository unavailable")

        return uow.tickets, uow.audit_events
    
    @staticmethod
    def _audit_actor_type(role: AuthRole) -> AuditActorType:
        if role is AuthRole.SUPPORT_AGENT:
            return AuditActorType.AGENT

        if role is AuthRole.ADMIN:
            return AuditActorType.ADMIN

        raise TicketUpdateAccessDeniedError("Only support agents and administrators may update tickets")
    
    @staticmethod
    def _audit_state(ticket: TicketModel) -> dict[str, Any]:
        return {
            "status": ticket.status,
            "priority": ticket.priority,
            "category": ticket.category,
            "assigned_agent_id": str(ticket.assigned_agent_id) if ticket.assigned_agent_id is not None else None,
            "resolution_summary": ticket.resolution_summary,
            "row_version": ticket.row_version,
            "assigned_at": ticket.assigned_at.isoformat() if ticket.assigned_at is not None else None,
            "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at is not None else None,
            "closed_at": ticket.closed_at.isoformat() if ticket.closed_at is not None else None,
        }

    @staticmethod
    def _to_result(*, ticket: TicketModel, previous_status: str, changed: bool) -> UpdateTicketResult:
        if ticket.id is None:
            raise TicketPersistenceContractError("Persisted ticket has no ID")

        if ticket.ticket_number is None:
            raise TicketPersistenceContractError("Persisted ticket has no ticket number")

        return UpdateTicketResult(
            ticket_id=ticket.id,
            ticket_number=ticket.ticket_number,
            ticket_reference=f"TKT-{ticket.ticket_number:08d}",
            conversation_id=ticket.conversation_id,
            customer_id=ticket.customer_id,
            previous_status=previous_status,
            current_status=ticket.status,
            priority=ticket.priority,
            category=ticket.category,
            assigned_agent_id=ticket.assigned_agent_id,
            resolution_summary=ticket.resolution_summary,
            row_version=ticket.row_version,
            assigned_at=ticket.assigned_at,
            resolved_at=ticket.resolved_at,
            closed_at=ticket.closed_at,
            updated_at=ticket.updated_at,
            changed=changed,
        )

    @staticmethod
    def _validate_clock_value(value: datetime) -> None:
        if not isinstance(value, datetime):
            raise TypeError("clock must return a datetime")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)