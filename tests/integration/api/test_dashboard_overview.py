# AI-customer-support-agent\tests\integration\api\test_dashboard_overview.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
import uuid
from uuid6 import uuid7

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
    
def _trace_query_range() -> dict[str, str]:
    now = datetime.now(timezone.utc)

    return {
        "started_at": (
            now - timedelta(minutes=5)
        ).isoformat(),
        "ended_at": (
            now + timedelta(minutes=5)
        ).isoformat(),
    }


class TestDashboardTraceQueries:
    def test_lists_api_only_trace(
        self,
        client: TestClient,
    ) -> None:
        trace_id = uuid7()

        source_response = client.get(
            "/v1/health",
            headers={
                "X-Trace-ID": str(trace_id),
            },
        )

        assert source_response.status_code == 200

        response = client.get(
            "/v1/dashboard/traces",
            params={
                **_trace_query_range(),
                "trace_id": str(trace_id),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1
        assert body["has_more"] is False
        assert body["next_offset"] is None

        trace = body["items"][0]

        assert trace["trace_id"] == str(trace_id)
        assert trace["status"] == "success"
        assert trace["api_request_count"] == 1
        assert trace["ai_run_count"] == 0
        assert trace["failed_api_request_count"] == 0
        assert trace["failed_ai_run_count"] == 0
        assert trace["running_ai_run_count"] == 0
        assert trace["maximum_api_latency_ms"] is not None
        assert trace["maximum_api_latency_ms"] >= 0
        assert trace["maximum_ai_latency_ms"] is None

    def test_correlates_api_request_and_ai_run(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
    ) -> None:
        trace_id = uuid7()

        message_response = client.post(
            (
                f"/v1/conversations/"
                f"{seeded_conversation}/messages"
            ),
            headers={
                "X-Trace-ID": str(trace_id),
            },
            json={
                "message": "Where is my order ORD-12345?",
            },
        )

        assert message_response.status_code == 200

        message_body = message_response.json()
        ai_run_id = uuid.UUID(message_body["ai_run_id"])

        response = client.get(
            "/v1/dashboard/traces",
            params={
                **_trace_query_range(),
                "trace_id": str(trace_id),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1

        trace = body["items"][0]

        assert trace["trace_id"] == str(trace_id)
        assert trace["status"] == "success"
        assert trace["api_request_count"] == 1
        assert trace["ai_run_count"] == 1
        assert trace["failed_api_request_count"] == 0
        assert trace["failed_ai_run_count"] == 0
        assert trace["running_ai_run_count"] == 0
        assert trace["maximum_api_latency_ms"] is not None
        assert trace["maximum_ai_latency_ms"] is not None

        by_conversation = client.get(
            "/v1/dashboard/traces",
            params={
                **_trace_query_range(),
                "conversation_id": str(seeded_conversation),
            },
        )

        assert by_conversation.status_code == 200
        assert by_conversation.json()["total"] == 1
        assert (
            by_conversation.json()["items"][0]["trace_id"]
            == str(trace_id)
        )

        by_ai_run = client.get(
            "/v1/dashboard/traces",
            params={
                **_trace_query_range(),
                "ai_run_id": str(ai_run_id),
            },
        )

        assert by_ai_run.status_code == 200
        assert by_ai_run.json()["total"] == 1
        assert (
            by_ai_run.json()["items"][0]["trace_id"]
            == str(trace_id)
        )

    def test_filters_error_traces(
        self,
        client: TestClient,
    ) -> None:
        trace_id = uuid7()

        invalid_response = client.get(
            "/v1/dashboard/overview",
            headers={
                "X-Trace-ID": str(trace_id),
            },
            params={
                "started_at": "2026-09-02T00:00:00+00:00",
                "ended_at": "2026-09-01T00:00:00+00:00",
            },
        )

        assert invalid_response.status_code == 422

        response = client.get(
            "/v1/dashboard/traces",
            params={
                **_trace_query_range(),
                "trace_id": str(trace_id),
                "status": "error",
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1

        trace = body["items"][0]

        assert trace["trace_id"] == str(trace_id)
        assert trace["status"] == "error"
        assert trace["api_request_count"] == 1
        assert trace["failed_api_request_count"] == 1
        assert trace["ai_run_count"] == 0

        success_filter = client.get(
            "/v1/dashboard/traces",
            params={
                **_trace_query_range(),
                "trace_id": str(trace_id),
                "status": "success",
            },
        )

        assert success_filter.status_code == 200
        assert success_filter.json()["total"] == 0
        assert success_filter.json()["items"] == []

    def test_paginates_trace_results(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        first_trace_id = uuid7()
        second_trace_id = uuid7()

        for trace_id in (
            first_trace_id,
            second_trace_id,
        ):
            response = client.get(
                "/v1/health",
                headers={
                    "X-Trace-ID": str(trace_id),
                },
            )

            assert response.status_code == 200
            
        with test_session_factory() as session:
            recorded_started_at = tuple(
                session.scalars(
                    select(APIRequestModel.started_at)
                    .where(
                        APIRequestModel.trace_id.in_(
                            (
                                first_trace_id,
                                second_trace_id,
                            )
                        )
                    )
                )
            )

        assert len(recorded_started_at) == 2

        query_ended_at = max(recorded_started_at)

        query_range = {
            "started_at": (
                query_ended_at - timedelta(minutes=5)
            ).isoformat(),
            "ended_at": query_ended_at.isoformat(),
        }

        first_page = client.get(
            "/v1/dashboard/traces",
            params={
                **query_range,
                "limit": 1,
                "offset": 0,
            },
        )

        assert first_page.status_code == 200

        first_body = first_page.json()

        assert first_body["total"] == 2
        assert first_body["count"] == 1
        assert first_body["limit"] == 1
        assert first_body["offset"] == 0
        assert first_body["has_more"] is True
        assert first_body["next_offset"] == 1

        second_page = client.get(
            "/v1/dashboard/traces",
            params={
                **query_range,
                "limit": 1,
                "offset": 1,
            },
        )

        assert second_page.status_code == 200

        second_body = second_page.json()

        # The first trace-list request is recorded after its response, so it
        # becomes another trace visible to the second query. Pagination must
        # nevertheless remain internally consistent.
        assert second_body["total"] == 2
        assert second_body["count"] == 1
        assert second_body["offset"] == 1
        assert second_body["has_more"] is False
        assert second_body["next_offset"] is None

        assert (
            first_body["items"][0]["trace_id"]
            != second_body["items"][0]["trace_id"]
        )
        
        # assert second_body["total"] == first_body["total"]
        # assert second_body["count"] == 1
        # assert second_body["offset"] == 1

        # expected_has_more = second_body["total"] > 2

        # assert second_body["has_more"] is expected_has_more
        # assert second_body["next_offset"] == (
        #     2 if expected_has_more else None
        # )

        # assert (
        #     first_body["items"][0]["trace_id"]
        #     != second_body["items"][0]["trace_id"]
        # )

    def test_rejects_invalid_trace_status(
        self,
        client: TestClient,
    ) -> None:
        response = client.get(
            "/v1/dashboard/traces",
            params={
                **_trace_query_range(),
                "status": "unknown",
            },
        )

        assert response.status_code == 422


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