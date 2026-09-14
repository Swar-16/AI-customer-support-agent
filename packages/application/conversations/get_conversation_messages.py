# AI-customer-support-agent\packages\application\conversations\get_conversation_messages.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.application.conversations.query_conversations import ConversationQueryAccessDeniedError, ConversationQueryPersistenceContractError
from packages.application.conversations.query_conversations import ConversationRequesterDoesNotExistError, ConversationRequesterNotActiveError
from packages.application.conversations.query_conversations import ConversationRequesterRoleMismatchError, QueriedConversationDoesNotExistError
from packages.database.models.support.conversation import ConversationModel
from packages.database.models.support.message import MessageModel
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
MAX_PAGE_LIMIT: Final[int] = 200

@dataclass(frozen=True, slots=True)
class GetConversationMessagesQuery:
    conversation_id: uuid.UUID
    principal: AuthenticatedPrincipal
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, uuid.UUID):
            raise TypeError("conversation_id must be a UUID")

        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if self.principal.role not in {AuthRole.CUSTOMER, AuthRole.ADMIN,}:
            raise ConversationQueryAccessDeniedError("Support-agent conversation access requires an explicit assignment policy")

        _validate_pagination(limit=self.limit, offset=self.offset)

@dataclass(frozen=True, slots=True)
class ConversationMessageView:
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    sequence_number: int
    created_at: datetime

@dataclass(frozen=True, slots=True)
class ConversationMessagePage:
    items: tuple[ConversationMessageView, ...]
    total: int
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None

    @property
    def count(self) -> int:
        return len(self.items)

class GetConversationMessages:
    """
    Return a safe, chronological page of conversation messages.

    Customers may read only their own conversations. Administrators may read any conversation.
    Support-agent access remains disabled until conversation assignment is represented explicitly.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def execute(self, query: GetConversationMessagesQuery) -> ConversationMessagePage:
        if not isinstance(query, GetConversationMessagesQuery):
            raise TypeError("query must be a GetConversationMessagesQuery")

        with self._uow_factory() as uow:
            _require_repositories(uow)
            _validate_principal(principal=query.principal, uow=uow)
            conversation = uow.conversations.get_by_id(query.conversation_id)
            if conversation is None:
                raise QueriedConversationDoesNotExistError(query.conversation_id)

            _authorize_access(conversation=conversation, principal=query.principal)
            messages = uow.messages.list_visible_by_conversation(query.conversation_id, limit=query.limit, offset=query.offset)
            total = uow.messages.count_visible_by_conversation(query.conversation_id)
            items = tuple(_to_message_view(message) for message in messages)
            consumed = query.offset + len(items)
            next_offset = consumed if consumed < total else None

            return ConversationMessagePage(
                items=items,
                total=total,
                limit=query.limit,
                offset=query.offset,
                has_more=next_offset is not None,
                next_offset=next_offset,
            )

def _require_repositories(uow: SqlAlchemyUnitOfWork) -> None:
    if uow.session is None:
        raise ConversationQueryPersistenceContractError("Active SQLAlchemy Session unavailable")

    if uow.users is None:
        raise ConversationQueryPersistenceContractError("UserRepository unavailable")

    if uow.conversations is None:
        raise ConversationQueryPersistenceContractError("ConversationRepository unavailable")

    if uow.messages is None:
        raise ConversationQueryPersistenceContractError("MessageRepository unavailable")

def _validate_principal(*, principal: AuthenticatedPrincipal, uow: SqlAlchemyUnitOfWork) -> None:
    requester = uow.users.get_by_id(principal.user_id)
    if requester is None:
        raise ConversationRequesterDoesNotExistError(principal.user_id)

    if requester.status != "active":
        raise ConversationRequesterNotActiveError(f"Conversation requester {principal.user_id} is not active: status={requester.status!r}")

    if requester.role != principal.role.value:
        raise ConversationRequesterRoleMismatchError(f"Authenticated role {principal.role.value!r} does not match persisted role {requester.role!r}")

def _authorize_access(*, conversation: ConversationModel, principal: AuthenticatedPrincipal) -> None:
    if principal.role is AuthRole.ADMIN:
        return

    if principal.role is AuthRole.CUSTOMER and conversation.user_id == principal.user_id:
        return

    # Conceal other customers' conversation existence.
    raise QueriedConversationDoesNotExistError(conversation.id)

def _to_message_view(message: MessageModel) -> ConversationMessageView:
    if message.id is None:
        raise ConversationQueryPersistenceContractError("Persisted message has no ID")

    if message.created_at is None:
        raise ConversationQueryPersistenceContractError("Persisted message has no created_at")

    if message.role not in {"customer", "assistant", "support_agent",}:
        raise ConversationQueryPersistenceContractError("Repository returned a non-visible message role")

    return ConversationMessageView(
        message_id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        sequence_number=message.sequence_number,
        created_at=message.created_at,
    )

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