from __future__ import annotations
import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.database.models.ai.llm_call import LLMCallModel


class LLMCallRepository:
    """
    Persistence adapter for LLM invocation records.

    Responsibilities:
    - persist LLM call telemetry
    - retrieve calls by run/provider/model/request identifier
    - expose operational queries used by diagnostics and dashboards
    - apply lifecycle updates to an existing LLM call

    Explicitly NOT responsible for:
    - committing transactions
    - invoking an LLM provider
    - calculating pricing
    - retries/backoff
    - deciding whether failures are retryable
    - application/business decisions
    """

    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, call: LLMCallModel) -> None:
        """
        Add an LLM call to the current transaction.

        The Unit of Work owns commit/rollback.
        """

        if not isinstance(call, LLMCallModel):
            raise TypeError("call must be an LLMCallModel")

        self._session.add(call)

    def flush(self) -> None:
        """
        Flush pending changes without committing.

        Useful when database-generated IDs/defaults are required before the
        surrounding transaction completes.
        """
        self._session.flush()

    # Lookup operations
    def get_by_id(self, call_id: uuid.UUID) -> LLMCallModel | None:
        statement = (
            select(LLMCallModel)
            .where(LLMCallModel.id == call_id)
        )

        return self._session.scalar(statement)

    def get_by_provider_request_id(self, provider_request_id: str) -> LLMCallModel | None:
        """
        Find a provider invocation using the upstream request identifier.

        Useful when correlating our telemetry with provider-side logs.
        """
        normalized = provider_request_id.strip()

        if not normalized:
            raise ValueError("provider_request_id cannot be empty")

        statement = (
            select(LLMCallModel)
            .where(
                LLMCallModel.provider_request_id
                == normalized
            )
        )

        return self._session.scalar(statement)

    def get_by_ai_run(self, ai_run_id: uuid.UUID) -> Sequence[LLMCallModel]:
        """
        Return every LLM call belonging to one AI run in execution order.
        """
        statement = (
            select(LLMCallModel)
            .where(
                LLMCallModel.ai_run_id == ai_run_id
            )
            .order_by(
                LLMCallModel.started_at.asc(),
                LLMCallModel.id.asc(),
            )
        )

        return tuple(self._session.scalars(statement))

    def get_by_purpose(self, purpose: str, *, limit: int = 100) -> Sequence[LLMCallModel]:
        """
        Return recent calls for a pipeline purpose, for example:
        intent_classification or answer_generation.
        """
        normalized = purpose.strip()

        if not normalized:
            raise ValueError("purpose cannot be empty")

        self._validate_limit(limit)

        statement = (
            select(LLMCallModel)
            .where(LLMCallModel.purpose == normalized)
            .order_by(LLMCallModel.started_at.desc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def get_failed(self, *, limit: int = 100) -> Sequence[LLMCallModel]:
        """
        Return the most recent failed/timeout provider calls.

        Useful for operational troubleshooting.
        """
        self._validate_limit(limit)

        statement = (
            select(LLMCallModel)
            .where(
                LLMCallModel.status.in_(
                    ("failed", "timeout")
                )
            )
            .order_by(LLMCallModel.started_at.desc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))


    # Lifecycle updates
    def mark_succeeded(self, call: LLMCallModel, *, completed_at: datetime, latency_ms: int, input_tokens: int, output_tokens: int,
                       cached_input_tokens: int = 0, estimated_cost_usd: Decimal | None = None, provider_request_id: str | None = None
    ) -> None:
        """
        Mark an LLM invocation as successful and persist usage telemetry.
        """
        self._validate_call_instance(call)
        self._validate_non_negative(
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
        )

        if estimated_cost_usd is not None and estimated_cost_usd < 0:
            raise ValueError("estimated_cost_usd cannot be negative")

        normalized_request_id = provider_request_id.strip() if provider_request_id is not None else None

        if provider_request_id is not None and not normalized_request_id:
            raise ValueError("provider_request_id cannot be blank")

        total_tokens = (input_tokens + output_tokens)
        call.status = "success"
        call.input_tokens = input_tokens
        call.output_tokens = output_tokens
        call.cached_input_tokens = cached_input_tokens
        call.total_tokens = total_tokens
        call.estimated_cost_usd = estimated_cost_usd
        call.latency_ms = latency_ms
        call.completed_at = completed_at
        call.provider_request_id = normalized_request_id
        call.error_code = None
        call.error_message = None

    def mark_failed(self, call: LLMCallModel, *, completed_at: datetime, latency_ms: int,
                    error_code: str, error_message: str, provider_request_id: str | None = None
    ) -> None:
        """
        Mark an LLM invocation as failed.

        Do not classify retryability here. That belongs in the provider/
        resilience layer.
        """
        self._validate_call_instance(call)

        if latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")

        normalized_code = error_code.strip()
        normalized_message = error_message.strip()

        if not normalized_code:
            raise ValueError("error_code cannot be empty")

        if not normalized_message:
            raise ValueError("error_message cannot be empty")

        normalized_request_id = provider_request_id.strip() if provider_request_id is not None else None

        if provider_request_id is not None and not normalized_request_id:
            raise ValueError("provider_request_id cannot be blank")

        call.status = "failed"
        call.completed_at = completed_at
        call.latency_ms = latency_ms
        call.provider_request_id = normalized_request_id
        call.error_code = normalized_code
        call.error_message = normalized_message

    def mark_timeout(self, call: LLMCallModel, *, completed_at: datetime, latency_ms: int,
        error_message: str = "LLM provider request timed out.", provider_request_id: str | None = None,
    ) -> None:
        """
        Mark an invocation as timed out.

        Timeout is kept separate from generic failure because dashboards,
        alerting and retry policies often treat it differently.
        """
        self._validate_call_instance(call)

        if latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")

        normalized_message = error_message.strip()

        if not normalized_message:
            raise ValueError("error_message cannot be empty")

        normalized_request_id = provider_request_id.strip() if provider_request_id is not None else None

        if provider_request_id is not None and not normalized_request_id:
            raise ValueError("provider_request_id cannot be blank")

        call.status = "timeout"
        call.completed_at = completed_at
        call.latency_ms = latency_ms
        call.provider_request_id = normalized_request_id
        call.error_code = "TIMEOUT"
        call.error_message = normalized_message


    # Aggregate telemetry queries
    def get_total_usage_for_run(self, ai_run_id: uuid.UUID) -> tuple[int, int, int, Decimal]:
        """
        Return aggregate usage for one AI run.

        Returns:
            (
                total_input_tokens,
                total_output_tokens,
                total_tokens,
                total_estimated_cost_usd,
            )
        """

        statement = select(
            func.coalesce(
                func.sum(LLMCallModel.input_tokens),0,
            ),
            func.coalesce(
                func.sum(LLMCallModel.output_tokens),0,
            ),
            func.coalesce(
                func.sum(LLMCallModel.total_tokens),0,
            ),
            func.coalesce(
                func.sum(LLMCallModel.estimated_cost_usd),Decimal("0"),
            ),
        ).where(LLMCallModel.ai_run_id == ai_run_id)

        row = self._session.execute(
            statement
        ).one()

        return (
            int(row[0]),
            int(row[1]),
            int(row[2]),
            Decimal(row[3]),
        )


    # Internal validation

    @staticmethod
    def _validate_call_instance(call: LLMCallModel) -> None:
        if not isinstance(call, LLMCallModel):
            raise TypeError("call must be an LLMCallModel")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

    @staticmethod
    def _validate_non_negative(**values: int) -> None:
        for name, value in values.items():
            if value < 0:
                raise ValueError(f"{name} cannot be negative")