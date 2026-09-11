# AI-customer-support-agent\tests\integration\api\test_dashboard_audit_events.py

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.audit.audit_event import (
    AuditEventModel,
)


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolate_database(clean_database):
    """Keep audit dashboard assertions isolated."""
    yield


def _seed_audit_event(
    *,
    test_session_factory,
    event_type: str = "ticket.updated",
    entity_type: str = "ticket",
    action: str = "updated",
    actor_type: str = "system",
    actor_id: uuid.UUID | None = None,
    trace_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    ai_run_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, uuid.UUID | datetime]:
    event_id = uuid7()
    entity_id = uuid7()
    resolved_trace_id = trace_id or uuid7()
    resolved_conversation_id = conversation_id or uuid7()
    resolved_occurred_at = (
        occurred_at or datetime.now(timezone.utc)
    )

    event = AuditEventModel(
        id=event_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        trace_id=resolved_trace_id,
        conversation_id=resolved_conversation_id,
        ai_run_id=ai_run_id,
        before_state={
            "status": "open",
            "secret": "SECRET-BEFORE-STATE",
        },
        after_state={
            "status": "resolved",
            "secret": "SECRET-AFTER-STATE",
        },
        reason="SECRET-AUDIT-REASON",
        metadata_={
            "secret": "SECRET-AUDIT-METADATA",
        },
        occurred_at=resolved_occurred_at,
        recorded_at=resolved_occurred_at,
    )

    with test_session_factory() as session:
        session.add(event)
        session.commit()

    return {
        "event_id": event_id,
        "entity_id": entity_id,
        "trace_id": resolved_trace_id,
        "conversation_id": resolved_conversation_id,
        "occurred_at": resolved_occurred_at,
    }


class TestDashboardAuditEvents:
    def test_returns_sanitized_audit_event(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        identifiers = _seed_audit_event(
            test_session_factory=test_session_factory,
        )

        response = client.get(
            "/v1/dashboard/audit-events",
            params={
                "trace_id": str(identifiers["trace_id"]),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1
        assert body["limit"] == 100
        assert body["offset"] == 0
        assert body["has_more"] is False
        assert body["next_offset"] is None

        event = body["items"][0]

        assert event["id"] == str(
            identifiers["event_id"]
        )
        assert event["event_type"] == "ticket.updated"
        assert event["entity_type"] == "ticket"
        assert event["entity_id"] == str(
            identifiers["entity_id"]
        )
        assert event["action"] == "updated"
        assert event["actor_type"] == "system"
        assert event["actor_id"] is None
        assert event["trace_id"] == str(
            identifiers["trace_id"]
        )
        assert event["conversation_id"] == str(
            identifiers["conversation_id"]
        )
        assert event["ai_run_id"] is None
        assert event["has_before_state"] is True
        assert event["has_after_state"] is True
        assert event["has_reason"] is True
        assert event["occurred_at"] is not None
        assert event["recorded_at"] is not None

    def test_filters_by_event_entity_action_and_actor(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        identifiers = _seed_audit_event(
            test_session_factory=test_session_factory,
            event_type="knowledge_version.published",
            entity_type="knowledge_version",
            action="published",
            actor_type="admin",
            actor_id=uuid7(),
        )

        response = client.get(
            "/v1/dashboard/audit-events",
            params={
                "event_type": (
                    "knowledge_version.published"
                ),
                "entity_type": "knowledge_version",
                "entity_id": str(
                    identifiers["entity_id"]
                ),
                "action": "published",
                "actor_type": "admin",
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1

        event = body["items"][0]

        assert (
            event["event_type"]
            == "knowledge_version.published"
        )
        assert event["entity_type"] == "knowledge_version"
        assert event["action"] == "published"
        assert event["actor_type"] == "admin"

    def test_filters_by_trace_and_conversation(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        trace_id = uuid7()
        conversation_id = uuid7()

        identifiers = _seed_audit_event(
            test_session_factory=test_session_factory,
            trace_id=trace_id,
            conversation_id=conversation_id,
        )

        response = client.get(
            "/v1/dashboard/audit-events",
            params={
                "trace_id": str(trace_id),
                "conversation_id": str(conversation_id),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["items"][0]["id"] == str(
            identifiers["event_id"]
        )

    def test_respects_explicit_time_range(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        now = datetime.now(timezone.utc)

        included = _seed_audit_event(
            test_session_factory=test_session_factory,
            occurred_at=now - timedelta(hours=1),
        )
        _seed_audit_event(
            test_session_factory=test_session_factory,
            occurred_at=now - timedelta(days=2),
        )

        response = client.get(
            "/v1/dashboard/audit-events",
            params={
                "started_at": (
                    now - timedelta(hours=2)
                ).isoformat(),
                "ended_at": now.isoformat(),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["items"][0]["id"] == str(
            included["event_id"]
        )

    def test_non_matching_filter_returns_empty_page(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        _seed_audit_event(
            test_session_factory=test_session_factory,
        )

        response = client.get(
            "/v1/dashboard/audit-events",
            params={
                "trace_id": str(uuid7()),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["items"] == []
        assert body["total"] == 0
        assert body["count"] == 0
        assert body["has_more"] is False
        assert body["next_offset"] is None

    def test_paginates_without_duplicates(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        _seed_audit_event(
            test_session_factory=test_session_factory,
        )
        _seed_audit_event(
            test_session_factory=test_session_factory,
        )

        first_response = client.get(
            "/v1/dashboard/audit-events",
            params={
                "limit": 1,
                "offset": 0,
            },
        )
        second_response = client.get(
            "/v1/dashboard/audit-events",
            params={
                "limit": 1,
                "offset": 1,
            },
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200

        first_body = first_response.json()
        second_body = second_response.json()

        assert first_body["total"] == 2
        assert second_body["total"] == 2
        assert first_body["count"] == 1
        assert second_body["count"] == 1

        assert first_body["has_more"] is True
        assert first_body["next_offset"] == 1
        assert second_body["has_more"] is False
        assert second_body["next_offset"] is None

        assert (
            first_body["items"][0]["id"]
            != second_body["items"][0]["id"]
        )

    def test_rejects_invalid_actor_type(
        self,
        client: TestClient,
    ) -> None:
        response = client.get(
            "/v1/dashboard/audit-events",
            params={
                "actor_type": "superuser",
            },
        )

        assert response.status_code == 422

    def test_does_not_expose_sensitive_audit_state(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        identifiers = _seed_audit_event(
            test_session_factory=test_session_factory,
        )

        response = client.get(
            "/v1/dashboard/audit-events",
            params={
                "trace_id": str(identifiers["trace_id"]),
            },
        )

        assert response.status_code == 200

        event = response.json()["items"][0]

        prohibited_fields = {
            "before_state",
            "after_state",
            "reason",
            "metadata",
            "metadata_",
        }

        assert set(event).isdisjoint(prohibited_fields)
        assert "SECRET-BEFORE-STATE" not in response.text
        assert "SECRET-AFTER-STATE" not in response.text
        assert "SECRET-AUDIT-REASON" not in response.text
        assert "SECRET-AUDIT-METADATA" not in response.text