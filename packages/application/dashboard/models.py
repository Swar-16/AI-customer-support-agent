# AI-customer-support-agent\packages\application\dashboard\models.py
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Generic, TypeVar

T = TypeVar("T")
MAX_PAGE_SIZE = 500

class DashboardSortDirection(StrEnum):
    ASCENDING = "asc"
    DESCENDING = "desc"

class DashboardTimeBucket(StrEnum):
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"

@dataclass(frozen=True, slots=True)
class DashboardTimeRange:
    """
    Inclusive dashboard reporting interval.

    All values are normalized to UTC so repositories receive a consistent query boundary regardless of the API client's timezone.
    """
    started_at: datetime
    ended_at: datetime

    def __post_init__(self) -> None:
        self._validate_datetime(self.started_at, field_name="started_at")
        self._validate_datetime(self.ended_at, field_name="ended_at")
        normalized_start = self.started_at.astimezone(timezone.utc)
        normalized_end = self.ended_at.astimezone(timezone.utc)
        if normalized_start > normalized_end:
            raise ValueError("started_at cannot be later than ended_at")

        object.__setattr__(self, "started_at", normalized_start)
        object.__setattr__(self, "ended_at", normalized_end)

    @property
    def duration_seconds(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()

    def contains(self, value: datetime) -> bool:
        self._validate_datetime(value, field_name="value")
        normalized = value.astimezone(timezone.utc)

        return self.started_at <= normalized <= self.ended_at

    @staticmethod
    def _validate_datetime(value: datetime, *, field_name: str) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")

@dataclass(frozen=True, slots=True)
class DashboardPagination:
    """Offset-based pagination used by dashboard explorer endpoints."""
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer")

        if isinstance(self.offset, bool) or not isinstance(self.offset, int):
            raise TypeError("offset must be an integer")

        if self.limit <= 0:
            raise ValueError("limit must be greater than zero")

        if self.limit > MAX_PAGE_SIZE:
            raise ValueError(f"limit must not exceed {MAX_PAGE_SIZE}")

        if self.offset < 0:
            raise ValueError("offset must not be negative")

    @property
    def next_offset(self) -> int:
        return self.offset + self.limit


@dataclass(frozen=True, slots=True)
class DashboardTraceFilters:
    """
    Shared correlation filters for trace-oriented dashboard queries.

    Domain-specific filters such as provider, intent, stage, or HTTP status remain in their respective query commands.
    """
    time_range: DashboardTimeRange
    trace_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    ai_run_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.time_range, DashboardTimeRange):
            raise TypeError("time_range must be a DashboardTimeRange")

        for field_name, value in (("trace_id", self.trace_id), ("conversation_id", self.conversation_id), ("ai_run_id", self.ai_run_id),):
            if value is not None and not isinstance(value, uuid.UUID):
                raise TypeError(f"{field_name} must be a UUID or None")


@dataclass(frozen=True, slots=True)
class DashboardMetric:
    """
    One named dashboard KPI.

    `value` must be an aggregate rather than a raw customer or provider payload. Optional metadata may describe units or calculation details.
    """
    key: str
    value: int | float
    unit: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.key, str):
            raise TypeError("key must be a string")

        normalized_key = self.key.strip().lower()
        if not normalized_key:
            raise ValueError("key cannot be blank")

        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("value must be an integer or float")

        if self.unit is not None:
            if not isinstance(self.unit, str):
                raise TypeError("unit must be a string or None")

            normalized_unit = self.unit.strip().lower()
            if not normalized_unit:
                raise ValueError("unit cannot be blank")

            object.__setattr__(self, "unit", normalized_unit)

        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary")

        object.__setattr__(self, "key", normalized_key)
        object.__setattr__(self, "metadata", dict(self.metadata))

@dataclass(frozen=True, slots=True)
class DashboardTimeSeriesPoint:
    """One aggregate metric value for one time bucket."""
    bucket_started_at: datetime
    value: int | float

    def __post_init__(self) -> None:
        DashboardTimeRange._validate_datetime(self.bucket_started_at, field_name="bucket_started_at")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("value must be an integer or float")

        object.__setattr__(self, "bucket_started_at", self.bucket_started_at.astimezone(timezone.utc))

@dataclass(frozen=True, slots=True)
class DashboardPage(Generic[T]):
    """Immutable page returned by dashboard explorer queries."""
    items: tuple[T, ...]
    total: int
    limit: int
    offset: int

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise TypeError("items must be a tuple")

        for field_name, value in (("total", self.total), ("limit", self.limit), ("offset", self.offset),):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")

        if self.total < 0:
            raise ValueError("total must not be negative")

        if self.limit <= 0:
            raise ValueError("limit must be greater than zero")

        if self.limit > MAX_PAGE_SIZE:
            raise ValueError(f"limit must not exceed {MAX_PAGE_SIZE}")

        if self.offset < 0:
            raise ValueError("offset must not be negative")

        if len(self.items) > self.limit:
            raise ValueError("items cannot contain more records than limit")

    @property
    def returned_count(self) -> int:
        return len(self.items)

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total

    @property
    def next_offset(self) -> int | None:
        if not self.has_more:
            return None

        return self.offset + len(self.items)