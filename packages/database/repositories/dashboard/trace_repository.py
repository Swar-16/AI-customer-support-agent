# AI-customer-support-agent\packages\database\repositories\dashboard\trace_repository.py
from __future__ import annotations
import uuid
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import Integer, case, func, literal, select, union_all
from sqlalchemy.orm import Session

from packages.database.models.ai.run import AIRunModel
from packages.database.models.audit.api_request import APIRequestModel

VALID_TRACE_STATUSES = frozenset({"success", "error", "running",})

@dataclass(frozen=True, slots=True)
class TraceSummaryRecord:
    trace_id: uuid.UUID
    first_seen_at: datetime
    last_seen_at: datetime
    status: str
    api_request_count: int
    ai_run_count: int
    failed_api_request_count: int
    failed_ai_run_count: int
    running_ai_run_count: int
    maximum_api_latency_ms: int | None
    maximum_ai_latency_ms: int | None

class DashboardTraceRepository:
    """
    Read-optimized repository for the dashboard trace explorer.

    HTTP requests and AI runs are normalized into one Lula event stream and aggregated by trace ID in PostgreSQL.
    Only paginated trace summaries are materialized in Python.

    The repository never mutates or commits database state.
    """
    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session instance")

        self._session = session

    def query_traces(self, *, started_at: datetime, ended_at: datetime, trace_id: uuid.UUID | None = None, conversation_id: uuid.UUID | None = None,
                     ai_run_id: uuid.UUID | None = None, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[tuple[TraceSummaryRecord, ...], int]:
        self._validate_time_range(started_at=started_at, ended_at=ended_at)
        self._validate_pagination(limit=limit, offset=offset)
        for field_name, value in (("trace_id", trace_id), ("conversation_id", conversation_id), ("ai_run_id", ai_run_id),):
            if value is not None:
                self._validate_uuid(value, field_name=field_name)

        normalized_status = self._normalize_status(status)
        trace_source = self._build_trace_query(started_at=started_at, ended_at=ended_at)
        statement = select(trace_source)
        if trace_id is not None:
            statement = statement.where(trace_source.c.trace_id == trace_id)

        if conversation_id is not None or ai_run_id is not None:
            eligible_traces = select(AIRunModel.trace_id)

            if conversation_id is not None:
                eligible_traces = eligible_traces.where(AIRunModel.conversation_id == conversation_id)

            if ai_run_id is not None:
                eligible_traces = eligible_traces.where(AIRunModel.id == ai_run_id)

            statement = statement.where(trace_source.c.trace_id.in_(eligible_traces))

        if normalized_status is not None:
            statement = statement.where(trace_source.c.status == normalized_status)

        count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
        total = int(self._session.scalar(count_statement) or 0)
        statement = (statement.order_by(trace_source.c.last_seen_at.desc(),
                                        trace_source.c.trace_id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        rows = self._session.execute(statement).all()
        records = tuple(
            TraceSummaryRecord(
                trace_id=row.trace_id,
                first_seen_at=row.first_seen_at,
                last_seen_at=row.last_seen_at,
                status=row.status,
                api_request_count=int(row.api_request_count or 0),
                ai_run_count=int(row.ai_run_count or 0),
                failed_api_request_count=int(row.failed_api_request_count or 0),
                failed_ai_run_count=int(row.failed_ai_run_count or 0),
                running_ai_run_count=int(row.running_ai_run_count or 0),
                maximum_api_latency_ms=int(row.maximum_api_latency_ms) if row.maximum_api_latency_ms is not None else None,
                maximum_ai_latency_ms=int(row.maximum_ai_latency_ms) if row.maximum_ai_latency_ms is not None else None,
            )
            for row in rows
        )

        return records, total

    @staticmethod
    def _build_trace_query(*, started_at: datetime, ended_at: datetime):
        api_events = select(APIRequestModel.trace_id.label("trace_id"),
                             APIRequestModel.started_at.label("first_seen_at"),
                             APIRequestModel.completed_at.label("last_seen_at"),
                             literal(1, type_=Integer).label("api_request_count"),
                             literal(0, type_=Integer).label("ai_run_count"),
                             case((APIRequestModel.status_code >= 400, 1), else_=0).label("failed_api_request_count"),
                             literal(0, type_=Integer).label("failed_ai_run_count"),
                             literal(0, type_=Integer).label("running_ai_run_count"),
                             APIRequestModel.latency_ms.label("api_latency_ms"),
                             literal(None, type_=Integer).label("ai_latency_ms"),
        ).where(APIRequestModel.started_at >= started_at,
                APIRequestModel.started_at <= ended_at)

        ai_events = select(AIRunModel.trace_id.label("trace_id"),
                           AIRunModel.started_at.label("first_seen_at"),
                           func.coalesce(AIRunModel.completed_at, AIRunModel.started_at).label("last_seen_at"),
                           literal(0, type_=Integer).label("api_request_count"),
                           literal(1, type_=Integer).label("ai_run_count"),
                           literal(0, type_=Integer).label("failed_api_request_count"),
                           case((AIRunModel.status.in_(("failed", "cancelled")), 1), else_=0).label("failed_ai_run_count"),
                           case((AIRunModel.status == "running", 1), else_=0).label("running_ai_run_count"),
                           literal(None, type_=Integer).label("api_latency_ms"),
                           AIRunModel.total_latency_ms.label("ai_latency_ms"),
        ).where(AIRunModel.started_at >= started_at,
                AIRunModel.started_at <= ended_at)

        events = union_all(api_events, ai_events,).cte("dashboard_trace_events")
        aggregated = (
            select(events.c.trace_id,
                   func.min(events.c.first_seen_at).label("first_seen_at"),
                   func.max(events.c.last_seen_at).label("last_seen_at"),
                   func.sum(events.c.api_request_count).label("api_request_count"),
                   func.sum(events.c.ai_run_count).label("ai_run_count"),
                   func.sum(events.c.failed_api_request_count).label("failed_api_request_count"),
                   func.sum(events.c.failed_ai_run_count).label("failed_ai_run_count"),
                   func.sum(events.c.running_ai_run_count).label("running_ai_run_count"),
                   func.max(events.c.api_latency_ms).label("maximum_api_latency_ms"),
                   func.max(events.c.ai_latency_ms).label("maximum_ai_latency_ms"),
            ).where(events.c.trace_id.is_not(None))
             .group_by(events.c.trace_id)
             .cte("dashboard_trace_aggregates")
        )

        trace_status = case((aggregated.c.running_ai_run_count > 0, "running"),
                            ((aggregated.c.failed_api_request_count + aggregated.c.failed_ai_run_count) > 0, "error"),
                            else_="success").label("status")

        return (
            select(
                aggregated.c.trace_id,
                aggregated.c.first_seen_at,
                aggregated.c.last_seen_at,
                trace_status,
                aggregated.c.api_request_count,
                aggregated.c.ai_run_count,
                aggregated.c.failed_api_request_count,
                aggregated.c.failed_ai_run_count,
                aggregated.c.running_ai_run_count,
                aggregated.c.maximum_api_latency_ms,
                aggregated.c.maximum_ai_latency_ms,
            ).cte("dashboard_traces")
        )

    @staticmethod
    def _normalize_status(status: str | None) -> str | None:
        if status is None:
            return None

        if not isinstance(status, str):
            raise TypeError("status must be a string or None")

        normalized = status.strip().lower()
        if not normalized:
            raise ValueError("status cannot be blank")

        if normalized not in VALID_TRACE_STATUSES:
            expected = ", ".join(sorted(VALID_TRACE_STATUSES))
            raise ValueError(f"status must be one of: {expected}")

        return normalized

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