from __future__ import annotations
import uuid
from uuid6 import uuid7
import pytest
from sqlalchemy import delete, select

from packages.application.composition.application_factory import create_application
from packages.application.conversations.process_customer_message import ProcessCustomerMessageCommand
from packages.config.settings import get_settings
from packages.database.models.ai.decision import AIDecisionModel
from packages.database.models.ai.intent_prediction import IntentPredictionModel
from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.conversation import ConversationModel
from packages.database.models.support.message import MessageModel
from packages.database.models.support.user import UserModel
from packages.database.session import create_session_factory


pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_provider,
    pytest.mark.live_smoke,
]


@pytest.fixture(scope="module")
def live_settings():
    """
    Use the test database, but override the provider to Groq.

    This prevents a live smoke test from ever touching the normal
    development database.
    """
    settings = get_settings("test")

    if settings.database_name != "support_ai_test":
        pytest.fail("Live smoke tests must run against support_ai_test")

    if not settings.groq_api_key:
        pytest.skip("GROQ_API_KEY is not configured")

    # The test DB should remain the DB source of truth.
    # Provider selection is overridden explicitly below.
    return settings


@pytest.fixture(scope="module")
def live_session_factory(live_settings):
    """
    Create sessions against support_ai_test.
    """
    return create_session_factory(database_url=live_settings.database_url, echo=False)


@pytest.fixture
def live_conversation(live_session_factory):
    external_id = (f"live-smoke-{uuid7()}")

    with live_session_factory() as session:
        user = UserModel(
            external_id=external_id,
            email=None,
            display_name="Live Smoke User",
            role="customer",
            status="active",
        )

        session.add(user)
        session.flush()

        conversation = ConversationModel(
            user_id=user.id,
            status="open",
            channel="web",
            title="Live Groq smoke test",
        )

        session.add(conversation)
        session.commit()

        user_id = user.id
        conversation_id = conversation.id

    yield {
        "user_id": user_id,
        "conversation_id": conversation_id,
    }

    # Cleanup committed smoke-test data
    with live_session_factory() as session:
        run_ids = tuple(session.scalars(
                select(AIRunModel.id)
                .where(AIRunModel.conversation_id == conversation_id)
            )
        )

        if run_ids:
            session.execute(
                delete(AIDecisionModel)
                .where(AIDecisionModel.ai_run_id.in_(run_ids))
            )

            session.execute(
                delete(IntentPredictionModel)
                .where(IntentPredictionModel.ai_run_id.in_(run_ids))
            )

            session.execute(
                delete(LLMCallModel)
                .where(LLMCallModel.ai_run_id.in_(run_ids))
            )

            session.execute(
                delete(AIRunModel)
                .where(AIRunModel.id.in_(run_ids))
            )

        session.execute(
            delete(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
        )

        session.execute(
            delete(ConversationModel)
            .where(ConversationModel.id == conversation_id)
        )

        session.execute(
            delete(UserModel)
            .where(UserModel.id == user_id)
        )

        session.commit()


def test_full_application_with_real_groq_and_postgres(live_settings, live_session_factory, live_conversation) -> None:
    """
    Full-system smoke test.

    Real:
        PostgreSQL
        repositories
        UnitOfWork
        InstrumentedLLMProvider
        GroqProvider
        IntentClassifier
        DecisionEngine
        AIOrchestrator
        TelemetryRecorder
        ProcessCustomerMessage
    """
    # Build real application composition
    # We keep the DB settings from .env.test but explicitly choose Groq
    # for this smoke test.
    smoke_settings = live_settings.model_copy(
        update={"llm_provider": "groq",}
    )

    services = create_application(settings=smoke_settings, session_factory=live_session_factory)
    conversation_id = live_conversation["conversation_id"]
    trace_id = uuid7()

    # Execute real application workflow
    result = services.process_customer_message.execute(
        ProcessCustomerMessageCommand(
            conversation_id=conversation_id,
            customer_message="I was charged twice for order ORD-123. Please help me understand what happened.",
            trace_id=trace_id,
        )
    )

    # Application result
    assert result.succeeded is True
    assert result.trace_id == trace_id
    assert result.intent is not None
    assert result.decision is not None

    # Database verification
    with live_session_factory() as session:
        ai_run = session.get(
            AIRunModel,
            result.ai_run_id,
        )

        assert ai_run is not None
        assert ai_run.status == "completed"
        assert ai_run.trace_id == trace_id
        assert ai_run.completed_at is not None
        assert ai_run.total_latency_ms is not None

        # Real Groq call telemetry
        llm_calls = tuple(session.scalars(
                select(LLMCallModel)
                .where(LLMCallModel.ai_run_id == result.ai_run_id)
            )
        )

        assert len(llm_calls) == 1
        llm_call = llm_calls[0]
        assert llm_call.status == "success"
        assert llm_call.provider == "groq"
        assert llm_call.model
        assert llm_call.purpose == "intent_classification"
        assert llm_call.input_tokens > 0
        assert llm_call.output_tokens > 0
        assert llm_call.total_tokens > 0
        assert llm_call.latency_ms is not None
        assert llm_call.latency_ms >= 0
        assert llm_call.completed_at is not None

        # Intent prediction
        predictions = tuple(session.scalars(
                select(IntentPredictionModel)
                .where(IntentPredictionModel.ai_run_id == result.ai_run_id)
            )
        )

        assert len(predictions) == 1
        prediction = predictions[0]
        assert prediction.intent
        assert prediction.confidence is not None
        assert prediction.llm_call_id == llm_call.id

        # Decision
        decisions = tuple(session.scalars(
                select(AIDecisionModel)
                .where(AIDecisionModel.ai_run_id == result.ai_run_id)
            )
        )

        assert len(decisions) == 1
        decision = decisions[0]
        assert decision.llm_call_id is None
        assert decision.decision_type
        assert decision.reason_code

        # Trigger message
        message = session.get(MessageModel, result.customer_message_id)

        assert message is not None
        assert message.role == "customer"
        assert message.conversation_id == conversation_id