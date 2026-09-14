# AI-customer-support-agent\tests\integration\api\test_feedback_flow.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.conversation import (
    ConversationModel,
)
from packages.database.models.support.feedback import FeedbackModel
from packages.database.models.support.message import MessageModel
# from packages.database.models.support.user import UserModel


@dataclass(frozen=True, slots=True)
class FeedbackTestContext:
    customer_id: uuid.UUID
    other_customer_id: uuid.UUID
    agent_id: uuid.UUID
    admin_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    ai_run_id: uuid.UUID
    customer_headers: dict[str, str]
    other_customer_headers: dict[str, str]
    agent_headers: dict[str, str]
    admin_headers: dict[str, str]


@pytest.fixture()
def feedback_context(
    test_session_factory,
    customer_identity,
    support_agent_identity,
    admin_identity,
    authenticated_identity_factory,
) -> FeedbackTestContext:
    other_customer_identity = authenticated_identity_factory(
        role="customer",
        email="other-feedback-customer@example.com",
    )

    conversation_id = uuid7()
    customer_message_id = uuid7()
    assistant_message_id = uuid7()
    ai_run_id = uuid7()
    completed_at = datetime.now(timezone.utc)

    with test_session_factory() as session:
        session.add(
            ConversationModel(
                id=conversation_id,
                user_id=customer_identity.user_id,
            )
        )
        session.flush()

        session.add_all(
            [
                MessageModel(
                    id=customer_message_id,
                    conversation_id=conversation_id,
                    role="customer",
                    content="What is your refund policy?",
                    sequence_number=1,
                    metadata_={},
                ),
                MessageModel(
                    id=assistant_message_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=(
                        "Refunds can be requested within the "
                        "eligible return period."
                    ),
                    sequence_number=2,
                    metadata_={
                        "grounded": True,
                    },
                ),
            ]
        )
        session.flush()

        session.add(
            AIRunModel(
                id=ai_run_id,
                conversation_id=conversation_id,
                trigger_message_id=customer_message_id,
                response_message_id=assistant_message_id,
                parent_run_id=None,
                pipeline_version="test-v1",
                status="completed",
                completed_at=completed_at,
                total_latency_ms=25,
                error_code=None,
                error_message=None,
            )
        )
        session.commit()

    return FeedbackTestContext(
        customer_id=customer_identity.user_id,
        other_customer_id=other_customer_identity.user_id,
        agent_id=support_agent_identity.user_id,
        admin_id=admin_identity.user_id,
        conversation_id=conversation_id,
        customer_message_id=customer_message_id,
        assistant_message_id=assistant_message_id,
        ai_run_id=ai_run_id,
        customer_headers=customer_identity.authorization_headers,
        other_customer_headers=(
            other_customer_identity.authorization_headers
        ),
        agent_headers=(
            support_agent_identity.authorization_headers
        ),
        admin_headers=admin_identity.authorization_headers,
    )


def _feedback_payload(
    context: FeedbackTestContext,
    *,
    rating: int = 2,
) -> dict[str, Any]:
    return {
        "response_message_id": str(
            context.assistant_message_id
        ),
        "ai_run_id": str(context.ai_run_id),
        "rating": rating,
        "helpful": False,
        "comment": (
            "The answer did not explain the exact "
            "eligibility period."
        ),
        "reason_codes": [
            "INCOMPLETE_ANSWER",
            "MISSING_CITATION",
        ],
        "metadata": {
            "channel": "chat",
        },
    }


def _submit_feedback(
    client: TestClient,
    context: FeedbackTestContext,
) -> dict[str, Any]:
    response = client.post(
        f"/v1/conversations/{context.conversation_id}/feedback",
        headers=context.customer_headers,
        json=_feedback_payload(context),
    )

    assert response.status_code == 201, response.text
    return response.json()


