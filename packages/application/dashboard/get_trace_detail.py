# AI-customer-support-agent\packages\application\dashboard\get_trace_detail.py
from __future__ import annotations
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from packages.database.repositories.dashboard import DashboardTraceDetailRepository, TraceDetailRecord

TraceValue = str | int | float | bool | None

@dataclass(frozen=True, slots=True)
class GetTraceDetailCommand:
    trace_id: uuid.UUID

    def __post_init__(self) -> None:
        if not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID")

@dataclass(frozen=True, slots=True)
class TraceTimelineEvent:
    id: uuid.UUID
    category: str
    event_type: str
    occurred_at: datetime
    status: str | None
    duration_ms: int | None
    details: Mapping[str, TraceValue]

@dataclass(frozen=True, slots=True)
class TraceComponentCounts:
    api_requests: int
    ai_runs: int
    stage_events: int
    llm_calls: int
    embedding_calls: int
    retrieval_runs: int
    retrieval_candidates: int
    reranker_calls: int
    escalations: int
    tickets: int
    feedback: int
    audit_events: int

@dataclass(frozen=True, slots=True)
class GetTraceDetailResult:
    trace_id: uuid.UUID
    status: str
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    conversation_ids: tuple[uuid.UUID, ...]
    ai_run_ids: tuple[uuid.UUID, ...]
    component_counts: TraceComponentCounts
    timeline: tuple[TraceTimelineEvent, ...]

class TraceDetailUnitOfWork(Protocol):
    dashboard_trace_detail: DashboardTraceDetailRepository | None

    def __enter__(self) -> "TraceDetailUnitOfWork":
        ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: Any) -> None:
        ...

TraceDetailUnitOfWorkFactory = Callable[[], TraceDetailUnitOfWork]

