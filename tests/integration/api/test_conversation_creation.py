# AI-customer-support-agent\tests\integration\api\test_conversation_creation.py
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from packages.database.models.audit.audit_event import (
    AuditEventModel,
)
from packages.database.models.support.conversation import (
    ConversationModel,
)


class TestConversationCreation:
    def test_customer_creates_owned_conversation(
        self,
        client: TestClient,
        customer_identity,
        test_session_factory,
    ) -> None:
        response = client.post(
            "/v1/conversations",
            headers=customer_identity.authorization_headers,
            json={
                "channel": "web",
                "title": "Refund assistance",
            },
        )

        assert response.status_code == 201, response.text

        body = response.json()
        conversation_id = uuid.UUID(body["conversation_id"])

        assert body["customer_id"] == str(
            customer_identity.user_id
        )
        assert body["status"] == "open"
        assert body["channel"] == "web"
        assert body["title"] == "Refund assistance"
        assert body["created_at"] is not None
        assert body["updated_at"] is not None
        assert "next_message_sequence" not in body

        with test_session_factory() as session:
            conversation = session.get(
                ConversationModel,
                conversation_id,
            )

            assert conversation is not None
            assert (
                conversation.user_id
                == customer_identity.user_id
            )
            assert conversation.status == "open"
            assert conversation.channel == "web"
            assert conversation.title == "Refund assistance"
            assert conversation.next_message_sequence == 1

    def test_uses_safe_defaults(
        self,
        client: TestClient,
        customer_identity,
    ) -> None:
        response = client.post(
            "/v1/conversations",
            headers=customer_identity.authorization_headers,
            json={},
        )

        assert response.status_code == 201, response.text

        body = response.json()

        assert body["customer_id"] == str(
            customer_identity.user_id
        )
        assert body["status"] == "open"
        assert body["channel"] == "web"
        assert body["title"] is None

    def test_normalizes_blank_title_to_none(
        self,
        client: TestClient,
        customer_identity,
    ) -> None:
        response = client.post(
            "/v1/conversations",
            headers=customer_identity.authorization_headers,
            json={
                "channel": "mobile",
                "title": "   ",
            },
        )

        assert response.status_code == 201, response.text

        body = response.json()

        assert body["channel"] == "mobile"
        assert body["title"] is None

    def test_records_authenticated_creation_audit(
        self,
        client: TestClient,
        customer_identity,
        test_session_factory,
    ) -> None:
        supplied_trace_id = uuid.uuid4()

        response = client.post(
            "/v1/conversations",
            headers={
                **customer_identity.authorization_headers,
                "X-Trace-ID": str(supplied_trace_id),
            },
            json={
                "channel": "web",
                "title": "Audit correlation",
            },
        )

        assert response.status_code == 201, response.text
        assert response.headers["X-Trace-ID"] == str(
            supplied_trace_id
        )

        conversation_id = uuid.UUID(
            response.json()["conversation_id"]
        )

        with test_session_factory() as session:
            audit_event = session.scalar(
                select(AuditEventModel).where(
                    AuditEventModel.event_type
                    == "conversation.created",
                    AuditEventModel.entity_type
                    == "conversation",
                    AuditEventModel.entity_id
                    == conversation_id,
                )
            )

            assert audit_event is not None
            assert audit_event.actor_type == "customer"
            assert (
                audit_event.actor_id
                == customer_identity.user_id
            )
            assert audit_event.trace_id == supplied_trace_id
            assert (
                audit_event.conversation_id
                == conversation_id
            )
            assert audit_event.before_state is None
            assert audit_event.after_state == {
                "status": "open",
                "channel": "web",
                "title_present": True,
            }

    def test_missing_authentication_returns_401(
        self,
        client: TestClient,
    ) -> None:
        response = client.post(
            "/v1/conversations",
            json={
                "channel": "web",
            },
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == (
            "UNAUTHENTICATED"
        )
        assert response.json()["error"]["trace_id"] == (
            response.headers["X-Trace-ID"]
        )

    def test_support_agent_cannot_create_customer_conversation(
        self,
        client: TestClient,
        support_agent_identity,
    ) -> None:
        response = client.post(
            "/v1/conversations",
            headers=(
                support_agent_identity.authorization_headers
            ),
            json={
                "channel": "web",
            },
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"

    def test_admin_cannot_use_customer_creation_endpoint(
        self,
        client: TestClient,
        admin_identity,
    ) -> None:
        response = client.post(
            "/v1/conversations",
            headers=admin_identity.authorization_headers,
            json={
                "channel": "web",
            },
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"

    def test_rejects_client_supplied_owner_identity(
        self,
        client: TestClient,
        customer_identity,
    ) -> None:
        response = client.post(
            "/v1/conversations",
            headers=customer_identity.authorization_headers,
            json={
                "channel": "web",
                "customer_id": str(uuid.uuid4()),
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "INVALID_REQUEST"
        )

    def test_rejects_invalid_channel(
        self,
        client: TestClient,
        customer_identity,
    ) -> None:
        response = client.post(
            "/v1/conversations",
            headers=customer_identity.authorization_headers,
            json={
                "channel": "untrusted-channel",
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "INVALID_REQUEST"
        )