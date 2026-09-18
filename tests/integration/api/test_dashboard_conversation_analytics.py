# AI-customer-support-agent\tests\integration\api\test_dashboard_conversation_analytics.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
from packages.database.models.support.message import (
    MessageModel,
)
from packages.database.models.support.user import UserModel


UTC = timezone.utc

WINDOW_START = datetime(
    2026,
    9,
    10,
    0,
    0,
    tzinfo=UTC,
)
WINDOW_END = datetime(
    2026,
    9,
    13,
    0,
    0,
    tzinfo=UTC,
)


def _analytics_params(
    *,
    started_at: datetime = WINDOW_START,
    ended_at: datetime = WINDOW_END,
    bucket: str = "day",
) -> dict[str, str]:
    return {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "bucket": bucket,
    }


def _create_conversation(
    session,
    *,
    user_id: UUID,
    status: str,
    created_at: datetime,
    updated_at: datetime | None = None,
    resolved_at: datetime | None = None,
    closed_at: datetime | None = None,
) -> UUID:
    conversation_id = uuid7()

    session.add(
        ConversationModel(
            id=conversation_id,
            user_id=user_id,
            status=status,
            channel="web",
            title="Analytics integration conversation",
            next_message_sequence=1,
            created_at=created_at,
            updated_at=updated_at or created_at,
            resolved_at=resolved_at,
            closed_at=closed_at,
        )
    )

    return conversation_id


def _create_message(
    session,
    *,
    conversation_id: UUID,
    role: str,
    sequence_number: int,
    created_at: datetime,
) -> UUID:
    message_id = uuid7()

    session.add(
        MessageModel(
            id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=f"Safe {role} integration-test message.",
            sequence_number=sequence_number,
            metadata_={
                "integration_test": True,
            },
            created_at=created_at,
        )
    )

    return message_id


def _create_escalation(
    session,
    *,
    conversation_id: UUID,
    created_at: datetime,
) -> UUID:
    escalation_id = uuid7()

    session.add(
        EscalationModel(
            id=escalation_id,
            conversation_id=conversation_id,
            ai_run_id=None,
            trigger_message_id=None,
            source="system",
            reason_code="low_confidence",
            reason_summary="Integration-test escalation.",
            priority="high",
            status="open",
            handoff_summary=None,
            metadata_={
                "integration_test": True,
            },
            created_at=created_at,
            updated_at=created_at,
            resolved_at=None,
        )
    )

    return escalation_id


def _seed_analytics_dataset(
    test_session_factory,
) -> None:
    first_user_id = uuid7()
    second_user_id = uuid7()
    outside_user_id = uuid7()

    first_created_at = WINDOW_START + timedelta(hours=1)
    first_closed_at = WINDOW_START + timedelta(
        days=1,
        hours=3,
    )

    second_created_at = WINDOW_START + timedelta(
        days=1,
        hours=1,
    )

    outside_created_at = WINDOW_START - timedelta(days=2)

    with test_session_factory() as session:
        session.add_all(
            [
                UserModel(id=first_user_id),
                UserModel(id=second_user_id),
                UserModel(id=outside_user_id),
            ]
        )
        session.flush()

        first_conversation_id = _create_conversation(
            session,
            user_id=first_user_id,
            status="closed",
            created_at=first_created_at,
            updated_at=first_closed_at,
            closed_at=first_closed_at,
        )

        second_conversation_id = _create_conversation(
            session,
            user_id=second_user_id,
            status="open",
            created_at=second_created_at,
        )

        outside_conversation_id = _create_conversation(
            session,
            user_id=outside_user_id,
            status="open",
            created_at=outside_created_at,
        )

        session.flush()

        _create_message(
            session,
            conversation_id=first_conversation_id,
            role="customer",
            sequence_number=1,
            created_at=first_created_at + timedelta(minutes=5),
        )
        _create_message(
            session,
            conversation_id=first_conversation_id,
            role="assistant",
            sequence_number=2,
            created_at=first_created_at + timedelta(minutes=6),
        )
        _create_message(
            session,
            conversation_id=second_conversation_id,
            role="customer",
            sequence_number=1,
            created_at=second_created_at + timedelta(minutes=5),
        )

        # This message is outside the requested window.
        _create_message(
            session,
            conversation_id=outside_conversation_id,
            role="customer",
            sequence_number=1,
            created_at=outside_created_at + timedelta(minutes=5),
        )

        _create_escalation(
            session,
            conversation_id=second_conversation_id,
            created_at=second_created_at + timedelta(minutes=10),
        )

        session.commit()


def _categories(
    body: dict[str, Any],
    field_name: str,
) -> dict[str, int]:
    return {
        item["category"]: item["count"]
        for item in body[field_name]
    }


class TestDashboardConversationAnalyticsAuthorization:
    def test_requires_authentication(
        self,
        client: TestClient,
    ) -> None:
        response = client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(),
        )

        assert response.status_code == 401

    def test_rejects_customer(
        self,
        customer_client: TestClient,
    ) -> None:
        response = customer_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(),
        )

        assert response.status_code == 403

    def test_rejects_support_agent(
        self,
        support_agent_client: TestClient,
    ) -> None:
        response = support_agent_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(),
        )

        assert response.status_code == 403


