# AI-customer-support-agent\packages\application\conversations\conversation_notification.py
from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Mapping

from packages.database.models.support.message import MessageModel
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

MAX_NOTIFICATION_LENGTH: Final[int] = 2_000
MAX_METADATA_KEYS: Final[int] = 30
MAX_METADATA_SERIALIZED_LENGTH: Final[int] = 5_000
VALID_NOTIFICATION_KINDS: Final[frozenset[str]] = frozenset({
    "escalation_in_review", "escalation_resolved", "escalation_dismissed", "ticket_created", "ticket_in_progress", 
    "ticket_waiting_for_customer", "ticket_resolved", "ticket_closed", "ticket_reopened",
})

class ConversationNotificationError(RuntimeError):
    """Base error for customer-visible conversation notifications."""

class ConversationNotificationContractError(ConversationNotificationError):
    """Raised when persistence wiring or generated state is incomplete."""

class NotificationConversationDoesNotExistError(ConversationNotificationError):
    """Raised when the target conversation does not exist."""

    def __init__(self, conversation_id: uuid.UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation does not exist: {conversation_id}")

@dataclass(frozen=True, slots=True)
class AppendConversationNotificationCommand:
    """
    Append one deterministic customer-visible lifecycle notification.

    This command contains only application-controlled text. Raw provider output, internal summaries,
    audit metadata, and unrestricted support notes must never be passed through this boundary.
    """
    conversation_id: uuid.UUID
    notification_kind: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, uuid.UUID):
            raise TypeError("conversation_id must be a UUID")

        notification_kind = self._normalize_notification_kind(self.notification_kind)
        content = self._normalize_content(self.content)
        metadata = self._normalize_metadata(self.metadata)

        object.__setattr__(self, "notification_kind", notification_kind)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "metadata", MappingProxyType(metadata))

    @staticmethod
    def _normalize_notification_kind(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("notification_kind must be a string")

        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("notification_kind cannot be blank")

        if normalized not in VALID_NOTIFICATION_KINDS:
            expected = ", ".join(sorted(VALID_NOTIFICATION_KINDS))
            raise ValueError(f"notification_kind must be one of: {expected}")

        return normalized

    @staticmethod
    def _normalize_content(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("content must be a string")

        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("content cannot be blank")

        if len(normalized) > MAX_NOTIFICATION_LENGTH:
            raise ValueError(f"content exceeds {MAX_NOTIFICATION_LENGTH} characters")

        return normalized

    @staticmethod
    def _normalize_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("metadata must be a mapping")

        if len(value) > MAX_METADATA_KEYS:
            raise ValueError("metadata contains too many keys")

        normalized: dict[str, Any] = {}

        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("metadata keys must be strings")

            normalized_key = key.strip()

            if not normalized_key:
                raise ValueError("metadata keys cannot be blank")

            if normalized_key in normalized:
                raise ValueError("metadata contains duplicate keys after normalization")

            normalized[normalized_key] = item

        try:
            serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must contain only JSON-serializable values") from exc

        if len(serialized) > MAX_METADATA_SERIALIZED_LENGTH:
            raise ValueError(f"serialized metadata exceeds {MAX_METADATA_SERIALIZED_LENGTH} characters")

        return normalized

@dataclass(frozen=True, slots=True)
class AppendConversationNotificationResult:
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    notification_kind: str
    sequence_number: int
    content: str
    created_at: datetime

class ConversationNotificationWriter:
    """
    Append application-controlled lifecycle notices to conversation history.

    The caller owns the Unit of Work and commit. This ensures that the lifecycle mutation, audit event,
    and notification either all commit or all roll back.

    Notifications use the assistant role because that role is already customer-visible.
    They are explicitly marked as lifecycle notices and are not eligible for feedback.

    This component never invokes an LLM.
    """
    def execute_in_uow(self, *, command: AppendConversationNotificationCommand, uow: SqlAlchemyUnitOfWork) -> AppendConversationNotificationResult:
        if not isinstance(command, AppendConversationNotificationCommand):
            raise TypeError("command must be an AppendConversationNotificationCommand")

        if not isinstance(uow, SqlAlchemyUnitOfWork):
            raise TypeError("uow must be a SqlAlchemyUnitOfWork")

        self._require_repositories(uow)
        conversation = uow.conversations.get_by_id_for_update(command.conversation_id)

        if conversation is None:
            raise NotificationConversationDoesNotExistError(command.conversation_id)

        sequence_number = uow.conversations.allocate_message_sequence(command.conversation_id)
        metadata = {
            "message_kind": "lifecycle_notice",
            "notification_kind": command.notification_kind,
            "feedback_eligible": False,
            **dict(command.metadata),
        }

        # Reserved safety fields cannot be replaced by caller metadata.
        metadata["message_kind"] = "lifecycle_notice"
        metadata["notification_kind"] = command.notification_kind
        metadata["feedback_eligible"] = False
        message = MessageModel(
            conversation_id=command.conversation_id,
            role="assistant",
            content=command.content,
            sequence_number=sequence_number,
            metadata_=metadata,
        )

        uow.messages.add(message)
        uow.messages.flush()
        
        if message.id is None:
            raise ConversationNotificationContractError("Notification message ID was not generated after flush")

        if message.created_at is None:
            raise ConversationNotificationContractError("Notification created_at was not generated after flush")

        return AppendConversationNotificationResult(
            message_id=message.id,
            conversation_id=message.conversation_id,
            notification_kind=command.notification_kind,
            sequence_number=message.sequence_number,
            content=message.content,
            created_at=message.created_at,
        )

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> None:
        if uow.session is None:
            raise ConversationNotificationContractError("Active SQLAlchemy Session unavailable")

        if uow.conversations is None:
            raise ConversationNotificationContractError("ConversationRepository unavailable")

        if uow.messages is None:
            raise ConversationNotificationContractError("MessageRepository unavailable")