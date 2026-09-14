# AI-customer-support-agent\tests\integration\api\test_user_access_management.py
from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from uuid6 import uuid7

from packages.database.models.audit.audit_event import (
    AuditEventModel,
)
from packages.database.models.support.auth_session import (
    AuthSessionModel,
)
from packages.database.models.support.user import UserModel


pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class UserAccessContext:
    admin_id: uuid.UUID
    customer_id: uuid.UUID
    agent_id: uuid.UUID
    customer_session_id: uuid.UUID
    admin_headers: dict[str, str]
    customer_headers: dict[str, str]
    agent_headers: dict[str, str]


@pytest.fixture()
def user_access_context(
    authenticated_identity_factory,
) -> UserAccessContext:
    admin = authenticated_identity_factory(
        role="admin",
    )
    customer = authenticated_identity_factory(
        role="customer",
    )
    agent = authenticated_identity_factory(
        role="support_agent",
    )

    return UserAccessContext(
        admin_id=admin.user_id,
        customer_id=customer.user_id,
        agent_id=agent.user_id,
        customer_session_id=customer.session_id,
        admin_headers=admin.authorization_headers,
        customer_headers=customer.authorization_headers,
        agent_headers=agent.authorization_headers,
    )


class TestAdministrativeAccessUpdates:
    def test_admin_promotes_customer_and_revokes_sessions(
        self,
        client: TestClient,
        test_session_factory,
        user_access_context: UserAccessContext,
    ) -> None:
        trace_id = uuid7()

        response = client.patch(
            (
                "/v1/users/"
                f"{user_access_context.customer_id}/access"
            ),
            headers={
                **user_access_context.admin_headers,
                "X-Trace-ID": str(trace_id),
            },
            json={
                "role": "support_agent",
                "reason": (
                    "Customer was approved as a support agent."
                ),
            },
        )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["user_id"] == str(
            user_access_context.customer_id
        )
        assert body["role"] == "support_agent"
        assert body["status"] == "active"
        assert body["changed"] is True
        assert body["revoked_session_count"] == 1
        assert body["updated_at"] is not None

        with test_session_factory() as session:
            user = session.get(
                UserModel,
                user_access_context.customer_id,
            )
            auth_session = session.get(
                AuthSessionModel,
                user_access_context.customer_session_id,
            )

            audit_event = session.scalar(
                select(AuditEventModel)
                .where(
                    AuditEventModel.event_type
                    == "user.access_updated",
                    AuditEventModel.entity_id
                    == user_access_context.customer_id,
                )
            )

            assert user is not None
            assert user.role == "support_agent"
            assert user.status == "active"

            assert auth_session is not None
            assert auth_session.revoked_at is not None
            assert (
                auth_session.revocation_reason
                == "user_access_changed"
            )

            assert audit_event is not None
            assert audit_event.entity_type == "user"
            assert audit_event.action == "access_updated"
            assert audit_event.actor_type == "admin"
            assert audit_event.actor_id == (
                user_access_context.admin_id
            )
            assert audit_event.trace_id == trace_id
            assert audit_event.before_state == {
                "role": "customer",
                "status": "active",
            }
            assert audit_event.after_state == {
                "role": "support_agent",
                "status": "active",
            }
            assert audit_event.reason == (
                "Customer was approved as a support agent."
            )
            assert (
                audit_event.metadata_["revoked_session_count"]
                == 1
            )

    def test_admin_disables_user(
        self,
        client: TestClient,
        test_session_factory,
        user_access_context: UserAccessContext,
    ) -> None:
        response = client.patch(
            (
                "/v1/users/"
                f"{user_access_context.customer_id}/access"
            ),
            headers=user_access_context.admin_headers,
            json={
                "status": "disabled",
                "reason": "Account disabled after security review.",
            },
        )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["role"] == "customer"
        assert body["status"] == "disabled"
        assert body["changed"] is True
        assert body["revoked_session_count"] == 1

        with test_session_factory() as session:
            user = session.get(
                UserModel,
                user_access_context.customer_id,
            )

            assert user is not None
            assert user.status == "disabled"

    def test_unchanged_update_is_idempotent(
        self,
        client: TestClient,
        test_session_factory,
        user_access_context: UserAccessContext,
    ) -> None:
        response = client.patch(
            (
                "/v1/users/"
                f"{user_access_context.customer_id}/access"
            ),
            headers=user_access_context.admin_headers,
            json={
                "role": "customer",
                "status": "active",
                "reason": "Confirm existing customer access.",
            },
        )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["changed"] is False
        assert body["revoked_session_count"] == 0

        with test_session_factory() as session:
            auth_session = session.get(
                AuthSessionModel,
                user_access_context.customer_session_id,
            )

            audit_count = session.scalar(
                select(func.count(AuditEventModel.id))
                .where(
                    AuditEventModel.event_type
                    == "user.access_updated",
                    AuditEventModel.entity_id
                    == user_access_context.customer_id,
                )
            )

            assert auth_session is not None
            assert auth_session.revoked_at is None
            assert audit_count == 0

    def test_old_access_token_is_rejected_after_role_change(
        self,
        client: TestClient,
        user_access_context: UserAccessContext,
    ) -> None:
        update_response = client.patch(
            (
                "/v1/users/"
                f"{user_access_context.customer_id}/access"
            ),
            headers=user_access_context.admin_headers,
            json={
                "role": "support_agent",
                "reason": "Approved for the support team.",
            },
        )

        assert update_response.status_code == 200

        me_response = client.get(
            "/v1/auth/me",
            headers=user_access_context.customer_headers,
        )

        assert me_response.status_code == 401
        assert me_response.json()["error"]["code"] == (
            "UNAUTHENTICATED"
        )


