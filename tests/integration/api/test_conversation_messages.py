# AI-customer-support-agent\tests\integration\api\test_conversation_messages.py
from __future__ import annotations
import uuid
from uuid6 import uuid7
from fastapi.testclient import TestClient
import pytest

from packages.database.models.support.conversation import ConversationModel
from packages.database.models.ai.decision import AIDecisionModel
from packages.database.models.ai.intent_prediction import IntentPredictionModel
from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.message import MessageModel
from packages.ai.intent.taxonomy import IntentType
from packages.ai.decision.schemas import DecisionType
from packages.ai.orchestration.state import PipelineStage

import hashlib

from datetime import datetime, timedelta, timezone

from packages.database.models.knowledge.document import (
    KnowledgeDocumentModel,
)
from packages.database.models.knowledge.document_version import (
    KnowledgeDocumentVersionModel,
)
from packages.database.models.knowledge.chunk import (
    KnowledgeChunkModel,
)
from packages.database.models.ai.retrieval_run import (
    RetrievalRunModel,
)

@pytest.fixture()
def seeded_conversation(
    test_session_factory,
    customer_identity,
) -> uuid.UUID:
    """
    Create a conversation owned by the authenticated test customer.
    """
    conversation_id = uuid7()

    with test_session_factory() as session:
        session.add(
            ConversationModel(
                id=conversation_id,
                user_id=customer_identity.user_id,
                status="open",
                channel="web",
                title="Authenticated message test",
            )
        )
        session.commit()

    return conversation_id

@pytest.fixture()
def seeded_published_return_policy(
    test_session_factory,
) -> dict[str, uuid.UUID]:
    now = datetime.now(timezone.utc)

    document_id = uuid7()
    version_id = uuid7()
    chunk_id = uuid7()

    source_content = (
        "Return Policy\n\n"
        "Eligible items may be returned within 30 calendar "
        "days of delivery. Items must be unused and remain "
        "in their original condition."
    )

    with test_session_factory() as session:
        session.add(
            KnowledgeDocumentModel(
                id=document_id,
                title="Customer Return Policy",
                description=(
                    "Return-policy knowledge used by the "
                    "grounded API integration test."
                ),
                content_type="policy",
                visibility="customer",
                status="active",
                metadata_={"integration_test": True},
                created_at=now,
                updated_at=now,
                archived_at=None,
                deleted_at=None,
            )
        )
        session.flush()

        session.add(
            KnowledgeDocumentVersionModel(
                id=version_id,
                document_id=document_id,
                version_number=1,
                source_type="plain_text",
                source_content=source_content,
                source_name="return-policy.txt",
                source_uri=None,
                content_hash=hashlib.sha256(
                    source_content.encode("utf-8")
                ).hexdigest(),
                status="published",
                ingestion_status="completed",
                metadata_={"integration_test": True},
                created_at=now - timedelta(seconds=10),
                updated_at=now,
                processing_started_at=(
                    now - timedelta(seconds=9)
                ),
                processing_completed_at=(
                    now - timedelta(seconds=5)
                ),
                ready_at=now - timedelta(seconds=5),
                published_at=now,
                superseded_at=None,
                archived_at=None,
                failure_code=None,
                failure_message=None,
            )
        )
        session.flush()

        session.add(
            KnowledgeChunkModel(
                id=chunk_id,
                version_id=version_id,
                chunk_index=0,
                content=source_content,
                section_title="Return eligibility",
                start_offset=None,
                end_offset=None,
                token_count=31,
                metadata_={"integration_test": True},
                created_at=now,
                updated_at=now,
            )
        )

        session.commit()

    return {
        "document_id": document_id,
        "version_id": version_id,
        "chunk_id": chunk_id,
    }

