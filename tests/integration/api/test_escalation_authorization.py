# AI-customer-support-agent\tests\integration\api\test_escalation_authorization.py
from __future__ import annotations

from fastapi.testclient import TestClient


class TestEscalationAuthorization:
    def test_missing_token_returns_401(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/v1/escalations")

        assert response.status_code == 401
        assert (
            response.json()["error"]["code"]
            == "UNAUTHENTICATED"
        )

    def test_customer_cannot_access_internal_queue(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            "/v1/escalations",
            headers=customer_auth_headers,
        )

        assert response.status_code == 403
        assert (
            response.json()["error"]["code"]
            == "FORBIDDEN"
        )

    def test_customer_cannot_access_internal_conversation_history(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            "/v1/conversations/"
            "00000000-0000-0000-0000-000000000001/"
            "escalations",
            headers=customer_auth_headers,
        )

        assert response.status_code == 403
        assert (
            response.json()["error"]["code"]
            == "FORBIDDEN"
        )

    def test_support_agent_can_access_queue(
        self,
        client: TestClient,
        support_agent_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            "/v1/escalations",
            headers=support_agent_auth_headers,
        )

        assert response.status_code == 200

    def test_admin_can_access_queue(
        self,
        client: TestClient,
        admin_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            "/v1/escalations",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200