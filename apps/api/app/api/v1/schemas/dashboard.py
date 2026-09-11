# AI-customer-support-agent\apps\api\app\api\v1\schemas\dashboard.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
import uuid

from packages.application.dashboard.get_overview import DashboardOverviewResult, DashboardOverviewSection
from packages.application.dashboard.models import DashboardMetric, DashboardPage
from packages.application.dashboard.query_traces import DashboardTraceSummary
from packages.application.dashboard.get_trace_detail import GetTraceDetailResult, TraceComponentCounts, TraceTimelineEvent
from packages.application.dashboard.query_llm_calls import DashboardLLMCall
from packages.application.dashboard.query_retrieval_runs import DashboardRetrievalRun
from packages.application.dashboard.query_api_requests import DashboardAPIRequest
from packages.application.dashboard.query_audit_events import DashboardAuditEvent

class DashboardTimeRangeResponse(BaseModel):
    model_config = ConfigDict(frozen=True,extra="forbid")
    started_at: datetime
    ended_at: datetime

class DashboardMetricResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str = Field(min_length=1, max_length=100)
    value: int | float
    unit: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_application(cls, metric: DashboardMetric) -> "DashboardMetricResponse":
        if not isinstance(metric, DashboardMetric):
            raise TypeError("metric must be a DashboardMetric")

        return cls(key=metric.key, value=metric.value, unit=metric.unit, metadata=dict(metric.metadata))

class DashboardOverviewSectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    metrics: tuple[DashboardMetricResponse, ...]

    @classmethod
    def from_application(cls, section: DashboardOverviewSection) -> "DashboardOverviewSectionResponse":
        if not isinstance(section, DashboardOverviewSection):
            raise TypeError("section must be a DashboardOverviewSection")

        return cls(
            key=section.key,
            title=section.title,
            metrics=tuple(DashboardMetricResponse.from_application(metric) for metric in section.metrics),
        )

class DashboardOverviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    time_range: DashboardTimeRangeResponse
    generated_at: datetime
    sections: tuple[DashboardOverviewSectionResponse, ...]

    @classmethod
    def from_application(cls, result: DashboardOverviewResult) -> "DashboardOverviewResponse":
        if not isinstance(result, DashboardOverviewResult):
            raise TypeError("result must be a DashboardOverviewResult")

        return cls(
            time_range=DashboardTimeRangeResponse(started_at=result.time_range.started_at, ended_at=result.time_range.ended_at),
            generated_at=result.generated_at,
            sections=tuple(DashboardOverviewSectionResponse.from_application(section) for section in result.sections),
        )
        
class DashboardTraceSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    trace_id: uuid.UUID
    first_seen_at: datetime
    last_seen_at: datetime
    status: str = Field(min_length=1, max_length=32)
    api_request_count: int = Field(ge=0)
    ai_run_count: int = Field(ge=0)
    failed_api_request_count: int = Field(ge=0)
    failed_ai_run_count: int = Field(ge=0)
    running_ai_run_count: int = Field(ge=0)
    maximum_api_latency_ms: int | None = Field(default=None, ge=0)
    maximum_ai_latency_ms: int | None = Field(default=None, ge=0)

    @classmethod
    def from_application(cls, trace: DashboardTraceSummary) -> "DashboardTraceSummaryResponse":
        if not isinstance(trace, DashboardTraceSummary):
            raise TypeError("trace must be a DashboardTraceSummary")

        return cls(
            trace_id=trace.trace_id,
            first_seen_at=trace.first_seen_at,
            last_seen_at=trace.last_seen_at,
            status=trace.status,
            api_request_count=trace.api_request_count,
            ai_run_count=trace.ai_run_count,
            failed_api_request_count=trace.failed_api_request_count,
            failed_ai_run_count=trace.failed_ai_run_count,
            running_ai_run_count=trace.running_ai_run_count,
            maximum_api_latency_ms=trace.maximum_api_latency_ms,
            maximum_ai_latency_ms=trace.maximum_ai_latency_ms,
        )

class DashboardTraceListResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[DashboardTraceSummaryResponse, ...]
    total: int = Field(ge=0)
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)

    @classmethod
    def from_application(cls, page: DashboardPage[DashboardTraceSummary]) -> "DashboardTraceListResponse":
        if not isinstance(page, DashboardPage):
            raise TypeError("page must be a DashboardPage")

        return cls(
            items=tuple(DashboardTraceSummaryResponse.from_application(item) for item in page.items),
            total=page.total,
            count=page.returned_count,
            limit=page.limit,
            offset=page.offset,
            has_more=page.has_more,
            next_offset=page.next_offset,
        )
        
class DashboardTraceComponentCountsResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    api_requests: int = Field(ge=0)
    ai_runs: int = Field(ge=0)
    stage_events: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    embedding_calls: int = Field(ge=0)
    retrieval_runs: int = Field(ge=0)
    retrieval_candidates: int = Field(ge=0)
    reranker_calls: int = Field(ge=0)
    escalations: int = Field(ge=0)
    tickets: int = Field(ge=0)
    feedback: int = Field(ge=0)
    audit_events: int = Field(ge=0)

    @classmethod
    def from_application(cls, counts: TraceComponentCounts) -> "DashboardTraceComponentCountsResponse":
        if not isinstance(counts, TraceComponentCounts):
            raise TypeError("counts must be a TraceComponentCounts")

        return cls(
            api_requests=counts.api_requests,
            ai_runs=counts.ai_runs,
            stage_events=counts.stage_events,
            llm_calls=counts.llm_calls,
            embedding_calls=counts.embedding_calls,
            retrieval_runs=counts.retrieval_runs,
            retrieval_candidates=counts.retrieval_candidates,
            reranker_calls=counts.reranker_calls,
            escalations=counts.escalations,
            tickets=counts.tickets,
            feedback=counts.feedback,
            audit_events=counts.audit_events,
        )

class DashboardTraceTimelineEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: uuid.UUID
    category: str = Field(min_length=1, max_length=64)
    event_type: str = Field(min_length=1, max_length=100)
    occurred_at: datetime
    status: str | None = Field(default=None, max_length=32)
    duration_ms: int | None = Field(default=None, ge=0)
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @classmethod
    def from_application(cls, event: TraceTimelineEvent) -> "DashboardTraceTimelineEventResponse":
        if not isinstance(event, TraceTimelineEvent):
            raise TypeError("event must be a TraceTimelineEvent")

        return cls(
            id=event.id,
            category=event.category,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            status=event.status,
            duration_ms=event.duration_ms,
            details=dict(event.details),
        )

class DashboardTraceDetailResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    trace_id: uuid.UUID
    status: str = Field(min_length=1, max_length=32)
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None = Field(default=None, ge=0)
    conversation_ids: tuple[uuid.UUID, ...]
    ai_run_ids: tuple[uuid.UUID, ...]
    component_counts: DashboardTraceComponentCountsResponse
    timeline: tuple[DashboardTraceTimelineEventResponse, ...]

    @classmethod
    def from_application(cls, result: GetTraceDetailResult) -> "DashboardTraceDetailResponse":
        if not isinstance(result, GetTraceDetailResult):
            raise TypeError("result must be a GetTraceDetailResult")

        return cls(
            trace_id=result.trace_id,
            status=result.status,
            started_at=result.started_at,
            ended_at=result.ended_at,
            duration_ms=result.duration_ms,
            conversation_ids=result.conversation_ids,
            ai_run_ids=result.ai_run_ids,
            component_counts=DashboardTraceComponentCountsResponse.from_application(result.component_counts),
            timeline=tuple(DashboardTraceTimelineEventResponse.from_application(event) for event in result.timeline),
        )
        
class DashboardLLMCallResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: uuid.UUID
    ai_run_id: uuid.UUID
    trace_id: uuid.UUID
    conversation_id: uuid.UUID
    prompt_version_id: uuid.UUID | None
    purpose: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    status: str = Field(min_length=1, max_length=32)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: Decimal | None = Field(default=None, ge=0)
    temperature: Decimal | None = Field(default=None, ge=0, le=2)
    latency_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=100)
    started_at: datetime
    completed_at: datetime | None

    @classmethod
    def from_application(cls, call: DashboardLLMCall) -> "DashboardLLMCallResponse":
        if not isinstance(call, DashboardLLMCall):
            raise TypeError("call must be a DashboardLLMCall")

        return cls(
            id=call.id,
            ai_run_id=call.ai_run_id,
            trace_id=call.trace_id,
            conversation_id=call.conversation_id,
            prompt_version_id=call.prompt_version_id,
            purpose=call.purpose,
            provider=call.provider,
            model=call.model,
            status=call.status,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cached_input_tokens=call.cached_input_tokens,
            total_tokens=call.total_tokens,
            estimated_cost_usd=call.estimated_cost_usd,
            temperature=call.temperature,
            latency_ms=call.latency_ms,
            error_code=call.error_code,
            started_at=call.started_at,
            completed_at=call.completed_at,
        )

class DashboardLLMCallListResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[DashboardLLMCallResponse, ...]
    total: int = Field(ge=0)
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)

    @classmethod
    def from_application(cls, page: DashboardPage[DashboardLLMCall]) -> "DashboardLLMCallListResponse":
        if not isinstance(page, DashboardPage):
            raise TypeError("page must be a DashboardPage")

        return cls(
            items=tuple(DashboardLLMCallResponse.from_application(item) for item in page.items),
            total=page.total,
            count=page.returned_count,
            limit=page.limit,
            offset=page.offset,
            has_more=page.has_more,
            next_offset=page.next_offset,
        )
        
class DashboardRetrievalRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: uuid.UUID
    ai_run_id: uuid.UUID | None
    trace_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    embedding_call_id: uuid.UUID | None
    retrieval_mode: str = Field(min_length=1, max_length=32)
    profile_identity: str = Field(min_length=1, max_length=255)
    query_fingerprint: str = Field(min_length=1, max_length=64)
    query_character_count: int = Field(ge=0)
    requested_limit: int = Field(ge=1)
    vector_candidate_count: int = Field(ge=0)
    lexical_candidate_count: int = Field(ge=0)
    fused_candidate_count: int = Field(ge=0)
    reranked_candidate_count: int = Field(ge=0)
    selected_candidate_count: int = Field(ge=0)
    context_block_count: int = Field(ge=0)
    context_token_count: int = Field(ge=0)
    reranker_used: bool
    context_truncated: bool
    zero_result: bool | None
    vector_latency_ms: int | None = Field(default=None, ge=0)
    lexical_latency_ms: int | None = Field(default=None, ge=0)
    fusion_latency_ms: int | None = Field(default=None, ge=0)
    reranker_latency_ms: int | None = Field(default=None, ge=0)
    context_build_latency_ms: int | None = Field(default=None, ge=0)
    total_latency_ms: int | None = Field(default=None, ge=0)
    status: str = Field(min_length=1, max_length=32)
    error_code: str | None = Field(default=None, max_length=100)
    started_at: datetime
    completed_at: datetime | None
    embedding_provider: str | None = Field(default=None, max_length=100)
    embedding_model: str | None = Field(default=None, max_length=200)
    embedding_status: str | None = Field(default=None, max_length=32)
    embedding_dimensions: int | None = Field(default=None, gt=0)
    embedding_latency_ms: int | None = Field(default=None, ge=0)
    embedding_error_code: str | None = Field(default=None, max_length=100)
    reranker_call_count: int = Field(ge=0)
    failed_reranker_call_count: int = Field(ge=0)
    maximum_reranker_call_latency_ms: int | None = Field(default=None, ge=0)

    @classmethod
    def from_application(cls, run: DashboardRetrievalRun) -> "DashboardRetrievalRunResponse":
        if not isinstance(run, DashboardRetrievalRun):
            raise TypeError("run must be a DashboardRetrievalRun")

        return cls(
            id=run.id,
            ai_run_id=run.ai_run_id,
            trace_id=run.trace_id,
            conversation_id=run.conversation_id,
            embedding_call_id=run.embedding_call_id,
            retrieval_mode=run.retrieval_mode,
            profile_identity=run.profile_identity,
            query_fingerprint=run.query_fingerprint,
            query_character_count=run.query_character_count,
            requested_limit=run.requested_limit,
            vector_candidate_count=run.vector_candidate_count,
            lexical_candidate_count=run.lexical_candidate_count,
            fused_candidate_count=run.fused_candidate_count,
            reranked_candidate_count=run.reranked_candidate_count,
            selected_candidate_count=run.selected_candidate_count,
            context_block_count=run.context_block_count,
            context_token_count=run.context_token_count,
            reranker_used=run.reranker_used,
            context_truncated=run.context_truncated,
            zero_result=run.zero_result,
            vector_latency_ms=run.vector_latency_ms,
            lexical_latency_ms=run.lexical_latency_ms,
            fusion_latency_ms=run.fusion_latency_ms,
            reranker_latency_ms=run.reranker_latency_ms,
            context_build_latency_ms=run.context_build_latency_ms,
            total_latency_ms=run.total_latency_ms,
            status=run.status,
            error_code=run.error_code,
            started_at=run.started_at,
            completed_at=run.completed_at,
            embedding_provider=run.embedding_provider,
            embedding_model=run.embedding_model,
            embedding_status=run.embedding_status,
            embedding_dimensions=run.embedding_dimensions,
            embedding_latency_ms=run.embedding_latency_ms,
            embedding_error_code=run.embedding_error_code,
            reranker_call_count=run.reranker_call_count,
            failed_reranker_call_count=run.failed_reranker_call_count,
            maximum_reranker_call_latency_ms=run.maximum_reranker_call_latency_ms,
        )


class DashboardRetrievalRunListResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[DashboardRetrievalRunResponse, ...]
    total: int = Field(ge=0)
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)

    @classmethod
    def from_application(cls, page: DashboardPage[DashboardRetrievalRun]) -> "DashboardRetrievalRunListResponse":
        if not isinstance(page, DashboardPage):
            raise TypeError("page must be a DashboardPage")

        return cls(
            items=tuple(DashboardRetrievalRunResponse.from_application(item) for item in page.items),
            total=page.total,
            count=page.returned_count,
            limit=page.limit,
            offset=page.offset,
            has_more=page.has_more,
            next_offset=page.next_offset,
        )
        
class DashboardAPIRequestResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: uuid.UUID
    trace_id: uuid.UUID
    method: str = Field(min_length=1, max_length=16)
    route_template: str | None = Field(default=None, max_length=500)
    status_code: int = Field(ge=100, le=599)
    outcome: str = Field(min_length=1, max_length=32)
    error_code: str | None = Field(default=None, max_length=100)
    actor_user_id: uuid.UUID | None
    actor_role: str | None = Field(default=None, max_length=32)
    request_size_bytes: int | None = Field(default=None, ge=0)
    response_size_bytes: int | None = Field(default=None, ge=0)
    latency_ms: int = Field(ge=0)
    started_at: datetime
    completed_at: datetime

    @classmethod
    def from_application(cls, request: DashboardAPIRequest) -> "DashboardAPIRequestResponse":
        if not isinstance(request, DashboardAPIRequest):
            raise TypeError("request must be a DashboardAPIRequest")

        return cls(
            id=request.id,
            trace_id=request.trace_id,
            method=request.method,
            route_template=request.route_template,
            status_code=request.status_code,
            outcome=request.outcome,
            error_code=request.error_code,
            actor_user_id=request.actor_user_id,
            actor_role=request.actor_role,
            request_size_bytes=request.request_size_bytes,
            response_size_bytes=request.response_size_bytes,
            latency_ms=request.latency_ms,
            started_at=request.started_at,
            completed_at=request.completed_at,
        )

class DashboardAPIRequestListResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[DashboardAPIRequestResponse, ...]
    total: int = Field(ge=0)
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)

    @classmethod
    def from_application(cls, page: DashboardPage[DashboardAPIRequest]) -> "DashboardAPIRequestListResponse":
        if not isinstance(page, DashboardPage):
            raise TypeError("page must be a DashboardPage")

        return cls(
            items=tuple(DashboardAPIRequestResponse.from_application(item) for item in page.items),
            total=page.total,
            count=page.returned_count,
            limit=page.limit,
            offset=page.offset,
            has_more=page.has_more,
            next_offset=page.next_offset,
        )
        
class DashboardAuditEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: uuid.UUID
    event_type: str = Field(min_length=1, max_length=100)
    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: uuid.UUID
    action: str = Field(min_length=1, max_length=64)
    actor_type: str = Field(min_length=1, max_length=32)
    actor_id: uuid.UUID | None
    trace_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    ai_run_id: uuid.UUID | None
    has_before_state: bool
    has_after_state: bool
    has_reason: bool
    occurred_at: datetime
    recorded_at: datetime

    @classmethod
    def from_application(cls, event: DashboardAuditEvent) -> "DashboardAuditEventResponse":
        if not isinstance(event, DashboardAuditEvent):
            raise TypeError("event must be a DashboardAuditEvent")

        return cls(
            id=event.id,
            event_type=event.event_type,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            action=event.action,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            trace_id=event.trace_id,
            conversation_id=event.conversation_id,
            ai_run_id=event.ai_run_id,
            has_before_state=event.has_before_state,
            has_after_state=event.has_after_state,
            has_reason=event.has_reason,
            occurred_at=event.occurred_at,
            recorded_at=event.recorded_at,
        )

class DashboardAuditEventListResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[DashboardAuditEventResponse, ...]
    total: int = Field(ge=0)
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)

    @classmethod
    def from_application(cls, page: DashboardPage[DashboardAuditEvent]) -> "DashboardAuditEventListResponse":
        if not isinstance(page, DashboardPage):
            raise TypeError("page must be a DashboardPage")

        return cls(
            items=tuple(DashboardAuditEventResponse.from_application(item) for item in page.items),
            total=page.total,
            count=page.returned_count,
            limit=page.limit,
            offset=page.offset,
            has_more=page.has_more,
            next_offset=page.next_offset,
        )