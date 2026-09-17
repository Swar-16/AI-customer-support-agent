# AI-customer-support-agent\tests\integration\api\test_start_conversation.py
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from uuid6 import uuid7

from packages.ai.providers.mock import MockLLMProvider
from packages.application.auth.models import (
    AuthenticatedPrincipal,
    AuthRole,
)
from packages.application.composition.application_factory import (
    ApplicationServices,
)
from packages.application.conversations.accept_conversation_start import (
    AcceptConversationStartCommand,
)
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.conversation import (
    ConversationModel,
)
from packages.database.models.support.conversation_start_request import (
    ConversationStartRequestModel,
)
from packages.database.models.support.message import MessageModel
from packages.database.unit_of_work.sqlalchemy_uow import (
    SqlAlchemyUnitOfWork,
)


def _headers(
    customer_auth_headers: dict[str, str],
    *,
    idempotency_key: str,
    trace_id: uuid.UUID | None = None,
) -> dict[str, str]:
    result = {
        **customer_auth_headers,
        "Idempotency-Key": idempotency_key,
    }

    if trace_id is not None:
        result["X-Trace-ID"] = str(trace_id)

    return result


def _payload(
    message: str = "Where is order ORD-12345?",
) -> dict[str, object]:
    return {
        "message": message,
        "channel": "web",
        "title": None,
    }


