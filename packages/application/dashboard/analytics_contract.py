# AI-customer-support-agent\packages\application\dashboard\analytics_contract.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Final

UTC: Final = timezone.utc

class DashboardAnalyticsError(ValueError):
    """Base error for invalid dashboard analytics requests."""

class InvalidAnalyticsTimestampError(DashboardAnalyticsError):
    def __init__(self, *, field_name: str) -> None:
        self.field_name = field_name
        super().__init__(f"{field_name} must be a timezone-aware datetime.")

class InvalidAnalyticsWindowError(DashboardAnalyticsError):
    def __init__(self) -> None:
        super().__init__("started_at must be earlier than ended_at.")

class AnalyticsRangeTooLargeError(DashboardAnalyticsError):
    def __init__(self, *, bucket: "AnalyticsBucket", maximum_duration: timedelta) -> None:
        self.bucket = bucket
        self.maximum_duration = maximum_duration
        super().__init__(f"The requested analytics range is too large for the {bucket.value!r} bucket.")

class UnsupportedAnalyticsBucketError(DashboardAnalyticsError):
    def __init__(self, bucket: object) -> None:
        self.bucket = bucket
        super().__init__("Analytics bucket must be one of: hour, day, week.")

class DashboardAnalyticsAccessDeniedError(PermissionError):
    """Raised when a principal cannot access dashboard analytics."""
    def __init__(self) -> None:
        super().__init__("Dashboard analytics are restricted to administrators.")


class AnalyticsBucket(str, Enum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"

_MAXIMUM_WINDOW_BY_BUCKET: Final[dict[AnalyticsBucket, timedelta]] = {
    AnalyticsBucket.HOUR: timedelta(days=31), AnalyticsBucket.DAY: timedelta(days=731), AnalyticsBucket.WEEK: timedelta(days=1_827),
}

@dataclass(frozen=True, slots=True)
class AnalyticsWindow:
    """
    Validated UTC analytics interval.

    The interval is half-open:

        started_at <= timestamp < ended_at

    This prevents records on adjacent windows from being counted twice.
    """
    started_at: datetime
    ended_at: datetime
    bucket: AnalyticsBucket

    def __post_init__(self) -> None:
        if not isinstance(self.started_at, datetime):
            raise TypeError("started_at must be a datetime.")

        if not isinstance(self.ended_at, datetime):
            raise TypeError("ended_at must be a datetime.")

        if not isinstance(self.bucket, AnalyticsBucket):
            raise UnsupportedAnalyticsBucketError(self.bucket)

        self._validate_timezone(value=self.started_at, field_name="started_at")
        self._validate_timezone(value=self.ended_at, field_name="ended_at")
        normalized_started_at = self.started_at.astimezone(UTC)
        normalized_ended_at = self.ended_at.astimezone(UTC)
        if normalized_started_at >= normalized_ended_at:
            raise InvalidAnalyticsWindowError()

        duration = normalized_ended_at - normalized_started_at
        maximum_duration = _MAXIMUM_WINDOW_BY_BUCKET[self.bucket]
        if duration > maximum_duration:
            raise AnalyticsRangeTooLargeError(bucket=self.bucket, maximum_duration=maximum_duration)

        object.__setattr__(self, "started_at", normalized_started_at)
        object.__setattr__(self, "ended_at", normalized_ended_at)

    @property
    def duration(self) -> timedelta:
        return self.ended_at - self.started_at

    @staticmethod
    def _validate_timezone(*, value: datetime, field_name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidAnalyticsTimestampError(field_name=field_name)