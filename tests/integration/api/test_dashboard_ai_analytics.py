# AI-customer-support-agent\tests\integration\api\test_dashboard_ai_analytics.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from packages.ai.providers.mock import MockLLMProvider


UTC = timezone.utc


def _analytics_params(
    *,
    started_at: datetime,
    ended_at: datetime,
    bucket: str = "hour",
) -> dict[str, str]:
    return {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "bucket": bucket,
    }


def _create_customer_conversation(
    client: TestClient,
    *,
    customer_headers: dict[str, str],
) -> str:
    response = client.post(
        "/v1/conversations",
        headers=customer_headers,
        json={
            "title": "AI analytics integration test",
        },
    )

    assert response.status_code == 201, response.text
    return response.json()["conversation_id"]


def _send_customer_message(
    client: TestClient,
    *,
    customer_headers: dict[str, str],
    conversation_id: str,
) -> Any:
    return client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=customer_headers,
        json={
            "message": "Where is my order ORD-12345?",
        },
    )


def _get_ai_analytics(
    client: TestClient,
    *,
    admin_headers: dict[str, str],
    started_at: datetime,
    ended_at: datetime,
    bucket: str = "hour",
):
    return client.get(
        "/v1/dashboard/ai-analytics",
        headers=admin_headers,
        params=_analytics_params(
            started_at=started_at,
            ended_at=ended_at,
            bucket=bucket,
        ),
    )


def _category_map(
    body: dict[str, Any],
    field_name: str,
) -> dict[str, int]:
    return {
        item["category"]: item["count"]
        for item in body[field_name]
    }


class TestDashboardAIAnalyticsAuthorization:
    def test_requires_authentication(
        self,
        client: TestClient,
    ) -> None:
        now = datetime.now(UTC)

        response = client.get(
            "/v1/dashboard/ai-analytics",
            params=_analytics_params(
                started_at=now - timedelta(hours=1),
                ended_at=now + timedelta(hours=1),
            ),
        )

        assert response.status_code == 401

    def test_rejects_customer(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)

        response = client.get(
            "/v1/dashboard/ai-analytics",
            headers=customer_auth_headers,
            params=_analytics_params(
                started_at=now - timedelta(hours=1),
                ended_at=now + timedelta(hours=1),
            ),
        )

        assert response.status_code == 403

    def test_rejects_support_agent(
        self,
        client: TestClient,
        support_agent_auth_headers: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)

        response = client.get(
            "/v1/dashboard/ai-analytics",
            headers=support_agent_auth_headers,
            params=_analytics_params(
                started_at=now - timedelta(hours=1),
                ended_at=now + timedelta(hours=1),
            ),
        )

        assert response.status_code == 403