class TestStartConversation:
    def test_creates_conversation_and_processes_first_message(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
        test_session_factory,
    ) -> None:
        key = str(uuid7())
        trace_id = uuid7()

        response = client.post(
            "/v1/conversations/start",
            headers=_headers(
                customer_auth_headers,
                idempotency_key=key,
                trace_id=trace_id,
            ),
            json=_payload(),
        )

        assert response.status_code == 201, response.text

        body = response.json()

        assert body["created"] is True
        assert body["replayed"] is False
        assert body["idempotency_status"] == "completed"
        assert body["succeeded"] is True
        assert body["trace_id"] == str(trace_id)

        request_id = uuid.UUID(
            body["start_request_id"]
        )
        conversation_id = uuid.UUID(
            body["conversation_id"]
        )
        message_id = uuid.UUID(
            body["customer_message_id"]
        )
        ai_run_id = uuid.UUID(body["ai_run_id"])

        with test_session_factory() as session:
            start_request = session.get(
                ConversationStartRequestModel,
                request_id,
            )
            conversation = session.get(
                ConversationModel,
                conversation_id,
            )
            message = session.get(
                MessageModel,
                message_id,
            )
            ai_run = session.get(
                AIRunModel,
                ai_run_id,
            )

        assert start_request is not None
        assert start_request.status == "completed"
        assert start_request.attempt_count == 1
        assert start_request.response_snapshot is not None
        assert start_request.latest_ai_run_id == ai_run_id

        assert conversation is not None
        assert conversation.next_message_sequence == 2

        assert message is not None
        assert message.role == "customer"
        assert message.sequence_number == 1
        assert message.content == "Where is order ORD-12345?"

        assert ai_run is not None
        assert ai_run.trigger_message_id == message_id
        assert ai_run.status == "completed"

    def test_identical_retry_replays_terminal_result(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
        test_session_factory,
    ) -> None:
        key = str(uuid7())
        payload = _payload()

        first = client.post(
            "/v1/conversations/start",
            headers=_headers(
                customer_auth_headers,
                idempotency_key=key,
            ),
            json=payload,
        )
        second = client.post(
            "/v1/conversations/start",
            headers=_headers(
                customer_auth_headers,
                idempotency_key=key,
            ),
            json=payload,
        )

        assert first.status_code == 201, first.text
        assert second.status_code == 200, second.text

        first_body = first.json()
        second_body = second.json()

        assert first_body["created"] is True
        assert first_body["replayed"] is False

        assert second_body["created"] is False
        assert second_body["replayed"] is True

        for field_name in (
            "start_request_id",
            "conversation_id",
            "customer_message_id",
            "ai_run_id",
            "trace_id",
            "pipeline_stage",
            "intent",
            "decision",
            "assistant_message_id",
            "escalation_id",
            "response",
            "succeeded",
            "failure_code",
            "failure_retryable",
        ):
            assert (
                second_body[field_name]
                == first_body[field_name]
            )

        conversation_id = uuid.UUID(
            first_body["conversation_id"]
        )

        with test_session_factory() as session:
            message_count = session.scalar(
                select(func.count(MessageModel.id))
                .where(
                    MessageModel.conversation_id
                    == conversation_id,
                    MessageModel.role == "customer",
                )
            )
            run_count = session.scalar(
                select(func.count(AIRunModel.id))
                .where(
                    AIRunModel.conversation_id
                    == conversation_id
                )
            )

        assert message_count == 1
        assert run_count == 1

    def test_same_key_with_different_message_returns_conflict(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
    ) -> None:
        key = str(uuid7())

        first = client.post(
            "/v1/conversations/start",
            headers=_headers(
                customer_auth_headers,
                idempotency_key=key,
            ),
            json=_payload(
                "Where is order ORD-12345?"
            ),
        )

        assert first.status_code == 201, first.text

        conflicting = client.post(
            "/v1/conversations/start",
            headers=_headers(
                customer_auth_headers,
                idempotency_key=key,
            ),
            json=_payload(
                "Please reset my account password."
            ),
        )

        assert conflicting.status_code == 409

        error = conflicting.json()["error"]
        assert (
            error["code"]
            == "CONVERSATION_START_CONFLICT"
        )
        assert "trace_id" in error

    def test_active_processing_lease_returns_202(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
        customer_identity,
        application_services: ApplicationServices,
        test_session_factory,
    ) -> None:
        key = str(uuid7())
        trace_id = uuid7()
        principal = AuthenticatedPrincipal(
            user_id=customer_identity.user_id,
            session_id=customer_identity.session_id,
            role=AuthRole.CUSTOMER,
        )

        accepted = (
            application_services
            .accept_conversation_start
            .execute(
                AcceptConversationStartCommand(
                    principal=principal,
                    idempotency_key=key,
                    customer_message=(
                        "Where is order ORD-12345?"
                    ),
                    trace_id=trace_id,
                    channel="web",
                    title=None,
                )
            )
        )

        now = datetime.now(timezone.utc)

        with SqlAlchemyUnitOfWork(
            session_factory=test_session_factory
        ) as uow:
            assert (
                uow.conversation_start_requests
                is not None
            )

            acquired = (
                uow.conversation_start_requests
                .acquire_processing_lease(
                    request_id=accepted.request_id,
                    processing_token=uuid7(),
                    acquired_at=now,
                    processing_expires_at=(
                        now + timedelta(seconds=30)
                    ),
                )
            )

            assert acquired is not None
            uow.commit()

        response = client.post(
            "/v1/conversations/start",
            headers=_headers(
                customer_auth_headers,
                idempotency_key=key,
                trace_id=trace_id,
            ),
            json=_payload(),
        )

        assert response.status_code == 202, response.text
        assert response.headers["Retry-After"]

        body = response.json()
        assert body["start_request_id"] == str(
            accepted.request_id
        )
        assert body["conversation_id"] == str(
            accepted.conversation_id
        )
        assert body["idempotency_status"] == "processing"
        assert body["retry_after_seconds"] >= 1

    def test_failed_ai_run_preserves_accepted_first_message(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
        test_session_factory,
        mock_llm_provider: MockLLMProvider,
    ) -> None:
        key = str(uuid7())

        mock_llm_provider.queue_timeout()

        response = client.post(
            "/v1/conversations/start",
            headers=_headers(
                customer_auth_headers,
                idempotency_key=key,
            ),
            json=_payload(),
        )

        # Conversation acceptance succeeded even though AI processing failed.
        assert response.status_code == 201, response.text

        body = response.json()

        assert body["created"] is True
        assert body["replayed"] is False
        assert body["idempotency_status"] == "failed"
        assert body["succeeded"] is False
        assert body["failure_code"] is not None
        assert body["failure_retryable"] is not None

        request_id = uuid.UUID(
            body["start_request_id"]
        )
        conversation_id = uuid.UUID(
            body["conversation_id"]
        )
        message_id = uuid.UUID(
            body["customer_message_id"]
        )
        ai_run_id = uuid.UUID(body["ai_run_id"])

        assert body["assistant_message_id"] is None
        assert body["response"] is None

        with test_session_factory() as session:
            start_request = session.get(
                ConversationStartRequestModel,
                request_id,
            )
            conversation = session.get(
                ConversationModel,
                conversation_id,
            )
            message = session.get(
                MessageModel,
                message_id,
            )
            ai_run = session.get(
                AIRunModel,
                ai_run_id,
            )

        assert start_request is not None
        assert start_request.status == "failed"
        assert start_request.response_snapshot is not None

        assert conversation is not None

        assert message is not None
        assert message.role == "customer"
        assert message.sequence_number == 1

        assert ai_run is not None
        assert ai_run.status == "failed"
        assert ai_run.trigger_message_id == message_id