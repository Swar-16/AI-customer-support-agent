from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.application.escalations.create_escalation import (
    CreateEscalation,
    CreateEscalationCommand,
)
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.conversation import (
    ConversationModel,
)
from packages.database.models.support.escalation import (
    EscalationModel,
)
from packages.database.models.support.message import MessageModel
from packages.database.models.support.user import UserModel
from packages.database.repositories.support.escalation_repository import (
    EscalationRepository,
)


@dataclass(frozen=True, slots=True)
class SeededEscalation:
    customer_id: uuid.UUID
    conversation_id: uuid.UUID
    escalation_id: uuid.UUID


@pytest.fixture()
def seeded_escalation(
    clean_database,
    test_session_factory,
) -> SeededEscalation:
    customer_id = uuid7()
    conversation_id = uuid7()
    escalation_id = uuid7()

    with test_session_factory() as session:
        customer = UserModel(id=customer_id)
        session.add(customer)
        session.flush()

        conversation = ConversationModel(
            id=conversation_id,
            user_id=customer_id,
        )
        session.add(conversation)
        session.flush()

        escalation = EscalationModel(
            id=escalation_id,
            conversation_id=conversation_id,
            ai_run_id=None,
            trigger_message_id=None,
            source="manual",
            reason_code="CUSTOMER_REQUESTED_HUMAN",
            reason_summary=(
                "Customer requested assistance from a support agent."
            ),
            priority="high",
            status="open",
            handoff_summary="Review the customer conversation.",
            metadata_={
                "test": True,
            },
            resolved_at=None,
        )
        session.add(escalation)
        session.commit()

    return SeededEscalation(
        customer_id=customer_id,
        conversation_id=conversation_id,
        escalation_id=escalation_id,
    )


