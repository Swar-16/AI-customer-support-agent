# AI-customer-support-agent\apps\api\app\api\v1\dashboard.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Annotated
from fastapi import APIRouter, HTTPException, Query, status, Depends
import uuid

from apps.api.app.api.dependencies import ApplicationServicesDependency
from apps.api.app.api.v1.schemas.dashboard import DashboardAPIRequestListResponse, DashboardAuditEventListResponse, DashboardLLMCallListResponse, DashboardOverviewResponse
from apps.api.app.api.v1.schemas.dashboard import DashboardRetrievalRunListResponse, DashboardTraceDetailResponse, DashboardTraceListResponse
from packages.application.dashboard.get_overview import GetDashboardOverviewCommand
from packages.application.dashboard.models import DashboardPagination, DashboardTimeRange
from packages.application.dashboard.query_traces import QueryDashboardTracesCommand
from packages.application.dashboard.get_trace_detail import GetTraceDetailCommand
from packages.application.dashboard.query_llm_calls import QueryDashboardLLMCallsCommand
from packages.application.dashboard.query_retrieval_runs import QueryDashboardRetrievalRunsCommand
from packages.application.dashboard.query_api_requests import QueryDashboardAPIRequestsCommand
from packages.application.dashboard.query_audit_events import QueryDashboardAuditEventsCommand
from apps.api.app.api.dependencies import require_roles
from packages.application.auth.models import AuthRole

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_roles(AuthRole.ADMIN))],
)
DEFAULT_OVERVIEW_WINDOW = timedelta(hours=24)
MAX_OVERVIEW_WINDOW = timedelta(days=90)

@router.get(
    "/overview",
    response_model=DashboardOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get dashboard overview",
    description="Return aggregated operational, AI, retrieval, support, feedback, and Knowledge Management metrics for the selected time range.",
)
def get_dashboard_overview(
    services: ApplicationServicesDependency,
    started_at: Annotated[
        datetime | None,
        Query(description="Inclusive reporting-window start. Must include timezone information. Defaults to 24 hours before ended_at."),
    ] = None,
    ended_at: Annotated[
        datetime | None,
        Query(description="Inclusive reporting-window end. Must include timezone information. Defaults to the current UTC time."),
    ] = None,
) -> DashboardOverviewResponse:
    time_range = _resolve_time_range(started_at=started_at, ended_at=ended_at)
    result = services.get_dashboard_overview.execute(GetDashboardOverviewCommand(time_range=time_range))

    return DashboardOverviewResponse.from_application(result)

@router.get(
    "/traces",
    response_model=DashboardTraceListResponse,
    status_code=status.HTTP_200_OK,
    summary="Query dashboard traces",
    description="Return paginated trace summaries correlated across HTTP requests and AI runs.",
)
def query_dashboard_traces(
    services: ApplicationServicesDependency,
    started_at: Annotated[
        datetime | None,
        Query(description="Inclusive trace-window start. Must include timezone information. Defaults to 24 hours before ended_at."),
    ] = None,
    ended_at: Annotated[
        datetime | None,
        Query(description="Inclusive trace-window end. Must include timezone information. Defaults to the current UTC time."),
    ] = None,
    trace_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by exact trace ID."),
    ] = None,
    conversation_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by conversation ID."),
    ] = None,
    ai_run_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by AI-run ID."),
    ] = None,
    trace_status: Annotated[
        str | None,
        Query(alias="status", pattern="^(success|error|running)$", description="Filter by derived trace status."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=500),
    ] = 100,
    offset: Annotated[
        int,
        Query(ge=0),
    ] = 0,
) -> DashboardTraceListResponse:
    time_range = _resolve_time_range(started_at=started_at, ended_at=ended_at)
    result = services.query_dashboard_traces.execute(
        QueryDashboardTracesCommand(
            time_range=time_range,
            pagination=DashboardPagination(limit=limit, offset=offset),
            trace_id=trace_id,
            conversation_id=conversation_id,
            ai_run_id=ai_run_id,
            status=trace_status,
        )
    )

    return DashboardTraceListResponse.from_application(result)

@router.get(
    "/traces/{trace_id}",
    response_model=DashboardTraceDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get dashboard trace detail",
    description="Return a sanitized chronological view of API, AI, retrieval, provider, support-workflow, and audit activity for one trace.",
)
def get_dashboard_trace_detail(trace_id: uuid.UUID, services: ApplicationServicesDependency) -> DashboardTraceDetailResponse:
    result = services.get_dashboard_trace_detail.execute(GetTraceDetailCommand(trace_id=trace_id))
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DASHBOARD_TRACE_NOT_FOUND",
                "message": f"No dashboard trace was found for trace ID {trace_id}.",
            },
        )

    return DashboardTraceDetailResponse.from_application(result)

