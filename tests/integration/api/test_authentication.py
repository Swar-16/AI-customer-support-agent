# AI-customer-support-agent\tests\integration\api\test_authentication.py
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from packages.application.auth.token_service import TokenService
from packages.database.models.audit.api_request import (
    APIRequestModel,
)
from packages.database.models.audit.audit_event import (
    AuditEventModel,
)
from packages.database.models.support.auth_session import (
    AuthSessionModel,
)
from packages.database.models.support.user import UserModel
from packages.database.models.support.user_credential import (
    UserCredentialModel,
)


STRONG_PASSWORD = "Correct-Horse-Battery-Staple-47!"


def _unique_email() -> str:
    return f"customer-{uuid.uuid4().hex}@example.com"


def _register(
    client: TestClient,
    *,
    email: str | None = None,
    password: str = STRONG_PASSWORD,
    display_name: str = "Test Customer",
):
    resolved_email = email or _unique_email()

    response = client.post(
        "/v1/auth/register",
        json={
            "email": resolved_email,
            "password": password,
            "display_name": display_name,
        },
    )

    return resolved_email, response


def _bearer(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
    }


class TestRegistration:
    def test_registers_customer_and_creates_session(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        email, response = _register(client)
        # print(response.status_code)
        # print(response.text)

        assert response.status_code == 201

        body = response.json()
        user_id = uuid.UUID(body["user"]["id"])

        assert body["user"]["email"] == email
        assert body["user"]["display_name"] == "Test Customer"
        assert body["user"]["role"] == "customer"
        assert body["user"]["status"] == "active"

        assert body["tokens"]["access_token"]
        assert body["tokens"]["refresh_token"]
        assert body["tokens"]["token_type"] == "Bearer"

        serialized = response.text.lower()
        assert "password_hash" not in serialized
        assert "refresh_token_hash" not in serialized
        assert "failed_login_attempts" not in serialized
        assert "token_family_id" not in serialized

        refresh_token_hash = TokenService.hash_refresh_token(
            body["tokens"]["refresh_token"]
        )

        with test_session_factory() as session:
            user = session.get(UserModel, user_id)
            credential = session.get(
                UserCredentialModel,
                user_id,
            )
            auth_session = session.scalar(
                select(AuthSessionModel).where(
                    AuthSessionModel.refresh_token_hash
                    == refresh_token_hash
                )
            )
            audit_event = session.scalar(
                select(AuditEventModel).where(
                    AuditEventModel.event_type
                    == "auth.user_registered",
                    AuditEventModel.entity_id == user_id,
                )
            )

        assert user is not None
        assert user.email == email
        assert user.role == "customer"
        assert user.status == "active"

        assert credential is not None
        assert credential.email_normalized == email
        assert credential.password_hash != STRONG_PASSWORD
        assert credential.password_hash.startswith(
            "$argon2id$"
        )
        assert credential.failed_login_attempts == 0

        assert auth_session is not None
        assert auth_session.user_id == user_id
        assert auth_session.revoked_at is None
        assert auth_session.expires_at > auth_session.created_at

        assert audit_event is not None
        assert audit_event.actor_id == user_id
        assert audit_event.actor_type == "customer"

    def test_registration_is_case_insensitively_unique(
        self,
        client: TestClient,
    ) -> None:
        email = _unique_email()

        first = client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": STRONG_PASSWORD,
            },
        )
        second = client.post(
            "/v1/auth/register",
            json={
                "email": email.upper(),
                "password": STRONG_PASSWORD,
            },
        )

        assert first.status_code == 201
        assert second.status_code == 409
        assert (
            second.json()["error"]["code"]
            == "EMAIL_ALREADY_REGISTERED"
        )

    def test_rejects_weak_password(
        self,
        client: TestClient,
    ) -> None:
        response = client.post(
            "/v1/auth/register",
            json={
                "email": _unique_email(),
                "password": "password",
            },
        )

        assert response.status_code == 400
        assert (
            response.json()["error"]["code"]
            == "PASSWORD_POLICY_VIOLATION"
        )

    def test_rejects_unknown_request_fields(
        self,
        client: TestClient,
    ) -> None:
        response = client.post(
            "/v1/auth/register",
            json={
                "email": _unique_email(),
                "password": STRONG_PASSWORD,
                "role": "admin",
            },
        )

        assert response.status_code == 422
        assert (
            response.json()["error"]["code"]
            == "INVALID_REQUEST"
        )