class GetTraceDetail:
    """
    Build a sanitized, chronological view of one distributed trace.

    Only explicitly allow-listed fields are copied into the result. Raw messages, prompts, generated responses,
    document content, vectors, exception messages and unrestricted metadata are never returned.
    """
    def __init__(self, *, uow_factory: TraceDetailUnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        self._uow_factory = uow_factory

    def execute(self, command: GetTraceDetailCommand) -> GetTraceDetailResult | None:
        if not isinstance(command, GetTraceDetailCommand):
            raise TypeError("command must be a GetTraceDetailCommand")

        with self._uow_factory() as uow:
            repository = uow.dashboard_trace_detail
            if repository is None:
                raise RuntimeError("dashboard_trace_detail repository is unavailable")

            record = repository.get_trace_detail(command.trace_id)
            if record is None:
                return None

            return self._map_result(record)

    def _map_result(self, record: TraceDetailRecord) -> GetTraceDetailResult:
        timeline = self._build_timeline(record)
        started_at = min(event.occurred_at for event in timeline)
        ended_at = self._resolve_ended_at(record)
        duration_ms = self._calculate_duration_ms(started_at=started_at, ended_at=ended_at)

        return GetTraceDetailResult(
            trace_id=record.trace_id,
            status=self._resolve_status(record),
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            conversation_ids=self._unique_uuids(run.conversation_id for run in record.ai_runs),
            ai_run_ids=tuple(run.id for run in record.ai_runs),
            component_counts=TraceComponentCounts(
                api_requests=len(record.api_requests),
                ai_runs=len(record.ai_runs),
                stage_events=len(record.stage_events),
                llm_calls=len(record.llm_calls),
                embedding_calls=len(record.embedding_calls),
                retrieval_runs=len(record.retrieval_runs),
                retrieval_candidates=len(record.retrieval_candidates),
                reranker_calls=len(record.reranker_calls),
                escalations=len(record.escalations),
                tickets=len(record.tickets),
                feedback=len(record.feedback),
                audit_events=len(record.audit_events),
            ),
            timeline=timeline,
        )

    def _build_timeline(self, record: TraceDetailRecord) -> tuple[TraceTimelineEvent, ...]:
        events: list[TraceTimelineEvent] = []
        
        for item in record.api_requests:
            events.append(
                self._event(
                    event_id=item.id,
                    category="api",
                    event_type="api_request",
                    occurred_at=item.started_at,
                    status=item.outcome,
                    duration_ms=item.latency_ms,
                    details={
                        "method": item.method,
                        "route_template": item.route_template,
                        "status_code": item.status_code,
                        "error_code": item.error_code,
                        "actor_user_id": self._uuid_text(item.actor_user_id),
                        "actor_role": item.actor_role,
                        "request_size_bytes": item.request_size_bytes,
                        "response_size_bytes": item.response_size_bytes,
                    },
                )
            )

        for item in record.ai_runs:
            events.append(
                self._event(
                    event_id=item.id,
                    category="ai_run",
                    event_type="ai_run",
                    occurred_at=item.started_at,
                    status=item.status,
                    duration_ms=item.total_latency_ms,
                    details={
                        "ai_run_id": str(item.id),
                        "conversation_id": str(item.conversation_id),
                        "trigger_message_id": str(item.trigger_message_id),
                        "response_message_id": self._uuid_text(item.response_message_id),
                        "parent_run_id": self._uuid_text(item.parent_run_id),
                        "pipeline_version": item.pipeline_version,
                        "error_code": item.error_code,
                    },
                )
            )

        for item in record.stage_events:
            events.append(
                self._event(
                    event_id=item.id,
                    category="ai_stage",
                    event_type=item.event_type,
                    occurred_at=item.occurred_at,
                    status=self._stage_status(item.event_type),
                    duration_ms=item.duration_ms,
                    details={
                        "ai_run_id": str(item.ai_run_id),
                        "conversation_id": str(item.conversation_id),
                        "stage": item.stage,
                        "error_code": item.error_code,
                        "retryable": item.retryable,
                    },
                )
            )

        for item in record.llm_calls:
            events.append(
                self._event(
                    event_id=item.id,
                    category="llm",
                    event_type="llm_call",
                    occurred_at=item.started_at,
                    status=item.status,
                    duration_ms=item.latency_ms,
                    details={
                        "ai_run_id": str(item.ai_run_id),
                        "purpose": item.purpose,
                        "provider": item.provider,
                        "model": item.model,
                        "input_tokens": item.input_tokens,
                        "output_tokens": item.output_tokens,
                        "cached_input_tokens": item.cached_input_tokens,
                        "total_tokens": item.total_tokens,
                        "estimated_cost_usd": float(item.estimated_cost_usd) if item.estimated_cost_usd is not None else None,
                        "error_code": item.error_code,
                    },
                )
            )

        for item in record.embedding_calls:
            events.append(
                self._event(
                    event_id=item.id,
                    category="embedding",
                    event_type="embedding_call",
                    occurred_at=item.started_at,
                    status=item.status,
                    duration_ms=item.latency_ms,
                    details={
                        "ai_run_id": self._uuid_text(item.ai_run_id),
                        "knowledge_version_id": self._uuid_text(item.knowledge_version_id),
                        "purpose": item.purpose,
                        "provider": item.provider,
                        "model": item.model,
                        "provider_revision": item.provider_revision,
                        "input_count": item.input_count,
                        "total_input_characters": item.total_input_characters,
                        "dimensions": item.dimensions,
                        "error_code": item.error_code,
                    },
                )
            )

        for item in record.retrieval_runs:
            events.append(
                self._event(
                    event_id=item.id,
                    category="retrieval",
                    event_type="retrieval_run",
                    occurred_at=item.started_at,
                    status=item.status,
                    duration_ms=item.total_latency_ms,
                    details={
                        "ai_run_id": self._uuid_text(item.ai_run_id),
                        "embedding_call_id": self._uuid_text(item.embedding_call_id),
                        "conversation_id": self._uuid_text(item.conversation_id),
                        "retrieval_mode": item.retrieval_mode,
                        "requested_limit": item.requested_limit,
                        "vector_candidate_count": item.vector_candidate_count,
                        "lexical_candidate_count": item.lexical_candidate_count,
                        "fused_candidate_count": item.fused_candidate_count,
                        "reranked_candidate_count": item.reranked_candidate_count,
                        "selected_candidate_count": item.selected_candidate_count,
                        "context_block_count": item.context_block_count,
                        "context_token_count": item.context_token_count,
                        "reranker_used": item.reranker_used,
                        "context_truncated": item.context_truncated,
                        "zero_result": item.zero_result,
                        "vector_latency_ms": item.vector_latency_ms,
                        "lexical_latency_ms": item.lexical_latency_ms,
                        "fusion_latency_ms": item.fusion_latency_ms,
                        "reranker_latency_ms": item.reranker_latency_ms,
                        "context_build_latency_ms": item.context_build_latency_ms,
                        "error_code": item.error_code,
                    },
                )
            )

        for item in record.retrieval_candidates:
            events.append(
                self._event(
                    event_id=item.id,
                    category="retrieval_candidate",
                    event_type="candidate_recorded",
                    occurred_at=item.recorded_at,
                    status="selected" if item.selected_for_context else "rejected",
                    duration_ms=None,
                    details={
                        "retrieval_run_id": str(item.retrieval_run_id),
                        "chunk_id": str(item.chunk_id),
                        "version_id": str(item.version_id),
                        "document_id": str(item.document_id),
                        "vector_rank": item.vector_rank,
                        "lexical_rank": item.lexical_rank,
                        "fusion_rank": item.fusion_rank,
                        "reranker_rank": item.reranker_rank,
                        "final_rank": item.final_rank,
                        "vector_similarity": item.vector_similarity,
                        "lexical_score": item.lexical_score,
                        "fusion_score": item.fusion_score,
                        "reranker_score": item.reranker_score,
                        "final_score": item.final_score,
                        "rejection_reason": item.rejection_reason,
                    },
                )
            )

        for item in record.reranker_calls:
            events.append(
                self._event(
                    event_id=item.id,
                    category="reranker",
                    event_type="reranker_call",
                    occurred_at=item.started_at,
                    status=item.status,
                    duration_ms=item.latency_ms,
                    details={
                        "retrieval_run_id": str(item.retrieval_run_id),
                        "reranker_id": item.reranker_id,
                        "provider": item.provider,
                        "model": item.model,
                        "revision": item.revision,
                        "input_candidate_count": item.input_candidate_count,
                        "requested_limit": item.requested_limit,
                        "output_candidate_count": item.output_candidate_count,
                        "error_code": item.error_code,
                    },
                )
            )

        for item in record.escalations:
            events.append(
                self._event(
                    event_id=item.id,
                    category="escalation",
                    event_type="escalation",
                    occurred_at=item.created_at,
                    status=item.status,
                    duration_ms=None,
                    details={
                        "conversation_id": str(item.conversation_id),
                        "ai_run_id": self._uuid_text(item.ai_run_id),
                        "source": item.source,
                        "reason_code": item.reason_code,
                        "priority": item.priority,
                    },
                )
            )

        for item in record.tickets:
            events.append(
                self._event(
                    event_id=item.id,
                    category="ticket",
                    event_type="ticket",
                    occurred_at=item.created_at,
                    status=item.status,
                    duration_ms=None,
                    details={
                        "ticket_number": item.ticket_number,
                        "conversation_id": str(item.conversation_id),
                        "escalation_id": self._uuid_text(item.escalation_id),
                        "assigned_agent_id": self._uuid_text(item.assigned_agent_id),
                        "source": item.source,
                        "category": item.category,
                        "priority": item.priority,
                    },
                )
            )

        for item in record.feedback:
            events.append(
                self._event(
                    event_id=item.id,
                    category="feedback",
                    event_type="feedback",
                    occurred_at=item.created_at,
                    status=item.status,
                    duration_ms=None,
                    details={
                        "conversation_id": str(item.conversation_id),
                        "ai_run_id": self._uuid_text(item.ai_run_id),
                        "rating": item.rating,
                        "helpful": item.helpful,
                        "reason_code_count": len(item.reason_codes),
                    },
                )
            )

        for item in record.audit_events:
            events.append(
                self._event(
                    event_id=item.id,
                    category="business_audit",
                    event_type=item.event_type,
                    occurred_at=item.occurred_at,
                    status=None,
                    duration_ms=None,
                    details={
                        "entity_type": item.entity_type,
                        "entity_id": str(item.entity_id),
                        "action": item.action,
                        "actor_type": item.actor_type,
                        "actor_id": self._uuid_text(item.actor_id),
                        "conversation_id": self._uuid_text(item.conversation_id),
                        "ai_run_id": self._uuid_text(item.ai_run_id),
                    },
                )
            )

        return tuple(sorted(events, key=lambda event: (event.occurred_at, event.category, str(event.id),)))

    @staticmethod
    def _resolve_status(record: TraceDetailRecord) -> str:
        if any(run.status == "running" for run in record.ai_runs):
            return "running"

        if any(run.status in {"failed", "cancelled"} for run in record.ai_runs):
            return "error"

        if any(request.status_code >= 500 or request.outcome == "error" for request in record.api_requests):
            return "error"

        return "success"

    @staticmethod
    def _resolve_ended_at(record: TraceDetailRecord) -> datetime | None:
        completed_at = [value for value in (
            *(request.completed_at for request in record.api_requests),
            *(run.completed_at for run in record.ai_runs ),
            *(call.completed_at for call in record.llm_calls),
            *(call.completed_at for call in record.embedding_calls),
            *(run.completed_at for run in record.retrieval_runs),
            *(call.completed_at for call in record.reranker_calls),
        ) if value is not None]

        if not completed_at:
            return None

        return max(completed_at)

    @staticmethod
    def _calculate_duration_ms(*, started_at: datetime, ended_at: datetime | None) -> int | None:
        if ended_at is None:
            return None

        duration = ended_at - started_at
        return max(0, round(duration.total_seconds() * 1000))

    @staticmethod
    def _event(*, event_id: uuid.UUID, category: str, event_type: str, occurred_at: datetime, status: str | None, duration_ms: int | None,
               details: Mapping[str, TraceValue]) -> TraceTimelineEvent:
        return TraceTimelineEvent(
            id=event_id,
            category=category,
            event_type=event_type,
            occurred_at=occurred_at,
            status=status,
            duration_ms=duration_ms,
            details={key: value for key, value in details.items() if value is not None},
        )

    @staticmethod
    def _stage_status(event_type: str) -> str | None:
        mapping = {
            "stage_started": "running",
            "stage_completed": "success",
            "stage_failed": "error",
        }
        return mapping.get(event_type)

    @staticmethod
    def _uuid_text(value: uuid.UUID | None) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _unique_uuids(values: Any) -> tuple[uuid.UUID, ...]:
        return tuple(dict.fromkeys(value for value in values if value is not None))