@router.get(
    "/llm-calls",
    response_model=DashboardLLMCallListResponse,
    status_code=status.HTTP_200_OK,
    summary="Query dashboard LLM calls",
    description="Return paginated and sanitized LLM-call telemetry, including provider, model, token usage, cost, latency, and status.",
)
def query_dashboard_llm_calls(
    services: ApplicationServicesDependency,
    started_at: Annotated[
        datetime | None,
        Query(description="Inclusive LLM-call window start. Must include timezone information. Defaults to 24 hours before ended_at."),
    ] = None,
    ended_at: Annotated[
        datetime | None,
        Query(description="Inclusive LLM-call window end. Must include timezone information. Defaults to the current UTC time."),
    ] = None,
    trace_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by exact trace ID."),
    ] = None,
    conversation_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by conversation ID."),
    ] = None,
    ai_run_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by AI-run ID."),
    ] = None,
    purpose: Annotated[
        str | None,
        Query(
            pattern=(
                "^(intent_classification|query_rewrite|"
                "answer_generation|action_decision|"
                "escalation_summary|guardrail_validation|"
                "conversation_summary|other)$"
            ),
            description="Filter by LLM-call purpose.",
        ),
    ] = None,
    provider: Annotated[
        str | None,
        Query(min_length=1, max_length=100, description="Filter by exact provider name."),
    ] = None,
    model: Annotated[
        str | None,
        Query(min_length=1, max_length=200, description="Filter by exact model name."),
    ] = None,
    call_status: Annotated[
        str | None,
        Query(alias="status", pattern="^(started|success|failed|timeout)$", description="Filter by LLM-call status."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500),] = 100,
    offset: Annotated[int, Query(ge=0),] = 0,
) -> DashboardLLMCallListResponse:
    time_range = _resolve_time_range(started_at=started_at, ended_at=ended_at)
    result = services.query_dashboard_llm_calls.execute(
        QueryDashboardLLMCallsCommand(
            time_range=time_range,
            pagination=DashboardPagination(limit=limit, offset=offset),
            trace_id=trace_id,
            conversation_id=conversation_id,
            ai_run_id=ai_run_id,
            purpose=purpose,
            provider=provider,
            model=model,
            status=call_status,
        )
    )

    return DashboardLLMCallListResponse.from_application(result)

@router.get(
    "/retrieval-runs",
    response_model=DashboardRetrievalRunListResponse,
    status_code=status.HTTP_200_OK,
    summary="Query dashboard retrieval runs",
    description="Return paginated retrieval telemetry including vector, lexical, fusion, reranking, grounding-context, and embedding metrics.",
)
def query_dashboard_retrieval_runs(
    services: ApplicationServicesDependency,
    started_at: Annotated[
        datetime | None,
        Query(description="Inclusive retrieval window start. Must include timezone information. Defaults to 24 hours before ended_at."),
    ] = None,
    ended_at: Annotated[
        datetime | None,
        Query(description="Inclusive retrieval window end. Must include timezone information. Defaults to the current UTC time."),
    ] = None,
    trace_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by exact trace ID."),
    ] = None,
    conversation_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by conversation ID."),
    ] = None,
    ai_run_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by AI-run ID."),
    ] = None,
    retrieval_mode: Annotated[
        str | None,
        Query(pattern="^(vector|lexical|hybrid)$", description="Filter by retrieval mode."),
    ] = None,
    profile_identity: Annotated[
        str | None,
        Query(min_length=1, max_length=255, description="Filter by exact retrieval-profile identity."),
    ] = None,
    retrieval_status: Annotated[
        str | None,
        Query(alias="status", pattern="^(started|success|failed|timeout)$", description="Filter by retrieval-run status."),
    ] = None,
    zero_result: Annotated[
        bool | None,
        Query(description="Filter by whether retrieval selected no context."),
    ] = None,
    reranker_used: Annotated[
        bool | None,
        Query(description="Filter by whether reranking was enabled for the run."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DashboardRetrievalRunListResponse:
    time_range = _resolve_time_range(started_at=started_at, ended_at=ended_at)
    result = services.query_dashboard_retrieval_runs.execute(
        QueryDashboardRetrievalRunsCommand(
            time_range=time_range,
            pagination=DashboardPagination(limit=limit, offset=offset),
            trace_id=trace_id,
            conversation_id=conversation_id,
            ai_run_id=ai_run_id,
            retrieval_mode=retrieval_mode,
            profile_identity=profile_identity,
            status=retrieval_status,
            zero_result=zero_result,
            reranker_used=reranker_used,
        )
    )

    return DashboardRetrievalRunListResponse.from_application(result)

@router.get(
    "/api-requests",
    response_model=DashboardAPIRequestListResponse,
    status_code=status.HTTP_200_OK,
    summary="Query dashboard API requests",
    description="Return paginated and sanitized HTTP request telemetry, including route, status, latency, actor, outcome, and trace correlation.",
)
def query_dashboard_api_requests(
    services: ApplicationServicesDependency,
    started_at: Annotated[
        datetime | None,
        Query(description="Inclusive API-request window start. Must include timezone information. Defaults to 24 hours before ended_at."),
    ] = None,
    ended_at: Annotated[
        datetime | None,
        Query(description="Inclusive API-request window end. Must include timezone information. Defaults to the current UTC time."),
    ] = None,
    trace_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by exact trace ID."),
    ] = None,
    method: Annotated[
        str | None,
        Query(pattern="^(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)$", description="Filter by HTTP method."),
    ] = None,
    route_template: Annotated[
        str | None,
        Query(min_length=1, max_length=500, description="Filter by exact normalized route template."),
    ] = None,
    request_status_code: Annotated[
        int | None,
        Query(alias="status_code", ge=100, le=599, description="Filter by exact HTTP status code."),
    ] = None,
    outcome: Annotated[
        str | None,
        Query(pattern="^(success|client_error|server_error)$", description="Filter by request outcome."),
    ] = None,
    error_code: Annotated[
        str | None,
        Query(min_length=1, max_length=100, description="Filter by stable application error code."),
    ] = None,
    actor_user_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by authenticated actor ID."),
    ] = None,
    actor_role: Annotated[
        str | None,
        Query(min_length=1, max_length=32, description="Filter by authenticated actor role."),
    ] = None,
    minimum_latency_ms: Annotated[
        int | None,
        Query(ge=0, description="Return requests whose latency is at least this value."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500),] = 100,
    offset: Annotated[int, Query(ge=0),] = 0,
) -> DashboardAPIRequestListResponse:
    time_range = _resolve_time_range(started_at=started_at, ended_at=ended_at)

    result = services.query_dashboard_api_requests.execute(
        QueryDashboardAPIRequestsCommand(
            time_range=time_range,
            pagination=DashboardPagination(limit=limit, offset=offset),
            trace_id=trace_id,
            method=method,
            route_template=route_template,
            status_code=request_status_code,
            outcome=outcome,
            error_code=error_code,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            minimum_latency_ms=minimum_latency_ms,
        )
    )

    return DashboardAPIRequestListResponse.from_application(result)

