# AI-customer-support-agent\tests\integration\api\conftest.py
from __future__ import annotations
import uuid
from collections.abc import Generator
from typing import Any
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from uuid6 import uuid7
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from packages.application.auth.password_hasher import Argon2PasswordHasher
from packages.application.auth.token_service import TokenService, TokenServiceConfig
from packages.config.settings import Settings
from packages.database.models.support.auth_session import AuthSessionModel
from packages.database.models.support.user_credential import UserCredentialModel
from apps.api.app.main import create_api_app
from packages.ai.intent.schemas import IntentResult
from packages.ai.providers.mock import MockLLMProvider
from packages.application.composition.application_factory import ApplicationServices, create_application
from packages.database.models.support.conversation import ConversationModel
from packages.database.models.support.user import UserModel

# Deterministic LLM
def _structured_llm_resolver(system_prompt: str, user_prompt: str, response_model: type[BaseModel]) -> dict[str, Any] | BaseModel:
    """
    Deterministic boundary for API integration tests.

    We keep the real:
        FastAPI
        application service
        UoW
        repositories
        PostgreSQL
        orchestration
        IntentClassifier
        DecisionEngine
        telemetry

    Only the external LLM behaviour is controlled.
    """

    if response_model is IntentResult:
        return {
            "intent": "order_status",
            "confidence": 0.99,
            "entities": { "order_id": "ORD-12345"},
            "needs_clarification": False,
            "reason_summary": "Customer is asking for the status of a specific order.",
        }

    raise AssertionError(f"Unexpected structured response model: {response_model.__name__}")


@pytest.fixture()
def mock_llm_provider() -> MockLLMProvider:
    return MockLLMProvider(structured_resolver=_structured_llm_resolver)


# Real application composition
@pytest.fixture()
def application_services(test_settings, test_session_factory, mock_llm_provider) -> ApplicationServices:
    return create_application(
        settings=test_settings,
        session_factory=test_session_factory,
        base_provider=mock_llm_provider,
    )


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, application_services: ApplicationServices) -> Generator[TestClient, None, None]:

    monkeypatch.setattr("apps.api.app.main.get_application_services", lambda: application_services)
    app = create_api_app()

    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture()
def admin_client(client: TestClient, admin_auth_headers: dict[str, str]) -> TestClient:
    client.headers.update(admin_auth_headers)
    return client

@pytest.fixture()
def support_agent_client(client: TestClient, support_agent_auth_headers: dict[str, str]) -> TestClient:
    client.headers.update(support_agent_auth_headers)
    return client

@pytest.fixture()
def customer_client(client: TestClient, customer_auth_headers: dict[str, str]) -> TestClient:
    client.headers.update(customer_auth_headers)
    return client

@dataclass(frozen=True, slots=True)
class AuthenticatedTestIdentity:
    user_id: uuid.UUID
    session_id: uuid.UUID
    email: str
    role: str
    access_token: str
    refresh_token: str

    @property
    def authorization_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

AuthenticatedIdentityFactory = Callable[..., AuthenticatedTestIdentity]

@pytest.fixture(scope="session")
def test_password_hash() -> str:
    """
    Generate one valid Argon2id hash for authorization fixtures.

    These fixtures test JWT/session/role authorization rather than password verification, so recomputing Argon2 for every identity is unnecessary.
    """
    return Argon2PasswordHasher().hash_password("Integration-Identity-Password-47!")

@pytest.fixture()
def authentication_token_service(test_settings: Settings) -> TokenService:
    return TokenService(
        TokenServiceConfig(
            secret_key=test_settings.auth_jwt_secret,
            issuer=test_settings.auth_jwt_issuer,
            audience=test_settings.auth_jwt_audience,
            access_token_ttl=test_settings.auth_access_token_ttl,
            clock_skew_seconds=test_settings.auth_clock_skew_seconds,
        )
    )

