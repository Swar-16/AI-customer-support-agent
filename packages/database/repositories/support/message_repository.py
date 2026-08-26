from __future__ import annotations
import uuid
from collections.abc import Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.support.message import MessageModel


class MessageRepository:
    """
    Persistence adapter for support conversation messages.

    Responsibilities:
    - persist messages
    - retrieve messages by stable identifiers
    - return deterministic conversation history
    - expose bounded recent-history queries for LLM context building

    Explicitly NOT responsible for:
    - allocating message sequence numbers
    - committing transactions
    - loading conversations
    - generating AI responses
    - applying business logic

    Message sequence allocation belongs to ConversationRepository because
    the sequence counter is owned by the conversation aggregate.
    """

    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, message: MessageModel) -> None:
        """
        Add a message to the current transaction.
        """
        self._validate_message_instance(message)
        self._session.add(message)

    def flush(self) -> None:
        """
        Flush pending ORM changes without committing.
        """
        self._session.flush()

    # Primary lookups
    def get_by_id(self, message_id: uuid.UUID) -> MessageModel | None:
        statement = (
            select(MessageModel)
            .where(MessageModel.id == message_id)
        )

        return self._session.scalar(statement)

    def get_by_conversation(self, conversation_id: uuid.UUID, *, limit: int | None = None) -> Sequence[MessageModel]:
        """
        Return conversation messages in canonical sequence order.

        If limit is provided, this returns the earliest N messages.
        For LLM context, prefer get_recent_by_conversation().
        """

        statement = (
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.sequence_number.asc())
        )

        if limit is not None:
            self._validate_limit(limit)
            statement = statement.limit(limit)

        return tuple(self._session.scalars(statement))

    def get_recent_by_conversation(self, conversation_id: uuid.UUID, *, limit: int = 20) -> Sequence[MessageModel]:
        """
        Return the most recent N messages while preserving chronological
        order in the returned collection.

        Query:
            newest → oldest

        Return:
            oldest → newest

        This is useful for bounded conversation context sent to an LLM.
        """
        self._validate_limit(limit)
        statement = (
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.sequence_number.desc())
            .limit(limit)
        )

        messages = tuple(self._session.scalars(statement))
        return tuple(reversed(messages))

    def get_latest(self, conversation_id: uuid.UUID) -> MessageModel | None:
        """
        Return the newest message in a conversation.
        """
        statement = (
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.sequence_number.desc())
            .limit(1)
        )

        return self._session.scalar(statement)

    # Role-based lookups
    def get_by_role(self, conversation_id: uuid.UUID, *, role: str, limit: int = 100) -> Sequence[MessageModel]:
        """
        Return recent messages for one role, preserving chronological order.

        Supported role validity is enforced by the database/model contract.
        """
        normalized_role = self._normalize_required_string(
            role,
            field_name="role",
        )

        self._validate_limit(limit)

        statement = (
            select(MessageModel)
            .where(
                MessageModel.conversation_id == conversation_id,
                MessageModel.role == normalized_role,
            )
            .order_by(MessageModel.sequence_number.desc())
            .limit(limit)
        )

        messages = tuple(self._session.scalars(statement))
        return tuple(reversed(messages))

    def get_latest_customer_message(self, conversation_id: uuid.UUID) -> MessageModel | None:
        """
        Return the latest customer-authored message.
        """
        return self._get_latest_by_role(conversation_id=conversation_id, role="customer")

    def get_latest_assistant_message(self, conversation_id: uuid.UUID) -> MessageModel | None:
        """
        Return the latest AI-assistant message.
        """
        return self._get_latest_by_role(conversation_id=conversation_id, role="assistant")


    # Internal query helpers
    def _get_latest_by_role(self, *, conversation_id: uuid.UUID, role: str) -> MessageModel | None:
        statement = (
            select(MessageModel)
            .where(
                MessageModel.conversation_id == conversation_id,
                MessageModel.role == role,
            )
            .order_by(MessageModel.sequence_number.desc())
            .limit(1)
        )

        return self._session.scalar(statement)


    # Validation helpers

    @staticmethod
    def _validate_message_instance(message: MessageModel) -> None:
        if not isinstance(message, MessageModel):
            raise TypeError("message must be a MessageModel")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        # bool is a subclass of int in Python, so reject it explicitly.
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

    @staticmethod
    def _normalize_required_string(value: str, *, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be empty")

        return normalized