class TestEscalationQueries:
    def test_gets_escalation(
        self,
        client: TestClient,
        seeded_escalation: SeededEscalation,
    ) -> None:
        response = client.get(
            f"/v1/escalations/{seeded_escalation.escalation_id}"
        )

        assert response.status_code == 200

        body = response.json()

        assert body["escalation_id"] == str(
            seeded_escalation.escalation_id
        )
        assert body["conversation_id"] == str(
            seeded_escalation.conversation_id
        )
        assert body["source"] == "manual"
        assert (
            body["reason_code"]
            == "CUSTOMER_REQUESTED_HUMAN"
        )
        assert body["priority"] == "high"
        assert body["status"] == "open"
        assert body["metadata"] == {"test": True}

    def test_lists_dashboard_escalations(
        self,
        client: TestClient,
        seeded_escalation: SeededEscalation,
    ) -> None:
        response = client.get(
            "/v1/escalations",
            params={
                "active_only": "true",
                "priority": "high",
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["count"] == 1
        assert body["limit"] == 10
        assert body["offset"] == 0
        assert body["has_more"] is False
        assert len(body["items"]) == 1
        assert body["items"][0]["escalation_id"] == str(
            seeded_escalation.escalation_id
        )

    def test_lists_conversation_escalations(
        self,
        client: TestClient,
        seeded_escalation: SeededEscalation,
    ) -> None:
        response = client.get(
            "/v1/conversations/"
            f"{seeded_escalation.conversation_id}/escalations"
        )

        assert response.status_code == 200

        body = response.json()

        assert len(body) == 1
        assert body[0]["escalation_id"] == str(
            seeded_escalation.escalation_id
        )
        assert body[0]["conversation_id"] == str(
            seeded_escalation.conversation_id
        )

    def test_missing_escalation_returns_canonical_error(
        self,
        client: TestClient,
        clean_database,
    ) -> None:
        missing_id = uuid7()

        response = client.get(
            f"/v1/escalations/{missing_id}"
        )

        assert response.status_code == 404

        body = response.json()
        error = body["error"]

        assert error["code"] == "ESCALATION_NOT_FOUND"
        assert error["message"] == (
            "The requested escalation does not exist."
        )

        response_trace_id = response.headers["X-Trace-ID"]

        assert uuid.UUID(response_trace_id)
        assert error["trace_id"] == response_trace_id


class TestEscalationLifecycle:
    def test_moves_open_to_in_review_to_resolved(
        self,
        client: TestClient,
        seeded_escalation: SeededEscalation,
        test_session_factory,
    ) -> None:
        in_review_response = client.patch(
            f"/v1/escalations/{seeded_escalation.escalation_id}",
            json={
                "status": "in_review",
            },
        )

        assert in_review_response.status_code == 200

        in_review_body = in_review_response.json()

        assert in_review_body["previous_status"] == "open"
        assert in_review_body["current_status"] == "in_review"
        assert in_review_body["resolved_at"] is None
        assert in_review_body["changed"] is True

        resolved_response = client.patch(
            f"/v1/escalations/{seeded_escalation.escalation_id}",
            json={
                "status": "resolved",
            },
        )

        assert resolved_response.status_code == 200

        resolved_body = resolved_response.json()

        assert resolved_body["previous_status"] == "in_review"
        assert resolved_body["current_status"] == "resolved"
        assert resolved_body["resolved_at"] is not None
        assert resolved_body["changed"] is True

        with test_session_factory() as session:
            persisted = session.get(
                EscalationModel,
                seeded_escalation.escalation_id,
            )

            assert persisted is not None
            assert persisted.status == "resolved"
            assert persisted.resolved_at is not None

    def test_repeating_current_status_is_idempotent(
        self,
        client: TestClient,
        seeded_escalation: SeededEscalation,
    ) -> None:
        response = client.patch(
            f"/v1/escalations/{seeded_escalation.escalation_id}",
            json={
                "status": "open",
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["previous_status"] == "open"
        assert body["current_status"] == "open"
        assert body["changed"] is False

    def test_invalid_terminal_transition_returns_conflict(
        self,
        client: TestClient,
        seeded_escalation: SeededEscalation,
    ) -> None:
        resolved_response = client.patch(
            f"/v1/escalations/{seeded_escalation.escalation_id}",
            json={
                "status": "resolved",
            },
        )

        assert resolved_response.status_code == 200

        invalid_response = client.patch(
            f"/v1/escalations/{seeded_escalation.escalation_id}",
            json={
                "status": "in_review",
            },
        )

        assert invalid_response.status_code == 409

        error = invalid_response.json()["error"]

        assert error["code"] == "ESCALATION_CONFLICT"
        assert error["message"] == (
            "The escalation operation conflicts with the "
            "escalation's current state."
        )
        assert error["trace_id"] == (
            invalid_response.headers["X-Trace-ID"]
        )

    def test_invalid_list_filter_combination_returns_422(
        self,
        client: TestClient,
        seeded_escalation: SeededEscalation,
    ) -> None:
        response = client.get(
            "/v1/escalations",
            params={
                "active_only": "true",
                "status": "resolved",
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_REQUEST"


class TestEscalationCreationIdempotency:
    def test_same_ai_run_returns_existing_escalation(
        self,
        clean_database,
        test_session_factory,
    ) -> None:
        customer_id = uuid7()
        conversation_id = uuid7()
        trigger_message_id = uuid7()
        ai_run_id = uuid7()

        with test_session_factory() as session:
            customer = UserModel(id=customer_id)
            session.add(customer)
            session.flush()

            conversation = ConversationModel(
                id=conversation_id,
                user_id=customer_id,
            )
            session.add(conversation)
            session.flush()

            trigger_message = MessageModel(
                id=trigger_message_id,
                conversation_id=conversation_id,
                role="customer",
                content="I need a human agent.",
                sequence_number=1,
                metadata_={},
            )
            session.add(trigger_message)
            session.flush()

            ai_run = AIRunModel(
                id=ai_run_id,
                conversation_id=conversation_id,
                trigger_message_id=trigger_message_id,
                response_message_id=None,
                parent_run_id=None,
                pipeline_version="test-v1",
                status="running",
            )
            session.add(ai_run)
            session.flush()

            repository = EscalationRepository(session)
            service = CreateEscalation(
                repository=repository
            )
            command = CreateEscalationCommand(
                conversation_id=conversation_id,
                ai_run_id=ai_run_id,
                trigger_message_id=trigger_message_id,
                source="decision",
                reason_code="HUMAN_REVIEW_REQUIRED",
                reason_summary=(
                    "The request requires human review."
                ),
                priority="high",
                handoff_summary=(
                    "Review the customer's request."
                ),
                metadata={
                    "pipeline_stage": "decision",
                },
            )

            first = service.execute(command)
            second = service.execute(command)

            session.commit()

        assert first.created is True
        assert second.created is False
        assert second.escalation_id == first.escalation_id
        assert second.conversation_id == conversation_id
        assert second.ai_run_id == ai_run_id