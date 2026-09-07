from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.support.conversation import (
    ConversationModel,
)
from packages.database.models.support.escalation import (
    EscalationModel,
)
from packages.database.models.support.ticket import TicketModel
from packages.database.models.support.ticket_comment import (
    TicketCommentModel,
)
from packages.database.models.support.user import UserModel


@dataclass(frozen=True, slots=True)
class TicketTestContext:
    customer_id: uuid.UUID
    other_customer_id: uuid.UUID
    agent_id: uuid.UUID
    admin_id: uuid.UUID
    conversation_id: uuid.UUID
    escalation_id: uuid.UUID


@pytest.fixture()
def ticket_context(
    clean_database,
    test_session_factory,
) -> TicketTestContext:
    customer_id = uuid7()
    other_customer_id = uuid7()
    agent_id = uuid7()
    admin_id = uuid7()
    conversation_id = uuid7()
    escalation_id = uuid7()

    with test_session_factory() as session:
        session.add_all(
            [
                UserModel(
                    id=customer_id,
                    external_id="ticket-customer",
                    role="customer",
                    status="active",
                ),
                UserModel(
                    id=other_customer_id,
                    external_id="other-ticket-customer",
                    role="customer",
                    status="active",
                ),
                UserModel(
                    id=agent_id,
                    external_id="ticket-agent",
                    role="support_agent",
                    status="active",
                ),
                UserModel(
                    id=admin_id,
                    external_id="ticket-admin",
                    role="admin",
                    status="active",
                ),
            ]
        )
        session.flush()

        session.add(
            ConversationModel(
                id=conversation_id,
                user_id=customer_id,
            )
        )
        session.flush()

        session.add(
            EscalationModel(
                id=escalation_id,
                conversation_id=conversation_id,
                ai_run_id=None,
                trigger_message_id=None,
                source="manual",
                reason_code="CUSTOMER_REQUESTED_HUMAN",
                reason_summary=(
                    "Customer requested support-agent assistance."
                ),
                priority="high",
                status="open",
                handoff_summary=(
                    "Review the customer's billing issue."
                ),
                metadata_={"test": True},
                resolved_at=None,
            )
        )

        session.commit()

    return TicketTestContext(
        customer_id=customer_id,
        other_customer_id=other_customer_id,
        agent_id=agent_id,
        admin_id=admin_id,
        conversation_id=conversation_id,
        escalation_id=escalation_id,
    )


def _create_customer_ticket(
    client: TestClient,
    context: TicketTestContext,
    *,
    subject: str = "Duplicate payment",
) -> dict[str, Any]:
    response = client.post(
        f"/v1/conversations/{context.conversation_id}/tickets",
        json={
            "customer_id": str(context.customer_id),
            "source": "customer",
            "subject": subject,
            "description": (
                "I was charged twice for the same order."
            ),
            "category": "billing",
            "priority": "normal",
            "metadata": {
                "channel": "chat",
            },
        },
    )

    assert response.status_code == 201, response.text
    return response.json()


class TestTicketCreation:
    def test_customer_creates_persisted_ticket(
        self,
        client: TestClient,
        ticket_context: TicketTestContext,
        test_session_factory,
    ) -> None:
        body = _create_customer_ticket(
            client,
            ticket_context,
        )

        assert uuid.UUID(body["ticket_id"])
        assert body["ticket_number"] > 0
        assert body["ticket_reference"].startswith("TKT-")
        assert body["conversation_id"] == str(
            ticket_context.conversation_id
        )
        assert body["customer_id"] == str(
            ticket_context.customer_id
        )
        assert body["status"] == "open"
        assert body["priority"] == "normal"
        assert body["category"] == "billing"
        assert body["created"] is True

        with test_session_factory() as session:
            ticket = session.get(
                TicketModel,
                uuid.UUID(body["ticket_id"]),
            )

            assert ticket is not None
            assert ticket.customer_id == ticket_context.customer_id
            assert (
                ticket.conversation_id
                == ticket_context.conversation_id
            )
            assert ticket.source == "customer"
            assert ticket.subject == "Duplicate payment"
            assert ticket.metadata_ == {"channel": "chat"}

    def test_escalation_conversion_is_idempotent(
        self,
        client: TestClient,
        ticket_context: TicketTestContext,
    ) -> None:
        payload = {
            "customer_id": str(ticket_context.customer_id),
            "source": "escalation",
            "subject": "Human review required",
            "description": (
                "The conversation was escalated for human review."
            ),
            "category": "billing",
            "priority": "high",
            "escalation_id": str(ticket_context.escalation_id),
            "metadata": {
                "origin": "escalation",
            },
        }

        first = client.post(
            f"/v1/conversations/{ticket_context.conversation_id}/tickets",
            json=payload,
        )
        second = client.post(
            f"/v1/conversations/{ticket_context.conversation_id}/tickets",
            json=payload,
        )

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text

        first_body = first.json()
        second_body = second.json()

        assert first_body["created"] is True
        assert second_body["created"] is False
        assert (
            second_body["ticket_id"]
            == first_body["ticket_id"]
        )
        assert (
            second_body["ticket_number"]
            == first_body["ticket_number"]
        )


