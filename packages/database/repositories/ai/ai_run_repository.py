# small, transaction-aware, query-focused, and free of business logic.
from __future__ import annotations
import uuid
from collections.abc import Sequence
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.ai.run import AIRunModel


class AIRunRepository:
    """
    Persistence adapter for AI run records.

    Responsibilities:
    - create/persist AI runs
    - retrieve runs by stable identifiers
    - query runs by conversation/status
    - update run lifecycle fields

    Explicitly NOT responsible for:
    - committing transactions
    - deciding pipeline behavior
    - constructing telemetry
    - interpreting failures
    - retry logic
    """

    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session
    
    # Write operations
    def add(self, run: AIRunModel) -> None:
        """
        Add an AI run to the current transaction.
        No commit is performed here.
        """
        if not isinstance(run, AIRunModel):
            raise TypeError("run must be an AIRunModel")

        self._session.add(run)

    # Lookup operations
    def get_by_id(self, run_id: uuid.UUID, ) -> AIRunModel | None:
        statement = (
            select(AIRunModel)
            .where(AIRunModel.id == run_id)
        )

        return self._session.scalar(statement)

    def get_by_trace_id(self, trace_id: uuid.UUID) -> Sequence[AIRunModel]:
        """
        Return all runs belonging to one distributed/application trace.

        trace_id is intentionally not assumed unique because child runs may
        share the same trace.
        """
        statement = (
            select(AIRunModel)
            .where(AIRunModel.trace_id == trace_id)
            .order_by(AIRunModel.started_at.asc())
        )

        return tuple(self._session.scalars(statement))

    def get_by_conversation(self, conversation_id: uuid.UUID, *, limit: int = 100) -> Sequence[AIRunModel]:
        """
        Return recent AI runs for a conversation.
        """
        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        statement = (
            select(AIRunModel)
            .where(
                AIRunModel.conversation_id == conversation_id
            )
            .order_by(AIRunModel.started_at.desc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def get_by_trigger_message_id(self, message_id: uuid.UUID) -> Sequence[AIRunModel]:
        """
        Return runs triggered by a particular customer message.

        Multiple runs are possible because retries/reprocessing may happen.
        """
        statement = (
            select(AIRunModel)
            .where(
                AIRunModel.trigger_message_id == message_id
            )
            .order_by(AIRunModel.started_at.asc())
        )

        return tuple(self._session.scalars(statement))

    def get_running(self, *, limit: int = 100) -> Sequence[AIRunModel]:
        """
        Return currently running AI executions.

        Useful for operational dashboards and stuck-run detection.
        """
        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        statement = (
            select(AIRunModel)
            .where(AIRunModel.status == "running")
            .order_by(AIRunModel.started_at.asc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def mark_completed(self, run: AIRunModel, *, response_message_id: uuid.UUID | None,
                       completed_at: datetime, total_latency_ms: int
    ) -> None:
        """
        Transition a run to completed state.

        The repository applies persistence changes only.
        Business-level transition authorization belongs elsewhere.
        """
        if total_latency_ms < 0:
            raise ValueError("total_latency_ms cannot be negative")

        run.status = "completed"
        run.response_message_id = response_message_id
        run.completed_at = completed_at
        run.total_latency_ms = total_latency_ms

        run.error_code = None
        run.error_message = None

    def mark_failed(self, run: AIRunModel, *, completed_at: datetime, 
                    total_latency_ms: int, error_code: str, error_message: str
    ) -> None:
        """
        Transition a run to failed state.
        """
        if total_latency_ms < 0:
            raise ValueError("total_latency_ms cannot be negative")

        normalized_code = error_code.strip()
        normalized_message = error_message.strip()

        if not normalized_code:
            raise ValueError("error_code cannot be empty")

        if not normalized_message:
            raise ValueError("error_message cannot be empty")

        run.status = "failed"
        run.completed_at = completed_at
        run.total_latency_ms = total_latency_ms

        run.error_code = normalized_code
        run.error_message = normalized_message

    def mark_cancelled(self, run: AIRunModel, *,completed_at: datetime, total_latency_ms: int) -> None:
        if total_latency_ms < 0:
            raise ValueError("total_latency_ms cannot be negative")

        run.status = "cancelled"
        run.completed_at = completed_at
        run.total_latency_ms = total_latency_ms

    def flush(self) -> None:
        """
        Flush pending ORM changes without committing.

        Useful when the caller needs generated database values (for example
        UUID/default timestamps) before the transaction is committed.
        """
        self._session.flush()