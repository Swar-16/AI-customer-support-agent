# AI-customer-support-agent\tests\integration\api\test_dashboard_llm_calls.py

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.support.conversation import ConversationModel

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolate_database(clean_database):
    """Keep LLM dashboard assertions independent of other tests."""
    yield

@pytest.fixture()
def seeded_conversation(
    test_session_factory,
    customer_identity,
) -> uuid.UUID:
    conversation_id = uuid7()

    with test_session_factory() as session:
        session.add(
            ConversationModel(
                id=conversation_id,
                user_id=customer_identity.user_id,
                status="open",
                channel="web",
                title="Dashboard LLM telemetry test",
            )
        )
        session.commit()

    return conversation_id

def _create_llm_call(
    *,
    admin_client: TestClient,
    customer_auth_headers: dict[str, str],
    conversation_id: uuid.UUID,
    trace_id: uuid.UUID,
    message: str = "Where is my order ORD-12345?",
) -> dict[str, Any]:
    response = admin_client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers={
            **customer_auth_headers,
            "X-Trace-ID": str(trace_id),
        },
        json={
            "message": message,
        },
    )

    assert response.status_code == 200, response.text

    return response.json()


class TestDashboardLLMCalls:
    def test_returns_correlated_llm_call(
        self,
        admin_client: TestClient,
        seeded_conversation: uuid.UUID,
        customer_auth_headers: dict[str, str],
    ) -> None:
        trace_id = uuid7()

        message_result = _create_llm_call(
            admin_client=admin_client,
            customer_auth_headers=customer_auth_headers,
            conversation_id=seeded_conversation,
            trace_id=trace_id,
        )

        response = admin_client.get(
            "/v1/dashboard/llm-calls",
            params={
                "trace_id": str(trace_id),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1
        assert body["limit"] == 100
        assert body["offset"] == 0
        assert body["has_more"] is False
        assert body["next_offset"] is None

        call = body["items"][0]

        assert uuid.UUID(call["id"])
        assert call["ai_run_id"] == message_result["ai_run_id"]
        assert call["trace_id"] == str(trace_id)
        assert call["conversation_id"] == str(
            seeded_conversation
        )
        assert call["purpose"] == "intent_classification"
        assert call["status"] == "success"
        assert call["provider"]
        assert call["model"]
        assert call["input_tokens"] >= 0
        assert call["output_tokens"] >= 0
        assert call["cached_input_tokens"] >= 0
        assert call["total_tokens"] >= 0
        assert call["latency_ms"] is not None
        assert call["latency_ms"] >= 0
        assert call["started_at"] is not None
        assert call["completed_at"] is not None

    def test_filters_by_ai_run_and_conversation(
        self,
        admin_client: TestClient,
        seeded_conversation: uuid.UUID,
        customer_auth_headers: dict[str, str],
    ) -> None:
        trace_id = uuid7()

        message_result = _create_llm_call(
            admin_client=admin_client,
            customer_auth_headers=customer_auth_headers,
            conversation_id=seeded_conversation,
            trace_id=trace_id,
        )

        response = admin_client.get(
            "/v1/dashboard/llm-calls",
            params={
                "ai_run_id": message_result["ai_run_id"],
                "conversation_id": str(
                    seeded_conversation
                ),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["items"][0]["ai_run_id"] == (
            message_result["ai_run_id"]
        )
        assert body["items"][0]["conversation_id"] == (
            str(seeded_conversation)
        )

    def test_filters_by_provider_model_purpose_and_status(
        self,
        admin_client: TestClient,
        seeded_conversation: uuid.UUID,
        customer_auth_headers: dict[str, str],
    ) -> None:
        trace_id = uuid7()

        _create_llm_call(
            admin_client=admin_client,
            customer_auth_headers=customer_auth_headers,
            conversation_id=seeded_conversation,
            trace_id=trace_id,
        )

        initial_response = admin_client.get(
            "/v1/dashboard/llm-calls",
            params={
                "trace_id": str(trace_id),
            },
        )

        assert initial_response.status_code == 200

        initial_call = initial_response.json()["items"][0]

        filtered_response = admin_client.get(
            "/v1/dashboard/llm-calls",
            params={
                "trace_id": str(trace_id),
                "provider": initial_call["provider"],
                "model": initial_call["model"],
                "purpose": initial_call["purpose"],
                "status": initial_call["status"],
            },
        )

        assert filtered_response.status_code == 200

        body = filtered_response.json()

        assert body["total"] == 1
        assert body["count"] == 1
        assert body["items"][0]["id"] == initial_call["id"]

    def test_non_matching_trace_returns_empty_page(
        self,
        admin_client: TestClient,
        seeded_conversation: uuid.UUID,
        customer_auth_headers: dict[str, str],
    ) -> None:
        _create_llm_call(
            admin_client=admin_client,
            customer_auth_headers=customer_auth_headers,
            conversation_id=seeded_conversation,
            trace_id=uuid7(),
        )

        response = admin_client.get(
            "/v1/dashboard/llm-calls",
            params={
                "trace_id": str(uuid7()),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["items"] == []
        assert body["total"] == 0
        assert body["count"] == 0
        assert body["has_more"] is False
        assert body["next_offset"] is None

    def test_paginates_llm_calls_without_duplicates(
        self,
        admin_client: TestClient,
        seeded_conversation: uuid.UUID,
        customer_auth_headers: dict[str, str],
    ) -> None:
        _create_llm_call(
            admin_client=admin_client,
            customer_auth_headers=customer_auth_headers,
            conversation_id=seeded_conversation,
            trace_id=uuid7(),
        )
        _create_llm_call(
            admin_client=admin_client,
            customer_auth_headers=customer_auth_headers,
            conversation_id=seeded_conversation,
            trace_id=uuid7(),
        )

        first_response = admin_client.get(
            "/v1/dashboard/llm-calls",
            params={
                "limit": 1,
                "offset": 0,
            },
        )
        second_response = admin_client.get(
            "/v1/dashboard/llm-calls",
            params={
                "limit": 1,
                "offset": 1,
            },
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200

        first_body = first_response.json()
        second_body = second_response.json()

        assert first_body["total"] == 2
        assert second_body["total"] == 2

        assert first_body["count"] == 1
        assert second_body["count"] == 1

        assert first_body["has_more"] is True
        assert first_body["next_offset"] == 1

        assert second_body["has_more"] is False
        assert second_body["next_offset"] is None

        assert (
            first_body["items"][0]["id"]
            != second_body["items"][0]["id"]
        )

    def test_rejects_invalid_status(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            "/v1/dashboard/llm-calls",
            params={
                "status": "unknown",
            },
        )

        assert response.status_code == 422

    def test_rejects_invalid_purpose(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            "/v1/dashboard/llm-calls",
            params={
                "purpose": "raw_prompt_debugging",
            },
        )

        assert response.status_code == 422

    def test_does_not_expose_sensitive_llm_fields(
        self,
        admin_client: TestClient,
        seeded_conversation: uuid.UUID,
        customer_auth_headers: dict[str, str],
    ) -> None:
        secret_message = (
            "SECRET-LLM-INPUT-MUST-NOT-BE-RETURNED"
        )
        trace_id = uuid7()

        _create_llm_call(
            admin_client=admin_client,
            customer_auth_headers=customer_auth_headers,
            conversation_id=seeded_conversation,
            trace_id=trace_id,
            message=secret_message,
        )

        response = admin_client.get(
            "/v1/dashboard/llm-calls",
            params={
                "trace_id": str(trace_id),
            },
        )

        assert response.status_code == 200

        body = response.json()
        call = body["items"][0]

        assert secret_message not in response.text

        prohibited_fields = {
            "prompt",
            "system_prompt",
            "user_prompt",
            "response",
            "content",
            "error_message",
            "provider_request_id",
            "metadata",
            "metadata_",
        }

        assert set(call).isdisjoint(prohibited_fields)