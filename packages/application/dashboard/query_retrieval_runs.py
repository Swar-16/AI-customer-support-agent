# AI-customer-support-agent\packages\application\dashboard\query_retrieval_runs.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from packages.application.dashboard.models import DashboardPage, DashboardPagination, DashboardTimeRange
from packages.database.repositories.dashboard.retrieval_run_repository import DashboardRetrievalRunRecord, DashboardRetrievalRunRepository

@dataclass(frozen=True, slots=True)
class QueryDashboardRetrievalRunsCommand:
    time_range: DashboardTimeRange
    pagination: DashboardPagination
    trace_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    ai_run_id: uuid.UUID | None = None
    retrieval_mode: str | None = None
    profile_identity: str | None = None
    status: str | None = None
    zero_result: bool | None = None
    reranker_used: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.time_range, DashboardTimeRange):
            raise TypeError("time_range must be a DashboardTimeRange")

        if not isinstance(self.pagination, DashboardPagination):
            raise TypeError("pagination must be a DashboardPagination")

        for field_name, value in (("trace_id", self.trace_id), ("conversation_id", self.conversation_id), ("ai_run_id", self.ai_run_id),):
            if value is not None and not isinstance(value, uuid.UUID):
                raise TypeError(f"{field_name} must be a UUID or None")

        for field_name, value in (("zero_result", self.zero_result), ("reranker_used", self.reranker_used),):
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"{field_name} must be a boolean or None")

@dataclass(frozen=True, slots=True)
class DashboardRetrievalRun:
    id: uuid.UUID
    ai_run_id: uuid.UUID | None
    trace_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    embedding_call_id: uuid.UUID | None
    retrieval_mode: str
    profile_identity: str
    query_fingerprint: str
    query_character_count: int
    requested_limit: int
    vector_candidate_count: int
    lexical_candidate_count: int
    fused_candidate_count: int
    reranked_candidate_count: int
    selected_candidate_count: int
    context_block_count: int
    context_token_count: int
    reranker_used: bool
    context_truncated: bool
    zero_result: bool | None
    vector_latency_ms: int | None
    lexical_latency_ms: int | None
    fusion_latency_ms: int | None
    reranker_latency_ms: int | None
    context_build_latency_ms: int | None
    total_latency_ms: int | None
    status: str
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None
    embedding_provider: str | None
    embedding_model: str | None
    embedding_status: str | None
    embedding_dimensions: int | None
    embedding_latency_ms: int | None
    embedding_error_code: str | None
    reranker_call_count: int
    failed_reranker_call_count: int
    maximum_reranker_call_latency_ms: int | None

class DashboardRetrievalRunsUnitOfWork(Protocol):
    dashboard_retrieval_runs: DashboardRetrievalRunRepository | None

    def __enter__(self) -> "DashboardRetrievalRunsUnitOfWork":
        ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: Any) -> None:
        ...

DashboardRetrievalRunsUnitOfWorkFactory = Callable[[], DashboardRetrievalRunsUnitOfWork]

class QueryDashboardRetrievalRuns:
    def __init__(self, *, uow_factory: DashboardRetrievalRunsUnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        self._uow_factory = uow_factory

    def execute(self, command: QueryDashboardRetrievalRunsCommand) -> DashboardPage[DashboardRetrievalRun]:
        if not isinstance(command, QueryDashboardRetrievalRunsCommand):
            raise TypeError("command must be a QueryDashboardRetrievalRunsCommand")

        with self._uow_factory() as uow:
            repository = uow.dashboard_retrieval_runs
            if repository is None:
                raise RuntimeError("dashboard_retrieval_runs repository is unavailable")

            records, total = repository.query_retrieval_runs(
                    started_at=command.time_range.started_at,
                    ended_at=command.time_range.ended_at,
                    trace_id=command.trace_id,
                    conversation_id=command.conversation_id,
                    ai_run_id=command.ai_run_id,
                    retrieval_mode=command.retrieval_mode,
                    profile_identity=command.profile_identity,
                    status=command.status,
                    zero_result=command.zero_result,
                    reranker_used=command.reranker_used,
                    limit=command.pagination.limit,
                    offset=command.pagination.offset,
                )

        items = tuple(self._map_record(record) for record in records)
        return DashboardPage(items=items, total=total, limit=command.pagination.limit, offset=command.pagination.offset)

    @staticmethod
    def _map_record(record: DashboardRetrievalRunRecord) -> DashboardRetrievalRun:
        return DashboardRetrievalRun(
            id=record.id,
            ai_run_id=record.ai_run_id,
            trace_id=record.trace_id,
            conversation_id=record.conversation_id,
            embedding_call_id=record.embedding_call_id,
            retrieval_mode=record.retrieval_mode,
            profile_identity=record.profile_identity,
            query_fingerprint=record.query_fingerprint,
            query_character_count=record.query_character_count,
            requested_limit=record.requested_limit,
            vector_candidate_count=record.vector_candidate_count,
            lexical_candidate_count=record.lexical_candidate_count,
            fused_candidate_count=record.fused_candidate_count,
            reranked_candidate_count=record.reranked_candidate_count,
            selected_candidate_count=record.selected_candidate_count,
            context_block_count=record.context_block_count,
            context_token_count=record.context_token_count,
            reranker_used=record.reranker_used,
            context_truncated=record.context_truncated,
            zero_result=record.zero_result,
            vector_latency_ms=record.vector_latency_ms,
            lexical_latency_ms=record.lexical_latency_ms,
            fusion_latency_ms=record.fusion_latency_ms,
            reranker_latency_ms=record.reranker_latency_ms,
            context_build_latency_ms=record.context_build_latency_ms,
            total_latency_ms=record.total_latency_ms,
            status=record.status,
            error_code=record.error_code,
            started_at=record.started_at,
            completed_at=record.completed_at,
            embedding_provider=record.embedding_provider,
            embedding_model=record.embedding_model,
            embedding_status=record.embedding_status,
            embedding_dimensions=record.embedding_dimensions,
            embedding_latency_ms=record.embedding_latency_ms,
            embedding_error_code=record.embedding_error_code,
            reranker_call_count=record.reranker_call_count,
            failed_reranker_call_count=record.failed_reranker_call_count,
            maximum_reranker_call_latency_ms=record.maximum_reranker_call_latency_ms,
        )