# AI-customer-support-agent\packages\application\tickets\add_ticket_comment.py
from __future__ import annotations
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Mapping

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.database.models.support.ticket_comment import TicketCommentModel
from packages.database.repositories.support.ticket_comment_repository import TicketCommentRepository
from packages.database.repositories.support.ticket_repository import TicketRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork,]
VALID_COMMENT_VISIBILITIES: Final[frozenset[str]] = frozenset({"customer", "internal",})
COMMENTABLE_TICKET_STATUSES: Final[frozenset[str]] = frozenset({"open", "in_progress", "waiting_for_customer", "reopened",})
MAX_COMMENT_LENGTH: Final[int] = 20_000
MAX_METADATA_KEYS: Final[int] = 100
MAX_METADATA_SERIALIZED_LENGTH: Final[int] = 20_000

class AddTicketCommentError(RuntimeError):
    """Base application error for adding ticket comments."""

class CommentTicketDoesNotExistError(AddTicketCommentError):
    def __init__(self, ticket_id: uuid.UUID) -> None:
        self.ticket_id = ticket_id
        super().__init__(f"Ticket does not exist: {ticket_id}")

class CommentAuthorDoesNotExistError(AddTicketCommentError):
    def __init__(self, author_id: uuid.UUID) -> None:
        self.author_id = author_id
        super().__init__(f"Comment author does not exist: {author_id}")

class CommentAuthorNotActiveError(AddTicketCommentError):
    """Raised when a disabled or deleted user attempts to comment."""

class CommentAuthorRoleMismatchError(AddTicketCommentError):
    """Raised when the declared author role does not match persisted identity."""

class TicketCommentOwnershipError(AddTicketCommentError):
    """Raised when a customer attempts to comment on another customer's ticket."""

class CustomerInternalCommentError(AddTicketCommentError):
    """Raised when a customer attempts to create an internal support note."""

class TicketNotCommentableError(AddTicketCommentError):
    """Raised when a comment is added to a resolved or closed ticket."""

class TicketCommentPersistenceContractError(AddTicketCommentError):
    """Raised when Unit of Work wiring or generated persistence state is incomplete."""

@dataclass(frozen=True, slots=True)
class AddTicketCommentCommand:
    """Add an authenticated user's append-only ticket comment."""
    ticket_id: uuid.UUID
    principal: AuthenticatedPrincipal
    trace_id: uuid.UUID
    content: str
    visibility: str = "customer"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_uuid(self.ticket_id, field_name="ticket_id")
        self._validate_uuid(self.trace_id, field_name="trace_id")

        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if self.principal.role not in {AuthRole.CUSTOMER, AuthRole.SUPPORT_AGENT, AuthRole.ADMIN,}:
            raise CommentAuthorRoleMismatchError("Authenticated role cannot create ticket comments")

        visibility = self._normalize_choice(self.visibility, field_name="visibility", valid_values=VALID_COMMENT_VISIBILITIES)
        content = self._normalize_content(self.content)
        if self.principal.role is AuthRole.CUSTOMER and visibility == "internal":
            raise CustomerInternalCommentError("Customer comments cannot be internal")

        metadata = self._normalize_metadata(self.metadata)
        object.__setattr__(self, "visibility", visibility)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "metadata", MappingProxyType(metadata))

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
    def _normalize_content(content: str) -> str:
        if not isinstance(content, str):
            raise TypeError("content must be a string")

        normalized = content.strip()
        if not normalized:
            raise ValueError("content cannot be blank")

        if len(normalized) > MAX_COMMENT_LENGTH:
            raise ValueError(f"content exceeds {MAX_COMMENT_LENGTH} characters")

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
class AddTicketCommentResult:
    """Detached result returned after commit."""
    comment_id: uuid.UUID
    ticket_id: uuid.UUID
    author_id: uuid.UUID | None
    author_role: str
    visibility: str
    content: str
    created_at: datetime

