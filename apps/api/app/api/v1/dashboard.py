# AI-customer-support-agent\apps\api\app\api\v1\dashboard.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Annotated
from fastapi import APIRouter, HTTPException, Query, status

from apps.api.app.api.dependencies import ApplicationServicesDependency
from apps.api.app.api.v1.schemas.dashboard import DashboardOverviewResponse
from packages.application.dashboard.get_overview import GetDashboardOverviewCommand
from packages.application.dashboard.models import DashboardTimeRange

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
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
                "message": "The dashboard overview time range cannot exceed 90 days.",
            },
        )

    return DashboardTimeRange(started_at=normalized_start, ended_at=normalized_end)