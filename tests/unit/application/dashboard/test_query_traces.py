# AI-customer-support-agent\tests\unit\application\dashboard\test_query_traces.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from packages.application.dashboard.models import DashboardPagination, DashboardTimeRange
from packages.application.dashboard.query_traces import (
    QueryDashboardTraces,
    QueryDashboardTracesCommand,
)
from packages.database.repositories.dashboard import DashboardTraceRepository


def _make_time_range() -> DashboardTimeRange:
    now = datetime.now(timezone.utc)
    return DashboardTimeRange(
        started_at=now,
        ended_at=now,
    )


def test_query_traces_command_validates_has_ai_runs():
    time_range = _make_time_range()

    # Valid values
    cmd1 = QueryDashboardTracesCommand(time_range=time_range, has_ai_runs=True)
    assert cmd1.has_ai_runs is True

    cmd2 = QueryDashboardTracesCommand(time_range=time_range, has_ai_runs=False)
    assert cmd2.has_ai_runs is False

    cmd3 = QueryDashboardTracesCommand(time_range=time_range, has_ai_runs=None)
    assert cmd3.has_ai_runs is None

    # Invalid values
    with pytest.raises(TypeError, match="has_ai_runs must be a bool or None"):
        QueryDashboardTracesCommand(time_range=time_range, has_ai_runs="true")  # type: ignore[arg-type]


def test_query_traces_passes_has_ai_runs_to_repository():
    time_range = _make_time_range()
    cmd = QueryDashboardTracesCommand(
        time_range=time_range,
        pagination=DashboardPagination(limit=25, offset=0),
        has_ai_runs=True,
    )

    mock_repository = MagicMock(spec=DashboardTraceRepository)
    mock_repository.query_traces.return_value = ((), 0)

    mock_uow = MagicMock()
    mock_uow.dashboard_trace = mock_repository
    mock_uow.__enter__.return_value = mock_uow

    service = QueryDashboardTraces(uow_factory=lambda: mock_uow)
    page = service.execute(cmd)

    assert page.total == 0
    assert page.items == ()
    mock_repository.query_traces.assert_called_once_with(
        started_at=time_range.started_at,
        ended_at=time_range.ended_at,
        trace_id=None,
        conversation_id=None,
        ai_run_id=None,
        status=None,
        has_ai_runs=True,
        limit=25,
        offset=0,
    )
