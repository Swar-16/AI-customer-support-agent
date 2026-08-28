from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.ai.decision import AIDecisionModel
from packages.database.models.ai.intent_prediction import IntentPredictionModel
from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.message import MessageModel

import pytest

pytestmark = pytest.mark.usefixtures("clean_database")

class TestSendCustomerMessage:

    def test_processes_customer_message_successfully(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
    ) -> None:
        trace_id = uuid7()

        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            headers={
                "X-Trace-ID": str(trace_id),
            },
            json={
                "message": "Where is my order ORD-12345?",
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["conversation_id"] == str(
            seeded_conversation
        )
        assert uuid.UUID(body["customer_message_id"])
        assert uuid.UUID(body["ai_run_id"])

        assert body["trace_id"] == str(trace_id)

        assert body["succeeded"] is True
        assert body["pipeline_stage"] == "decision_made"

        assert body["intent"] == "order_status"
        assert body["decision"] == "retrieve_information"


    def test_persists_customer_message(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
        test_session_factory,
    ) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            json={
                "message": "Where is my order ORD-12345?",
            },
        )

        assert response.status_code == 200

        customer_message_id = uuid.UUID(
            response.json()["customer_message_id"]
        )

        with test_session_factory() as session:
            message = session.get(
                MessageModel,
                customer_message_id,
            )

            assert message is not None
            assert message.conversation_id == seeded_conversation
            assert message.role == "customer"
            assert message.content == (
                "Where is my order ORD-12345?"
            )


    def test_creates_completed_ai_run(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
        test_session_factory,
    ) -> None:
        trace_id = uuid7()

        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            headers={
                "X-Trace-ID": str(trace_id),
            },
            json={
                "message": "Where is my order ORD-12345?",
            },
        )

        assert response.status_code == 200

        ai_run_id = uuid.UUID(
            response.json()["ai_run_id"]
        )

        with test_session_factory() as session:
            ai_run = session.get(
                AIRunModel,
                ai_run_id,
            )

            assert ai_run is not None
            assert ai_run.conversation_id == (
                seeded_conversation
            )
            assert ai_run.trace_id == trace_id
            assert ai_run.status == "completed"


    def test_persists_ai_telemetry(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
        test_session_factory,
    ) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            json={
                "message": "Where is my order ORD-12345?",
            },
        )

        assert response.status_code == 200

        ai_run_id = uuid.UUID(
            response.json()["ai_run_id"]
        )

        with test_session_factory() as session:
            llm_calls = (
                session.query(LLMCallModel)
                .filter(
                    LLMCallModel.ai_run_id == ai_run_id
                )
                .all()
            )

            predictions = (
                session.query(IntentPredictionModel)
                .filter(
                    IntentPredictionModel.ai_run_id
                    == ai_run_id
                )
                .all()
            )

            decisions = (
                session.query(AIDecisionModel)
                .filter(
                    AIDecisionModel.ai_run_id
                    == ai_run_id
                )
                .all()
            )

            assert len(llm_calls) == 1
            assert len(predictions) == 1
            assert len(decisions) == 1


    def test_intent_prediction_is_linked_to_llm_call(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
        test_session_factory,
    ) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            json={
                "message": "Where is my order ORD-12345?",
            },
        )

        assert response.status_code == 200

        ai_run_id = uuid.UUID(
            response.json()["ai_run_id"]
        )

        with test_session_factory() as session:
            prediction = (
                session.query(IntentPredictionModel)
                .filter(
                    IntentPredictionModel.ai_run_id
                    == ai_run_id
                )
                .one()
            )

            llm_call = (
                session.query(LLMCallModel)
                .filter(
                    LLMCallModel.ai_run_id
                    == ai_run_id
                )
                .one()
            )

            assert prediction.llm_call_id == llm_call.id