@pytest.fixture()
def authenticated_identity_factory(clean_database, test_settings: Settings, test_session_factory, authentication_token_service: TokenService, test_password_hash: str) -> AuthenticatedIdentityFactory:
    """
    Persist a real user, credential, and active authentication session and issue a real signed access token.

    No authentication dependency is bypassed or overridden.
    """
    def create_identity(*, role: str, email: str | None = None, display_name: str | None = None) -> AuthenticatedTestIdentity:
        allowed_roles = {"customer", "support_agent", "admin",}
        if role not in allowed_roles:
            raise ValueError(f"Unsupported test identity role: {role!r}")

        now = datetime.now(timezone.utc)
        user_id = uuid7()
        session_id = uuid7()
        family_id = uuid7()
        resolved_email = (email or f"{role}-{uuid.uuid4().hex}@example.com").strip().lower()
        resolved_display_name = display_name or role.replace("_", " ").title()
        refresh_material = authentication_token_service.generate_refresh_token()
        refresh_expires_at = now + test_settings.auth_refresh_token_ttl
        issued_access_token = authentication_token_service.issue_access_token(user_id=user_id, session_id=session_id, role=role, now=now)

        with test_session_factory() as session:
            user = UserModel(
                id=user_id, email=resolved_email, display_name=resolved_display_name, role=role, status="active", created_at=now, updated_at=now
            )
            session.add(user)

            # Explicitly establish the FK parent.
            session.flush()

            credential = UserCredentialModel(
                user_id=user_id, email_normalized=resolved_email, password_hash=test_password_hash, failed_login_attempts=0,
                locked_until=None, password_changed_at=now, created_at=now, updated_at=now
            )

            auth_session = AuthSessionModel(
                id=session_id, user_id=user_id, family_id=family_id, refresh_token_hash=refresh_material.token_hash, 
                replaced_by_session_id=None, client_ip="testclient", user_agent="integration-test", created_at=now,
                expires_at=refresh_expires_at, last_used_at=None, revoked_at=None, revocation_reason=None
            )

            session.add_all([credential, auth_session,])
            session.commit()

        return AuthenticatedTestIdentity(
            user_id=user_id, session_id=session_id, email=resolved_email, role=role, 
            access_token=issued_access_token.token, refresh_token=refresh_material.raw_token,
        )

    return create_identity

@pytest.fixture()
def customer_identity(authenticated_identity_factory: AuthenticatedIdentityFactory) -> AuthenticatedTestIdentity:
    return authenticated_identity_factory(role="customer")

@pytest.fixture()
def support_agent_identity(authenticated_identity_factory: AuthenticatedIdentityFactory) -> AuthenticatedTestIdentity:
    return authenticated_identity_factory(role="support_agent")

@pytest.fixture()
def admin_identity(authenticated_identity_factory: AuthenticatedIdentityFactory) -> AuthenticatedTestIdentity:
    return authenticated_identity_factory(role="admin")

@pytest.fixture()
def customer_auth_headers(customer_identity: AuthenticatedTestIdentity) -> dict[str, str]:
    return customer_identity.authorization_headers

@pytest.fixture()
def support_agent_auth_headers(support_agent_identity: AuthenticatedTestIdentity) -> dict[str, str]:
    return support_agent_identity.authorization_headers

@pytest.fixture()
def admin_auth_headers(admin_identity: AuthenticatedTestIdentity) -> dict[str, str]:
    return admin_identity.authorization_headers

# Seed data
@pytest.fixture()
def seeded_conversation(test_session_factory) -> uuid.UUID:
    user_id = uuid7()
    conversation_id = uuid7()

    with test_session_factory() as session:
        user = UserModel(id=user_id)
        session.add(user)
        # Explicitly establish FK parent before conversation insert.
        session.flush()
        conversation = ConversationModel(id=conversation_id, user_id=user_id)
        session.add(conversation)
        session.commit()

    return conversation_id