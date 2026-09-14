# AI-customer-support-agent\packages\application\conversations\close_conversation.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.database.models.support.conversation import ConversationModel
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository
from packages.database.repositories.support.conversation_repository import ConversationRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

class CloseConversationError(RuntimeError):
    """Base application error for conversation closure."""

class ConversationToCloseDoesNotExistError(CloseConversationError):
    def __init__(self, conversation_id: uuid.UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation does not exist: {conversation_id}")

class ConversationCloseAccessDeniedError(CloseConversationError):
    """Raised when the principal cannot close a conversation."""

class ConversationCloserDoesNotExistError(CloseConversationError):
    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id
        super().__init__(f"Conversation closer does not exist: {user_id}")

class ConversationCloserNotActiveError(CloseConversationError):
    """Raised when an inactive user attempts closure."""

class ConversationCloserRoleMismatchError(CloseConversationError):
    """Raised when token and persisted roles differ."""

class ConversationClosePersistenceContractError(CloseConversationError):
    """Raised when persistence wiring or state is invalid."""

@dataclass(frozen=True, slots=True)
class CloseConversationCommand:
    conversation_id: uuid.UUID
    principal: AuthenticatedPrincipal
    trace_id: uuid.UUID

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, uuid.UUID):
            raise TypeError("conversation_id must be a UUID")

        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID")

        if self.principal.role not in {AuthRole.CUSTOMER, AuthRole.ADMIN}:
            raise ConversationCloseAccessDeniedError("Only customers and administrators may close conversations")

@dataclass(frozen=True, slots=True)
class CloseConversationResult:
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    status: str
    resolved_at: datetime | None
    closed_at: datetime
    updated_at: datetime
    changed: bool

@dataclass(frozen=True, slots=True)
class _ConversationRepositories:
    conversations: ConversationRepository
    audit_events: AuditEventRepository

class CloseConversation:
    """
    Close and atomically audit a conversation.

    Customers may close only conversations they own. Administrators may close any conversation.
    Repeated closure returns the existing state without creating another audit event.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def execute(self, command: CloseConversationCommand) -> CloseConversationResult:
        if not isinstance(command, CloseConversationCommand):
            raise TypeError("command must be a CloseConversationCommand")

        with self._uow_factory() as uow:
            repositories = self._require_repositories(uow)
            self._validate_principal(principal=command.principal, uow=uow)
            conversation = repositories.conversations.get_by_id_for_update(command.conversation_id)
            if conversation is None:
                raise ConversationToCloseDoesNotExistError(command.conversation_id)

            self._authorize_conversation(conversation=conversation, principal=command.principal)
            if conversation.status == "closed":
                return self._to_result(conversation, changed=False)

            occurred_at = datetime.now(timezone.utc)
            before_state = self._audit_state(conversation)
            repositories.conversations.mark_closed(conversation, closed_at=occurred_at)
            repositories.conversations.flush()

            self._validate_closed_state(conversation)
            AuditRecorder(repository=repositories.audit_events).record(
                RecordAuditEventCommand(
                    event_type="conversation.closed",
                    entity_type="conversation",
                    entity_id=conversation.id,
                    action="closed",
                    actor=AuditActor(actor_type=self._audit_actor_type(command.principal.role), actor_id=command.principal.user_id),
                    trace_id=command.trace_id,
                    conversation_id=conversation.id,
                    before_state=before_state,
                    after_state=self._audit_state(conversation),
                    metadata={},
                    occurred_at=occurred_at,
                )
            )

            result = self._to_result(conversation, changed=True)
            uow.commit()

            return result

    @staticmethod
    def _validate_principal(*, principal: AuthenticatedPrincipal, uow: SqlAlchemyUnitOfWork) -> None:
        if uow.users is None:
            raise ConversationClosePersistenceContractError("UserRepository unavailable")

        requester = uow.users.get_by_id(principal.user_id)
        if requester is None:
            raise ConversationCloserDoesNotExistError(principal.user_id)

        if requester.status != "active":
            raise ConversationCloserNotActiveError(f"Conversation closer {principal.user_id} is not active: status={requester.status!r}")

        if requester.role != principal.role.value:
            raise ConversationCloserRoleMismatchError(f"Authenticated role {principal.role.value!r} does not match persisted role {requester.role!r}")

        if principal.role not in {AuthRole.CUSTOMER, AuthRole.ADMIN,}:
            raise ConversationCloseAccessDeniedError("Only customers and administrators may close conversations")

    @staticmethod
    def _authorize_conversation(*, conversation: ConversationModel, principal: AuthenticatedPrincipal) -> None:
        if principal.role is AuthRole.ADMIN:
            return

        if principal.role is AuthRole.CUSTOMER and conversation.user_id == principal.user_id:
            return

        # Conceal another customer's conversation.
        raise ConversationToCloseDoesNotExistError(conversation.id)

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> _ConversationRepositories:
        if uow.session is None:
            raise ConversationClosePersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.users is None:
            raise ConversationClosePersistenceContractError("UserRepository unavailable")

        if uow.conversations is None:
            raise ConversationClosePersistenceContractError("ConversationRepository unavailable")

        if uow.audit_events is None:
            raise ConversationClosePersistenceContractError("AuditEventRepository unavailable")

        return _ConversationRepositories(conversations=uow.conversations, audit_events=uow.audit_events)

    @staticmethod
    def _validate_closed_state(conversation: ConversationModel) -> None:
        if conversation.id is None:
            raise ConversationClosePersistenceContractError("Persisted conversation has no ID")

        if conversation.status != "closed":
            raise ConversationClosePersistenceContractError("Conversation repository did not persist the closed status")

        if conversation.closed_at is None:
            raise ConversationClosePersistenceContractError("Closed conversation has no closed_at")

        if conversation.resolved_at is None:
            raise ConversationClosePersistenceContractError("Closed conversation has no resolved_at")

        if conversation.updated_at is None:
            raise ConversationClosePersistenceContractError("Closed conversation has no updated_at")

    @staticmethod
    def _audit_state(conversation: ConversationModel) -> dict[str, object]:
        return {
            "status": conversation.status,
            "resolved_at": conversation.resolved_at.isoformat() if conversation.resolved_at is not None else None,
            "closed_at": conversation.closed_at.isoformat() if conversation.closed_at is not None else None,
        }

    @staticmethod
    def _audit_actor_type(role: AuthRole) -> AuditActorType:
        if role is AuthRole.CUSTOMER:
            return AuditActorType.CUSTOMER

        if role is AuthRole.ADMIN:
            return AuditActorType.ADMIN

        raise ConversationCloseAccessDeniedError(f"Unsupported closer role: {role.value!r}")

    @staticmethod
    def _to_result(conversation: ConversationModel, *, changed: bool) -> CloseConversationResult:
        CloseConversation._validate_closed_state(conversation)

        return CloseConversationResult(
            conversation_id=conversation.id,
            customer_id=conversation.user_id,
            status=conversation.status,
            resolved_at=conversation.resolved_at,
            closed_at=conversation.closed_at,
            updated_at=conversation.updated_at,
            changed=changed,
        )