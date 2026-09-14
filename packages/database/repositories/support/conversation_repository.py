# AI-customer-support-agent\packages\database\repositories\support\conversation_repository.py
from __future__ import annotations
import uuid
from collections.abc import Sequence
from datetime import datetime
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from packages.database.models.support.conversation import ConversationModel
from packages.database.repositories.support.errors import ConversationNotFoundError


class ConversationRepository:
    """
    Persistence adapter for support conversations.

    Responsibilities:
    - persist conversations
    - retrieve conversations
    - allocate message sequence numbers atomically
    - update conversation lifecycle fields

    Explicitly NOT responsible for:
    - retrieving conversation messages
    - committing transactions
    - generating AI responses
    - business-policy decisions
    """

    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, conversation: ConversationModel) -> None:
        if not isinstance(conversation, ConversationModel):
            raise TypeError("conversation must be a ConversationModel")

        self._session.add(conversation)

    def flush(self) -> None:
        """
        Flush pending ORM changes without committing.
        """
        self._session.flush()

    # Lookups
    def get_by_id(self, conversation_id: uuid.UUID) -> ConversationModel | None:
        statement = (
            select(ConversationModel)
            .where(ConversationModel.id == conversation_id)
        )

        return self._session.scalar(statement)
    
    def get_by_id_for_update(self, conversation_id: uuid.UUID) -> ConversationModel | None:
        statement = (select(ConversationModel)
                     .where(ConversationModel.id == conversation_id)
                     .with_for_update()
        )

        return self._session.scalar(statement)

    def get_by_user(self, user_id: uuid.UUID, *, limit: int = 100) -> Sequence[ConversationModel]:
        self._validate_limit(limit)
        statement = (
            select(ConversationModel)
            .where(ConversationModel.user_id == user_id)
            .order_by(ConversationModel.created_at.desc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))
    
    def list_recent(self, *, user_id: uuid.UUID | None = None, status: str | None = None, channel: str | None = None, limit: int = 50, offset: int = 0) -> Sequence[ConversationModel]:
        self._validate_limit(limit)
        self._validate_offset(offset)
        statement = select(ConversationModel)
        if user_id is not None:
            statement = statement.where(ConversationModel.user_id == user_id)

        if status is not None:
            statement = statement.where(ConversationModel.status == status)

        if channel is not None:
            statement = statement.where(ConversationModel.channel == channel)

        statement = (statement.order_by(ConversationModel.created_at.desc(),
                                        ConversationModel.id.desc())
                              .limit(limit)
                              .offset(offset)
        )

        return tuple(self._session.scalars(statement))
    
    def count_recent(self, *, user_id: uuid.UUID | None = None, status: str | None = None, channel: str | None = None) -> int:
        statement = select(func.count(ConversationModel.id))
        if user_id is not None:
            statement = statement.where(ConversationModel.user_id == user_id)

        if status is not None:
            statement = statement.where(ConversationModel.status == status)

        if channel is not None:
            statement = statement.where(ConversationModel.channel == channel)

        return int(self._session.scalar(statement) or 0)

    # Message sequence allocation
    def allocate_message_sequence(self, conversation_id: uuid.UUID) -> int:
        """
        Atomically allocate the next message sequence number.

        PostgreSQL serializes concurrent updates to the same conversation row,
        while different conversations remain independently writable.
        """
        statement = (
            update(ConversationModel)
            .where(ConversationModel.id == conversation_id)
            .values(
                next_message_sequence=(
                    ConversationModel.next_message_sequence
                    + 1
                )
            )
            .returning(
                ConversationModel.next_message_sequence
                - 1
            )
        )

        sequence_number = self._session.scalar(statement)

        if sequence_number is None:
            raise ConversationNotFoundError(conversation_id=conversation_id)

        return int(sequence_number)

    # Lifecycle updates
    def mark_resolved(self, conversation: ConversationModel, *, resolved_at: datetime) -> None:
        self._validate_conversation_instance(conversation)
        conversation.status = "resolved"
        conversation.resolved_at = resolved_at
        conversation.closed_at = None
        
    def mark_escalated(self, conversation: ConversationModel) -> None:
        """
        Mark a conversation as awaiting human support.

        The escalation record itself is persisted separately through EscalationRepository within the same Unit of Work.
        """
        self._validate_conversation_instance(conversation)
        conversation.status = "escalated"
        conversation.resolved_at = None
        conversation.closed_at = None

    def mark_closed(self, conversation: ConversationModel, *, closed_at: datetime) -> None:
        self._validate_conversation_instance(conversation)
        conversation.status = "closed"
        conversation.closed_at = closed_at

        if conversation.resolved_at is None:
            conversation.resolved_at = closed_at

    # Internal validation

    @staticmethod
    def _validate_conversation_instance(conversation: ConversationModel) -> None:
        if not isinstance(conversation, ConversationModel):
            raise TypeError("conversation must be a ConversationModel")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if limit > 200:
            raise ValueError("limit must not exceed 200")
        
    @staticmethod
    def _validate_offset(offset: int) -> None:
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")

        if offset < 0:
            raise ValueError("offset must not be negative")