class AddTicketComment:
    """
    Add an append-only comment to an active ticket.

    The ticket row is locked before validation and insertion, preventing a concurrent ticket closure from racing with comment creation.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def execute(self, command: AddTicketCommentCommand) -> AddTicketCommentResult:
        if not isinstance(command, AddTicketCommentCommand):
            raise TypeError("command must be an AddTicketCommentCommand")

        with self._uow_factory() as uow:
            tickets, comments, audit_events = self._require_repositories(uow)
            ticket = tickets.get_by_id_for_update(command.ticket_id)
            if ticket is None:
                raise CommentTicketDoesNotExistError(command.ticket_id)

            if ticket.status not in COMMENTABLE_TICKET_STATUSES:
                raise TicketNotCommentableError(f"Ticket {ticket.id} cannot receive comments while status={ticket.status!r}")

            self._validate_author(command=command, ticket_customer_id=ticket.customer_id, uow=uow)
            comment = TicketCommentModel(
                ticket_id=ticket.id,
                author_id=command.principal.user_id,
                author_role=command.principal.role.value,
                visibility=command.visibility,
                content=command.content,
                metadata_=dict(command.metadata),
            )

            comments.add(comment)
            comments.flush()

            if comment.id is None:
                raise TicketCommentPersistenceContractError("Ticket comment ID was not generated after flush")
            
            if comment.created_at is None:
                raise TicketCommentPersistenceContractError("Ticket comment created_at was not generated after flush")

            AuditRecorder(repository=audit_events).record(
                RecordAuditEventCommand(
                    event_type="ticket.comment_added",
                    entity_type="ticket",
                    entity_id=ticket.id,
                    action="comment_added",
                    actor=self._resolve_audit_actor(command.principal),
                    trace_id=command.trace_id,
                    conversation_id=ticket.conversation_id,
                    before_state=None,
                    after_state={
                        "comment_id": str(comment.id),
                        "visibility": comment.visibility,
                        "author_role": comment.author_role,
                    },
                    metadata={"comment_length": len(comment.content),},
                    occurred_at=comment.created_at,
                )
            )

            result = AddTicketCommentResult(
                comment_id=comment.id,
                ticket_id=comment.ticket_id,
                author_id=comment.author_id,
                author_role=comment.author_role,
                visibility=comment.visibility,
                content=comment.content,
                created_at=comment.created_at,
            )

            uow.commit()
            return result

    @staticmethod
    def _validate_author(*, command: AddTicketCommentCommand, ticket_customer_id: uuid.UUID, uow: SqlAlchemyUnitOfWork) -> None:
        if uow.users is None:
            raise TicketCommentPersistenceContractError("UserRepository unavailable")

        principal = command.principal
        author = uow.users.get_by_id(principal.user_id)
        if author is None:
            raise CommentAuthorDoesNotExistError(principal.user_id)

        if author.status != "active":
            raise CommentAuthorNotActiveError(f"Comment author {author.id} is not active: status={author.status!r}")

        if author.role != principal.role.value:
            raise CommentAuthorRoleMismatchError(f"Authenticated role {principal.role.value!r} does not match persisted role {author.role!r}")

        if principal.role is AuthRole.CUSTOMER and principal.user_id != ticket_customer_id :
            raise TicketCommentOwnershipError(f"Customer {principal.user_id} does not own ticket {command.ticket_id}")

        if principal.role is AuthRole.CUSTOMER and command.visibility == "internal":
            raise CustomerInternalCommentError("Customer comments cannot be internal")

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> tuple[TicketRepository, TicketCommentRepository, AuditEventRepository,]:
        if uow.session is None:
            raise TicketCommentPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.tickets is None:
            raise TicketCommentPersistenceContractError("TicketRepository unavailable")

        if uow.ticket_comments is None:
            raise TicketCommentPersistenceContractError("TicketCommentRepository unavailable")

        if uow.users is None:
            raise TicketCommentPersistenceContractError("UserRepository unavailable")

        if uow.audit_events is None:
            raise TicketCommentPersistenceContractError("AuditEventRepository unavailable")

        return (uow.tickets, uow.ticket_comments, uow.audit_events,)
    
    @staticmethod
    def _resolve_audit_actor(principal: AuthenticatedPrincipal) -> AuditActor:
        actor_types = {
            AuthRole.CUSTOMER: AuditActorType.CUSTOMER,
            AuthRole.SUPPORT_AGENT: AuditActorType.AGENT,
            AuthRole.ADMIN: AuditActorType.ADMIN,
        }

        actor_type = actor_types.get(principal.role)
        if actor_type is None:
            raise CommentAuthorRoleMismatchError("Authenticated role cannot create ticket comments")

        return AuditActor(actor_type=actor_type, actor_id=principal.user_id)