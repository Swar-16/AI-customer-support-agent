# AI-customer-support-agent\tests\integration\api\test_dashboard_trace_detail.py

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolate_database(clean_database):
    """Keep trace-detail assertions independent of other tests."""
    yield


def _create_customer_message_trace(
    *,
    client: TestClient,
    conversation_id: uuid.UUID,
    trace_id: uuid.UUID,
    customer_message: str = "Where is my order ORD-12345?",
) -> dict[str, Any]:
    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers={
            "X-Trace-ID": str(trace_id),
        },
        json={
            "message": customer_message,
        },
    )

    assert response.status_code == 200

    return response.json()


def _timeline_categories(
    body: dict[str, Any],
) -> set[str]:
    return {
        event["category"]
        for event in body["timeline"]
    }


def _walk_dictionary_keys(
    value: Any,
) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            yield key
            yield from _walk_dictionary_keys(nested_value)

    elif isinstance(value, list):
        for item in value:
            yield from _walk_dictionary_keys(item)


class TestDashboardTraceDetail:
    def test_returns_correlated_customer_message_trace(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
    ) -> None:
        trace_id = uuid7()

        message_result = _create_customer_message_trace(
            client=client,
            conversation_id=seeded_conversation,
            trace_id=trace_id,
        )

        response = client.get(
            f"/v1/dashboard/traces/{trace_id}"
        )

        assert response.status_code == 200

        body = response.json()

        assert body["trace_id"] == str(trace_id)
        assert body["status"] == "success"
        assert body["started_at"] is not None
        assert body["ended_at"] is not None
        assert body["duration_ms"] >= 0

        assert body["conversation_ids"] == [
            str(seeded_conversation)
        ]
        assert body["ai_run_ids"] == [
            message_result["ai_run_id"]
        ]

        counts = body["component_counts"]

        assert counts["api_requests"] == 1
        assert counts["ai_runs"] == 1
        assert counts["stage_events"] >= 1
        assert counts["llm_calls"] == 1

        categories = _timeline_categories(body)

        assert "api" in categories
        assert "ai_run" in categories
        assert "ai_stage" in categories
        assert "llm" in categories

    def test_timeline_is_chronological(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
    ) -> None:
        trace_id = uuid7()

        _create_customer_message_trace(
            client=client,
            conversation_id=seeded_conversation,
            trace_id=trace_id,
        )

        response = client.get(
            f"/v1/dashboard/traces/{trace_id}"
        )

        assert response.status_code == 200

        timeline = response.json()["timeline"]

        assert timeline

        occurred_at_values = [
            event["occurred_at"]
            for event in timeline
        ]

        assert occurred_at_values == sorted(
            occurred_at_values
        )

    def test_returns_api_only_trace(
        self,
        client: TestClient,
    ) -> None:
        trace_id = uuid7()

        health_response = client.get(
            "/v1/health",
            headers={
                "X-Trace-ID": str(trace_id),
            },
        )

        assert health_response.status_code == 200

        response = client.get(
            f"/v1/dashboard/traces/{trace_id}"
        )

        assert response.status_code == 200

        body = response.json()
        counts = body["component_counts"]

        assert body["trace_id"] == str(trace_id)
        assert body["status"] == "success"
        assert counts["api_requests"] == 1
        assert counts["ai_runs"] == 0
        assert counts["stage_events"] == 0
        assert counts["llm_calls"] == 0
        assert counts["embedding_calls"] == 0
        assert counts["retrieval_runs"] == 0
        assert counts["retrieval_candidates"] == 0
        assert counts["reranker_calls"] == 0

        assert _timeline_categories(body) == {"api"}

    def test_unknown_trace_returns_not_found(
        self,
        client: TestClient,
    ) -> None:
        unknown_trace_id = uuid7()

        response = client.get(
            f"/v1/dashboard/traces/{unknown_trace_id}"
        )

        assert response.status_code == 404

        error = response.json()["error"]

        assert error["code"] == "DASHBOARD_TRACE_NOT_FOUND"

    def test_invalid_trace_id_returns_validation_error(
        self,
        client: TestClient,
    ) -> None:
        response = client.get(
            "/v1/dashboard/traces/not-a-uuid"
        )

        assert response.status_code == 422

    def test_does_not_expose_sensitive_payloads(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
    ) -> None:
        trace_id = uuid7()
        secret_customer_message = (
            "SECRET-CUSTOMER-CONTENT-DO-NOT-EXPOSE"
        )

        _create_customer_message_trace(
            client=client,
            conversation_id=seeded_conversation,
            trace_id=trace_id,
            customer_message=secret_customer_message,
        )

        response = client.get(
            f"/v1/dashboard/traces/{trace_id}"
        )

        assert response.status_code == 200

        body = response.json()
        serialized_body = response.text

        assert secret_customer_message not in serialized_body

        returned_keys = set(
            _walk_dictionary_keys(body)
        )

        prohibited_keys = {
            "prompt",
            "system_prompt",
            "user_prompt",
            "response",
            "content",
            "source_content",
            "vector",
            "embedding",
            "error_message",
            "description",
            "subject",
            "resolution_summary",
            "handoff_summary",
            "comment",
            "review_notes",
            "before_state",
            "after_state",
            "metadata",
            "metadata_",
            "client_ip",
            "user_agent",
        }

        assert returned_keys.isdisjoint(prohibited_keys)

    def test_component_counts_match_timeline_categories(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
    ) -> None:
        trace_id = uuid7()

        _create_customer_message_trace(
            client=client,
            conversation_id=seeded_conversation,
            trace_id=trace_id,
        )

        response = client.get(
            f"/v1/dashboard/traces/{trace_id}"
        )

        assert response.status_code == 200

        body = response.json()
        timeline = body["timeline"]
        counts = body["component_counts"]

        category_counts = {
            category: sum(
                event["category"] == category
                for event in timeline
            )
            for category in {
                event["category"]
                for event in timeline
            }
        }

        assert (
            category_counts.get("api", 0)
            == counts["api_requests"]
        )
        assert (
            category_counts.get("ai_run", 0)
            == counts["ai_runs"]
        )
        assert (
            category_counts.get("ai_stage", 0)
            == counts["stage_events"]
        )
        assert (
            category_counts.get("llm", 0)
            == counts["llm_calls"]
        )
        assert (
            category_counts.get("embedding", 0)
            == counts["embedding_calls"]
        )
        assert (
            category_counts.get("retrieval", 0)
            == counts["retrieval_runs"]
        )
        assert (
            category_counts.get(
                "retrieval_candidate",
                0,
            )
            == counts["retrieval_candidates"]
        )
        assert (
            category_counts.get("reranker", 0)
            == counts["reranker_calls"]
        )
        assert (
            category_counts.get("escalation", 0)
            == counts["escalations"]
        )
        assert (
            category_counts.get("ticket", 0)
            == counts["tickets"]
        )
        assert (
            category_counts.get("feedback", 0)
            == counts["feedback"]
        )
        assert (
            category_counts.get(
                "business_audit",
                0,
            )
            == counts["audit_events"]
        )