class TestDashboardConversationAnalytics:
    def test_returns_accurate_aggregates(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        _seed_analytics_dataset(test_session_factory)

        response = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(),
        )

        assert response.status_code == 200, response.text
        body = response.json()

        assert body["total_conversations"] == 2
        assert body["closed_conversations"] == 1
        assert body["escalated_conversations"] == 1
        assert body["customer_messages"] == 2
        assert body["assistant_messages"] == 1

        assert Decimal(
            str(body["average_messages_per_conversation"])
        ) == Decimal("1.5")

        assert Decimal(
            str(body["escalation_rate"])
        ) == Decimal("0.5")

        assert _categories(
            body,
            "status_distribution",
        ) == {
            "closed": 1,
            "open": 1,
        }

        duration = body["closure_duration"]

        assert duration["sample_count"] == 1
        assert Decimal(
            str(duration["average_ms"])
        ) == Decimal("93600000")
        assert Decimal(
            str(duration["p50_ms"])
        ) == Decimal("93600000")
        assert Decimal(
            str(duration["p95_ms"])
        ) == Decimal("93600000")

    def test_returns_zero_filled_daily_timeline(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        _seed_analytics_dataset(test_session_factory)

        response = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(),
        )

        assert response.status_code == 200, response.text
        timeline = response.json()["timeline"]

        assert len(timeline) == 3

        assert timeline[0]["conversations_created"] == 1
        assert timeline[0]["conversations_closed"] == 0
        assert timeline[0]["customer_messages"] == 1
        assert timeline[0]["assistant_messages"] == 1

        assert timeline[1]["conversations_created"] == 1
        assert timeline[1]["conversations_closed"] == 1
        assert timeline[1]["customer_messages"] == 1
        assert timeline[1]["assistant_messages"] == 0

        assert timeline[2]["conversations_created"] == 0
        assert timeline[2]["conversations_closed"] == 0
        assert timeline[2]["customer_messages"] == 0
        assert timeline[2]["assistant_messages"] == 0

    def test_empty_window_returns_zero_metrics(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(),
        )

        assert response.status_code == 200, response.text
        body = response.json()

        assert body["total_conversations"] == 0
        assert body["closed_conversations"] == 0
        assert body["escalated_conversations"] == 0
        assert body["customer_messages"] == 0
        assert body["assistant_messages"] == 0
        assert body["average_messages_per_conversation"] is None
        assert body["escalation_rate"] is None
        assert body["status_distribution"] == []

        duration = body["closure_duration"]
        assert duration == {
            "sample_count": 0,
            "average_ms": None,
            "p50_ms": None,
            "p95_ms": None,
        }

        # The requested interval still produces empty chart buckets.
        assert len(body["timeline"]) == 3
        assert all(
            point["conversations_created"] == 0
            and point["conversations_closed"] == 0
            and point["customer_messages"] == 0
            and point["assistant_messages"] == 0
            for point in body["timeline"]
        )

    def test_uses_half_open_time_boundaries(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        included_user_id = uuid7()
        excluded_user_id = uuid7()

        with test_session_factory() as session:
            session.add_all(
                [
                    UserModel(id=included_user_id),
                    UserModel(id=excluded_user_id),
                ]
            )
            session.flush()

            _create_conversation(
                session,
                user_id=included_user_id,
                status="open",
                created_at=WINDOW_START,
            )
            _create_conversation(
                session,
                user_id=excluded_user_id,
                status="open",
                created_at=WINDOW_END,
            )

            session.commit()

        response = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(),
        )

        assert response.status_code == 200, response.text
        assert response.json()["total_conversations"] == 1

    def test_does_not_expose_sensitive_fields(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        _seed_analytics_dataset(test_session_factory)

        response = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(),
        )

        assert response.status_code == 200, response.text

        serialized = response.text.lower()

        for forbidden_name in (
            "content",
            "email",
            "title",
            "reason_summary",
            "handoff_summary",
            "metadata_",
            "prompt",
            "password",
            "token",
        ):
            assert forbidden_name not in serialized


class TestDashboardConversationAnalyticsValidation:
    def test_rejects_naive_timestamp(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params={
                "started_at": "2026-09-10T00:00:00",
                "ended_at": "2026-09-13T00:00:00Z",
                "bucket": "day",
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "INVALID_ANALYTICS_WINDOW"
        )

    def test_rejects_reversed_window(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(
                started_at=WINDOW_END,
                ended_at=WINDOW_START,
            ),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "INVALID_ANALYTICS_WINDOW"
        )

    def test_rejects_equal_window(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(
                started_at=WINDOW_START,
                ended_at=WINDOW_START,
            ),
        )

        assert response.status_code == 422

    def test_rejects_excessive_hour_range(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(
                started_at=WINDOW_START,
                ended_at=WINDOW_START + timedelta(days=32),
                bucket="hour",
            ),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "INVALID_ANALYTICS_WINDOW"
        )

    def test_rejects_unknown_bucket(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params={
                "started_at": WINDOW_START.isoformat(),
                "ended_at": WINDOW_END.isoformat(),
                "bucket": "month",
            },
        )

        assert response.status_code == 422