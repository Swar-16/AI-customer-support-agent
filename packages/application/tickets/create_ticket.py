# AI-customer-support-agent\packages\application\tickets\create_ticket.py
from __future__ import annotations
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Mapping

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.database.models.support.ticket import TicketModel
from packages.database.repositories.support.escalation_repository import EscalationRepository
from packages.database.repositories.support.ticket_repository import TicketRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
VALID_TICKET_SOURCES: Final[frozenset[str]] = frozenset({"customer", "escalation", "agent","system",})
VALID_TICKET_CATEGORIES: Final[frozenset[str]] = frozenset({"billing", "refund", "order", "account", "technical", "security", "product", "general", "other",})
VALID_TICKET_PRIORITIES: Final[frozenset[str]] = frozenset({"low", "normal", "high", "urgent",})
MAX_SUBJECT_LENGTH: Final[int] = 300
MAX_DESCRIPTION_LENGTH: Final[int] = 20_000
MAX_METADATA_KEYS: Final[int] = 100
MAX_METADATA_SERIALIZED_LENGTH: Final[int] = 20_000

class CreateTicketError(RuntimeError):
    """Base application error for ticket creation."""
    
class TicketCreationAccessDeniedError(CreateTicketError):
    """Raised when a caller attempts an unauthorized creation path."""

