# AI-customer-support-agent\tests\integration\api\test_dashboard_support_analytics.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.support.conversation import (
    ConversationModel,
)
from packages.database.models.support.escalation import (
    EscalationModel,
)
from packages.database.models.support.feedback import (
    FeedbackModel,
)
from packages.database.models.support.message import MessageModel
from packages.database.models.support.ticket import TicketModel
from packages.database.models.support.user import UserModel


_ENDPOINT = "/v1/dashboard/support-analytics"


def _analytics_params(
    *,
    started_at: datetime,
    ended_at: datetime,
    bucket: str = "day",
) -> dict[str, str]:
    return {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "bucket": bucket,
    }


def _distribution(
    items: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        str(item["category"]): int(item["count"])
        for item in items
    }


def _seed_support_records(
    *,
    test_session_factory,
    admin_user_id: UUID,
    started_at: datetime,
) -> None:
    customer_id = uuid7()
    conversation_id = uuid7()
    response_message_id = uuid7()

    ticket_open_created = started_at + timedelta(hours=1)
    ticket_resolved_created = started_at + timedelta(hours=2)
    ticket_resolved_at = ticket_resolved_created + timedelta(hours=1)

    ticket_closed_created = started_at + timedelta(days=1, hours=1)
    ticket_closed_resolved_at = (
        ticket_closed_created + timedelta(hours=2)
    )
    ticket_closed_at = (
        ticket_closed_resolved_at + timedelta(minutes=30)
    )

    escalation_open_created = started_at + timedelta(hours=3)
    escalation_resolved_created = (
        started_at + timedelta(days=1, hours=2)
    )
    escalation_resolved_at = (
        escalation_resolved_created + timedelta(minutes=30)
    )

    pending_feedback_created = started_at + timedelta(hours=4)
    reviewed_feedback_created = (
        started_at + timedelta(days=1, hours=4)
    )
    reviewed_at = reviewed_feedback_created + timedelta(minutes=20)

    with test_session_factory() as session:
        customer = UserModel(
            id=customer_id,
            external_id=None,
            email="analytics-customer@example.com",
            display_name="Analytics Customer",
            role="customer",
            status="active",
            created_at=started_at - timedelta(days=1),
            updated_at=started_at - timedelta(days=1),
        )
        session.add(customer)
        session.flush()

        conversation = ConversationModel(
            id=conversation_id,
            user_id=customer_id,
            status="open",
            channel="web",
            title="Support analytics test conversation",
            next_message_sequence=3,
            created_at=started_at,
            updated_at=started_at,
            resolved_at=None,
            closed_at=None,
        )
        session.add(conversation)
        session.flush()

        customer_message = MessageModel(
            id=uuid7(),
            conversation_id=conversation_id,
            role="customer",
            content="I need support.",
            sequence_number=1,
            metadata_={},
            created_at=started_at,
        )
        assistant_message = MessageModel(
            id=response_message_id,
            conversation_id=conversation_id,
            role="assistant",
            content="A support response.",
            sequence_number=2,
            metadata_={},
            created_at=started_at + timedelta(minutes=1),
        )
        session.add_all([customer_message, assistant_message])
        session.flush()

        open_escalation = EscalationModel(
            id=uuid7(),
            conversation_id=conversation_id,
            ai_run_id=None,
            trigger_message_id=customer_message.id,
            source="manual",
            reason_code="CUSTOMER_REQUEST",
            reason_summary="Customer requested human review.",
            priority="high",
            status="open",
            handoff_summary=None,
            metadata_={},
            created_at=escalation_open_created,
            updated_at=escalation_open_created,
            resolved_at=None,
        )
        resolved_escalation = EscalationModel(
            id=uuid7(),
            conversation_id=conversation_id,
            ai_run_id=None,
            trigger_message_id=customer_message.id,
            source="manual",
            reason_code="COMPLETED_REVIEW",
            reason_summary="Support review completed.",
            priority="normal",
            status="resolved",
            handoff_summary="Resolved by support.",
            metadata_={},
            created_at=escalation_resolved_created,
            updated_at=escalation_resolved_at,
            resolved_at=escalation_resolved_at,
        )
        session.add_all(
            [open_escalation, resolved_escalation]
        )
        session.flush()

        open_ticket = TicketModel(
            id=uuid7(),
            conversation_id=conversation_id,
            customer_id=customer_id,
            source_message_id=customer_message.id,
            escalation_id=None,
            assigned_agent_id=None,
            source="customer",
            subject="Open billing request",
            description="An unresolved billing request.",
            category="billing",
            priority="high",
            status="open",
            resolution_summary=None,
            metadata_={},
            row_version=1,
            created_at=ticket_open_created,
            updated_at=ticket_open_created,
            assigned_at=None,
            resolved_at=None,
            closed_at=None,
        )
        resolved_ticket = TicketModel(
            id=uuid7(),
            conversation_id=conversation_id,
            customer_id=customer_id,
            source_message_id=customer_message.id,
            escalation_id=None,
            assigned_agent_id=None,
            source="customer",
            subject="Resolved refund request",
            description="A refund request resolved by support.",
            category="refund",
            priority="normal",
            status="resolved",
            resolution_summary="Refund was approved.",
            metadata_={},
            row_version=1,
            created_at=ticket_resolved_created,
            updated_at=ticket_resolved_at,
            assigned_at=None,
            resolved_at=ticket_resolved_at,
            closed_at=None,
        )
        closed_ticket = TicketModel(
            id=uuid7(),
            conversation_id=conversation_id,
            customer_id=customer_id,
            source_message_id=customer_message.id,
            escalation_id=None,
            assigned_agent_id=None,
            source="customer",
            subject="Closed technical request",
            description="A completed technical request.",
            category="technical",
            priority="urgent",
            status="closed",
            resolution_summary="Technical issue was fixed.",
            metadata_={},
            row_version=1,
            created_at=ticket_closed_created,
            updated_at=ticket_closed_at,
            assigned_at=None,
            resolved_at=ticket_closed_resolved_at,
            closed_at=ticket_closed_at,
        )
        session.add_all(
            [open_ticket, resolved_ticket, closed_ticket]
        )

        pending_feedback = FeedbackModel(
            id=uuid7(),
            conversation_id=conversation_id,
            customer_id=customer_id,
            response_message_id=response_message_id,
            ai_run_id=None,
            rating=5,
            helpful=True,
            comment="Helpful response.",
            reason_codes=[],
            status="pending",
            reviewed_by_user_id=None,
            review_notes=None,
            metadata_={},
            row_version=1,
            created_at=pending_feedback_created,
            updated_at=pending_feedback_created,
            reviewed_at=None,
        )

        # Feedback has a uniqueness constraint on response_message_id,
        # so create another assistant response for the second record.
        second_response_id = uuid7()
        second_response = MessageModel(
            id=second_response_id,
            conversation_id=conversation_id,
            role="assistant",
            content="A second support response.",
            sequence_number=3,
            metadata_={},
            created_at=reviewed_feedback_created,
        )
        conversation.next_message_sequence = 4
        session.add(second_response)
        session.flush()

        reviewed_feedback = FeedbackModel(
            id=uuid7(),
            conversation_id=conversation_id,
            customer_id=customer_id,
            response_message_id=second_response_id,
            ai_run_id=None,
            rating=3,
            helpful=False,
            comment="The answer needed clarification.",
            reason_codes=["INCOMPLETE"],
            status="reviewed",
            reviewed_by_user_id=admin_user_id,
            review_notes="Reviewed for quality analysis.",
            metadata_={},
            row_version=1,
            created_at=reviewed_feedback_created,
            updated_at=reviewed_at,
            reviewed_at=reviewed_at,
        )

        session.add_all(
            [pending_feedback, reviewed_feedback]
        )
        session.commit()


