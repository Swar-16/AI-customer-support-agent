# AI-customer-support-agent\tests\integration\api\test_close_conversation.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from uuid6 import uuid7

from packages.database.models.audit.audit_event import (
    AuditEventModel,
)
from packages.database.models.support.conversation import (
    ConversationModel,
)


@dataclass(frozen=True, slots=True)
class CloseConversationContext:
    customer_id: uuid.UUID
    other_customer_id: uuid.UUID
    open_conversation_id: uuid.UUID
    other_conversation_id: uuid.UUID
    resolved_conversation_id: uuid.UUID
    original_resolved_at: datetime
    customer_headers: dict[str, str]
    other_customer_headers: dict[str, str]
    agent_headers: dict[str, str]
    admin_headers: dict[str, str]


@pytest.fixture()
def close_conversation_context(
    authenticated_identity_factory,
    test_session_factory,
) -> CloseConversationContext:
    customer = authenticated_identity_factory(
        role="customer",
    )
    other_customer = authenticated_identity_factory(
        role="customer",
    )
    agent = authenticated_identity_factory(
        role="support_agent",
    )
    admin = authenticated_identity_factory(
        role="admin",
    )

    open_conversation_id = uuid7()
    other_conversation_id = uuid7()
    resolved_conversation_id = uuid7()

    original_resolved_at = (
        datetime.now(timezone.utc)
        - timedelta(hours=1)
    )

    with test_session_factory() as session:
        session.add_all(
            [
                ConversationModel(
                    id=open_conversation_id,
                    user_id=customer.user_id,
                    status="open",
                    channel="web",
                    title="Customer open conversation",
                    next_message_sequence=1,
                    resolved_at=None,
                    closed_at=None,
                ),
                ConversationModel(
                    id=other_conversation_id,
                    user_id=other_customer.user_id,
                    status="open",
                    channel="web",
                    title="Other customer conversation",
                    next_message_sequence=1,
                    resolved_at=None,
                    closed_at=None,
                ),
                ConversationModel(
                    id=resolved_conversation_id,
                    user_id=customer.user_id,
                    status="resolved",
                    channel="web",
                    title="Previously resolved conversation",
                    next_message_sequence=1,
                    resolved_at=original_resolved_at,
                    closed_at=None,
                ),
            ]
        )
        session.commit()

    return CloseConversationContext(
        customer_id=customer.user_id,
        other_customer_id=other_customer.user_id,
        open_conversation_id=open_conversation_id,
        other_conversation_id=other_conversation_id,
        resolved_conversation_id=resolved_conversation_id,
        original_resolved_at=original_resolved_at,
        customer_headers=customer.authorization_headers,
        other_customer_headers=(
            other_customer.authorization_headers
        ),
        agent_headers=agent.authorization_headers,
        admin_headers=admin.authorization_headers,
    )
    
