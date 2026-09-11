# AI-customer-support-agent\packages\database\repositories\dashboard\llm_call_repository.py
from __future__ import annotations
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.run import AIRunModel

VALID_LLM_CALL_STATUSES = frozenset({"started", "success", "failed", "timeout",})
VALID_LLM_CALL_PURPOSES = frozenset({
    "intent_classification", "query_rewrite", "answer_generation", "action_decision", 
    "escalation_summary", "guardrail_validation", "conversation_summary", "other",
})

@dataclass(frozen=True, slots=True)
class DashboardLLMCallRecord:
    """
    Sanitized dashboard representation of one LLM invocation.

    Raw prompts, generated responses, provider error messages and provider request identifiers are deliberately excluded.
    """
    id: uuid.UUID
    ai_run_id: uuid.UUID
    trace_id: uuid.UUID
    conversation_id: uuid.UUID
    prompt_version_id: uuid.UUID | None
    purpose: str
    provider: str
    model: str
    status: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    total_tokens: int
    estimated_cost_usd: Decimal | None
    temperature: Decimal | None
    latency_ms: int | None
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None

class DashboardLLMCallRepository:
    """
    Read-only repository for the dashboard LLM-call explorer.

    Filtering, counting and pagination are performed by PostgreSQL. The repository does not load prompts, responses or exception messages.
    """
    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session instance")

        self._session = session

    def query_llm_calls(self, *, started_at: datetime, ended_at: datetime, trace_id: uuid.UUID | None = None, 
                        conversation_id: uuid.UUID | None = None, ai_run_id: uuid.UUID | None = None, purpose: str | None = None,
                        provider: str | None = None, model: str | None = None, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[tuple[DashboardLLMCallRecord, ...], int]:
        self._validate_time_range(started_at=started_at, ended_at=ended_at)
        self._validate_pagination(limit=limit, offset=offset)
        for field_name, value in (("trace_id", trace_id), ("conversation_id", conversation_id), ("ai_run_id", ai_run_id)):
            if value is not None:
                self._validate_uuid(value, field_name=field_name)

        normalized_purpose = self._normalize_choice(purpose, field_name="purpose", valid_values=VALID_LLM_CALL_PURPOSES)
        normalized_status = self._normalize_choice(status, field_name="status", valid_values=VALID_LLM_CALL_STATUSES)
        normalized_provider = self._normalize_optional_text(provider, field_name="provider")
        normalized_model = self._normalize_optional_text(model, field_name="model")

        statement = (select(LLMCallModel.id.label("id"),
                            LLMCallModel.ai_run_id.label("ai_run_id"),
                            AIRunModel.trace_id.label("trace_id"),
                            AIRunModel.conversation_id.label("conversation_id"),
                            LLMCallModel.prompt_version_id.label("prompt_version_id"),
                            LLMCallModel.purpose.label("purpose"),
                            LLMCallModel.provider.label("provider"),
                            LLMCallModel.model.label("model"),
                            LLMCallModel.status.label("status"),
                            LLMCallModel.input_tokens.label("input_tokens"),
                            LLMCallModel.output_tokens.label("output_tokens"),
                            LLMCallModel.cached_input_tokens.label("cached_input_tokens"),
                            LLMCallModel.total_tokens.label("total_tokens"),
                            LLMCallModel.estimated_cost_usd.label("estimated_cost_usd"),
                            LLMCallModel.temperature.label("temperature"),
                            LLMCallModel.latency_ms.label("latency_ms"),
                            LLMCallModel.error_code.label("error_code"),
                            LLMCallModel.started_at.label("started_at"),
                            LLMCallModel.completed_at.label("completed_at"))
                     .join(AIRunModel, AIRunModel.id == LLMCallModel.ai_run_id)
                     .where(LLMCallModel.started_at >= started_at, LLMCallModel.started_at <= ended_at)
        )

        if trace_id is not None:
            statement = statement.where(AIRunModel.trace_id == trace_id)

        if conversation_id is not None:
            statement = statement.where(AIRunModel.conversation_id == conversation_id)

        if ai_run_id is not None:
            statement = statement.where(LLMCallModel.ai_run_id == ai_run_id)

        if normalized_purpose is not None:
            statement = statement.where(LLMCallModel.purpose == normalized_purpose)

        if normalized_provider is not None:
            statement = statement.where(LLMCallModel.provider == normalized_provider)

        if normalized_model is not None:
            statement = statement.where(LLMCallModel.model == normalized_model)

        if normalized_status is not None:
            statement = statement.where(LLMCallModel.status == normalized_status)

        count_statement = (select(func.count())
                           .select_from(statement.order_by(None).subquery())
        )
        total = int(self._session.scalar(count_statement) or 0)
        statement = (statement.order_by(LLMCallModel.started_at.desc(),
                                        LLMCallModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )
        rows = self._session.execute(statement).all()
        records = tuple(
            DashboardLLMCallRecord(
                id=row.id,
                ai_run_id=row.ai_run_id,
                trace_id=row.trace_id,
                conversation_id=row.conversation_id,
                prompt_version_id=row.prompt_version_id,
                purpose=row.purpose,
                provider=row.provider,
                model=row.model,
                status=row.status,
                input_tokens=int(row.input_tokens),
                output_tokens=int(row.output_tokens),
                cached_input_tokens=int(row.cached_input_tokens),
                total_tokens=int(row.total_tokens),
                estimated_cost_usd=Decimal(row.estimated_cost_usd) if row.estimated_cost_usd is not None else None,
                temperature=Decimal(row.temperature) if row.temperature is not None else None,
                latency_ms=int(row.latency_ms) if row.latency_ms is not None else None,
                error_code=row.error_code,
                started_at=row.started_at,
                completed_at=row.completed_at,
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
    def _normalize_optional_text(value: str | None, *, field_name: str) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        return normalized

    @classmethod
    def _normalize_choice(cls, value: str | None, *, field_name: str, valid_values: frozenset[str]) -> str | None:
        normalized = cls._normalize_optional_text(value, field_name=field_name)
        if normalized is None:
            return None

        normalized = normalized.lower()
        if normalized not in valid_values:
            expected = ", ".join(sorted(valid_values))
            raise ValueError(f"{field_name} must be one of: {expected}")

        return normalized