class TestTicketQueries:
    def test_customer_sees_only_owned_tickets(
        self,
        client: TestClient,
        ticket_context: TicketTestContext,
    ) -> None:
        created = _create_customer_ticket(
            client,
            ticket_context,
        )

        owner_response = client.get(
            "/v1/tickets",
            params={
                "requester_id": str(
                    ticket_context.customer_id
                ),
                "requester_role": "customer",
            },
        )

        assert owner_response.status_code == 200
        owner_body = owner_response.json()

        assert owner_body["count"] == 1
        assert owner_body["items"][0]["ticket_id"] == (
            created["ticket_id"]
        )
        assert owner_body["items"][0]["metadata"] == {}

        other_response = client.get(
            "/v1/tickets",
            params={
                "requester_id": str(
                    ticket_context.other_customer_id
                ),
                "requester_role": "customer",
            },
        )

        assert other_response.status_code == 200
        assert other_response.json()["count"] == 0

    def test_customer_cannot_open_another_customers_ticket(
        self,
        client: TestClient,
        ticket_context: TicketTestContext,
    ) -> None:
        created = _create_customer_ticket(
            client,
            ticket_context,
        )

        response = client.get(
            f"/v1/tickets/{created['ticket_id']}",
            params={
                "requester_id": str(
                    ticket_context.other_customer_id
                ),
                "requester_role": "customer",
            },
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == (
            "TICKET_ACCESS_DENIED"
        )

    def test_agent_can_view_active_queue_and_metadata(
        self,
        client: TestClient,
        ticket_context: TicketTestContext,
    ) -> None:
        created = _create_customer_ticket(
            client,
            ticket_context,
        )

        response = client.get(
            "/v1/tickets",
            params={
                "requester_id": str(ticket_context.agent_id),
                "requester_role": "support_agent",
                "active_only": "true",
                "unassigned_only": "true",
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["count"] == 1
        assert body["items"][0]["ticket_id"] == (
            created["ticket_id"]
        )
        assert body["items"][0]["metadata"] == {
            "channel": "chat"
        }

    def test_missing_ticket_returns_canonical_404(
        self,
        client: TestClient,
        ticket_context: TicketTestContext,
    ) -> None:
        response = client.get(
            f"/v1/tickets/{uuid7()}",
            params={
                "requester_id": str(ticket_context.agent_id),
                "requester_role": "support_agent",
            },
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "TICKET_NOT_FOUND"
        )
        assert response.json()["error"]["trace_id"] == (
            response.headers["X-Trace-ID"]
        )


class TestTicketComments:
    def test_customer_sees_public_comment_but_not_internal_note(
        self,
        client: TestClient,
        ticket_context: TicketTestContext,
        test_session_factory,
    ) -> None:
        created = _create_customer_ticket(
            client,
            ticket_context,
        )
        ticket_id = created["ticket_id"]

        public_response = client.post(
            f"/v1/tickets/{ticket_id}/comments",
            json={
                "author_id": str(ticket_context.agent_id),
                "author_role": "support_agent",
                "visibility": "customer",
                "content": (
                    "We are reviewing the duplicate charge."
                ),
                "metadata": {
                    "channel": "dashboard",
                },
            },
        )

        internal_response = client.post(
            f"/v1/tickets/{ticket_id}/comments",
            json={
                "author_id": str(ticket_context.agent_id),
                "author_role": "support_agent",
                "visibility": "internal",
                "content": (
                    "Check the payment processor logs."
                ),
                "metadata": {
                    "queue": "billing",
                },
            },
        )

        assert public_response.status_code == 201
        assert internal_response.status_code == 201

        customer_detail = client.get(
            f"/v1/tickets/{ticket_id}",
            params={
                "requester_id": str(
                    ticket_context.customer_id
                ),
                "requester_role": "customer",
            },
        )

        assert customer_detail.status_code == 200

        customer_comments = customer_detail.json()["comments"]

        assert len(customer_comments) == 1
        assert customer_comments[0]["visibility"] == "customer"
        assert customer_comments[0]["content"] == (
            "We are reviewing the duplicate charge."
        )
        assert customer_comments[0]["metadata"] == {}

        agent_detail = client.get(
            f"/v1/tickets/{ticket_id}",
            params={
                "requester_id": str(ticket_context.agent_id),
                "requester_role": "support_agent",
            },
        )

        assert agent_detail.status_code == 200

        agent_comments = agent_detail.json()["comments"]

        assert len(agent_comments) == 2
        assert {
            comment["visibility"]
            for comment in agent_comments
        } == {"customer", "internal"}

        with test_session_factory() as session:
            persisted_comments = (
                session.query(TicketCommentModel)
                .filter(
                    TicketCommentModel.ticket_id
                    == uuid.UUID(ticket_id)
                )
                .all()
            )

            assert len(persisted_comments) == 2

    def test_customer_internal_comment_is_rejected(
        self,
        client: TestClient,
        ticket_context: TicketTestContext,
    ) -> None:
        created = _create_customer_ticket(
            client,
            ticket_context,
        )

        response = client.post(
            f"/v1/tickets/{created['ticket_id']}/comments",
            json={
                "author_id": str(ticket_context.customer_id),
                "author_role": "customer",
                "visibility": "internal",
                "content": "Hidden customer note.",
            },
        )

        # The API schema rejects this before the application service runs.
        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "INVALID_REQUEST"
        )


class TestTicketLifecycle:
    def test_assigns_resolves_and_closes_ticket(
        self,
        client: TestClient,
        ticket_context: TicketTestContext,
    ) -> None:
        created = _create_customer_ticket(
            client,
            ticket_context,
        )
        ticket_id = created["ticket_id"]

        detail = client.get(
            f"/v1/tickets/{ticket_id}",
            params={
                "requester_id": str(ticket_context.agent_id),
                "requester_role": "support_agent",
            },
        )
        assert detail.status_code == 200

        initial_version = detail.json()["ticket"]["row_version"]

        assigned = client.patch(
            f"/v1/tickets/{ticket_id}",
            json={
                "expected_row_version": initial_version,
                "target_status": "in_progress",
                "assigned_agent_id": str(
                    ticket_context.agent_id
                ),
                "priority": "high",
            },
        )

        assert assigned.status_code == 200, assigned.text
        assigned_body = assigned.json()

        assert assigned_body["current_status"] == "in_progress"
        assert assigned_body["assigned_agent_id"] == str(
            ticket_context.agent_id
        )
        assert assigned_body["priority"] == "high"
        assert assigned_body["row_version"] > initial_version

        resolved = client.patch(
            f"/v1/tickets/{ticket_id}",
            json={
                "expected_row_version": assigned_body["row_version"],
                "target_status": "resolved",
                "resolution_summary": (
                    "Duplicate charge was reversed."
                ),
            },
        )

        assert resolved.status_code == 200, resolved.text
        resolved_body = resolved.json()

        assert resolved_body["current_status"] == "resolved"
        assert resolved_body["resolved_at"] is not None
        assert resolved_body["resolution_summary"] == (
            "Duplicate charge was reversed."
        )

        closed = client.patch(
            f"/v1/tickets/{ticket_id}",
            json={
                "expected_row_version": resolved_body["row_version"],
                "target_status": "closed",
            },
        )

        assert closed.status_code == 200, closed.text
        closed_body = closed.json()

        assert closed_body["current_status"] == "closed"
        assert closed_body["closed_at"] is not None
        assert closed_body["resolution_summary"] == (
            "Duplicate charge was reversed."
        )

    def test_stale_row_version_returns_conflict(
        self,
        client: TestClient,
        ticket_context: TicketTestContext,
    ) -> None:
        created = _create_customer_ticket(
            client,
            ticket_context,
        )
        ticket_id = created["ticket_id"]

        detail = client.get(
            f"/v1/tickets/{ticket_id}",
            params={
                "requester_id": str(ticket_context.admin_id),
                "requester_role": "admin",
            },
        )
        initial_version = detail.json()["ticket"]["row_version"]

        first_update = client.patch(
            f"/v1/tickets/{ticket_id}",
            json={
                "expected_row_version": initial_version,
                "priority": "urgent",
            },
        )

        assert first_update.status_code == 200

        stale_update = client.patch(
            f"/v1/tickets/{ticket_id}",
            json={
                "expected_row_version": initial_version,
                "category": "refund",
            },
        )

        assert stale_update.status_code == 409

        error = stale_update.json()["error"]

        assert error["code"] == "TICKET_CONCURRENT_UPDATE"
        assert error["trace_id"] == (
            stale_update.headers["X-Trace-ID"]
        )