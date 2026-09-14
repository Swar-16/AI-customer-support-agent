# AI-customer-support-agent\tests\integration\api\test_customer_escalation_status.py
from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.support.conversation import (
    ConversationModel,
)
from packages.database.models.support.escalation import (
    EscalationModel,
)


@dataclass(frozen=True, slots=True)
class CustomerEscalationFixture:
    customer_id: uuid.UUID
    conversation_id: uuid.UUID
    escalation_id: uuid.UUID


@pytest.fixture()
def customer_escalation(
    customer_identity,
    test_session_factory,
) -> CustomerEscalationFixture:
    conversation_id = uuid7()
    escalation_id = uuid7()

    with test_session_factory() as session:
        conversation = ConversationModel(
            id=conversation_id,
            user_id=customer_identity.user_id,
        )
        session.add(conversation)
        session.flush()

        escalation = EscalationModel(
            id=escalation_id,
            conversation_id=conversation_id,
            ai_run_id=None,
            trigger_message_id=None,
            source="guardrail",
            reason_code="CUSTOMER_REQUIRES_REVIEW",
            reason_summary=(
                "Sensitive internal reason summary."
            ),
            priority="high",
            status="open",
            handoff_summary=(
                "Sensitive internal handoff instructions."
            ),
            metadata_={
                "internal_only": True,
                "risk_score": 0.91,
            },
            resolved_at=None,
        )
        session.add(escalation)
        session.commit()

    return CustomerEscalationFixture(
        customer_id=customer_identity.user_id,
        conversation_id=conversation_id,
        escalation_id=escalation_id,
    )
    
class TestCustomerEscalationStatus:
    def test_owner_can_view_sanitized_status(
        self,
        client: TestClient,
        customer_identity,
        customer_escalation: CustomerEscalationFixture,
    ) -> None:
        response = client.get(
            (
                f"/v1/conversations/"
                f"{customer_escalation.conversation_id}/"
                "escalation-status"
            ),
            headers=(
                customer_identity.authorization_headers
            ),
        )

        assert response.status_code == 200

        body = response.json()

        assert body == {
            "escalation_id": str(
                customer_escalation.escalation_id
            ),
            "conversation_id": str(
                customer_escalation.conversation_id
            ),
            "status": "open",
            "priority": "high",
            "created_at": body["created_at"],
            "updated_at": body["updated_at"],
            "resolved_at": None,
        }

        forbidden_fields = {
            "ai_run_id",
            "trigger_message_id",
            "source",
            "reason_code",
            "reason_summary",
            "handoff_summary",
            "metadata",
        }

        assert forbidden_fields.isdisjoint(body)

    def test_different_customer_receives_404(
        self,
        client: TestClient,
        authenticated_identity_factory,
        customer_escalation: CustomerEscalationFixture,
    ) -> None:
        other_customer = authenticated_identity_factory(
            role="customer"
        )

        response = client.get(
            (
                f"/v1/conversations/"
                f"{customer_escalation.conversation_id}/"
                "escalation-status"
            ),
            headers=(
                other_customer.authorization_headers
            ),
        )

        assert response.status_code == 404
        assert (
            response.json()["error"]["code"]
            == "CUSTOMER_ESCALATION_STATUS_NOT_FOUND"
        )

    def test_owned_conversation_without_escalation_returns_404(
        self,
        client: TestClient,
        customer_identity,
        test_session_factory,
    ) -> None:
        conversation_id = uuid7()

        with test_session_factory() as session:
            session.add(
                ConversationModel(
                    id=conversation_id,
                    user_id=customer_identity.user_id,
                )
            )
            session.commit()

        response = client.get(
            (
                f"/v1/conversations/{conversation_id}/"
                "escalation-status"
            ),
            headers=(
                customer_identity.authorization_headers
            ),
        )

        assert response.status_code == 404
        assert (
            response.json()["error"]["code"]
            == "CUSTOMER_ESCALATION_STATUS_NOT_FOUND"
        )

    def test_missing_authentication_returns_401(
        self,
        client: TestClient,
        customer_escalation: CustomerEscalationFixture,
    ) -> None:
        response = client.get(
            (
                f"/v1/conversations/"
                f"{customer_escalation.conversation_id}/"
                "escalation-status"
            )
        )

        assert response.status_code == 401
        assert (
            response.json()["error"]["code"]
            == "UNAUTHENTICATED"
        )

    def test_support_agent_is_rejected_from_customer_endpoint(
        self,
        client: TestClient,
        support_agent_identity,
        customer_escalation: CustomerEscalationFixture,
    ) -> None:
        response = client.get(
            (
                f"/v1/conversations/"
                f"{customer_escalation.conversation_id}/"
                "escalation-status"
            ),
            headers=(
                support_agent_identity.authorization_headers
            ),
        )

        assert response.status_code == 403
        assert (
            response.json()["error"]["code"]
            == "FORBIDDEN"
        )
        
    def test_admin_is_rejected_from_customer_endpoint(
        self,
        client: TestClient,
        admin_identity,
        customer_escalation: CustomerEscalationFixture,
    ) -> None:
        response = client.get(
            (
                f"/v1/conversations/"
                f"{customer_escalation.conversation_id}/"
                "escalation-status"
            ),
            headers=admin_identity.authorization_headers,
        )

        assert response.status_code == 403
        assert (
            response.json()["error"]["code"]
            == "FORBIDDEN"
        )