# AI-customer-support-agent\tests\integration\api\test_dashboard_authorization.py
from __future__ import annotations

from fastapi.testclient import TestClient


class TestDashboardAuthorization:
    def test_missing_token_returns_401(
        self,
        client: TestClient,
    ) -> None:
        response = client.get(
            "/v1/dashboard/overview"
        )

        assert response.status_code == 401
        assert (
            response.json()["error"]["code"]
            == "UNAUTHENTICATED"
        )
        assert (
            response.headers["WWW-Authenticate"]
            == "Bearer"
        )

    def test_customer_returns_403(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            "/v1/dashboard/overview",
            headers=customer_auth_headers,
        )

        assert response.status_code == 403
        assert (
            response.json()["error"]["code"]
            == "FORBIDDEN"
        )

    def test_support_agent_returns_403(
        self,
        client: TestClient,
        support_agent_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            "/v1/dashboard/overview",
            headers=support_agent_auth_headers,
        )

        assert response.status_code == 403
        assert (
            response.json()["error"]["code"]
            == "FORBIDDEN"
        )

    def test_admin_can_access_dashboard(
        self,
        client: TestClient,
        admin_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            "/v1/dashboard/overview",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200