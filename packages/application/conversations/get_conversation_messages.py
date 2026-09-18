# AI-customer-support-agent\packages\application\conversations\get_conversation_messages.py
from __future__ import annotations
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.application.conversations.query_conversations import ConversationQueryAccessDeniedError, ConversationQueryPersistenceContractError
from packages.application.conversations.query_conversations import ConversationRequesterDoesNotExistError, ConversationRequesterNotActiveError
from packages.application.conversations.query_conversations import ConversationRequesterRoleMismatchError, QueriedConversationDoesNotExistError
from packages.database.models.support.conversation import ConversationModel
from packages.database.models.support.message import MessageModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.feedback import FeedbackModel
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
class ConversationMessageFeedbackView:
    """
    Customer-safe historical feedback summary.

    Administrative review notes, customer comments, metadata, reason codes, and reviewer identities are intentionally excluded.
    """
    feedback_id: uuid.UUID
    rating: int
    helpful: bool | None
    created_at: datetime

@dataclass(frozen=True, slots=True)
class ConversationMessageView:
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    sequence_number: int
    created_at: datetime
    ai_run_id: uuid.UUID | None
    feedback_eligible: bool
    feedback: ConversationMessageFeedbackView | None

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
            messages = tuple(uow.messages.list_visible_by_conversation(query.conversation_id, limit=query.limit, offset=query.offset))
            total = uow.messages.count_visible_by_conversation(query.conversation_id)
            assistant_message_ids = tuple(message.id for message in messages if (message.role == "assistant" and message.id is not None))
            runs = uow.ai_runs.list_by_response_message_ids(assistant_message_ids)
            feedback_records = uow.feedback.list_by_response_message_ids(assistant_message_ids)
            runs_by_response_message = _group_runs_by_response_message(runs=runs, conversation_id=conversation.id)
            feedback_by_response_message = _map_feedback_by_response_message(
                feedback_records=feedback_records,
                conversation_id=conversation.id,
                customer_id=conversation.user_id,
            )
            items = tuple(
                _to_message_view(message, runs_by_response_message=runs_by_response_message, feedback_by_response_message=feedback_by_response_message)
                for message in messages
            )
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
    
    if uow.ai_runs is None:
        raise ConversationQueryPersistenceContractError("AIRunRepository unavailable")

    if uow.feedback is None:
        raise ConversationQueryPersistenceContractError("FeedbackRepository unavailable")

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

def _to_message_view(message: MessageModel, *, runs_by_response_message: dict[uuid.UUID, tuple[AIRunModel, ...]],
                     feedback_by_response_message: dict[uuid.UUID, FeedbackModel]
) -> ConversationMessageView:
    if message.id is None:
        raise ConversationQueryPersistenceContractError("Persisted message has no ID")

    if message.created_at is None:
        raise ConversationQueryPersistenceContractError("Persisted message has no created_at")

    if message.role not in {"customer", "assistant", "support_agent"}:
        raise ConversationQueryPersistenceContractError("Repository returned a non-visible message role")

    if message.role != "assistant":
        return ConversationMessageView(
            message_id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            sequence_number=message.sequence_number,
            created_at=message.created_at,
            ai_run_id=None,
            feedback_eligible=False,
            feedback=None,
        )

    feedback_record = feedback_by_response_message.get(message.id)
    selected_run = _select_response_run(runs=runs_by_response_message.get(message.id, (),), feedback=feedback_record)
    feedback_view = _to_feedback_view(feedback_record) if feedback_record is not None else None

    return ConversationMessageView(
        message_id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        sequence_number=message.sequence_number,
        created_at=message.created_at,
        ai_run_id=selected_run.id if selected_run is not None else None,
        feedback_eligible=selected_run is not None,
        feedback=feedback_view,
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

def _group_runs_by_response_message(*, runs: Sequence[AIRunModel], conversation_id: uuid.UUID) -> dict[uuid.UUID, tuple[AIRunModel, ...]]:
    grouped: dict[uuid.UUID, list[AIRunModel]] = {}

    for run in runs:
        response_message_id = run.response_message_id
        if response_message_id is None:
            continue

        if run.conversation_id != conversation_id:
            continue

        grouped.setdefault(response_message_id, []).append(run)

    return {response_message_id: tuple(grouped_runs) for response_message_id, grouped_runs in grouped.items()}

def _map_feedback_by_response_message(*, feedback_records: Sequence[FeedbackModel], conversation_id: uuid.UUID, customer_id: uuid.UUID) -> dict[uuid.UUID, FeedbackModel]:
    result: dict[uuid.UUID, FeedbackModel] = {}

    for feedback in feedback_records:
        if feedback.conversation_id != conversation_id:
            continue

        if feedback.customer_id != customer_id:
            continue

        # The database unique constraint guarantees one feedback record per response message.
        # Preserve the first deterministic repository row if inconsistent legacy data somehow exists.
        result.setdefault(feedback.response_message_id, feedback)

    return result

def _select_response_run(*, runs: tuple[AIRunModel, ...], feedback: FeedbackModel | None) -> AIRunModel | None:
    completed_runs = tuple(run for run in runs if (run.status == "completed" and run.id is not None and run.response_message_id is not None))
    if not completed_runs:
        return None

    # Existing feedback contains the strongest persisted association.
    if feedback is not None and feedback.ai_run_id is not None:
        for run in completed_runs:
            if run.id == feedback.ai_run_id:
                return run

        # Do not silently associate historical feedback with a different AI run if persisted provenance is inconsistent.
        return None

    # AIRunRepository returns newest runs first for each response message.
    return completed_runs[0]

def _to_feedback_view(feedback: FeedbackModel) -> ConversationMessageFeedbackView:
    if feedback.id is None:
        raise ConversationQueryPersistenceContractError("Persisted feedback has no ID")

    if feedback.created_at is None:
        raise ConversationQueryPersistenceContractError("Persisted feedback has no created_at")

    if isinstance(feedback.rating, bool) or not isinstance(feedback.rating, int) or feedback.rating < 1 or feedback.rating > 5:
        raise ConversationQueryPersistenceContractError("Persisted feedback has an invalid rating")

    return ConversationMessageFeedbackView(
        feedback_id=feedback.id,
        rating=feedback.rating,
        helpful=feedback.helpful,
        created_at=feedback.created_at,
    )