@router.get(
    "/audit-events",
    response_model=DashboardAuditEventListResponse,
    status_code=status.HTTP_200_OK,
    summary="Query dashboard audit events",
    description="Return paginated immutable business-audit events with entity, actor, trace, conversation, and AI-run correlation."
)
def query_dashboard_audit_events(
    services: ApplicationServicesDependency,
    started_at: Annotated[
        datetime | None,
        Query(description="Inclusive audit-event window start. Must include timezone information. Defaults to 24 hours before ended_at."),
    ] = None,
    ended_at: Annotated[
        datetime | None,
        Query(description="Inclusive audit-event window end. Must include timezone information. Defaults to the current UTC time."),
    ] = None,
    event_type: Annotated[
        str | None,
        Query(min_length=1, max_length=100, description="Filter by exact audit event type."),
    ] = None,
    entity_type: Annotated[
        str | None,
        Query(min_length=1, max_length=64, description="Filter by exact audited entity type."),
    ] = None,
    entity_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by audited entity ID."),
    ] = None,
    action: Annotated[
        str | None,
        Query(min_length=1, max_length=64, description="Filter by exact audit action."),
    ] = None,
    actor_type: Annotated[
        str | None,
        Query(pattern="^(customer|agent|admin|system|ai)$", description="Filter by audit actor type."),
    ] = None,
    actor_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by actor user ID."),
    ] = None,
    trace_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by distributed trace ID."),
    ] = None,
    conversation_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by conversation ID."),
    ] = None,
    ai_run_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by AI-run ID."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500),] = 100,
    offset: Annotated[int, Query(ge=0),] = 0,
    
) -> DashboardAuditEventListResponse:
    time_range = _resolve_time_range(started_at=started_at, ended_at=ended_at)

    result = services.query_dashboard_audit_events.execute(
        QueryDashboardAuditEventsCommand(
            time_range=time_range,
            pagination=DashboardPagination(limit=limit, offset=offset),
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            ai_run_id=ai_run_id,
        )
    )

    return DashboardAuditEventListResponse.from_application(result)

def _resolve_time_range(*, started_at: datetime | None, ended_at: datetime | None) -> DashboardTimeRange:
    resolved_end = ended_at if ended_at is not None else datetime.now(timezone.utc)
    resolved_start = started_at if started_at is not None else resolved_end - DEFAULT_OVERVIEW_WINDOW
    for field_name, value in (("started_at", resolved_start), ("ended_at", resolved_end),):
        if value.tzinfo is None or value.utcoffset() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "INVALID_DASHBOARD_TIME_RANGE",
                    "message": f"{field_name} must include timezone information.",
                },
            )

    normalized_start = resolved_start.astimezone(timezone.utc)
    normalized_end = resolved_end.astimezone(timezone.utc)
    if normalized_start > normalized_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVALID_DASHBOARD_TIME_RANGE",
                "message": "started_at cannot be later than ended_at.",
            },
        )

    if normalized_end - normalized_start > MAX_OVERVIEW_WINDOW:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "DASHBOARD_TIME_RANGE_TOO_LARGE",
                "message": "The dashboard query time range cannot exceed 90 days.",
            },
        )

    return DashboardTimeRange(started_at=normalized_start, ended_at=normalized_end)