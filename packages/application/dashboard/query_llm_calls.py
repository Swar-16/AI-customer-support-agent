# AI-customer-support-agent\packages\application\dashboard\query_llm_calls.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from packages.application.dashboard.models import DashboardPage, DashboardPagination, DashboardTimeRange
from packages.database.repositories.dashboard.llm_call_repository import DashboardLLMCallRecord, DashboardLLMCallRepository

@dataclass(frozen=True, slots=True)
class QueryDashboardLLMCallsCommand:
    time_range: DashboardTimeRange
    pagination: DashboardPagination
    trace_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    ai_run_id: uuid.UUID | None = None
    purpose: str | None = None
    provider: str | None = None
    model: str | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.time_range, DashboardTimeRange):
            raise TypeError("time_range must be a DashboardTimeRange")

        if not isinstance(self.pagination, DashboardPagination):
            raise TypeError("pagination must be a DashboardPagination")

        for field_name, value in (("trace_id", self.trace_id), ("conversation_id", self.conversation_id), ("ai_run_id", self.ai_run_id),):
            if value is not None and not isinstance(value, uuid.UUID):
                raise TypeError(f"{field_name} must be a UUID or None")

@dataclass(frozen=True, slots=True)
class DashboardLLMCall:
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

class DashboardLLMCallsUnitOfWork(Protocol):
    dashboard_llm_calls: DashboardLLMCallRepository | None
    def __enter__(self) -> "DashboardLLMCallsUnitOfWork":
        ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: Any) -> None:
        ...

DashboardLLMCallsUnitOfWorkFactory = Callable[[], DashboardLLMCallsUnitOfWork]

class QueryDashboardLLMCalls:
    def __init__(self, *, uow_factory: DashboardLLMCallsUnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        self._uow_factory = uow_factory

    def execute(self, command: QueryDashboardLLMCallsCommand) -> DashboardPage[DashboardLLMCall]:
        if not isinstance(command, QueryDashboardLLMCallsCommand):
            raise TypeError("command must be a QueryDashboardLLMCallsCommand")

        with self._uow_factory() as uow:
            repository = uow.dashboard_llm_calls
            if repository is None:
                raise RuntimeError("dashboard_llm_calls repository is unavailable")

            records, total = repository.query_llm_calls(
                started_at=command.time_range.started_at,
                ended_at=command.time_range.ended_at,
                trace_id=command.trace_id,
                conversation_id=command.conversation_id,
                ai_run_id=command.ai_run_id,
                purpose=command.purpose,
                provider=command.provider,
                model=command.model,
                status=command.status,
                limit=command.pagination.limit,
                offset=command.pagination.offset,
            )

        items = tuple(self._map_record(record) for record in records)

        return DashboardPage(items=items, total=total, limit=command.pagination.limit, offset=command.pagination.offset)

    @staticmethod
    def _map_record(record: DashboardLLMCallRecord) -> DashboardLLMCall:
        return DashboardLLMCall(
            id=record.id,
            ai_run_id=record.ai_run_id,
            trace_id=record.trace_id,
            conversation_id=record.conversation_id,
            prompt_version_id=record.prompt_version_id,
            purpose=record.purpose,
            provider=record.provider,
            model=record.model,
            status=record.status,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            cached_input_tokens=record.cached_input_tokens,
            total_tokens=record.total_tokens,
            estimated_cost_usd=record.estimated_cost_usd,
            temperature=record.temperature,
            latency_ms=record.latency_ms,
            error_code=record.error_code,
            started_at=record.started_at,
            completed_at=record.completed_at,
        )