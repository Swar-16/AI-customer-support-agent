# AI-customer-support-agent\packages\application\audit\models.py
from __future__ import annotations
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

class AuditActorType(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"
    ADMIN = "admin"
    SYSTEM = "system"
    AI = "ai"

@dataclass(frozen=True, slots=True)
class AuditActor:
    """
    Identity responsible for a business mutation.

    actor_id may be absent for unauthenticated customers. System and AI actors must not contain a user identifier.
    """
    actor_type: AuditActorType
    actor_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.actor_type, AuditActorType):
            raise TypeError("actor_type must be an AuditActorType")

        if self.actor_id is not None and not isinstance(self.actor_id, uuid.UUID):
            raise TypeError("actor_id must be a UUID or None")

        if self.actor_type in {AuditActorType.SYSTEM, AuditActorType.AI,} and self.actor_id is not None:
            raise ValueError("system and ai actors cannot have actor_id")

@dataclass(frozen=True, slots=True)
class RecordAuditEventCommand:
    """
    Application contract for recording one immutable business event.

    event_type follows the format ``entity.action``, for example:

        ticket.created
        escalation.resolved
        feedback.reviewed
        knowledge_version.published
    """
    event_type: str
    entity_type: str
    entity_id: uuid.UUID
    action: str
    actor: AuditActor
    trace_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    ai_run_id: uuid.UUID | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        event_type = self._normalize_event_type(self.event_type)
        entity_type = self._normalize_name(self.entity_type, field_name="entity_type", max_length=64)
        action = self._normalize_name(self.action, field_name="action", max_length=64)
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "entity_type", entity_type)
        object.__setattr__(self, "action", action)

        if not isinstance(self.entity_id, uuid.UUID):
            raise TypeError("entity_id must be a UUID")

        if not isinstance(self.actor, AuditActor):
            raise TypeError("actor must be an AuditActor")

        for field_name, value in (("trace_id", self.trace_id), ("conversation_id", self.conversation_id), ("ai_run_id", self.ai_run_id),):
            if value is not None and not isinstance(value, uuid.UUID):
                raise TypeError(f"{field_name} must be a UUID or None")

        before_state = self._copy_optional_mapping(self.before_state, field_name="before_state")
        after_state = self._copy_optional_mapping(self.after_state, field_name="after_state")
        metadata = self._copy_mapping(self.metadata, field_name="metadata")
        object.__setattr__(self, "before_state", before_state)
        object.__setattr__(self, "after_state", after_state)
        object.__setattr__(self, "metadata", metadata)
        
        if self.reason is not None:
            if not isinstance(self.reason, str):
                raise TypeError("reason must be a string or None")

            normalized_reason = self.reason.strip()
            object.__setattr__(self, "reason", normalized_reason or None)

        if not isinstance(self.occurred_at, datetime):
            raise TypeError("occurred_at must be a datetime")

        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")

    @staticmethod
    def _normalize_event_type(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("event_type must be a string")

        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("event_type cannot be blank")

        if len(normalized) > 100:
            raise ValueError("event_type must not exceed 100 characters")

        if _EVENT_TYPE_PATTERN.fullmatch(normalized) is None:
            raise ValueError("event_type must use lowercase 'entity.action' format")

        return normalized

    @staticmethod
    def _normalize_name(value: str, *, field_name: str, max_length: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = value.strip().lower()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        if len(normalized) > max_length:
            raise ValueError(f"{field_name} must not exceed {max_length} characters")

        if _NAME_PATTERN.fullmatch(normalized) is None:
            raise ValueError(f"{field_name} must contain only lowercase letters, numbers, and underscores")

        return normalized

    @staticmethod
    def _copy_optional_mapping(value: dict[str, Any] | None, *, field_name: str) -> dict[str, Any] | None:
        if value is None:
            return None

        return RecordAuditEventCommand._copy_mapping(value, field_name=field_name)

    @staticmethod
    def _copy_mapping(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError(f"{field_name} must be a dictionary")

        if not all(isinstance(key, str) for key in value):
            raise TypeError(f"{field_name} keys must be strings")

        return dict(value)

@dataclass(frozen=True, slots=True)
class AuditEventView:
    """Persistence-independent audit event returned by query services."""
    id: uuid.UUID
    event_type: str
    entity_type: str
    entity_id: uuid.UUID
    action: str
    actor_type: AuditActorType
    actor_id: uuid.UUID | None
    trace_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    ai_run_id: uuid.UUID | None
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    reason: str | None
    metadata: dict[str, Any]
    occurred_at: datetime
    recorded_at: datetime

@dataclass(frozen=True, slots=True)
class AuditEventQuery:
    """
    Filters for the audit-event explorer.

    All filters are optional and combined using AND semantics.
    """
    event_type: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    action: str | None = None
    actor_type: AuditActorType | None = None
    actor_id: uuid.UUID | None = None
    trace_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    ai_run_id: uuid.UUID | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.actor_type is not None and not isinstance(self.actor_type, AuditActorType):
            raise TypeError("actor_type must be an AuditActorType or None")

        for field_name, value in (
            ("entity_id", self.entity_id), ("actor_id", self.actor_id), ("trace_id", self.trace_id), ("conversation_id", self.conversation_id), ("ai_run_id", self.ai_run_id),
        ):
            if value is not None and not isinstance(value, uuid.UUID):
                raise TypeError(f"{field_name} must be a UUID or None")

        for field_name, value in (("occurred_from", self.occurred_from), ("occurred_to", self.occurred_to),):
            if value is None:
                continue

            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime or None")

            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")

        if self.occurred_from is not None and self.occurred_to is not None and self.occurred_from > self.occurred_to:
            raise ValueError("occurred_from cannot be later than occurred_to")

        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer")

        if self.limit <= 0 or self.limit > 500:
            raise ValueError("limit must be between 1 and 500")

        if isinstance(self.offset, bool) or not isinstance(self.offset, int):
            raise TypeError("offset must be an integer")

        if self.offset < 0:
            raise ValueError("offset cannot be negative")