class TicketConversationDoesNotExistError(CreateTicketError):
    def __init__(self, conversation_id: uuid.UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation does not exist: {conversation_id}")

class TicketCustomerDoesNotExistError(CreateTicketError):
    def __init__(self, customer_id: uuid.UUID) -> None:
        self.customer_id = customer_id
        super().__init__(f"Customer does not exist: {customer_id}")

class TicketCustomerNotActiveError(CreateTicketError):
    def __init__(self, customer_id: uuid.UUID, *, status: str) -> None:
        self.customer_id = customer_id
        self.status = status
        super().__init__(f"Customer {customer_id} is not active: status={status!r}")

class TicketConversationOwnershipError(CreateTicketError):
    """Raised when the supplied customer does not own the conversation."""

class TicketSourceMessageDoesNotExistError(CreateTicketError):
    def __init__(self, message_id: uuid.UUID) -> None:
        self.message_id = message_id
        super().__init__(f"Source message does not exist: {message_id}")

class TicketSourceMessageMismatchError(CreateTicketError):
    """Raised when the source message belongs to another conversation."""

class TicketEscalationDoesNotExistError(CreateTicketError):
    def __init__(self, escalation_id: uuid.UUID) -> None:
        self.escalation_id = escalation_id
        super().__init__(f"Escalation does not exist: {escalation_id}")

class TicketEscalationMismatchError(CreateTicketError):
    """Raised when an escalation belongs to another conversation."""

class TicketEscalationNotActiveError(CreateTicketError):
    """Raised when a terminal escalation is used to create a new ticket."""

class TicketIdempotencyConflictError(CreateTicketError):
    """Raised when an existing escalation-linked ticket conflicts with the requested ticket provenance."""

class TicketPersistenceContractError(CreateTicketError):
    """Raised when Unit of Work wiring or generated persistence state is incomplete."""

@dataclass(frozen=True, slots=True)
class CreateTicketCommand:
    """
    Create a ticket through either an authenticated or internal path.

    Authenticated paths:
    - customer: customer_id and source are derived from the principal;
    - support agent/admin: source is derived as "agent", while
      customer_id identifies the customer receiving support.

    Internal paths:
    - principal=None permits only "escalation" and "system".
    """
    conversation_id: uuid.UUID
    subject: str
    description: str
    principal: AuthenticatedPrincipal | None = None
    trace_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    source: str | None = None
    category: str = "general"
    priority: str = "normal"
    source_message_id: uuid.UUID | None = None
    escalation_id: uuid.UUID | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_uuid(self.conversation_id, field_name="conversation_id")
        if self.trace_id is not None:
            self._validate_uuid(self.trace_id, field_name="trace_id")

        if self.customer_id is not None:
            self._validate_uuid(self.customer_id, field_name="customer_id")

        if self.source_message_id is not None:
            self._validate_uuid(self.source_message_id, field_name="source_message_id")

        if self.escalation_id is not None:
            self._validate_uuid(self.escalation_id, field_name="escalation_id")

        if self.principal is not None and not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal or None")

        customer_id, source = self._resolve_creation_identity()
        category = self._normalize_choice(self.category, field_name="category", valid_values=VALID_TICKET_CATEGORIES)
        priority = self._normalize_choice(self.priority, field_name="priority", valid_values=VALID_TICKET_PRIORITIES)
        subject = self._normalize_text(self.subject, field_name="subject", max_length=MAX_SUBJECT_LENGTH)
        description = self._normalize_text(self.description, field_name="description", max_length=MAX_DESCRIPTION_LENGTH)
        if source == "escalation" and self.escalation_id is None:
            raise ValueError("escalation_id is required when source='escalation'")

        if source != "escalation" and self.escalation_id is not None:
            raise ValueError("escalation_id may only be supplied when source='escalation'")

        metadata = self._normalize_metadata(self.metadata)
        object.__setattr__(self, "customer_id", customer_id)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "priority", priority)
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "metadata", MappingProxyType(metadata))

    def _resolve_creation_identity(self) -> tuple[uuid.UUID, str]:
        principal = self.principal
        if principal is None:
            if self.customer_id is None:
                raise ValueError("customer_id is required for internal ticket creation")

            if self.source is None:
                raise ValueError("source is required for internal ticket creation")

            source = self._normalize_choice(self.source, field_name="source", valid_values=VALID_TICKET_SOURCES)
            if source not in {"escalation", "system"}:
                raise TicketCreationAccessDeniedError("Unauthenticated internal ticket creation permits only escalation or system sources")

            return self.customer_id, source

        if self.trace_id is None:
            raise ValueError("trace_id is required for authenticated ticket creation")

        if principal.role is AuthRole.CUSTOMER:
            if self.customer_id is not None and self.customer_id != principal.user_id:
                raise TicketCreationAccessDeniedError("Customers cannot create tickets for another user")

            if self.source is not None:
                supplied_source = self._normalize_choice(self.source, field_name="source", valid_values=VALID_TICKET_SOURCES)
                if supplied_source != "customer":
                    raise TicketCreationAccessDeniedError("Customers may create only customer-source tickets")

            return principal.user_id, "customer"

        if principal.role in {AuthRole.SUPPORT_AGENT, AuthRole.ADMIN,}:
            if self.customer_id is None:
                raise ValueError("customer_id is required when staff create a ticket")

            if self.source is not None:
                supplied_source = self._normalize_choice(self.source, field_name="source", valid_values=VALID_TICKET_SOURCES)
                if supplied_source != "agent":
                    raise TicketCreationAccessDeniedError("Authenticated staff may create only agent-source tickets")

            return self.customer_id, "agent"

        raise TicketCreationAccessDeniedError("Authenticated role cannot create support tickets")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _normalize_choice(value: str, *, field_name: str, valid_values: frozenset[str]) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = value.strip().lower()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        if normalized not in valid_values:
            expected = ", ".join(sorted(valid_values))
            raise ValueError(f"{field_name} must be one of: {expected}")

        return normalized

    @staticmethod
    def _normalize_text(value: str, *, field_name: str, max_length: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        if len(normalized) > max_length:
            raise ValueError(f"{field_name} exceeds {max_length} characters")

        return normalized

    @staticmethod
    def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping")

        if len(metadata) > MAX_METADATA_KEYS:
            raise ValueError("metadata contains too many keys")

        normalized: dict[str, Any] = {}
        for key, value in metadata.items():
            if not isinstance(key, str):
                raise TypeError("metadata keys must be strings")

            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError("metadata keys cannot be blank")

            if normalized_key in normalized:
                raise ValueError("metadata contains duplicate keys after normalization")

            normalized[normalized_key] = value

        try:
            serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must contain only JSON-serializable values") from exc

        if len(serialized) > MAX_METADATA_SERIALIZED_LENGTH:
            raise ValueError(f"serialized metadata exceeds {MAX_METADATA_SERIALIZED_LENGTH} characters")

        return normalized

@dataclass(frozen=True, slots=True)
class CreateTicketResult:
    """Detached result returned after ticket persistence."""
    ticket_id: uuid.UUID
    ticket_number: int
    ticket_reference: str
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    escalation_id: uuid.UUID | None
    status: str
    priority: str
    category: str
    created: bool

@dataclass(frozen=True, slots=True)
class _TicketRepositories:
    tickets: TicketRepository
    escalations: EscalationRepository
    audit_events: AuditEventRepository

class CreateTicket:
    """
    Create a customer, escalation, agent, or system ticket.

    `execute()` owns a new Unit of Work for standalone API operations.

    `execute_in_uow()` reuses an already-active Unit of Work. This is required when converting an escalation
    into a ticket inside the same transaction as the originating AI run.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def execute(self, command: CreateTicketCommand) -> CreateTicketResult:
        """Create and commit a standalone ticket."""
        self._validate_command(command)
        with self._uow_factory() as uow:
            result = self.execute_in_uow(command=command, uow=uow)
            uow.commit()

            return result

    def execute_in_uow(self, *, command: CreateTicketCommand, uow: SqlAlchemyUnitOfWork) -> CreateTicketResult:
        """
        Create a ticket inside an existing transaction.

        This method flushes but never commits.
        """
        self._validate_command(command)
        repositories = self._require_repositories(uow)
        conversation = uow.conversations.get_by_id(command.conversation_id)
        if conversation is None:
            raise TicketConversationDoesNotExistError(command.conversation_id)

        customer = uow.users.get_by_id(command.customer_id)
        if customer is None:
            raise TicketCustomerDoesNotExistError(command.customer_id)

        if customer.status != "active":
            raise TicketCustomerNotActiveError(command.customer_id, status=customer.status)

        if customer.role != "customer":
            raise TicketConversationOwnershipError(f"User {command.customer_id} is not a customer")

        if conversation.user_id != command.customer_id:
            raise TicketConversationOwnershipError(f"Customer {command.customer_id} does not own conversation {command.conversation_id}")

        self._validate_source_message(command=command, uow=uow)
        existing = self._validate_escalation(command=command, repositories=repositories)
        if existing is not None:
            return self._existing_result(ticket=existing, command=command)

        ticket = TicketModel(
            conversation_id=command.conversation_id,
            customer_id=command.customer_id,
            source_message_id=command.source_message_id,
            escalation_id=command.escalation_id,
            assigned_agent_id=None,
            source=command.source,
            subject=command.subject,
            description=command.description,
            category=command.category,
            priority=command.priority,
            status="open",
            resolution_summary=None,
            metadata_=dict(command.metadata),
            assigned_at=None,
            resolved_at=None,
            closed_at=None,
        )

        repositories.tickets.add(ticket)
        repositories.tickets.flush()
        
        if ticket.id is None:
            raise TicketPersistenceContractError("Ticket ID was not generated after flush")

        AuditRecorder(repository=repositories.audit_events).record(
            RecordAuditEventCommand(
                event_type="ticket.created",
                entity_type="ticket",
                entity_id=ticket.id,
                action="created",
                actor=self._resolve_audit_actor(command),
                trace_id=command.trace_id,
                conversation_id=ticket.conversation_id,
                before_state=None,
                after_state={
                    "status": ticket.status,
                    "priority": ticket.priority,
                    "category": ticket.category,
                    "source": ticket.source,
                    "assigned_agent_id": str(ticket.assigned_agent_id) if ticket.assigned_agent_id is not None else None,
                    "escalation_id": str(ticket.escalation_id) if ticket.escalation_id is not None else None,
                },
                metadata={
                    "ticket_number": ticket.ticket_number,
                    "source_message_id": str(ticket.source_message_id) if ticket.source_message_id is not None else None,
                },
            )
        )

        return self._to_result(ticket=ticket, created=True)

    @staticmethod
    def _validate_command(command: CreateTicketCommand) -> None:
        if not isinstance(command, CreateTicketCommand):
            raise TypeError("command must be a CreateTicketCommand")

    @staticmethod
    def _validate_source_message(*, command: CreateTicketCommand, uow: SqlAlchemyUnitOfWork) -> None:
        if command.source_message_id is None:
            return

        if uow.messages is None:
            raise TicketPersistenceContractError("MessageRepository unavailable")

        message = uow.messages.get_by_id(command.source_message_id)
        if message is None:
            raise TicketSourceMessageDoesNotExistError(command.source_message_id)

        if message.conversation_id != command.conversation_id:
            raise TicketSourceMessageMismatchError(f"Message {command.source_message_id} does not belong to conversation {command.conversation_id}")

    @staticmethod
    def _validate_escalation(*, command: CreateTicketCommand, repositories: _TicketRepositories) -> TicketModel | None:
        if command.escalation_id is None:
            return None

        existing_ticket = repositories.tickets.get_by_escalation_id(command.escalation_id)
        if existing_ticket is not None:
            return existing_ticket

        escalation = repositories.escalations.get_by_id(command.escalation_id)
        if escalation is None:
            raise TicketEscalationDoesNotExistError(command.escalation_id)

        if escalation.conversation_id != command.conversation_id:
            raise TicketEscalationMismatchError(f"Escalation {command.escalation_id} does not belong to conversation {command.conversation_id}")

        if escalation.status not in {"open", "in_review",}:
            raise TicketEscalationNotActiveError(f"Escalation {command.escalation_id} is not active: status={escalation.status!r}")

        return None

    @staticmethod
    def _existing_result(*, ticket: TicketModel, command: CreateTicketCommand) -> CreateTicketResult:
        conflicts: list[str] = []
        if ticket.conversation_id != command.conversation_id:
            conflicts.append("conversation_id")

        if ticket.customer_id != command.customer_id:
            conflicts.append("customer_id")

        if ticket.source != command.source:
            conflicts.append("source")

        if ticket.source_message_id != command.source_message_id:
            conflicts.append("source_message_id")

        if conflicts:
            fields = ", ".join(conflicts)

            raise TicketIdempotencyConflictError(f"Existing ticket for escalation {command.escalation_id} conflicts on: {fields}")

        return CreateTicket._to_result(ticket=ticket, created=False)

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> _TicketRepositories:
        if uow.session is None:
            raise TicketPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.users is None:
            raise TicketPersistenceContractError("UserRepository unavailable")

        if uow.conversations is None:
            raise TicketPersistenceContractError("ConversationRepository unavailable")

        if uow.messages is None:
            raise TicketPersistenceContractError("MessageRepository unavailable")

        if uow.escalations is None:
            raise TicketPersistenceContractError("EscalationRepository unavailable")

        if uow.tickets is None:
            raise TicketPersistenceContractError("TicketRepository unavailable")
        
        if uow.audit_events is None:
            raise TicketPersistenceContractError("AuditEventRepository unavailable")

        return _TicketRepositories(tickets=uow.tickets, escalations=uow.escalations, audit_events=uow.audit_events)

    @staticmethod
    def _to_result(*, ticket: TicketModel, created: bool) -> CreateTicketResult:
        if ticket.id is None:
            raise TicketPersistenceContractError("Ticket ID was not generated after flush")

        if ticket.ticket_number is None:
            raise TicketPersistenceContractError("Ticket number was not generated after flush")

        return CreateTicketResult(
            ticket_id=ticket.id,
            ticket_number=ticket.ticket_number,
            ticket_reference=f"TKT-{ticket.ticket_number:08d}",
            conversation_id=ticket.conversation_id,
            customer_id=ticket.customer_id,
            escalation_id=ticket.escalation_id,
            status=ticket.status,
            priority=ticket.priority,
            category=ticket.category,
            created=created,
        )
        
    @staticmethod
    def _resolve_audit_actor(command: CreateTicketCommand) -> AuditActor:
        principal = command.principal
        if principal is None:
            return AuditActor(actor_type=AuditActorType.SYSTEM,)

        actor_types = {
            AuthRole.CUSTOMER: AuditActorType.CUSTOMER,
            AuthRole.SUPPORT_AGENT: AuditActorType.AGENT,
            AuthRole.ADMIN: AuditActorType.ADMIN,
        }

        actor_type = actor_types.get(principal.role)
        if actor_type is None:
            raise TicketCreationAccessDeniedError("Authenticated role cannot create support tickets")

        return AuditActor(actor_type=actor_type, actor_id=principal.user_id)