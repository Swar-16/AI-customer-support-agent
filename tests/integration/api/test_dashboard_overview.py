# AI-customer-support-agent\tests\integration\api\test_dashboard_overview.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from packages.database.models.audit.api_request import APIRequestModel


pytestmark = pytest.mark.integration

EXPECTED_SECTION_KEYS = {
    "api",
    "ai_runs",
    "llm",
    "retrieval",
    "escalations",
    "tickets",
    "feedback",
    "knowledge",
}


@pytest.fixture(autouse=True)
def isolate_database(clean_database):
    """
    Ensure dashboard assertions are isolated from telemetry produced by
    earlier integration tests.
    """
    yield


def _sections_by_key(
    response_body: dict,
) -> dict[str, dict]:
    return {
        section["key"]: section
        for section in response_body["sections"]
    }


def _metrics_by_key(
    section: dict,
) -> dict[str, dict]:
    return {
        metric["key"]: metric
        for metric in section["metrics"]
    }


class TestDashboardOverview:
    def test_default_range_returns_all_overview_sections(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/v1/dashboard/overview")

        assert response.status_code == 200

        body = response.json()

        assert set(_sections_by_key(body)) == EXPECTED_SECTION_KEYS
        assert body["generated_at"] is not None

        started_at = datetime.fromisoformat(
            body["time_range"]["started_at"]
        )
        ended_at = datetime.fromisoformat(
            body["time_range"]["ended_at"]
        )

        assert started_at.tzinfo is not None
        assert ended_at.tzinfo is not None
        assert started_at <= ended_at

        actual_duration = ended_at - started_at

        assert actual_duration == timedelta(hours=24)

        for section in body["sections"]:
            assert section["key"]
            assert section["title"]
            assert section["metrics"]

            metric_keys = [
                metric["key"]
                for metric in section["metrics"]
            ]

            assert len(metric_keys) == len(set(metric_keys))

    def test_accepts_explicit_timezone_aware_range(
        self,
        client: TestClient,
    ) -> None:
        started_at = datetime(
            2026,
            9,
            1,
            0,
            0,
            tzinfo=timezone.utc,
        )
        ended_at = datetime(
            2026,
            9,
            2,
            0,
            0,
            tzinfo=timezone.utc,
        )

        response = client.get(
            "/v1/dashboard/overview",
            params={
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
            },
        )

        assert response.status_code == 200

        body = response.json()

        returned_start = datetime.fromisoformat(
            body["time_range"]["started_at"]
        )
        returned_end = datetime.fromisoformat(
            body["time_range"]["ended_at"]
        )

        assert returned_start == started_at
        assert returned_end == ended_at

    def test_future_range_returns_zero_time_bound_metrics(
        self,
        client: TestClient,
    ) -> None:
        started_at = datetime.now(timezone.utc) + timedelta(days=1)
        ended_at = started_at + timedelta(hours=1)

        response = client.get(
            "/v1/dashboard/overview",
            params={
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
            },
        )

        assert response.status_code == 200

        sections = _sections_by_key(response.json())

        api_metrics = _metrics_by_key(sections["api"])
        ai_metrics = _metrics_by_key(sections["ai_runs"])
        llm_metrics = _metrics_by_key(sections["llm"])
        retrieval_metrics = _metrics_by_key(
            sections["retrieval"]
        )
        escalation_metrics = _metrics_by_key(
            sections["escalations"]
        )
        ticket_metrics = _metrics_by_key(sections["tickets"])
        feedback_metrics = _metrics_by_key(
            sections["feedback"]
        )
        knowledge_metrics = _metrics_by_key(
            sections["knowledge"]
        )

        assert api_metrics["total_requests"]["value"] == 0
        assert ai_metrics["total_runs"]["value"] == 0
        assert llm_metrics["total_calls"]["value"] == 0
        assert retrieval_metrics["total_runs"]["value"] == 0

        assert (
            escalation_metrics["created_escalations"]["value"]
            == 0
        )
        assert ticket_metrics["created_tickets"]["value"] == 0
        assert (
            feedback_metrics["submitted_feedback"]["value"]
            == 0
        )
        assert (
            knowledge_metrics["created_documents"]["value"]
            == 0
        )
        assert (
            knowledge_metrics["created_versions"]["value"]
            == 0
        )

    def test_rejects_reversed_range(
        self,
        client: TestClient,
    ) -> None:
        started_at = datetime(
            2026,
            9,
            2,
            tzinfo=timezone.utc,
        )
        ended_at = datetime(
            2026,
            9,
            1,
            tzinfo=timezone.utc,
        )

        response = client.get(
            "/v1/dashboard/overview",
            params={
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
            },
        )

        assert response.status_code == 422

        error = response.json()["error"]

        assert error["code"] == "INVALID_DASHBOARD_TIME_RANGE"

    def test_rejects_naive_datetime(
        self,
        client: TestClient,
    ) -> None:
        response = client.get(
            "/v1/dashboard/overview",
            params={
                "started_at": "2026-09-01T00:00:00",
                "ended_at": "2026-09-02T00:00:00+00:00",
            },
        )

        assert response.status_code == 422

        error = response.json()["error"]

        assert error["code"] == "INVALID_DASHBOARD_TIME_RANGE"

    def test_rejects_range_larger_than_ninety_days(
        self,
        client: TestClient,
    ) -> None:
        started_at = datetime(
            2026,
            1,
            1,
            tzinfo=timezone.utc,
        )
        ended_at = started_at + timedelta(days=91)

        response = client.get(
            "/v1/dashboard/overview",
            params={
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
            },
        )

        assert response.status_code == 422

        error = response.json()["error"]

        assert error["code"] == "DASHBOARD_TIME_RANGE_TOO_LARGE"

    def test_dashboard_request_is_recorded(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        response = client.get("/v1/dashboard/overview")
        import uuid

        trace_id = uuid.UUID(response.headers["X-Trace-ID"])

        with test_session_factory() as session:
            latest = session.scalar(
                select(APIRequestModel).where(
                    APIRequestModel.trace_id == trace_id
                )
            )

        assert latest is not None
        assert latest.request_path == "/v1/dashboard/overview"
        assert latest.route_template == "/v1/dashboard/overview"