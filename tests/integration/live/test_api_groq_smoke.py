from __future__ import annotations
import uuid
from collections.abc import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from uuid6 import uuid7
from typing import Any

from apps.api.app.main import create_api_app
from packages.application.composition.application_factory import ApplicationServices, create_application
from packages.database.models.ai.decision import AIDecisionModel
from packages.database.models.ai.intent_prediction import IntentPredictionModel
from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.conversation import ConversationModel
from packages.database.models.support.message import MessageModel
from packages.ai.intent.taxonomy import IntentType
from packages.ai.orchestration.state import PipelineStage
from packages.database.models.support.escalation import EscalationModel
from packages.ai.decision.schemas import DecisionReasonCode, DecisionType

LIVE_TEST_ORIGIN = "https://testserver"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_provider,
    pytest.mark.live_smoke,
]


@pytest.fixture()
def live_settings(test_settings):
    if not test_settings.groq_api_key:
        pytest.skip("GROQ_API_KEY is not configured")

    return test_settings.model_copy(
        update={
            "llm_provider": "groq",
            "browser_allowed_origins": (
                LIVE_TEST_ORIGIN,
            ),
            "auth_refresh_cookie_secure": True,
        }
    )


@pytest.fixture()
def live_application_services(
    live_settings,
    test_session_factory,
) -> ApplicationServices:
    return create_application(
        settings=live_settings,
        session_factory=test_session_factory,
    )


@pytest.fixture()
def live_client(
    monkeypatch: pytest.MonkeyPatch,
    live_application_services: ApplicationServices,
    live_settings,
    clean_database,
) -> Generator[TestClient, None, None]:
    monkeypatch.setattr(
        "apps.api.app.main.get_application_services",
        lambda: live_application_services,
    )
    monkeypatch.setattr(
        "apps.api.app.main.get_runtime_settings",
        lambda: live_settings,
    )

    app = create_api_app()

    with TestClient(
        app,
        base_url=LIVE_TEST_ORIGIN,
        headers={
            "Origin": LIVE_TEST_ORIGIN,
        },
    ) as client:
        yield client
        
@pytest.fixture()
def live_customer(
    live_client: TestClient,
) -> dict[str, Any]:
    email = f"live-groq-{uuid7()}@example.com"

    response = live_client.post(
        "/v1/auth/register",
        headers={
            "Origin": LIVE_TEST_ORIGIN,
        },
        json={
            "email": email,
            "password": "Live-Groq-Smoke-Password-47!",
            "display_name": "Live Groq Customer",
        },
    )

    assert response.status_code == 201, response.text

    body = response.json()

    return {
        "user_id": uuid.UUID(body["user"]["id"]),
        "origin": LIVE_TEST_ORIGIN,
        "headers": {
            "Authorization": (
                f"Bearer {body['tokens']['access_token']}"
            )
        },
    }

@pytest.fixture()
def live_conversation(
    test_session_factory,
    live_customer: dict[str, Any],
) -> uuid.UUID:
    conversation_id = uuid7()

    with test_session_factory() as session:
        session.add(
            ConversationModel(
                id=conversation_id,
                user_id=live_customer["user_id"],
                status="open",
                channel="web",
                title="Live Groq API smoke test",
            )
        )
        session.commit()

    return conversation_id

class TestLiveGroqAPI:
    def test_customer_message_reaches_real_groq_and_persists_result(
        self,
        live_client: TestClient,
        live_conversation: uuid.UUID,
        live_customer: dict[str, Any],
        test_session_factory,
    ) -> None:
        trace_id = uuid7()
        response = live_client.post(
            f"/v1/conversations/{live_conversation}/messages",
            headers={
                **live_customer["headers"],
                "Origin": live_customer["origin"],
                "X-Trace-ID": str(trace_id),
            },
            json={
                "message": (
                    "Please tell me the current status "
                    "of order ORD-12345."
                ),
            },
        )

        assert response.status_code == 200#, response.text

        body = response.json()
        
        ai_run_id = uuid.UUID(body["ai_run_id"])
        customer_message_id = uuid.UUID(body["customer_message_id"])
        escalation_id = uuid.UUID(body["escalation_id"])

        assert body["conversation_id"] == str(live_conversation)
        assert body["trace_id"] == str(trace_id)
        assert uuid.UUID(body["customer_message_id"])
        assert uuid.UUID(body["ai_run_id"])
        assert body["succeeded"] is True
        assert body["pipeline_stage"] == PipelineStage.ESCALATED.value
        assert body["intent"] == IntentType.ORDER_STATUS.value
        assert body["decision"] == DecisionType.ESCALATE.value

        assistant_message_id = uuid.UUID(
            body["assistant_message_id"]
        )

        assert body["response"] is not None
        assert body["response"].strip()
        assert uuid.UUID(body["escalation_id"])
        assert body.get("failure_code") is None
        assert body.get("failure_retryable") is None

        with test_session_factory() as session:
            escalation = session.get(
                EscalationModel,
                escalation_id,
            )
            assistant_message = session.get(
                MessageModel,
                assistant_message_id,
            )

        assert escalation is not None
        assert escalation.ai_run_id == ai_run_id
        assert escalation.trigger_message_id == customer_message_id
        assert escalation.reason_code == (
            DecisionReasonCode.OPERATIONAL_LOOKUP_UNAVAILABLE.value
        )
        
        assert assistant_message is not None
        assert assistant_message.role == "assistant"
        assert assistant_message.content == body["response"]

        with test_session_factory() as session:
            message = session.scalar(select(MessageModel)
                                     .where(MessageModel.id == customer_message_id)
            )

            ai_run = session.scalar(select(AIRunModel)
                                    .where(AIRunModel.id == ai_run_id)
            )

            llm_calls = list(session.scalars(select(LLMCallModel)
                                             .where(LLMCallModel.ai_run_id == ai_run_id)
                )
            )

            predictions = list(session.scalars(select(IntentPredictionModel)
                                               .where(IntentPredictionModel.ai_run_id == ai_run_id)
                )
            )

            decisions = list(session.scalars(select(AIDecisionModel)
                                             .where(AIDecisionModel.ai_run_id == ai_run_id)
                )
            )

        assert message is not None
        assert message.conversation_id == live_conversation
        assert message.content == "Please tell me the current status of order ORD-12345."
        assert ai_run is not None
        assert ai_run.status == "completed"
        assert ai_run.trace_id == trace_id
        assert ai_run.trigger_message_id == customer_message_id
        assert len(llm_calls) >= 1
        assert len(predictions) == 1
        assert len(decisions) == 1
        
        assert (
            ai_run.response_message_id
            == assistant_message_id
        )

        prediction = predictions[0]
        assert prediction.llm_call_id is not None
        llm_call_ids = {call.id for call in llm_calls}
        assert prediction.llm_call_id in llm_call_ids