class TestDashboardSupportAnalyticsAuthorization:
    def test_requires_authentication(
        self,
        client: TestClient,
    ) -> None:
        now = datetime.now(UTC)

        response = client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=now - timedelta(days=1),
                ended_at=now,
            ),
        )

        assert response.status_code == 401
        assert response.status_code != 200

    def test_rejects_customer(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)

        response = client.get(
            _ENDPOINT,
            headers=customer_auth_headers,
            params=_analytics_params(
                started_at=now - timedelta(days=1),
                ended_at=now,
            ),
        )

        assert response.status_code == 403
        assert response.status_code != 200

    def test_rejects_support_agent(
        self,
        client: TestClient,
        support_agent_auth_headers: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)

        response = client.get(
            _ENDPOINT,
            headers=support_agent_auth_headers,
            params=_analytics_params(
                started_at=now - timedelta(days=1),
                ended_at=now,
            ),
        )

        assert response.status_code == 403
        assert response.status_code != 200


class TestDashboardSupportAnalytics:
    def test_returns_accurate_aggregates(
        self,
        admin_client: TestClient,
        admin_identity,
        test_session_factory,
    ) -> None:
        started_at = datetime(2026, 9, 1, tzinfo=UTC)
        ended_at = started_at + timedelta(days=3)

        _seed_support_records(
            test_session_factory=test_session_factory,
            admin_user_id=admin_identity.user_id,
            started_at=started_at,
        )

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=started_at,
                ended_at=ended_at,
            ),
        )

        assert response.status_code == 200, response.text
        body = response.json()

        assert body["tickets_created"] == 3
        assert body["tickets_resolved"] == 2
        assert body["tickets_closed"] == 1
        assert body["current_ticket_backlog"] == 1

        assert body["escalations_created"] == 2
        assert body["escalations_resolved"] == 1

        assert body["feedback_submitted"] == 2
        assert float(body["average_feedback_rating"]) == 4.0

        ticket_statuses = _distribution(
            body["ticket_status_distribution"]
        )
        assert ticket_statuses == {
            "closed": 1,
            "open": 1,
            "resolved": 1,
        }

        assert _distribution(
            body["ticket_priority_distribution"]
        ) == {
            "high": 1,
            "normal": 1,
            "urgent": 1,
        }

        assert _distribution(
            body["ticket_category_distribution"]
        ) == {
            "billing": 1,
            "refund": 1,
            "technical": 1,
        }

        assert _distribution(
            body["escalation_status_distribution"]
        ) == {
            "open": 1,
            "resolved": 1,
        }

        assert _distribution(
            body["feedback_rating_distribution"]
        ) == {
            "3": 1,
            "5": 1,
        }

        assert _distribution(
            body["feedback_status_distribution"]
        ) == {
            "pending": 1,
            "reviewed": 1,
        }

        snapshot = datetime.fromisoformat(
            body["snapshot_measured_at"].replace("Z", "+00:00")
        )
        assert snapshot.tzinfo is not None

    def test_returns_resolution_duration_summaries(
        self,
        admin_client: TestClient,
        admin_identity,
        test_session_factory,
    ) -> None:
        started_at = datetime(2026, 9, 1, tzinfo=UTC)
        ended_at = started_at + timedelta(days=3)

        _seed_support_records(
            test_session_factory=test_session_factory,
            admin_user_id=admin_identity.user_id,
            started_at=started_at,
        )

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=started_at,
                ended_at=ended_at,
            ),
        )

        assert response.status_code == 200, response.text
        body = response.json()

        ticket_duration = body[
            "ticket_resolution_duration"
        ]
        assert ticket_duration["sample_count"] == 2
        assert float(ticket_duration["average_ms"]) == 5_400_000
        assert float(ticket_duration["p50_ms"]) == 5_400_000
        assert float(ticket_duration["p95_ms"]) == 7_020_000

        escalation_duration = body[
            "escalation_resolution_duration"
        ]
        assert escalation_duration["sample_count"] == 1
        assert float(escalation_duration["average_ms"]) == 1_800_000
        assert float(escalation_duration["p50_ms"]) == 1_800_000
        assert float(escalation_duration["p95_ms"]) == 1_800_000

    def test_returns_zero_filled_daily_timeline(
        self,
        admin_client: TestClient,
        admin_identity,
        test_session_factory,
    ) -> None:
        started_at = datetime(2026, 9, 1, tzinfo=UTC)
        ended_at = started_at + timedelta(days=3)

        _seed_support_records(
            test_session_factory=test_session_factory,
            admin_user_id=admin_identity.user_id,
            started_at=started_at,
        )

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=started_at,
                ended_at=ended_at,
                bucket="day",
            ),
        )

        assert response.status_code == 200, response.text
        timeline = response.json()["timeline"]

        assert len(timeline) == 3

        assert timeline[0]["tickets_created"] == 2
        assert timeline[0]["tickets_resolved"] == 1
        assert timeline[0]["tickets_closed"] == 0
        assert timeline[0]["escalations_created"] == 1
        assert timeline[0]["escalations_resolved"] == 0
        assert timeline[0]["feedback_submitted"] == 1

        assert timeline[1]["tickets_created"] == 1
        assert timeline[1]["tickets_resolved"] == 1
        assert timeline[1]["tickets_closed"] == 1
        assert timeline[1]["escalations_created"] == 1
        assert timeline[1]["escalations_resolved"] == 1
        assert timeline[1]["feedback_submitted"] == 1

        assert timeline[2]["tickets_created"] == 0
        assert timeline[2]["tickets_resolved"] == 0
        assert timeline[2]["tickets_closed"] == 0
        assert timeline[2]["escalations_created"] == 0
        assert timeline[2]["escalations_resolved"] == 0
        assert timeline[2]["feedback_submitted"] == 0

    def test_empty_window_returns_zero_event_metrics(
        self,
        admin_client: TestClient,
    ) -> None:
        started_at = datetime(2035, 1, 1, tzinfo=UTC)
        ended_at = started_at + timedelta(days=3)

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=started_at,
                ended_at=ended_at,
            ),
        )

        assert response.status_code == 200, response.text
        body = response.json()

        assert body["tickets_created"] == 0
        assert body["tickets_resolved"] == 0
        assert body["tickets_closed"] == 0
        assert body["escalations_created"] == 0
        assert body["escalations_resolved"] == 0
        assert body["feedback_submitted"] == 0
        assert body["average_feedback_rating"] is None
        assert len(body["timeline"]) == 3

        for point in body["timeline"]:
            assert point["tickets_created"] == 0
            assert point["tickets_resolved"] == 0
            assert point["tickets_closed"] == 0
            assert point["escalations_created"] == 0
            assert point["escalations_resolved"] == 0
            assert point["feedback_submitted"] == 0

    def test_rejects_invalid_window_instead_of_returning_200(
        self,
        admin_client: TestClient,
    ) -> None:
        boundary = datetime.now(UTC)

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=boundary,
                ended_at=boundary,
            ),
        )

        assert response.status_code == 422
        assert response.status_code != 200

        body = response.json()
        assert body["error"]["code"] == (
            "INVALID_ANALYTICS_WINDOW"
        )

    def test_rejects_naive_timestamps_instead_of_returning_200(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            _ENDPOINT,
            params={
                "started_at": "2026-09-01T00:00:00",
                "ended_at": "2026-09-02T00:00:00",
                "bucket": "day",
            },
        )

        assert response.status_code == 422
        assert response.status_code != 200

    def test_does_not_expose_sensitive_support_content(
        self,
        admin_client: TestClient,
        admin_identity,
        test_session_factory,
    ) -> None:
        started_at = datetime(2026, 9, 1, tzinfo=UTC)
        ended_at = started_at + timedelta(days=3)

        _seed_support_records(
            test_session_factory=test_session_factory,
            admin_user_id=admin_identity.user_id,
            started_at=started_at,
        )

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=started_at,
                ended_at=ended_at,
            ),
        )

        assert response.status_code == 200, response.text

        serialized = response.text.lower()

        for forbidden_content in (
            "i need support",
            "a support response",
            "open billing request",
            "an unresolved billing request",
            "customer requested human review",
            "reviewed for quality analysis",
            "helpful response",
            "incomplete",
        ):
            assert forbidden_content not in serialized