class TestSendCustomerMessage:
    def test_processes_customer_message_successfully(self, client: TestClient, seeded_conversation: uuid.UUID, customer_auth_headers: dict[str, str],) -> None:
        trace_id = uuid7()
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            headers={**customer_auth_headers, "X-Trace-ID": str(trace_id) },
            json={ "message": "Hello support assistant" },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["conversation_id"] == str(seeded_conversation)
        assert uuid.UUID(body["customer_message_id"])
        assert uuid.UUID(body["ai_run_id"])
        assert body["trace_id"] == str(trace_id)
        assert body["succeeded"] is True
        assert body["pipeline_stage"] == PipelineStage.GUARDRAILS_COMPLETED.value
        assert body["intent"] == IntentType.CONVERSATIONAL.value
        assert body["decision"] == DecisionType.ANSWER.value
        assert uuid.UUID(body["assistant_message_id"])
        assert body["escalation_id"] is None
        assert body["response"]

    def test_persists_customer_message(self, client: TestClient, seeded_conversation: uuid.UUID, test_session_factory, customer_auth_headers: dict[str, str],) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            headers=customer_auth_headers,
            json={ "message": "Hello support assistant" },
        )

        assert response.status_code == 200

        customer_message_id = uuid.UUID(response.json()["customer_message_id"])

        with test_session_factory() as session:
            message = session.get(MessageModel, customer_message_id)

            assert message is not None
            assert message.conversation_id == seeded_conversation
            assert message.role == "customer"
            assert message.content == "Hello support assistant"

    def test_creates_completed_ai_run(self, client: TestClient, seeded_conversation: uuid.UUID, test_session_factory, customer_auth_headers: dict[str, str],) -> None:
        trace_id = uuid7()

        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            headers={**customer_auth_headers, "X-Trace-ID": str(trace_id) },
            json={ "message": "Hello support assistant" },
        )

        assert response.status_code == 200

        ai_run_id = uuid.UUID(response.json()["ai_run_id"])
        with test_session_factory() as session:
            ai_run = session.get(AIRunModel, ai_run_id)

            assert ai_run is not None
            assert ai_run.conversation_id == seeded_conversation
            assert ai_run.trace_id == trace_id
            assert ai_run.status == "completed"

    def test_persists_ai_telemetry(self, client: TestClient, seeded_conversation: uuid.UUID, test_session_factory, customer_auth_headers: dict[str, str],) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            headers=customer_auth_headers,
            json={ "message": "Hello support assistant" },
        )

        assert response.status_code == 200

        ai_run_id = uuid.UUID(response.json()["ai_run_id"])

        with test_session_factory() as session:
            llm_calls = (session.query(LLMCallModel)
                         .filter(LLMCallModel.ai_run_id == ai_run_id)
                         .all()
            )

            predictions = (session.query(IntentPredictionModel)
                           .filter(IntentPredictionModel.ai_run_id == ai_run_id)
                           .all()
            )

            decisions = (session.query(AIDecisionModel)
                         .filter(AIDecisionModel.ai_run_id == ai_run_id)
                         .all()
            )

            assert len(llm_calls) == 1
            assert len(predictions) == 1
            assert len(decisions) == 1

    def test_intent_prediction_is_linked_to_llm_call(self, client: TestClient, seeded_conversation: uuid.UUID, test_session_factory, customer_auth_headers: dict[str, str],) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            headers=customer_auth_headers,
            json={ "message": "Hello support assistant" },
        )

        assert response.status_code == 200

        ai_run_id = uuid.UUID(response.json()["ai_run_id"])

        with test_session_factory() as session:
            prediction = (session.query(IntentPredictionModel)
                          .filter(IntentPredictionModel.ai_run_id == ai_run_id)
                          .one()
            )

            llm_call = (session.query(LLMCallModel)
                        .filter(LLMCallModel.ai_run_id == ai_run_id)
                        .one()
            )

            assert prediction.llm_call_id == llm_call.id
    
    def test_returns_grounded_answer_from_published_knowledge(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
        seeded_published_return_policy: dict[str, uuid.UUID],
        customer_auth_headers: dict[str, str],
        test_session_factory,
    ) -> None:
        trace_id = uuid7()

        response = client.post(
            (
                f"/v1/conversations/"
                f"{seeded_conversation}/messages"
            ),
            headers={
                **customer_auth_headers,
                "X-Trace-ID": str(trace_id),
            },
            json={
                "message": "What is your return policy?",
            },
        )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["conversation_id"] == str(
            seeded_conversation
        )
        assert body["trace_id"] == str(trace_id)
        assert body["succeeded"] is True
        assert body["pipeline_stage"] == (
            PipelineStage.GUARDRAILS_COMPLETED.value
        )
        assert body["intent"] == (
            IntentType.RETURN_EXCHANGE.value
        )
        assert body["decision"] == (
            DecisionType.RETRIEVE_INFORMATION.value
        )

        customer_message_id = uuid.UUID(
            body["customer_message_id"]
        )
        assistant_message_id = uuid.UUID(
            body["assistant_message_id"]
        )
        ai_run_id = uuid.UUID(body["ai_run_id"])

        assert body["escalation_id"] is None
        assert body["response"] == (
            "Eligible items may be returned within 30 calendar "
            "days of delivery, provided they are unused and in "
            "their original condition."
        )

        with test_session_factory() as session:
            customer_message = session.get(
                MessageModel,
                customer_message_id,
            )
            assistant_message = session.get(
                MessageModel,
                assistant_message_id,
            )
            ai_run = session.get(
                AIRunModel,
                ai_run_id,
            )

            retrieval_runs = tuple(
                session.query(RetrievalRunModel)
                .filter(
                    RetrievalRunModel.ai_run_id == ai_run_id
                )
                .all()
            )

            llm_calls = tuple(
                session.query(LLMCallModel)
                .filter(
                    LLMCallModel.ai_run_id == ai_run_id
                )
                .all()
            )

        assert customer_message is not None
        assert customer_message.role == "customer"
        assert customer_message.content == (
            "What is your return policy?"
        )

        assert assistant_message is not None
        assert assistant_message.role == "assistant"
        assert assistant_message.content == body["response"]

        assert ai_run is not None
        assert ai_run.status == "completed"
        assert ai_run.trace_id == trace_id
        assert ai_run.trigger_message_id == customer_message_id
        assert ai_run.response_message_id == assistant_message_id

        assert len(retrieval_runs) == 1
        retrieval_run = retrieval_runs[0]

        assert retrieval_run.status == "success"
        assert retrieval_run.zero_result is False
        assert retrieval_run.lexical_candidate_count >= 1
        assert retrieval_run.selected_candidate_count >= 1
        
        assert retrieval_run.zero_result is False
        assert retrieval_run.lexical_candidate_count >= 1
        assert retrieval_run.fused_candidate_count >= 1
        assert retrieval_run.selected_candidate_count >= 1

        assert len(llm_calls) == 2
        assert {
            call.purpose
            for call in llm_calls
        } == {
            "intent_classification",
            "answer_generation",
        }

        assert seeded_published_return_policy[
            "chunk_id"
        ] is not None
        