class TestLogin:
    def test_logs_in_with_normalized_email(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        email, registration = _register(client)
        # print(response.status_code)
        # print(response.text)
        assert registration.status_code == 201

        registered_user_id = registration.json()["user"]["id"]

        response = client.post(
            "/v1/auth/login",
            json={
                "email": f"  {email.upper()}  ",
                "password": STRONG_PASSWORD,
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["user"]["id"] == registered_user_id
        assert body["user"]["email"] == email
        assert body["tokens"]["access_token"]
        assert body["tokens"]["refresh_token"]

        user_id = uuid.UUID(registered_user_id)

        with test_session_factory() as session:
            sessions = tuple(
                session.scalars(
                    select(AuthSessionModel).where(
                        AuthSessionModel.user_id == user_id
                    )
                )
            )
            credential = session.get(
                UserCredentialModel,
                user_id,
            )

        assert len(sessions) == 2
        assert credential is not None
        assert credential.failed_login_attempts == 0
        assert credential.locked_until is None

    def test_wrong_password_returns_generic_401(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        email, registration = _register(client)
        # print(response.status_code)
        # print(response.text)
        assert registration.status_code == 201

        user_id = uuid.UUID(
            registration.json()["user"]["id"]
        )

        response = client.post(
            "/v1/auth/login",
            json={
                "email": email,
                "password": "Definitely-Wrong-Password-98!",
            },
        )

        assert response.status_code == 401
        assert (
            response.json()["error"]["code"]
            == "INVALID_CREDENTIALS"
        )
        assert response.headers["WWW-Authenticate"] == "Bearer"

        with test_session_factory() as session:
            credential = session.get(
                UserCredentialModel,
                user_id,
            )
            failed_event = session.scalar(
                select(AuditEventModel)
                .where(
                    AuditEventModel.event_type
                    == "auth.login_failed",
                    AuditEventModel.entity_id == user_id,
                )
                .order_by(
                    AuditEventModel.occurred_at.desc()
                )
            )

        assert credential is not None
        assert credential.failed_login_attempts == 1
        assert failed_event is not None

    def test_unknown_email_uses_same_public_failure(
        self,
        client: TestClient,
    ) -> None:
        response = client.post(
            "/v1/auth/login",
            json={
                "email": _unique_email(),
                "password": STRONG_PASSWORD,
            },
        )

        assert response.status_code == 401
        assert (
            response.json()["error"]["code"]
            == "INVALID_CREDENTIALS"
        )


class TestCurrentUser:
    def test_returns_authenticated_profile(
        self,
        client: TestClient,
    ) -> None:
        _, registration = _register(client)
        # print(response.status_code)
        # print(response.text)
        assert registration.status_code == 201

        registration_body = registration.json()
        access_token = registration_body["tokens"][
            "access_token"
        ]

        response = client.get(
            "/v1/auth/me",
            headers=_bearer(access_token),
        )

        assert response.status_code == 200
        assert (
            response.json()["id"]
            == registration_body["user"]["id"]
        )
        assert response.json()["role"] == "customer"

        assert response.headers["Cache-Control"].startswith(
            "no-store"
        )

    def test_rejects_missing_and_invalid_bearer_tokens(
        self,
        client: TestClient,
    ) -> None:
        missing = client.get("/v1/auth/me")
        invalid = client.get(
            "/v1/auth/me",
            headers=_bearer("not-a-valid-jwt"),
        )

        assert missing.status_code == 401
        assert invalid.status_code == 401

        assert (
            missing.json()["error"]["code"]
            == "UNAUTHENTICATED"
        )
        assert (
            invalid.json()["error"]["code"]
            == "UNAUTHENTICATED"
        )

        assert (
            missing.headers["WWW-Authenticate"]
            == "Bearer"
        )
        assert (
            invalid.headers["WWW-Authenticate"]
            == "Bearer"
        )


class TestRefreshRotation:
    def test_rotates_refresh_token_and_links_sessions(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        _, registration = _register(client)
        # print(response.status_code)
        # print(response.text)
        assert registration.status_code == 201

        original = registration.json()
        user_id = uuid.UUID(original["user"]["id"])
        original_refresh = original["tokens"]["refresh_token"]

        response = client.post(
            "/v1/auth/refresh",
            json={
                "refresh_token": original_refresh,
            },
        )

        assert response.status_code == 200

        rotated = response.json()

        assert (
            rotated["tokens"]["refresh_token"]
            != original_refresh
        )
        assert (
            rotated["tokens"]["access_token"]
            != original["tokens"]["access_token"]
        )

        original_hash = TokenService.hash_refresh_token(
            original_refresh
        )
        replacement_hash = TokenService.hash_refresh_token(
            rotated["tokens"]["refresh_token"]
        )

        with test_session_factory() as session:
            original_session = session.scalar(
                select(AuthSessionModel).where(
                    AuthSessionModel.refresh_token_hash
                    == original_hash
                )
            )
            replacement_session = session.scalar(
                select(AuthSessionModel).where(
                    AuthSessionModel.refresh_token_hash
                    == replacement_hash
                )
            )

        assert original_session is not None
        assert replacement_session is not None

        assert original_session.user_id == user_id
        assert original_session.revoked_at is not None
        assert (
            original_session.revocation_reason
            == "refresh_token_rotated"
        )
        assert (
            original_session.replaced_by_session_id
            == replacement_session.id
        )

        assert replacement_session.revoked_at is None
        assert (
            replacement_session.family_id
            == original_session.family_id
        )
        assert (
            replacement_session.expires_at
            == original_session.expires_at
        )

        me_response = client.get(
            "/v1/auth/me",
            headers=_bearer(
                rotated["tokens"]["access_token"]
            ),
        )
        assert me_response.status_code == 200

    def test_reusing_rotated_token_revokes_family(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        _, registration = _register(client)
        original = registration.json()

        original_refresh = original["tokens"]["refresh_token"]

        rotation = client.post(
            "/v1/auth/refresh",
            json={
                "refresh_token": original_refresh,
            },
        )
        assert rotation.status_code == 200

        rotated = rotation.json()
        replacement_access = rotated["tokens"][
            "access_token"
        ]

        reuse = client.post(
            "/v1/auth/refresh",
            json={
                "refresh_token": original_refresh,
            },
        )

        assert reuse.status_code == 401
        assert (
            reuse.json()["error"]["code"]
            == "INVALID_REFRESH_TOKEN"
        )

        # Reuse detection revokes the active replacement, making its access
        # token fail the persisted-session validation immediately.
        me_response = client.get(
            "/v1/auth/me",
            headers=_bearer(replacement_access),
        )
        assert me_response.status_code == 401

        user_id = uuid.UUID(original["user"]["id"])

        with test_session_factory() as session:
            active_sessions = tuple(
                session.scalars(
                    select(AuthSessionModel).where(
                        AuthSessionModel.user_id == user_id,
                        AuthSessionModel.revoked_at.is_(None),
                    )
                )
            )
            reuse_event = session.scalar(
                select(AuditEventModel)
                .where(
                    AuditEventModel.event_type
                    == "auth.refresh_reuse_detected",
                )
                .order_by(
                    AuditEventModel.occurred_at.desc()
                )
            )

        assert active_sessions == ()
        assert reuse_event is not None


class TestLogout:
    def test_logout_revokes_session_and_access(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        _, registration = _register(client)
        # print(response.status_code)
        # print(response.text)
        body = registration.json()

        access_token = body["tokens"]["access_token"]
        refresh_token = body["tokens"]["refresh_token"]

        response = client.post(
            "/v1/auth/logout",
            headers=_bearer(access_token),
        )

        assert response.status_code == 200
        assert response.json()["logged_out"] is True

        refresh_token_hash = TokenService.hash_refresh_token(
            refresh_token
        )

        with test_session_factory() as session:
            auth_session = session.scalar(
                select(AuthSessionModel).where(
                    AuthSessionModel.refresh_token_hash
                    == refresh_token_hash
                )
            )

        assert auth_session is not None
        assert auth_session.revoked_at is not None
        assert (
            auth_session.revocation_reason
            == "user_logout"
        )

        me_response = client.get(
            "/v1/auth/me",
            headers=_bearer(access_token),
        )

        assert me_response.status_code == 401


class TestAuthenticationRequestAudit:
    def test_successful_registration_records_actor(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        _, response = _register(client)
        # print(response.status_code)
        # print(response.text)
        assert response.status_code == 201

        trace_id = uuid.UUID(
            response.headers["X-Trace-ID"]
        )
        user_id = uuid.UUID(
            response.json()["user"]["id"]
        )

        with test_session_factory() as session:
            api_request = session.scalar(
                select(APIRequestModel).where(
                    APIRequestModel.trace_id == trace_id
                )
            )

        assert api_request is not None
        assert api_request.actor_user_id == user_id
        assert api_request.actor_role == "customer"
        assert api_request.status_code == 201
        assert (
            api_request.route_template
            == "/v1/auth/register"
        )