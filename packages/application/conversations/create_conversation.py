# AI-customer-support-agent\packages\application\conversations\create_conversation.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.database.models.support.conversation import ConversationModel
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository
from packages.database.repositories.support.conversation_repository import ConversationRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
VALID_CONVERSATION_CHANNELS: Final[frozenset[str]] = frozenset({"web", "mobile", "email", "api",})
MAX_CONVERSATION_TITLE_LENGTH: Final[int] = 500

class CreateConversationError(RuntimeError):
    """Base application error for conversation creation."""

class ConversationCreationAccessDeniedError(CreateConversationError):
    """Raised when the principal cannot create a conversation."""

class ConversationCreatorDoesNotExistError(CreateConversationError):
    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id
        super().__init__(f"Conversation creator does not exist: {user_id}")

class ConversationCreatorNotActiveError(CreateConversationError):
    """Raised when an inactive user attempts conversation creation."""

class ConversationCreatorRoleMismatchError(CreateConversationError):
    """Raised when authenticated and persisted roles differ."""

class ConversationCreationPersistenceContractError(CreateConversationError):
    """Raised when persistence wiring or generated state is invalid."""

@dataclass(frozen=True, slots=True)
class CreateConversationCommand:
    """
    Create a new conversation for an authenticated customer.

    The owner is always derived from the verified principal. No user ID supplied by an HTTP request is accepted.
    """
    principal: AuthenticatedPrincipal
    trace_id: uuid.UUID
    channel: str = "web"
    title: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID")

        if self.principal.role is not AuthRole.CUSTOMER:
            raise ConversationCreationAccessDeniedError("Only customers may create customer conversations")

        channel = self._normalize_channel(self.channel)
        title = self._normalize_title(self.title)
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "title", title)

    @staticmethod
    def _normalize_channel(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("channel must be a string")

        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("channel cannot be blank")

        if normalized not in VALID_CONVERSATION_CHANNELS:
            expected = ", ".join(sorted(VALID_CONVERSATION_CHANNELS))
            raise ValueError(f"channel must be one of: {expected}")

        return normalized

    @staticmethod
    def _normalize_title(value: str | None) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError("title must be a string or None")

        normalized = " ".join(value.split())
        if not normalized:
            return None

        if len(normalized) > MAX_CONVERSATION_TITLE_LENGTH:
            raise ValueError(f"title exceeds {MAX_CONVERSATION_TITLE_LENGTH} characters")

        return normalized

@dataclass(frozen=True, slots=True)
class CreateConversationResult:
    """Detached conversation state returned after commit."""
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    status: str
    channel: str
    title: str | None
    next_message_sequence: int
    created_at: datetime
    updated_at: datetime

@dataclass(frozen=True, slots=True)
class _ConversationRepositories:
    conversations: ConversationRepository
    audit_events: AuditEventRepository

class CreateConversation:
    """
    Create and atomically audit a customer-owned conversation.

    The conversation and corresponding immutable audit event share the same Unit of Work. 
    An audit persistence failure therefore rolls back conversation creation.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def execute(self, command: CreateConversationCommand) -> CreateConversationResult:
        if not isinstance(command, CreateConversationCommand):
            raise TypeError("command must be a CreateConversationCommand")

        with self._uow_factory() as uow:
            repositories = self._require_repositories(uow)
            self._validate_customer(principal=command.principal, uow=uow)
            conversation = ConversationModel(
                user_id=command.principal.user_id,
                status="open",
                channel=command.channel,
                title=command.title,
                next_message_sequence=1,
                resolved_at=None,
                closed_at=None,
            )
            repositories.conversations.add(conversation)
            repositories.conversations.flush()
            self._validate_persisted_conversation(conversation)
            AuditRecorder(repository=repositories.audit_events).record(
                RecordAuditEventCommand(
                    event_type="conversation.created",
                    entity_type="conversation",
                    entity_id=conversation.id,
                    action="created",
                    actor=AuditActor(actor_type=AuditActorType.CUSTOMER, actor_id=command.principal.user_id),
                    trace_id=command.trace_id,
                    conversation_id=conversation.id,
                    before_state=None,
                    after_state={
                        "status": conversation.status,
                        "channel": conversation.channel,
                        "title_present": conversation.title is not None,
                    },
                    metadata={},
                    occurred_at=conversation.created_at,
                )
            )

            result = self._to_result(conversation)
            uow.commit()

            return result

    @staticmethod
    def _validate_customer(*, principal: AuthenticatedPrincipal, uow: SqlAlchemyUnitOfWork) -> None:
        if uow.users is None:
            raise ConversationCreationPersistenceContractError("UserRepository unavailable")

        customer = uow.users.get_by_id(principal.user_id)
        if customer is None:
            raise ConversationCreatorDoesNotExistError(principal.user_id)

        if customer.status != "active":
            raise ConversationCreatorNotActiveError(f"Customer {principal.user_id} is not active: status={customer.status!r}")

        if customer.role != principal.role.value:
            raise ConversationCreatorRoleMismatchError(f"Authenticated role {principal.role.value!r} does not match persisted role {customer.role!r}")

        if customer.role != "customer":
            raise ConversationCreationAccessDeniedError(f"User {principal.user_id} cannot create a customer conversation: role={customer.role!r}")

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> _ConversationRepositories:
        if uow.session is None:
            raise ConversationCreationPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.users is None:
            raise ConversationCreationPersistenceContractError("UserRepository unavailable")

        if uow.conversations is None:
            raise ConversationCreationPersistenceContractError("ConversationRepository unavailable")

        if uow.audit_events is None:
            raise ConversationCreationPersistenceContractError("AuditEventRepository unavailable")

        return _ConversationRepositories(conversations=uow.conversations, audit_events=uow.audit_events)

    @staticmethod
    def _validate_persisted_conversation(conversation: ConversationModel) -> None:
        if conversation.id is None:
            raise ConversationCreationPersistenceContractError("Conversation ID was not generated after flush")

        if conversation.created_at is None:
            raise ConversationCreationPersistenceContractError("Conversation created_at was not generated after flush")

        if conversation.updated_at is None:
            raise ConversationCreationPersistenceContractError("Conversation updated_at was not generated after flush")

        if conversation.next_message_sequence is None:
            raise ConversationCreationPersistenceContractError("Conversation message sequence was not initialized")

    @staticmethod
    def _to_result(conversation: ConversationModel) -> CreateConversationResult:
        CreateConversation._validate_persisted_conversation(conversation)

        return CreateConversationResult(
            conversation_id=conversation.id,
            customer_id=conversation.user_id,
            status=conversation.status,
            channel=conversation.channel,
            title=conversation.title,
            next_message_sequence=conversation.next_message_sequence,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )