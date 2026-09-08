# AI-customer-support-agent\packages\database\repositories\ai\stage_event_repository.py
from __future__ import annotations
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.ai.stage_event import AIStageEventModel

VALID_STAGE_EVENT_TYPES = frozenset({"stage_started", "stage_completed", "stage_failed",})
VALID_PIPELINE_STAGES = frozenset({
    "received", "context_built", "intent_classified", "decision_made", "retrieval_completed", "response_generated",
    "guardrails_completed", "action_proposed", "action_completed", "escalated", "completed", "failed",
})


class AIStageEventRepository:
    """
    Persistence adapter for append-only AI stage lifecycle events.

    The repository never commits and exposes no update/delete operations.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, event: AIStageEventModel) -> None:
        self._validate_event(event)
        self._session.add(event)

    def add_many(self, events: Iterable[AIStageEventModel]) -> None:
        if isinstance(events, AIStageEventModel):
            raise TypeError("events must be an iterable of AIStageEventModel")

        try:
            records = tuple(events)
            
        except TypeError as exc:
            raise TypeError("events must be an iterable") from exc

        for event in records:
            self._validate_event(event)

        self._session.add_all(records)

    def flush(self) -> None:
        """Flush pending events without committing."""
        self._session.flush()

    # Primary lookups
    def get_by_id(self, event_id: uuid.UUID) -> AIStageEventModel | None:
        self._validate_uuid(event_id, field_name="event_id")
        statement = (select(AIStageEventModel)
                     .where(AIStageEventModel.id == event_id)
        )

        return self._session.scalar(statement)

    def list_for_run(self, ai_run_id: uuid.UUID, *, limit: int = 500) -> Sequence[AIStageEventModel]:
        """Return one AI run's stage events chronologically."""
        self._validate_uuid(ai_run_id, field_name="ai_run_id")
        self._validate_limit(limit)
        statement = (select(AIStageEventModel)
                     .where(AIStageEventModel.ai_run_id == ai_run_id)
                     .order_by(AIStageEventModel.occurred_at.asc(),
                               AIStageEventModel.id.asc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_for_trace(self, trace_id: uuid.UUID, *, limit: int = 500) -> Sequence[AIStageEventModel]:
        """Return stage events correlated with one trace chronologically."""
        self._validate_uuid(trace_id, field_name="trace_id")
        self._validate_limit(limit)
        statement = (select(AIStageEventModel)
                     .where(AIStageEventModel.trace_id == trace_id)
                     .order_by(AIStageEventModel.occurred_at.asc(),
                               AIStageEventModel.id.asc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Dashboard query
    def list_recent(self, *, event_type: str | None = None, stage: str | None = None, ai_run_id: uuid.UUID | None = None, 
                    trace_id: uuid.UUID | None = None, conversation_id: uuid.UUID | None = None, error_code: str | None = None, 
                    retryable: bool | None = None, occurred_from: datetime | None = None, occurred_to: datetime | None = None, 
                    limit: int = 100, offset: int = 0) -> Sequence[AIStageEventModel]:
        """
        Return filtered stage events ordered newest first.
        """
        self._validate_pagination(limit=limit, offset=offset)
        normalized_event_type = self._normalize_optional_choice(event_type, field_name="event_type", valid_values=VALID_STAGE_EVENT_TYPES)
        normalized_stage = self._normalize_optional_choice(stage, field_name="stage", valid_values=VALID_PIPELINE_STAGES)
        normalized_error_code = self._normalize_optional_text(error_code, field_name="error_code", uppercase=True)
        for field_name, value in (("ai_run_id", ai_run_id), ("trace_id", trace_id), ("conversation_id", conversation_id),):
            if value is not None:
                self._validate_uuid(value, field_name=field_name)

        if retryable is not None and not isinstance(retryable, bool):
            raise TypeError("retryable must be a boolean or None")

        self._validate_datetime_range(occurred_from=occurred_from, occurred_to=occurred_to)
        statement = select(AIStageEventModel)
        if normalized_event_type is not None:
            statement = statement.where(AIStageEventModel.event_type == normalized_event_type)

        if normalized_stage is not None:
            statement = statement.where(AIStageEventModel.stage == normalized_stage)

        if ai_run_id is not None:
            statement = statement.where(AIStageEventModel.ai_run_id == ai_run_id)

        if trace_id is not None:
            statement = statement.where(AIStageEventModel.trace_id == trace_id)

        if conversation_id is not None:
            statement = statement.where(AIStageEventModel.conversation_id == conversation_id)

        if normalized_error_code is not None:
            statement = statement.where(AIStageEventModel.error_code == normalized_error_code)

        if retryable is not None:
            statement = statement.where(AIStageEventModel.retryable == retryable)

        if occurred_from is not None:
            statement = statement.where(AIStageEventModel.occurred_at >= occurred_from)

        if occurred_to is not None:
            statement = statement.where(AIStageEventModel.occurred_at <= occurred_to)

        statement = (statement.order_by(AIStageEventModel.occurred_at.desc(),
                                        AIStageEventModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Validation helpers
    @staticmethod
    def _validate_event(event: AIStageEventModel) -> None:
        if not isinstance(event, AIStageEventModel):
            raise TypeError("event must be an AIStageEventModel")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
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

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str, uppercase: bool) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        return normalized.upper() if uppercase else normalized

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if limit > 1_000:
            raise ValueError("limit must not exceed 1000")

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