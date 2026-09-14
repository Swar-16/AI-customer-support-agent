# AI-customer-support-agent\packages\application\conversations\query_conversations.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.database.models.support.conversation import ConversationModel
from packages.database.repositories.support.conversation_repository import ConversationRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
VALID_CONVERSATION_STATUSES: Final[frozenset[str]] = frozenset({
        "open", "waiting_for_customer", "waiting_for_agent", "escalated", "resolved", "closed",
})
VALID_CONVERSATION_CHANNELS: Final[frozenset[str]] = frozenset({"web", "mobile", "email", "api",})
MAX_PAGE_LIMIT: Final[int] = 200

class ConversationQueryError(RuntimeError):
    """Base application error for conversation queries."""

class QueriedConversationDoesNotExistError(ConversationQueryError):
    def __init__(self, conversation_id: uuid.UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation does not exist: {conversation_id}")

class ConversationRequesterDoesNotExistError(ConversationQueryError):
    def __init__(self, requester_id: uuid.UUID) -> None:
        self.requester_id = requester_id
        super().__init__(f"Conversation requester does not exist: {requester_id}")

class ConversationRequesterNotActiveError(ConversationQueryError):
    """Raised when an inactive user requests conversations."""

class ConversationRequesterRoleMismatchError(ConversationQueryError):
    """Raised when token and persisted roles do not match."""

class ConversationQueryAccessDeniedError(ConversationQueryError):
    """Raised when the principal cannot use a conversation query."""

class ConversationQueryPersistenceContractError(ConversationQueryError):
    """Raised when query persistence wiring is incomplete."""

@dataclass(frozen=True, slots=True)
class ConversationView:
    """Detached customer-safe conversation representation."""
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    status: str
    channel: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    closed_at: datetime | None

@dataclass(frozen=True, slots=True)
class GetConversationQuery:
    conversation_id: uuid.UUID
    principal: AuthenticatedPrincipal

    def __post_init__(self) -> None:
        _validate_uuid(self.conversation_id, field_name="conversation_id")
        _validate_principal_type(self.principal)

@dataclass(frozen=True, slots=True)
class ListConversationsQuery:
    """
    List customer-owned conversations or an administrative view.

    Customers are always restricted to their own user ID. Administrators may optionally filter by customer.
    Support-agent access is denied until an explicit conversation-assignment model exists.
    """
    principal: AuthenticatedPrincipal
    status: str | None = None
    channel: str | None = None
    customer_id: uuid.UUID | None = None
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        _validate_principal_type(self.principal)

        status = _normalize_optional_choice(self.status, field_name="status", valid_values=VALID_CONVERSATION_STATUSES)
        channel = _normalize_optional_choice(self.channel, field_name="channel", valid_values=VALID_CONVERSATION_CHANNELS)
        if self.customer_id is not None:
            _validate_uuid(self.customer_id, field_name="customer_id")

        _validate_pagination(limit=self.limit, offset=self.offset)
        if self.principal.role is AuthRole.CUSTOMER:
            if self.customer_id is not None and self.customer_id != self.principal.user_id:
                raise ConversationQueryAccessDeniedError("Customers cannot list another customer's conversations")

        object.__setattr__(self, "status", status)
        object.__setattr__(self, "channel", channel)

@dataclass(frozen=True, slots=True)
class ConversationPage:
    items: tuple[ConversationView, ...]
    total: int
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None

    @property
    def count(self) -> int:
        return len(self.items)

class GetConversation:
    """Retrieve a customer-owned or administratively visible conversation."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, query: GetConversationQuery) -> ConversationView:
        if not isinstance(query, GetConversationQuery):
            raise TypeError("query must be a GetConversationQuery")

        with self._uow_factory() as uow:
            repository = _require_repositories(uow)
            _validate_principal(principal=query.principal, uow=uow)
            conversation = repository.get_by_id(query.conversation_id)
            if conversation is None:
                raise QueriedConversationDoesNotExistError(query.conversation_id)

            _authorize_conversation_access(conversation=conversation, principal=query.principal)

            return _to_conversation_view(conversation)

class ListConversations:
    """List customer-owned conversations or an administrative view."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, query: ListConversationsQuery) -> ConversationPage:
        if not isinstance(query, ListConversationsQuery):
            raise TypeError("query must be a ListConversationsQuery")

        with self._uow_factory() as uow:
            repository = _require_repositories(uow)
            _validate_principal(principal=query.principal, uow=uow)
            if query.principal.role is AuthRole.CUSTOMER:
                effective_customer_id = query.principal.user_id
            else:
                effective_customer_id = query.customer_id

            records = repository.list_recent(
                user_id=effective_customer_id,
                status=query.status,
                channel=query.channel,
                limit=query.limit,
                offset=query.offset,
            )

            total = repository.count_recent(user_id=effective_customer_id, status=query.status, channel=query.channel)
            count = len(records)
            next_offset = query.offset + count if query.offset + count < total else None

            return ConversationPage(
                items=tuple(_to_conversation_view(conversation) for conversation in records),
                total=total,
                limit=query.limit,
                offset=query.offset,
                has_more=next_offset is not None,
                next_offset=next_offset,
            )

def _validate_uow_factory(uow_factory: UnitOfWorkFactory) -> UnitOfWorkFactory:
    if uow_factory is None:
        raise TypeError("uow_factory cannot be None")

    if not callable(uow_factory):
        raise TypeError("uow_factory must be callable")

    return uow_factory

def _require_repositories(uow: SqlAlchemyUnitOfWork) -> ConversationRepository:
    if uow.session is None:
        raise ConversationQueryPersistenceContractError("Active SQLAlchemy Session unavailable")

    if uow.users is None:
        raise ConversationQueryPersistenceContractError("UserRepository unavailable")

    if uow.conversations is None:
        raise ConversationQueryPersistenceContractError("ConversationRepository unavailable")

    return uow.conversations

def _validate_principal_type(principal: AuthenticatedPrincipal) -> None:
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("principal must be an AuthenticatedPrincipal")

    if principal.role not in {AuthRole.CUSTOMER, AuthRole.ADMIN,}:
        raise ConversationQueryAccessDeniedError("Support-agent conversation access requires an explicit assignment policy")

def _validate_principal(*, principal: AuthenticatedPrincipal, uow: SqlAlchemyUnitOfWork) -> None:
    _validate_principal_type(principal)
    if uow.users is None:
        raise ConversationQueryPersistenceContractError("UserRepository unavailable")

    requester = uow.users.get_by_id(principal.user_id)
    if requester is None:
        raise ConversationRequesterDoesNotExistError(principal.user_id)

    if requester.status != "active":
        raise ConversationRequesterNotActiveError(f"Conversation requester {principal.user_id} is not active: status={requester.status!r}")

    if requester.role != principal.role.value:
        raise ConversationRequesterRoleMismatchError(f"Authenticated role {principal.role.value!r} does not match persisted role {requester.role!r}")

def _authorize_conversation_access(*, conversation: ConversationModel, principal: AuthenticatedPrincipal) -> None:
    if principal.role is AuthRole.ADMIN:
        return

    if principal.role is AuthRole.CUSTOMER and conversation.user_id == principal.user_id:
        return

    # Conceal the existence of another customer's conversation.
    raise QueriedConversationDoesNotExistError(conversation.id)

def _to_conversation_view(conversation: ConversationModel) -> ConversationView:
    if conversation.id is None:
        raise ConversationQueryPersistenceContractError("Persisted conversation has no ID")

    if conversation.created_at is None:
        raise ConversationQueryPersistenceContractError("Persisted conversation has no created_at")

    if conversation.updated_at is None:
        raise ConversationQueryPersistenceContractError("Persisted conversation has no updated_at")

    return ConversationView(
        conversation_id=conversation.id,
        customer_id=conversation.user_id,
        status=conversation.status,
        channel=conversation.channel,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        resolved_at=conversation.resolved_at,
        closed_at=conversation.closed_at,
    )

def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
    if not isinstance(value, uuid.UUID):
        raise TypeError(f"{field_name} must be a UUID")

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

def _validate_pagination(*, limit: int, offset: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")

    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    if limit > MAX_PAGE_LIMIT:
        raise ValueError(f"limit must not exceed {MAX_PAGE_LIMIT}")

    if isinstance(offset, bool) or not isinstance(offset, int):
        raise TypeError("offset must be an integer")

    if offset < 0:
        raise ValueError("offset must not be negative")