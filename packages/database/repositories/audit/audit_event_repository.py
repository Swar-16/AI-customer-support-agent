# AI-customer-support-agent\packages\database\repositories\audit\audit_event_repository.py
from __future__ import annotations
import uuid
from collections.abc import Sequence
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.audit.audit_event import AuditEventModel

VALID_AUDIT_ACTOR_TYPES = frozenset({"customer", "agent", "admin", "system", "ai",})

class AuditEventRepository:
    """
    Append-only persistence adapter for immutable business audit events.

    This repository deliberately exposes no update or delete operations.

    It owns query construction and persistence staging only. Transaction commits remain the responsibility of the Unit of Work.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, event: AuditEventModel) -> None:
        """
        Stage an audit event in the current transaction.

        This method does not flush or commit.
        """
        self._validate_event_instance(event)
        self._session.add(event)

    def flush(self) -> None:
        """Flush pending audit events without committing."""
        self._session.flush()

    # Primary lookups
    def get_by_id(self, event_id: uuid.UUID) -> AuditEventModel | None:
        self._validate_uuid(event_id, field_name="event_id")

        statement = (select(AuditEventModel)
                     .where(AuditEventModel.id == event_id)
        )

        return self._session.scalar(statement)

    def get_by_trace_id(self, trace_id: uuid.UUID, *, limit: int = 100) -> Sequence[AuditEventModel]:
        """Return events belonging to one trace in chronological order."""
        self._validate_uuid(trace_id, field_name="trace_id")
        self._validate_limit(limit)
        statement = (select(AuditEventModel)
                     .where(AuditEventModel.trace_id == trace_id)
                     .order_by(AuditEventModel.occurred_at.asc(),
                               AuditEventModel.id.asc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def get_entity_history(self, *, entity_type: str, entity_id: uuid.UUID, limit: int = 100, offset: int = 0) -> Sequence[AuditEventModel]:
        """
        Return the immutable history of one business entity.

        Events are returned oldest first so callers can inspect the entity's lifecycle in mutation order.
        """
        normalized_entity_type = self._normalize_required_text(entity_type, field_name="entity_type", lowercase=True)
        self._validate_uuid(entity_id, field_name="entity_id")
        self._validate_pagination(limit=limit, offset=offset)
        statement = (select(AuditEventModel)
                     .where(AuditEventModel.entity_type == normalized_entity_type,
                            AuditEventModel.entity_id == entity_id)
                     .order_by(AuditEventModel.occurred_at.asc(),
                               AuditEventModel.id.asc())
                     .offset(offset)
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Dashboard queries
    def list_recent(self, *, event_type: str | None = None, entity_type: str | None = None, entity_id: uuid.UUID | None = None, 
                    action: str | None = None, actor_type: str | None = None, actor_id: uuid.UUID | None = None, trace_id: uuid.UUID | None = None,
                    conversation_id: uuid.UUID | None = None, ai_run_id: uuid.UUID | None = None, occurred_from: datetime | None = None,
                    occurred_to: datetime | None = None, limit: int = 100, offset: int = 0) -> Sequence[AuditEventModel]:
        """
        Return filtered business audit events ordered newest first.

        Aggregate dashboard metrics should be implemented separately rather than calculated from this paginated result.
        """
        self._validate_pagination(limit=limit, offset=offset)
        normalized_event_type = self._normalize_optional_text(event_type, field_name="event_type", lowercase=True)
        normalized_entity_type = self._normalize_optional_text(entity_type, field_name="entity_type", lowercase=True)
        normalized_action = self._normalize_optional_text(action, field_name="action", lowercase=True)
        normalized_actor_type = self._normalize_optional_actor_type(actor_type)
        for field_name, value in (
            ("entity_id", entity_id), ("actor_id", actor_id), ("trace_id", trace_id), ("conversation_id", conversation_id), ("ai_run_id", ai_run_id),
        ):
            if value is not None:
                self._validate_uuid(value, field_name=field_name)

        self._validate_datetime_range(occurred_from=occurred_from, occurred_to=occurred_to)
        statement = select(AuditEventModel)
        if normalized_event_type is not None:
            statement = statement.where(AuditEventModel.event_type == normalized_event_type)

        if normalized_entity_type is not None:
            statement = statement.where(AuditEventModel.entity_type == normalized_entity_type)

        if entity_id is not None:
            statement = statement.where(AuditEventModel.entity_id == entity_id)

        if normalized_action is not None:
            statement = statement.where(AuditEventModel.action == normalized_action)

        if normalized_actor_type is not None:
            statement = statement.where(AuditEventModel.actor_type == normalized_actor_type)

        if actor_id is not None:
            statement = statement.where(AuditEventModel.actor_id == actor_id)

        if trace_id is not None:
            statement = statement.where(AuditEventModel.trace_id == trace_id)

        if conversation_id is not None:
            statement = statement.where(AuditEventModel.conversation_id == conversation_id)

        if ai_run_id is not None:
            statement = statement.where(AuditEventModel.ai_run_id == ai_run_id)

        if occurred_from is not None:
            statement = statement.where(AuditEventModel.occurred_at >= occurred_from)

        if occurred_to is not None:
            statement = statement.where(AuditEventModel.occurred_at <= occurred_to)

        statement = (statement.order_by(AuditEventModel.occurred_at.desc(),
                                        AuditEventModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Validation helpers
    @staticmethod
    def _validate_event_instance(event: AuditEventModel) -> None:
        if not isinstance(event, AuditEventModel):
            raise TypeError("event must be an AuditEventModel")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str, lowercase: bool) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        if lowercase:
            return normalized.lower()

        return normalized

    @classmethod
    def _normalize_optional_text(cls, value: str | None, *, field_name: str, lowercase: bool) -> str | None:
        if value is None:
            return None

        return cls._normalize_required_text(value, field_name=field_name, lowercase=lowercase)

    @staticmethod
    def _normalize_optional_actor_type(actor_type: str | None) -> str | None:
        if actor_type is None:
            return None

        if not isinstance(actor_type, str):
            raise TypeError("actor_type must be a string or None")

        normalized = actor_type.strip().lower()
        if not normalized:
            raise ValueError("actor_type cannot be blank")

        if normalized not in VALID_AUDIT_ACTOR_TYPES:
            expected = ", ".join(sorted(VALID_AUDIT_ACTOR_TYPES))
            raise ValueError(f"actor_type must be one of: {expected}")

        return normalized

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if limit > 500:
            raise ValueError("limit must not exceed 500")

    @classmethod
    def _validate_pagination(cls, *, limit: int, offset: int) -> None:
        cls._validate_limit(limit)

        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")

        if offset < 0:
            raise ValueError("offset must not be negative")

    @staticmethod
    def _validate_datetime_range(*, occurred_from: datetime | None, occurred_to: datetime | None) -> None:
        for field_name, value in (("occurred_from", occurred_from), ("occurred_to", occurred_to),):
            if value is None:
                continue

            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime or None")

            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")

        if occurred_from is not None and occurred_to is not None and occurred_from > occurred_to:
            raise ValueError("occurred_from cannot be later than occurred_to")