class TestDashboardAIAnalytics:
    def test_reports_successful_customer_message_pipeline(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
        admin_auth_headers: dict[str, str],
    ) -> None:
        started_at = datetime.now(UTC) - timedelta(
            minutes=1
        )

        conversation_id = _create_customer_conversation(
            client,
            customer_headers=customer_auth_headers,
        )

        message_response = _send_customer_message(
            client,
            customer_headers=customer_auth_headers,
            conversation_id=conversation_id,
        )

        assert message_response.status_code == 200, (
            message_response.text
        )

        ended_at = datetime.now(UTC) + timedelta(minutes=1)

        response = _get_ai_analytics(
            client,
            admin_headers=admin_auth_headers,
            started_at=started_at,
            ended_at=ended_at,
        )

        assert response.status_code == 200, response.text
        body = response.json()

        assert body["total_runs"] == 1
        assert body["running_runs"] == 0
        assert body["successful_runs"] == 1
        assert body["failed_runs"] == 0
        assert body["cancelled_runs"] == 0
        assert Decimal(str(body["success_rate"])) == Decimal(
            "1"
        )

        assert body["total_llm_calls"] >= 1
        assert body["successful_llm_calls"] >= 1
        assert body["failed_llm_calls"] == 0
        assert body["timed_out_llm_calls"] == 0

        assert body["input_tokens"] >= 0
        assert body["output_tokens"] >= 0
        assert body["cached_input_tokens"] >= 0
        assert Decimal(
            str(body["estimated_cost_usd"])
        ) >= Decimal("0")

        intents = _category_map(
            body,
            "intent_distribution",
        )
        assert intents["order_status"] == 1

        decisions = _category_map(
            body,
            "decision_distribution",
        )
        assert sum(decisions.values()) == 1

        providers = _category_map(
            body,
            "llm_provider_distribution",
        )
        assert sum(providers.values()) == (
            body["total_llm_calls"]
        )

        models = _category_map(
            body,
            "llm_model_distribution",
        )
        assert sum(models.values()) == (
            body["total_llm_calls"]
        )

        assert body["run_duration"]["sample_count"] == 1
        assert (
            body["llm_call_duration"]["sample_count"]
            == body["successful_llm_calls"]
        )

        assert len(body["timeline"]) >= 1
        assert sum(
            point["runs"]
            for point in body["timeline"]
        ) == body["total_runs"]

        assert sum(
            point["llm_calls"]
            for point in body["timeline"]
        ) == body["total_llm_calls"]

    def test_reports_timeout_separately_from_failure(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
        admin_auth_headers: dict[str, str],
        mock_llm_provider: MockLLMProvider,
    ) -> None:
        started_at = datetime.now(UTC) - timedelta(
            minutes=1
        )

        conversation_id = _create_customer_conversation(
            client,
            customer_headers=customer_auth_headers,
        )

        mock_llm_provider.queue_timeout()

        message_response = _send_customer_message(
            client,
            customer_headers=customer_auth_headers,
            conversation_id=conversation_id,
        )

        # The exact API error status belongs to the conversation
        # boundary. This test verifies persisted telemetry.
        assert message_response.status_code == 504
        assert message_response.json()["error"]["code"] == (
            "AI_PROVIDER_TIMEOUT"
        )

        ended_at = datetime.now(UTC) + timedelta(minutes=1)

        response = _get_ai_analytics(
            client,
            admin_headers=admin_auth_headers,
            started_at=started_at,
            ended_at=ended_at,
        )

        assert response.status_code == 200, response.text
        body = response.json()

        assert body["total_runs"] == 1
        assert body["successful_runs"] == 0
        assert body["failed_runs"] == 1

        assert body["total_llm_calls"] == 1
        assert body["successful_llm_calls"] == 0
        assert body["failed_llm_calls"] == 0
        assert body["timed_out_llm_calls"] == 1

        error_codes = _category_map(
            body,
            "llm_error_code_distribution",
        )
        assert error_codes == {"TIMEOUT": 1}

        assert sum(
            point["timed_out_llm_calls"]
            for point in body["timeline"]
        ) == 1

    def test_empty_window_returns_complete_zero_contract(
        self,
        client: TestClient,
        admin_auth_headers: dict[str, str],
    ) -> None:
        started_at = datetime(
            2020,
            1,
            1,
            tzinfo=UTC,
        )
        ended_at = started_at + timedelta(days=3)

        response = _get_ai_analytics(
            client,
            admin_headers=admin_auth_headers,
            started_at=started_at,
            ended_at=ended_at,
            bucket="day",
        )

        assert response.status_code == 200, response.text
        body = response.json()

        for field_name in (
            "total_runs",
            "running_runs",
            "successful_runs",
            "failed_runs",
            "cancelled_runs",
            "total_llm_calls",
            "started_llm_calls",
            "successful_llm_calls",
            "failed_llm_calls",
            "timed_out_llm_calls",
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "retrieval_runs",
            "started_retrieval_runs",
            "successful_retrieval_runs",
            "failed_retrieval_runs",
            "timed_out_retrieval_runs",
            "zero_result_retrievals",
            "reranker_calls",
            "started_reranker_calls",
            "successful_reranker_calls",
            "failed_reranker_calls",
            "timed_out_reranker_calls",
            "embedding_calls",
            "started_embedding_calls",
            "successful_embedding_calls",
            "failed_embedding_calls",
            "timed_out_embedding_calls",
        ):
            assert body[field_name] == 0

        assert Decimal(
            str(body["estimated_cost_usd"])
        ) == Decimal("0")

        assert body["success_rate"] is None
        assert body["zero_result_rate"] is None
        assert (
            body["average_retrieval_result_count"]
            is None
        )

        for field_name in (
            "run_duration",
            "llm_call_duration",
            "retrieval_duration",
            "reranker_duration",
            "embedding_duration",
        ):
            assert body[field_name] == {
                "sample_count": 0,
                "average_ms": None,
                "p50_ms": None,
                "p95_ms": None,
            }

        for field_name in (
            "intent_distribution",
            "decision_distribution",
            "decision_reason_distribution",
            "guardrail_event_distribution",
            "guardrail_error_code_distribution",
            "llm_provider_distribution",
            "llm_model_distribution",
            "llm_error_code_distribution",
            "retrieval_error_code_distribution",
            "reranker_provider_distribution",
            "reranker_model_distribution",
            "reranker_error_code_distribution",
            "embedding_provider_distribution",
            "embedding_model_distribution",
            "embedding_error_code_distribution",
        ):
            assert body[field_name] == []

        assert len(body["timeline"]) == 3

        for point in body["timeline"]:
            for field_name, value in point.items():
                if field_name == "bucket_started_at":
                    continue

                if field_name == "estimated_cost_usd":
                    assert Decimal(str(value)) == Decimal("0")
                else:
                    assert value == 0

    def test_response_does_not_expose_sensitive_payloads(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
        admin_auth_headers: dict[str, str],
    ) -> None:
        started_at = datetime.now(UTC) - timedelta(
            minutes=1
        )

        conversation_id = _create_customer_conversation(
        client,
        customer_headers=customer_auth_headers,
        )

        message_response = _send_customer_message(
            client,
            customer_headers=customer_auth_headers,
            conversation_id=conversation_id,
        )
        assert message_response.status_code == 200

        response = _get_ai_analytics(
            client,
            admin_headers=admin_auth_headers,
            started_at=started_at,
            ended_at=datetime.now(UTC) + timedelta(minutes=1),
        )

        assert response.status_code == 200
        serialized = response.text.casefold()

        for forbidden_name in (
            "error_message",
            "reason_summary",
            "reasoning_summary",
            "entities",
            "metadata_",
            "provider_request_id",
            "query_fingerprint",
            "request_fingerprint",
            "message_content",
            "source_content",
            "prompt_content",
        ):
            assert forbidden_name not in serialized