class TestConversationMessageFeedbackHistory:
    def test_history_exposes_feedback_eligibility_and_ai_run(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
        customer_auth_headers: dict[str, str],
    ) -> None:
        send_response = client.post(
            (
                f"/v1/conversations/"
                f"{seeded_conversation}/messages"
            ),
            headers=customer_auth_headers,
            json={
                "message": "Hello support assistant",
            },
        )

        assert send_response.status_code == 200
        send_body = send_response.json()

        assistant_message_id = send_body[
            "assistant_message_id"
        ]
        ai_run_id = send_body["ai_run_id"]

        assert assistant_message_id is not None

        history_response = client.get(
            (
                f"/v1/conversations/"
                f"{seeded_conversation}/messages"
            ),
            headers=customer_auth_headers,
        )

        assert history_response.status_code == 200
        history = history_response.json()

        assert history["total"] == 2
        assert history["count"] == 2

        customer_message = next(
            item
            for item in history["items"]
            if item["role"] == "customer"
        )
        assistant_message = next(
            item
            for item in history["items"]
            if item["role"] == "assistant"
        )

        assert customer_message["ai_run_id"] is None
        assert customer_message["feedback_eligible"] is False
        assert customer_message["feedback"] is None

        assert (
            assistant_message["message_id"]
            == assistant_message_id
        )
        assert assistant_message["ai_run_id"] == ai_run_id
        assert assistant_message["feedback_eligible"] is True
        assert assistant_message["feedback"] is None

    def test_saved_feedback_is_returned_after_history_reload(
        self,
        client: TestClient,
        seeded_conversation: uuid.UUID,
        customer_auth_headers: dict[str, str],
    ) -> None:
        send_response = client.post(
            (
                f"/v1/conversations/"
                f"{seeded_conversation}/messages"
            ),
            headers=customer_auth_headers,
            json={
                "message": "Hello support assistant",
            },
        )

        assert send_response.status_code == 200
        send_body = send_response.json()

        assistant_message_id = send_body[
            "assistant_message_id"
        ]
        ai_run_id = send_body["ai_run_id"]

        assert assistant_message_id is not None

        feedback_response = client.post(
            (
                f"/v1/conversations/"
                f"{seeded_conversation}/feedback"
            ),
            headers=customer_auth_headers,
            json={
                "response_message_id": assistant_message_id,
                "ai_run_id": ai_run_id,
                "rating": 4,
                "helpful": True,
                "comment": (
                    "The response clearly explained the "
                    "available support."
                ),
                "reason_codes": [],
                "metadata": {
                    "must_not_appear_in_history": True,
                },
            },
        )

        assert feedback_response.status_code == 201
        submitted_feedback = feedback_response.json()

        history_response = client.get(
            (
                f"/v1/conversations/"
                f"{seeded_conversation}/messages"
            ),
            headers=customer_auth_headers,
        )

        assert history_response.status_code == 200
        history = history_response.json()

        assistant_message = next(
            item
            for item in history["items"]
            if item["message_id"] == assistant_message_id
        )

        assert assistant_message["ai_run_id"] == ai_run_id
        assert assistant_message["feedback_eligible"] is True

        feedback = assistant_message["feedback"]

        assert feedback is not None
        assert feedback["feedback_id"] == (
            submitted_feedback["feedback_id"]
        )
        assert feedback["rating"] == 4
        assert feedback["helpful"] is True
        assert feedback["created_at"] is not None

        # Conversation history exposes only the deliberate customer-safe
        # feedback summary.
        assert set(feedback) == {
            "feedback_id",
            "rating",
            "helpful",
            "created_at",
        }

        serialized_message = str(
            assistant_message
        ).lower()

        for prohibited_field in (
            "comment",
            "reason_codes",
            "metadata",
            "review_notes",
            "reviewed_by_user_id",
            "row_version",
        ):
            assert prohibited_field not in serialized_message

    def test_orphan_assistant_message_is_not_feedback_eligible(
        self,
        client: TestClient,
        test_session_factory,
        seeded_conversation: uuid.UUID,
        customer_auth_headers: dict[str, str],
    ) -> None:
        assistant_message_id = uuid7()

        with test_session_factory() as session:
            session.add(
                MessageModel(
                    id=assistant_message_id,
                    conversation_id=seeded_conversation,
                    role="assistant",
                    content=(
                        "Legacy assistant response without "
                        "AI-run provenance."
                    ),
                    sequence_number=1,
                    metadata_={},
                )
            )
            session.commit()

        response = client.get(
            (
                f"/v1/conversations/"
                f"{seeded_conversation}/messages"
            ),
            headers=customer_auth_headers,
        )

        assert response.status_code == 200
        body = response.json()

        assert body["total"] == 1

        message = body["items"][0]

        assert message["message_id"] == str(
            assistant_message_id
        )
        assert message["role"] == "assistant"
        assert message["ai_run_id"] is None
        assert message["feedback_eligible"] is False
        assert message["feedback"] is None