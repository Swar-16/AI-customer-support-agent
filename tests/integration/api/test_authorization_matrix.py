from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.support.user import UserModel


pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    customer_id: uuid.UUID
    agent_id: uuid.UUID
    admin_id: uuid.UUID
    customer_headers: dict[str, str]
    agent_headers: dict[str, str]
    admin_headers: dict[str, str]


@pytest.fixture()
def authorization_context(
    authenticated_identity_factory,
) -> AuthorizationContext:
    customer = authenticated_identity_factory(
        role="customer",
    )
    agent = authenticated_identity_factory(
        role="support_agent",
    )
    admin = authenticated_identity_factory(
        role="admin",
    )

    return AuthorizationContext(
        customer_id=customer.user_id,
        agent_id=agent.user_id,
        admin_id=admin.user_id,
        customer_headers=customer.authorization_headers,
        agent_headers=agent.authorization_headers,
        admin_headers=admin.authorization_headers,
    )


def _headers_for_role(
    context: AuthorizationContext,
    role: str,
) -> dict[str, str]:
    mapping = {
        "customer": context.customer_headers,
        "support_agent": context.agent_headers,
        "admin": context.admin_headers,
    }

    return mapping[role]


class TestCustomerCapabilities:
    def test_customer_can_create_owned_conversation(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.post(
            "/v1/conversations",
            headers=authorization_context.customer_headers,
            json={
                "channel": "web",
                "title": "Authorization matrix test",
            },
        )

        assert response.status_code == 201, response.text

        body = response.json()

        assert body["customer_id"] == str(
            authorization_context.customer_id
        )
        assert body["status"] == "open"

    @pytest.mark.parametrize(
        "role",
        [
            "support_agent",
            "admin",
        ],
    )
    def test_non_customer_cannot_create_customer_conversation(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
        role: str,
    ) -> None:
        response = client.post(
            "/v1/conversations",
            headers=_headers_for_role(
                authorization_context,
                role,
            ),
            json={
                "channel": "web",
                "title": "Unauthorized conversation",
            },
        )

        assert response.status_code == 403

    def test_customer_can_list_owned_conversations(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.get(
            "/v1/conversations",
            headers=authorization_context.customer_headers,
        )

        assert response.status_code == 200
        assert response.json()["items"] == []

    def test_customer_can_access_owned_ticket_view(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.get(
            "/v1/tickets",
            headers=authorization_context.customer_headers,
        )

        assert response.status_code == 200

    def test_customer_cannot_access_internal_escalations(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.get(
            "/v1/escalations",
            headers=authorization_context.customer_headers,
        )

        assert response.status_code == 403

    @pytest.mark.parametrize(
        "path",
        [
            "/v1/dashboard/overview",
            "/v1/dashboard/traces",
            "/v1/dashboard/llm-calls",
            "/v1/dashboard/retrieval-runs",
            "/v1/dashboard/api-requests",
            "/v1/dashboard/audit-events",
        ],
    )
    def test_customer_cannot_access_dashboard(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
        path: str,
    ) -> None:
        response = client.get(
            path,
            headers=authorization_context.customer_headers,
        )

        assert response.status_code == 403


class TestSupportAgentCapabilities:
    def test_agent_can_access_escalation_queue(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.get(
            "/v1/escalations",
            headers=authorization_context.agent_headers,
        )

        assert response.status_code == 200, response.text

    def test_agent_can_access_ticket_queue(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.get(
            "/v1/tickets",
            headers=authorization_context.agent_headers,
        )

        assert response.status_code == 200, response.text

    def test_agent_cannot_query_conversations_without_assignment(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.get(
            "/v1/conversations",
            headers=authorization_context.agent_headers,
        )

        assert response.status_code == 403

    @pytest.mark.parametrize(
        "path",
        [
            "/v1/dashboard/overview",
            "/v1/dashboard/traces",
            "/v1/dashboard/llm-calls",
            "/v1/dashboard/retrieval-runs",
            "/v1/dashboard/api-requests",
            "/v1/dashboard/audit-events",
        ],
    )
    def test_agent_cannot_access_admin_dashboard(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
        path: str,
    ) -> None:
        response = client.get(
            path,
            headers=authorization_context.agent_headers,
        )

        assert response.status_code == 403

    def test_agent_cannot_manage_user_access(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.patch(
            (
                "/v1/users/"
                f"{authorization_context.customer_id}/access"
            ),
            headers=authorization_context.agent_headers,
            json={
                "status": "disabled",
                "reason": "Unauthorized agent mutation.",
            },
        )

        assert response.status_code == 403


class TestAdministratorCapabilities:
    @pytest.mark.parametrize(
        "path",
        [
            "/v1/dashboard/overview",
            "/v1/dashboard/traces",
            "/v1/dashboard/llm-calls",
            "/v1/dashboard/retrieval-runs",
            "/v1/dashboard/api-requests",
            "/v1/dashboard/audit-events",
        ],
    )
    def test_admin_can_access_dashboard(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
        path: str,
    ) -> None:
        response = client.get(
            path,
            headers=authorization_context.admin_headers,
        )

        assert response.status_code == 200, response.text

    def test_admin_can_list_conversations(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.get(
            "/v1/conversations",
            headers=authorization_context.admin_headers,
        )

        assert response.status_code == 200

    def test_admin_can_access_ticket_queue(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.get(
            "/v1/tickets",
            headers=authorization_context.admin_headers,
        )

        assert response.status_code == 200

    def test_admin_can_access_escalation_queue(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.get(
            "/v1/escalations",
            headers=authorization_context.admin_headers,
        )

        assert response.status_code == 200

    def test_admin_passes_user_management_authorization(
        self,
        client: TestClient,
        authorization_context: AuthorizationContext,
    ) -> None:
        response = client.patch(
            f"/v1/users/{uuid7()}/access",
            headers=authorization_context.admin_headers,
            json={
                "status": "disabled",
                "reason": "Authorization boundary verification.",
            },
        )

        # A 404 proves authentication and admin authorization succeeded;
        # only the deliberately absent target was rejected.
        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "USER_NOT_FOUND"
        )


class TestAuthenticationBoundary:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/v1/conversations"),
            ("get", "/v1/tickets"),
            ("get", "/v1/escalations"),
            ("get", "/v1/dashboard/overview"),
            ("get", "/v1/dashboard/audit-events"),
            (
                "patch",
                "/v1/users/00000000-0000-0000-0000-000000000001/access",
            ),
        ],
    )
    def test_protected_routes_reject_missing_authentication(
        self,
        client: TestClient,
        method: str,
        path: str,
    ) -> None:
        if method == "patch":
            response = client.patch(
                path,
                json={
                    "status": "disabled",
                    "reason": "Unauthenticated request.",
                },
            )
        else:
            response = client.get(path)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == (
            "UNAUTHENTICATED"
        )

    def test_malformed_access_token_is_rejected(
        self,
        client: TestClient,
    ) -> None:
        response = client.get(
            "/v1/conversations",
            headers={
                "Authorization": "Bearer not-a-valid-jwt",
            },
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == (
            "UNAUTHENTICATED"
        )

    def test_disabled_user_is_rejected_with_existing_token(
        self,
        client: TestClient,
        test_session_factory,
        authenticated_identity_factory,
    ) -> None:
        customer = authenticated_identity_factory(
            role="customer",
        )

        with test_session_factory() as session:
            user = session.get(
                UserModel,
                customer.user_id,
            )
            assert user is not None

            user.status = "disabled"
            session.commit()

        response = client.get(
            "/v1/conversations",
            headers=customer.authorization_headers,
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == (
            "UNAUTHENTICATED"
        )


class TestRegistrationSecurity:
    def test_public_registration_cannot_select_admin_role(
        self,
        client: TestClient,
    ) -> None:
        response = client.post(
            "/v1/auth/register",
            json={
                "email": (
                    f"role-injection-{uuid7()}@example.com"
                ),
                "password": (
                    "Safe-Registration-Password-47!"
                ),
                "display_name": "Role Injection",
                "role": "admin",
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "INVALID_REQUEST"
        )

    def test_sql_injection_shaped_login_does_not_authenticate(
        self,
        client: TestClient,
    ) -> None:
        response = client.post(
            "/v1/auth/login",
            json={
                "email": "nobody'--@example.com",
                "password": "' OR 1=1 --",
            },
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == (
            "INVALID_CREDENTIALS"
        )