def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestCustomerConversationClosure:
    def test_customer_closes_owned_conversation(
        self,
        client: TestClient,
        test_session_factory,
        close_conversation_context: CloseConversationContext,
    ) -> None:
        trace_id = uuid7()

        response = client.post(
            (
                "/v1/conversations/"
                f"{close_conversation_context.open_conversation_id}"
                "/close"
            ),
            headers={
                **close_conversation_context.customer_headers,
                "X-Trace-ID": str(trace_id),
            },
        )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["conversation_id"] == str(
            close_conversation_context.open_conversation_id
        )
        assert body["customer_id"] == str(
            close_conversation_context.customer_id
        )
        assert body["status"] == "closed"
        assert body["resolved_at"] is not None
        assert body["closed_at"] is not None
        assert body["updated_at"] is not None
        assert body["changed"] is True

        with test_session_factory() as session:
            conversation = session.get(
                ConversationModel,
                close_conversation_context.open_conversation_id,
            )

            assert conversation is not None
            assert conversation.status == "closed"
            assert conversation.closed_at is not None
            assert conversation.resolved_at is not None

            audit_event = session.scalar(
                select(AuditEventModel)
                .where(
                    AuditEventModel.event_type
                    == "conversation.closed",
                    AuditEventModel.entity_type
                    == "conversation",
                    AuditEventModel.entity_id
                    == close_conversation_context.open_conversation_id,
                )
            )

            assert audit_event is not None
            assert audit_event.action == "closed"
            assert audit_event.actor_type == "customer"
            assert audit_event.actor_id == (
                close_conversation_context.customer_id
            )
            assert audit_event.trace_id == trace_id
            assert audit_event.conversation_id == (
                close_conversation_context.open_conversation_id
            )
            assert audit_event.before_state["status"] == "open"
            assert audit_event.after_state["status"] == "closed"

    def test_repeated_closure_is_idempotent(
        self,
        client: TestClient,
        test_session_factory,
        close_conversation_context: CloseConversationContext,
    ) -> None:
        path = (
            "/v1/conversations/"
            f"{close_conversation_context.open_conversation_id}"
            "/close"
        )

        first_response = client.post(
            path,
            headers=close_conversation_context.customer_headers,
        )
        second_response = client.post(
            path,
            headers=close_conversation_context.customer_headers,
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200

        first_body = first_response.json()
        second_body = second_response.json()

        assert first_body["changed"] is True
        assert second_body["changed"] is False
        assert second_body["status"] == "closed"
        assert _parse_datetime(second_body["closed_at"]) == _parse_datetime(first_body["closed_at"])
        assert _parse_datetime(second_body["resolved_at"]) == _parse_datetime(first_body["resolved_at"])

        with test_session_factory() as session:
            audit_count = session.scalar(
                select(func.count(AuditEventModel.id))
                .where(
                    AuditEventModel.event_type
                    == "conversation.closed",
                    AuditEventModel.entity_id
                    == close_conversation_context.open_conversation_id,
                )
            )

        assert audit_count == 1

    def test_closing_resolved_conversation_preserves_resolution_time(
        self,
        client: TestClient,
        test_session_factory,
        close_conversation_context: CloseConversationContext,
    ) -> None:
        response = client.post(
            (
                "/v1/conversations/"
                f"{close_conversation_context.resolved_conversation_id}"
                "/close"
            ),
            headers=close_conversation_context.customer_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "closed"
        assert response.json()["changed"] is True

        with test_session_factory() as session:
            conversation = session.get(
                ConversationModel,
                close_conversation_context.resolved_conversation_id,
            )

            assert conversation is not None
            assert conversation.status == "closed"
            assert conversation.closed_at is not None
            assert conversation.resolved_at == (
                close_conversation_context.original_resolved_at
            )


class TestConversationClosureAuthorization:
    def test_customer_cannot_close_another_customers_conversation(
        self,
        client: TestClient,
        test_session_factory,
        close_conversation_context: CloseConversationContext,
    ) -> None:
        response = client.post(
            (
                "/v1/conversations/"
                f"{close_conversation_context.other_conversation_id}"
                "/close"
            ),
            headers=close_conversation_context.customer_headers,
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "CONVERSATION_NOT_FOUND"
        )

        with test_session_factory() as session:
            conversation = session.get(
                ConversationModel,
                close_conversation_context.other_conversation_id,
            )

            assert conversation is not None
            assert conversation.status == "open"
            assert conversation.closed_at is None

    def test_admin_can_close_any_conversation(
        self,
        client: TestClient,
        test_session_factory,
        close_conversation_context: CloseConversationContext,
    ) -> None:
        trace_id = uuid7()

        response = client.post(
            (
                "/v1/conversations/"
                f"{close_conversation_context.other_conversation_id}"
                "/close"
            ),
            headers={
                **close_conversation_context.admin_headers,
                "X-Trace-ID": str(trace_id),
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "closed"

        with test_session_factory() as session:
            audit_event = session.scalar(
                select(AuditEventModel)
                .where(
                    AuditEventModel.event_type
                    == "conversation.closed",
                    AuditEventModel.entity_id
                    == close_conversation_context.other_conversation_id,
                )
            )

            assert audit_event is not None
            assert audit_event.actor_type == "admin"
            assert audit_event.trace_id == trace_id

    def test_support_agent_is_denied(
        self,
        client: TestClient,
        close_conversation_context: CloseConversationContext,
    ) -> None:
        response = client.post(
            (
                "/v1/conversations/"
                f"{close_conversation_context.open_conversation_id}"
                "/close"
            ),
            headers=close_conversation_context.agent_headers,
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == (
            "CONVERSATION_ACCESS_DENIED"
        )

    def test_missing_authentication_returns_401(
        self,
        client: TestClient,
        close_conversation_context: CloseConversationContext,
    ) -> None:
        response = client.post(
            (
                "/v1/conversations/"
                f"{close_conversation_context.open_conversation_id}"
                "/close"
            )
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == (
            "UNAUTHENTICATED"
        )

    def test_missing_conversation_returns_404(
        self,
        client: TestClient,
        close_conversation_context: CloseConversationContext,
    ) -> None:
        response = client.post(
            f"/v1/conversations/{uuid7()}/close",
            headers=close_conversation_context.admin_headers,
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "CONVERSATION_NOT_FOUND"
        )