class TestFeedbackSubmission:
    def test_submits_and_persists_feedback(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
        test_session_factory,
    ) -> None:
        body = _submit_feedback(
            client,
            feedback_context,
        )

        feedback_id = uuid.UUID(body["feedback_id"])

        assert body["conversation_id"] == str(
            feedback_context.conversation_id
        )
        assert body["customer_id"] == str(
            feedback_context.customer_id
        )
        assert body["response_message_id"] == str(
            feedback_context.assistant_message_id
        )
        assert body["ai_run_id"] == str(
            feedback_context.ai_run_id
        )
        assert body["rating"] == 2
        assert body["helpful"] is False
        assert body["reason_codes"] == [
            "INCOMPLETE_ANSWER",
            "MISSING_CITATION",
        ]
        assert body["status"] == "pending"
        assert body["row_version"] == 1
        assert body["created"] is True

        with test_session_factory() as session:
            feedback = session.get(
                FeedbackModel,
                feedback_id,
            )

            assert feedback is not None
            assert feedback.rating == 2
            assert feedback.helpful is False
            assert feedback.status == "pending"
            assert feedback.metadata_ == {
                "channel": "chat"
            }

    def test_identical_retry_is_idempotent(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        first = client.post(
            f"/v1/conversations/"
            f"{feedback_context.conversation_id}/feedback",
            headers=feedback_context.customer_headers,
            json=_feedback_payload(feedback_context),
        )

        second = client.post(
            f"/v1/conversations/"
            f"{feedback_context.conversation_id}/feedback",
            headers=feedback_context.customer_headers,
            json=_feedback_payload(feedback_context),
        )

        assert first.status_code == 201
        assert second.status_code == 201

        first_body = first.json()
        second_body = second.json()

        assert first_body["created"] is True
        assert second_body["created"] is False
        assert (
            second_body["feedback_id"]
            == first_body["feedback_id"]
        )

    def test_conflicting_duplicate_returns_409(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        first = client.post(
            f"/v1/conversations/"
            f"{feedback_context.conversation_id}/feedback",
            headers=feedback_context.customer_headers,
            json=_feedback_payload(feedback_context),
        )

        assert first.status_code == 201

        conflicting_payload = _feedback_payload(
            feedback_context,
            rating=5,
        )
        conflicting_payload["helpful"] = True

        second = client.post(
            f"/v1/conversations/"
            f"{feedback_context.conversation_id}/feedback",
            headers=feedback_context.customer_headers,
            json=conflicting_payload,
        )

        assert second.status_code == 409

        error = second.json()["error"]

        assert error["code"] == "FEEDBACK_CONFLICT"
        assert error["trace_id"] == second.headers["X-Trace-ID"]

    def test_customer_cannot_rate_customer_message(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        payload = _feedback_payload(feedback_context)
        payload["response_message_id"] = str(
            feedback_context.customer_message_id
        )

        response = client.post(
            f"/v1/conversations/"
            f"{feedback_context.conversation_id}/feedback",
            headers=feedback_context.customer_headers,
            json=payload,
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == (
            "INVALID_FEEDBACK_OPERATION"
        )

    def test_wrong_customer_ownership_returns_403(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        response = client.post(
            f"/v1/conversations/"
            f"{feedback_context.conversation_id}/feedback",
            headers=feedback_context.other_customer_headers,
            json=_feedback_payload(feedback_context),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == (
            "FEEDBACK_ACCESS_DENIED"
        )
        
    def test_customer_id_input_is_rejected(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        payload = _feedback_payload(feedback_context)
        payload["customer_id"] = str(
            feedback_context.other_customer_id
        )

        response = client.post(
            f"/v1/conversations/"
            f"{feedback_context.conversation_id}/feedback",
            headers=feedback_context.customer_headers,
            json=payload,
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "INVALID_REQUEST"
        )


class TestFeedbackQueries:
    def test_customer_can_view_owned_feedback_without_internal_data(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        submitted = _submit_feedback(
            client,
            feedback_context,
        )

        response = client.get(
            f"/v1/feedback/{submitted['feedback_id']}",
            headers=feedback_context.customer_headers,
        )

        assert response.status_code == 200

        body = response.json()

        assert body["feedback_id"] == submitted["feedback_id"]
        assert body["metadata"] == {}
        assert body["reviewed_by_user_id"] is None
        assert body["review_notes"] is None
        assert body["reviewed_at"] is None

    def test_other_customer_cannot_view_feedback(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        submitted = _submit_feedback(
            client,
            feedback_context,
        )

        response = client.get(
            f"/v1/feedback/{submitted['feedback_id']}",
            headers=feedback_context.other_customer_headers,
        )

        # assert response.status_code == 403
        # assert response.json()["error"]["code"] == (
        #     "FEEDBACK_ACCESS_DENIED"
        # )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "FEEDBACK_NOT_FOUND"
        )

    def test_agent_can_filter_dashboard_feedback(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        submitted = _submit_feedback(
            client,
            feedback_context,
        )

        response = client.get(
            "/v1/feedback",
            headers=feedback_context.agent_headers,
            params={
                "status": "pending",
                "rating": 2,
                "helpful": "false",
                "reason_code": "INCOMPLETE_ANSWER",
            },
        )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["count"] == 1
        assert body["has_more"] is False
        assert body["items"][0]["feedback_id"] == (
            submitted["feedback_id"]
        )
        assert body["items"][0]["metadata"] == {
            "channel": "chat"
        }

    def test_missing_feedback_returns_canonical_404(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        response = client.get(
            f"/v1/feedback/{uuid7()}",
            headers=feedback_context.agent_headers,
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "FEEDBACK_NOT_FOUND"
        )
        assert response.json()["error"]["trace_id"] == (
            response.headers["X-Trace-ID"]
        )


class TestFeedbackReview:
    def test_agent_reviews_then_actions_feedback(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        submitted = _submit_feedback(
            client,
            feedback_context,
        )
        feedback_id = submitted["feedback_id"]

        reviewed = client.patch(
            f"/v1/feedback/{feedback_id}/review",
            headers=feedback_context.agent_headers,
            json={
                # "reviewer_id": str(feedback_context.agent_id),
                "expected_row_version": submitted["row_version"],
                "target_status": "reviewed",
            },
        )

        assert reviewed.status_code == 200, reviewed.text

        reviewed_body = reviewed.json()

        assert reviewed_body["previous_status"] == "pending"
        assert reviewed_body["current_status"] == "reviewed"
        assert reviewed_body["reviewed_by_user_id"] == str(
            feedback_context.agent_id
        )
        assert reviewed_body["reviewed_at"] is not None
        assert reviewed_body["changed"] is True
        assert (
            reviewed_body["row_version"]
            > submitted["row_version"]
        )

        actioned = client.patch(
            f"/v1/feedback/{feedback_id}/review",
            headers=feedback_context.admin_headers,
            json={
                # "reviewer_id": str(feedback_context.admin_id),
                "expected_row_version": (
                    reviewed_body["row_version"]
                ),
                "target_status": "actioned",
                "review_notes": (
                    "Knowledge article was updated with the "
                    "missing eligibility period."
                ),
            },
        )

        assert actioned.status_code == 200, actioned.text

        actioned_body = actioned.json()

        assert actioned_body["previous_status"] == "reviewed"
        assert actioned_body["current_status"] == "actioned"
        assert actioned_body["review_notes"] == (
            "Knowledge article was updated with the "
            "missing eligibility period."
        )
        assert actioned_body["changed"] is True

        # The original reviewer is intentionally retained.
        assert actioned_body["reviewed_by_user_id"] == str(
            feedback_context.agent_id
        )

    def test_customer_cannot_review_feedback(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        submitted = _submit_feedback(
            client,
            feedback_context,
        )

        response = client.patch(
            f"/v1/feedback/{submitted['feedback_id']}/review",
            headers=feedback_context.customer_headers,
            json={
                # "reviewer_id": str(feedback_context.customer_id),
                "expected_row_version": submitted["row_version"],
                "target_status": "reviewed",
            },
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"

    def test_stale_review_version_returns_409(
        self,
        client: TestClient,
        feedback_context: FeedbackTestContext,
    ) -> None:
        submitted = _submit_feedback(
            client,
            feedback_context,
        )
        feedback_id = submitted["feedback_id"]
        initial_version = submitted["row_version"]

        first = client.patch(
            f"/v1/feedback/{feedback_id}/review",
            headers=feedback_context.agent_headers,
            json={
                # "reviewer_id": str(feedback_context.agent_id),
                "expected_row_version": initial_version,
                "target_status": "reviewed",
            },
        )

        assert first.status_code == 200

        stale = client.patch(
            f"/v1/feedback/{feedback_id}/review",
            headers=feedback_context.admin_headers,
            json={
                # "reviewer_id": str(feedback_context.admin_id),
                "expected_row_version": initial_version,
                "target_status": "actioned",
                "review_notes": "Corrective action completed.",
            },
        )

        assert stale.status_code == 409

        error = stale.json()["error"]

        assert error["code"] == "FEEDBACK_CONCURRENT_UPDATE"
        assert error["trace_id"] == stale.headers["X-Trace-ID"]