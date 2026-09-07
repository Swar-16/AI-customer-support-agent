# AI-customer-support-agent\packages\application\tickets\add_ticket_comment.py
from __future__ import annotations
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Mapping

from packages.database.models.support.ticket_comment import TicketCommentModel
from packages.database.repositories.support.ticket_comment_repository import TicketCommentRepository
from packages.database.repositories.support.ticket_repository import TicketRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork,]
VALID_AUTHOR_ROLES: Final[frozenset[str]] = frozenset({"customer", "support_agent", "admin", "system",})
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
    """
    Add one append-only comment to a support ticket.

    `author_id` is required for customer, support-agent, and admin comments. It must be None for an unowned system-generated comment.

    The API authentication layer will eventually derive author_id and author_role from the authenticated
    principal rather than trusting arbitrary request-body values.
    """
    ticket_id: uuid.UUID
    author_role: str
    content: str
    author_id: uuid.UUID | None = None
    visibility: str = "customer"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_uuid(self.ticket_id, field_name="ticket_id")
        if self.author_id is not None:
            self._validate_uuid(self.author_id, field_name="author_id")
        author_role = self._normalize_choice(self.author_role, field_name="author_role", valid_values=VALID_AUTHOR_ROLES)
        visibility = self._normalize_choice(self.visibility, field_name="visibility", valid_values=VALID_COMMENT_VISIBILITIES)
        content = self._normalize_content(self.content)
        if author_role != "system" and self.author_id is None:
            raise ValueError(f"author_id is required for author_role={author_role!r}")

        if author_role == "customer" and visibility == "internal":
            raise CustomerInternalCommentError("Customer comments cannot be internal")

        metadata = self._normalize_metadata(self.metadata)
        object.__setattr__(self, "author_role", author_role)
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

        normalized = content.strip()    # Preserve meaningful user formatting while removing empty margins.
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
            raise ValueError(f"serialized metadata exceeds {MAX_METADATA_SERIALIZED_LENGTH} characterscharacters")

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
            tickets, comments = self._require_repositories(uow)
            ticket = tickets.get_by_id_for_update(command.ticket_id)
            if ticket is None:
                raise CommentTicketDoesNotExistError(command.ticket_id)

            if ticket.status not in COMMENTABLE_TICKET_STATUSES:
                raise TicketNotCommentableError(f"Ticket {ticket.id} cannot receive comments while status={ticket.status!r}")

            self._validate_author(command=command, ticket_customer_id=ticket.customer_id, uow=uow)
            comment = TicketCommentModel(
                ticket_id=ticket.id,
                author_id=command.author_id,
                author_role=command.author_role,
                visibility=command.visibility,
                content=command.content,
                metadata_=dict(command.metadata),
            )

            comments.add(comment)
            comments.flush()

            if comment.id is None:
                raise TicketCommentPersistenceContractError("Ticket comment ID was not generated after flush")

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
        if command.author_role == "system":
            AddTicketComment._validate_system_author(command=command, uow=uow)
            return

        if command.author_id is None:
            raise TicketCommentPersistenceContractError("Non-system comment has no author ID")

        if uow.users is None:
            raise TicketCommentPersistenceContractError("UserRepository unavailable")

        author = uow.users.get_by_id(command.author_id)
        if author is None:
            raise CommentAuthorDoesNotExistError(command.author_id)

        if author.status != "active":
            raise CommentAuthorNotActiveError(f"Comment author {author.id} is not active: status={author.status!r}")

        if author.role != command.author_role:
            raise CommentAuthorRoleMismatchError(f"Declared author_role {command.author_role!r} does not match persisted role {author.role!r}"            )

        if command.author_role == "customer" and command.author_id != ticket_customer_id:
            raise TicketCommentOwnershipError(f"Customer {command.author_id} does not own ticket {command.ticket_id}")

    @staticmethod
    def _validate_system_author(*, command: AddTicketCommentCommand, uow: SqlAlchemyUnitOfWork) -> None:
        """Allow anonymous system comments or comments tied to a persisted active system user."""
        if command.author_id is None:
            return

        if uow.users is None:
            raise TicketCommentPersistenceContractError("UserRepository unavailable")

        author = uow.users.get_by_id(command.author_id)

        if author is None:
            raise CommentAuthorDoesNotExistError(command.author_id)

        if author.status != "active":
            raise CommentAuthorNotActiveError(f"System author {author.id} is not active: status={author.status!r}")

        if author.role != "system":
            raise CommentAuthorRoleMismatchError(f"User {author.id} has role {author.role!r}, not 'system'")

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> tuple[TicketRepository, TicketCommentRepository,]:
        if uow.session is None:
            raise TicketCommentPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.tickets is None:
            raise TicketCommentPersistenceContractError("TicketRepository unavailable")

        if uow.ticket_comments is None:
            raise TicketCommentPersistenceContractError("TicketCommentRepository unavailable")

        if uow.users is None:
            raise TicketCommentPersistenceContractError("UserRepository unavailable")

        return (uow.tickets, uow.ticket_comments,)