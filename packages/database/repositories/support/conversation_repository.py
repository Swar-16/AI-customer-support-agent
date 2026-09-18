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

    def set_title_if_absent(self, conversation_id: uuid.UUID, *, title: str, updated_at: datetime) -> bool:
        """
        Atomically assign a title only when the conversation remains untitled.

        This compare-and-set operation prevents:

        - generated titles from replacing explicit customer titles;
        - retries from rewriting an existing title;
        - concurrent title generators from overwriting one another;
        - a late provider response from replacing a title set elsewhere.

        Returns:
            True when this transaction assigned the title. False when the conversation does not exist or already has a title.

        Transaction commit remains the Unit of Work's responsibility.
        """
        self._validate_uuid(conversation_id, field_name="conversation_id")
        normalized_title = self._normalize_title(title)
        self._validate_aware_datetime(updated_at, field_name="updated_at")

        statement = (update(ConversationModel)
                     .where(ConversationModel.id == conversation_id,
                            ConversationModel.title.is_(None))
                     .values(title=normalized_title, updated_at=updated_at)
                     .returning(ConversationModel.id)
        )

        assigned_id = self._session.scalar(statement)

        return assigned_id is not None

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
    
    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _normalize_title(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("title must be a string")

        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("title cannot be blank")

        # This is the database/repository compatibility limit. Generated
        # titles apply the stricter 80-character policy before reaching here.
        if len(normalized) > 500:
            raise ValueError("title must not exceed 500 characters")

        return normalized

    @staticmethod
    def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")