# AI-customer-support-agent\packages\database\repositories\dashboard\audit_event_repository.py
from __future__ import annotations
import uuid
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.database.models.audit.audit_event import AuditEventModel

VALID_AUDIT_ACTOR_TYPES = frozenset({"customer", "agent", "admin", "system", "ai",})

@dataclass(frozen=True, slots=True)
class DashboardAuditEventRecord:
    """
    Sanitized dashboard representation of one immutable audit event.

    State snapshots, reason text and unrestricted metadata are not exposed by the list query.
    """
    id: uuid.UUID
    event_type: str
    entity_type: str
    entity_id: uuid.UUID
    action: str
    actor_type: str
    actor_id: uuid.UUID | None
    trace_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    ai_run_id: uuid.UUID | None
    has_before_state: bool
    has_after_state: bool
    has_reason: bool
    occurred_at: datetime
    recorded_at: datetime

class DashboardAuditEventRepository:
    """
    Read-only repository for the dashboard business-audit explorer.

    PostgreSQL performs filtering, counting, ordering and pagination. Potentially sensitive state, reason
    and metadata values are deliberately excluded from the selected columns.
    """
    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session instance")

        self._session = session

    def query_audit_events(self, *, started_at: datetime, ended_at: datetime, event_type: str | None = None, entity_type: str | None = None,
                           entity_id: uuid.UUID | None = None, action: str | None = None, actor_type: str | None = None, actor_id: uuid.UUID | None = None,
                           trace_id: uuid.UUID | None = None, conversation_id: uuid.UUID | None = None, ai_run_id: uuid.UUID | None = None,
                           limit: int = 100, offset: int = 0
    ) -> tuple[tuple[DashboardAuditEventRecord, ...], int]:
        self._validate_time_range(started_at=started_at, ended_at=ended_at)
        self._validate_pagination(limit=limit, offset=offset)

        for field_name, value in (
            ("entity_id", entity_id), ("actor_id", actor_id), ("trace_id", trace_id), ("conversation_id", conversation_id), ("ai_run_id", ai_run_id),
        ):
            if value is not None:
                self._validate_uuid(value, field_name=field_name)

        normalized_event_type = self._normalize_optional_text(event_type, field_name="event_type", lowercase=True)
        normalized_entity_type = self._normalize_optional_text(entity_type, field_name="entity_type", lowercase=True)
        normalized_action = self._normalize_optional_text(action, field_name="action", lowercase=True)
        normalized_actor_type = self._normalize_actor_type(actor_type)

        statement = (select(AuditEventModel.id.label("id"),
                            AuditEventModel.event_type.label("event_type"),
                            AuditEventModel.entity_type.label("entity_type"),
                            AuditEventModel.entity_id.label("entity_id"),
                            AuditEventModel.action.label("action"),
                            AuditEventModel.actor_type.label("actor_type"),
                            AuditEventModel.actor_id.label("actor_id"),
                            AuditEventModel.trace_id.label("trace_id"),
                            AuditEventModel.conversation_id.label("conversation_id"),
                            AuditEventModel.ai_run_id.label("ai_run_id"),
                            AuditEventModel.before_state.is_not(None).label("has_before_state"),
                            AuditEventModel.after_state.is_not(None).label("has_after_state"),
                            AuditEventModel.reason.is_not(None).label("has_reason"),
                            AuditEventModel.occurred_at.label("occurred_at"),
                            AuditEventModel.recorded_at.label("recorded_at"),
            ).where(AuditEventModel.occurred_at >= started_at, AuditEventModel.occurred_at <= ended_at)
        )

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

        count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
        total = int(self._session.scalar(count_statement) or 0)
        statement = (statement.order_by(AuditEventModel.occurred_at.desc(),
                                        AuditEventModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        rows = self._session.execute(statement).all()
        records = tuple(DashboardAuditEventRecord(
            id=row.id,
            event_type=row.event_type,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            action=row.action,
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            trace_id=row.trace_id,
            conversation_id=row.conversation_id,
            ai_run_id=row.ai_run_id,
            has_before_state=bool(row.has_before_state),
            has_after_state=bool(row.has_after_state),
            has_reason=bool(row.has_reason),
            occurred_at=row.occurred_at,
            recorded_at=row.recorded_at,
            )
            for row in rows
        )

        return records, total

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_time_range(*, started_at: datetime, ended_at: datetime) -> None:
        for field_name, value in (("started_at", started_at), ("ended_at", ended_at),):
            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime")

            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")

        if started_at > ended_at:
            raise ValueError("started_at cannot be later than ended_at")

    @staticmethod
    def _validate_pagination(*, limit: int, offset: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if limit > 500:
            raise ValueError("limit must not exceed 500")

        if offset < 0:
            raise ValueError("offset must not be negative")

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str, lowercase: bool) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        if lowercase:
            return normalized.lower()

        return normalized

    @classmethod
    def _normalize_actor_type(cls, actor_type: str | None) -> str | None:
        normalized = cls._normalize_optional_text(actor_type, field_name="actor_type", lowercase=True)
        if normalized is None:
            return None

        if normalized not in VALID_AUDIT_ACTOR_TYPES:
            expected = ", ".join(sorted(VALID_AUDIT_ACTOR_TYPES))
            raise ValueError(f"actor_type must be one of: {expected}")

        return normalized