class TestAdministrativeSafety:
    def test_admin_cannot_demote_self(
        self,
        client: TestClient,
        user_access_context: UserAccessContext,
    ) -> None:
        response = client.patch(
            (
                "/v1/users/"
                f"{user_access_context.admin_id}/access"
            ),
            headers=user_access_context.admin_headers,
            json={
                "role": "customer",
                "reason": "Attempted self-demotion.",
            },
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == (
            "USER_ACCESS_CONFLICT"
        )

    def test_admin_cannot_disable_self(
        self,
        client: TestClient,
        user_access_context: UserAccessContext,
    ) -> None:
        response = client.patch(
            (
                "/v1/users/"
                f"{user_access_context.admin_id}/access"
            ),
            headers=user_access_context.admin_headers,
            json={
                "status": "disabled",
                "reason": "Attempted self-disable.",
            },
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == (
            "USER_ACCESS_CONFLICT"
        )

    def test_system_identity_cannot_be_modified(
        self,
        client: TestClient,
        test_session_factory,
        user_access_context: UserAccessContext,
    ) -> None:
        system_user_id = uuid7()

        with test_session_factory() as session:
            session.add(
                UserModel(
                    id=system_user_id,
                    external_id=f"system-{uuid7()}",
                    email=None,
                    display_name="Internal System",
                    role="system",
                    status="active",
                )
            )
            session.commit()

        response = client.patch(
            f"/v1/users/{system_user_id}/access",
            headers=user_access_context.admin_headers,
            json={
                "status": "disabled",
                "reason": "Attempted system-account mutation.",
            },
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == (
            "USER_ACCESS_DENIED"
        )

    def test_deleted_user_cannot_be_reactivated(
        self,
        client: TestClient,
        test_session_factory,
        user_access_context: UserAccessContext,
    ) -> None:
        with test_session_factory() as session:
            user = session.get(
                UserModel,
                user_access_context.customer_id,
            )
            assert user is not None

            user.status = "deleted"
            session.commit()

        response = client.patch(
            (
                "/v1/users/"
                f"{user_access_context.customer_id}/access"
            ),
            headers=user_access_context.admin_headers,
            json={
                "status": "active",
                "reason": "Attempted deleted-account recovery.",
            },
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == (
            "USER_ACCESS_CONFLICT"
        )


class TestUserAccessAuthorization:
    @pytest.mark.parametrize(
        "actor_headers_name",
        [
            "customer_headers",
            "agent_headers",
        ],
    )
    def test_non_admin_cannot_manage_access(
        self,
        client: TestClient,
        user_access_context: UserAccessContext,
        actor_headers_name: str,
    ) -> None:
        actor_headers = getattr(
            user_access_context,
            actor_headers_name,
        )

        response = client.patch(
            (
                "/v1/users/"
                f"{user_access_context.customer_id}/access"
            ),
            headers=actor_headers,
            json={
                "status": "disabled",
                "reason": "Unauthorized access mutation.",
            },
        )

        assert response.status_code == 403

    def test_missing_authentication_returns_401(
        self,
        client: TestClient,
        user_access_context: UserAccessContext,
    ) -> None:
        response = client.patch(
            (
                "/v1/users/"
                f"{user_access_context.customer_id}/access"
            ),
            json={
                "status": "disabled",
                "reason": "Unauthenticated mutation.",
            },
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == (
            "UNAUTHENTICATED"
        )

    def test_missing_target_returns_404(
        self,
        client: TestClient,
        user_access_context: UserAccessContext,
    ) -> None:
        response = client.patch(
            f"/v1/users/{uuid7()}/access",
            headers=user_access_context.admin_headers,
            json={
                "status": "disabled",
                "reason": "Disable missing account.",
            },
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "USER_NOT_FOUND"
        )

    @pytest.mark.parametrize(
        "payload",
        [
            {
                "reason": "No mutation supplied.",
            },
            {
                "role": "system",
                "reason": "Invalid assignable role.",
            },
            {
                "status": "deleted",
                "reason": "Invalid manageable status.",
            },
            {
                "status": "disabled",
                "reason": "",
            },
        ],
    )
    def test_rejects_invalid_request(
        self,
        client: TestClient,
        user_access_context: UserAccessContext,
        payload: dict[str, str],
    ) -> None:
        response = client.patch(
            (
                "/v1/users/"
                f"{user_access_context.customer_id}/access"
            ),
            headers=user_access_context.admin_headers,
            json=payload,
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "INVALID_REQUEST"
        )