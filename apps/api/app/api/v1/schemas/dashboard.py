# AI-customer-support-agent\apps\api\app\api\v1\schemas\dashboard.py
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from packages.application.dashboard.get_overview import DashboardOverviewResult, DashboardOverviewSection
from packages.application.dashboard.models import DashboardMetric

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