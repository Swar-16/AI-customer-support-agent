# AI-customer-support-agent\tests\live\application\test_process_customer_message_real_kb.py
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker
from uuid6 import uuid7

from packages.ai.orchestration.state import PipelineStage
from packages.application.composition.application_factory import (
    create_application,
)
from packages.application.conversations.process_customer_message import (
    ProcessCustomerMessageCommand,
)
from packages.config.settings import get_settings
from packages.database.models.ai.decision import AIDecisionModel
from packages.database.models.ai.intent_prediction import (
    IntentPredictionModel,
)
from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.conversation import (
    ConversationModel,
)
from packages.database.models.support.message import MessageModel
from packages.database.models.support.user import UserModel


# ---------------------------------------------------------------------------
# Live-test configuration
# ---------------------------------------------------------------------------

pytestmark = [
    pytest.mark.live_provider,
    pytest.mark.live_embedding,
    pytest.mark.live_smoke,
]


LIVE_CUSTOMER_MESSAGE = (
    "According to your refund policy, are purchases generally eligible "
    "for a refund when the refund is requested 20 days after purchase? "
    "I am only asking about the policy and eligibility requirements; "
    "I am not asking you to process a refund."
)


# ---------------------------------------------------------------------------
# Settings / database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_settings():
    """
    Load the normal application environment.

    This live test intentionally targets the real development database,
    because that database contains the real published knowledge base and
    its Jina embeddings.
    """

    settings = get_settings("development")

    database_url = settings.database_url.render_as_string(
        hide_password=False,
    )

    engine = create_engine(database_url)

    # Extremely important safety check:
    # this live test must never accidentally target some unrelated DB.
    if engine.url.database != "support_ai":
        engine.dispose()

        pytest.skip(
            "Real-KB live test requires the support_ai database; "
            f"configured database is {engine.url.database!r}."
        )

    engine.dispose()

    return settings


@pytest.fixture(scope="module")
def live_engine(live_settings):
    database_url = live_settings.database_url.render_as_string(
        hide_password=False,
    )

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
    )

    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def live_session_factory(live_engine):
    return sessionmaker(
        bind=live_engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


# ---------------------------------------------------------------------------
# Temporary support-domain state
# ---------------------------------------------------------------------------


@pytest.fixture
def live_conversation(live_session_factory):
    """
    Create temporary support-domain rows in support_ai.

    The knowledge base itself is never modified.

    Cleanup is explicit because ProcessCustomerMessage commits its own
    application transaction.
    """

    user_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None

    external_id = f"live-rag-user-{uuid7()}"

    with live_session_factory() as session:
        user = UserModel(
            external_id=external_id,
            display_name="Live RAG Smoke Test",
            role="customer",
            status="active",
        )

        session.add(user)
        session.flush()

        if user.id is None:
            raise RuntimeError(
                "Live-test user ID was not generated."
            )

        user_id = user.id

        conversation = ConversationModel(
            user_id=user.id,
            status="open",
            channel="web",
            title="Live RAG + Groq smoke test",
        )

        session.add(conversation)
        session.flush()

        if conversation.id is None:
            raise RuntimeError(
                "Live-test conversation ID was not generated."
            )

        conversation_id = conversation.id

        session.commit()

    try:
        yield {
            "user_id": user_id,
            "conversation_id": conversation_id,
        }

    finally:
        if (
            user_id is None
            or conversation_id is None
        ):
            return

        # ---------------------------------------------------------------
        # Cleanup only rows owned by this temporary live-test conversation.
        #
        # NEVER delete knowledge rows here.
        # ---------------------------------------------------------------

        with live_session_factory() as session:
            run_ids = list(
                session.scalars(
                    select(AIRunModel.id).where(
                        AIRunModel.conversation_id
                        == conversation_id
                    )
                )
            )

            if run_ids:
                session.execute(
                    delete(AIDecisionModel).where(
                        AIDecisionModel.ai_run_id.in_(
                            run_ids
                        )
                    )
                )

                session.execute(
                    delete(IntentPredictionModel).where(
                        IntentPredictionModel.ai_run_id.in_(
                            run_ids
                        )
                    )
                )

                session.execute(
                    delete(LLMCallModel).where(
                        LLMCallModel.ai_run_id.in_(
                            run_ids
                        )
                    )
                )

                session.execute(
                    delete(AIRunModel).where(
                        AIRunModel.id.in_(run_ids)
                    )
                )

            session.execute(
                delete(MessageModel).where(
                    MessageModel.conversation_id
                    == conversation_id
                )
            )

            session.execute(
                delete(ConversationModel).where(
                    ConversationModel.id
                    == conversation_id
                )
            )

            session.execute(
                delete(UserModel).where(
                    UserModel.id == user_id
                )
            )

            session.commit()


# ---------------------------------------------------------------------------
# Real application composition
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_application(
    live_settings,
    live_session_factory,
):
    """
    Compose the application exactly as production composition does.

    No MockLLMProvider.
    No deterministic embedding provider.

    Expected configured providers:

        LLM       -> Groq
        Embedding -> Jina

    ProcessCustomerMessage will create request-scoped pipeline components
    and use the same support_ai Session for knowledge retrieval.
    """

    services = create_application(
        settings=live_settings,
        session_factory=live_session_factory,
    )

    assert (
        services.base_llm_provider.provider_name
        == "groq"
    )

    return services


# ---------------------------------------------------------------------------
# Live end-to-end RAG + Groq smoke test
# ---------------------------------------------------------------------------


def test_customer_message_uses_real_kb_jina_and_groq(
    live_application,
    live_session_factory,
    live_conversation,
):
    """
    Exercise the real customer-support AI path:

        support_ai
            ↓
        customer message
            ↓
        real Groq intent classification
            ↓
        deterministic DecisionEngine
            ↓
        real knowledge retrieval
            ├── real Jina query embedding
            ├── existing 1024-dim Jina chunk embeddings
            ├── PostgreSQL vector retrieval
            ├── lexical retrieval
            └── reciprocal-rank fusion
            ↓
        grounding context
            ↓
        real Groq grounded response generation
            ↓
        persisted AI telemetry

    The test intentionally does not assert exact generated prose because
    Groq output is probabilistic.

    Instead, it asserts stable architectural invariants.
    """

    conversation_id = (
        live_conversation["conversation_id"]
    )

    trace_id = uuid7()

    result = (
        live_application
        .process_customer_message
        .execute(
            ProcessCustomerMessageCommand(
                conversation_id=conversation_id,
                customer_message=(
                    LIVE_CUSTOMER_MESSAGE
                ),
                trace_id=trace_id,
            )
        )
    )

    # -------------------------------------------------------------------
    # Application result
    # -------------------------------------------------------------------

    assert result.conversation_id == conversation_id
    assert result.trace_id == trace_id

    assert result.succeeded is True

    assert (
        result.pipeline_stage
        is PipelineStage.RESPONSE_GENERATED
    )

    # Groq should classify this as a refund-related request.
    #
    # REFUND_REQUEST is the expected result. PAYMENT_ISSUE remains an
    # acceptable classification because the request concerns a financial
    # transaction, but both must route into knowledge retrieval.
    assert result.intent in {
        "refund_request",
        "payment_issue",
        "general_question",
    }

    assert result.decision == "retrieve_information"

    # -------------------------------------------------------------------
    # Persisted database state
    # -------------------------------------------------------------------

    with live_session_factory() as session:
        ai_run = session.get(
            AIRunModel,
            result.ai_run_id,
        )

        assert ai_run is not None

        assert ai_run.status == "completed"
        assert ai_run.trace_id == trace_id
        assert (
            ai_run.conversation_id
            == conversation_id
        )

        assert (
            ai_run.trigger_message_id
            == result.customer_message_id
        )

        assert ai_run.error_code is None
        assert ai_run.error_message is None
        assert ai_run.total_latency_ms is not None
        assert ai_run.total_latency_ms >= 0

        # ---------------------------------------------------------------
        # Customer message
        # ---------------------------------------------------------------

        customer_message = session.get(
            MessageModel,
            result.customer_message_id,
        )

        assert customer_message is not None

        assert customer_message.role == "customer"
        assert (
            customer_message.content
            == LIVE_CUSTOMER_MESSAGE
        )

        # ---------------------------------------------------------------
        # Provider calls
        # ---------------------------------------------------------------

        llm_calls = list(
            session.scalars(
                select(LLMCallModel)
                .where(
                    LLMCallModel.ai_run_id
                    == result.ai_run_id
                )
            )
        )

        assert len(llm_calls) >= 2

        calls_by_purpose = {
            call.purpose: call
            for call in llm_calls
        }

        assert (
            "intent_classification"
            in calls_by_purpose
        )

        assert (
            "answer_generation"
            in calls_by_purpose
        )

        intent_call = calls_by_purpose[
            "intent_classification"
        ]

        generation_call = calls_by_purpose[
            "answer_generation"
        ]

        # Both calls must genuinely have gone through Groq.
        assert intent_call.provider == "groq"
        assert generation_call.provider == "groq"

        assert intent_call.status == "success"
        assert generation_call.status == "success"

        assert intent_call.input_tokens is not None
        assert intent_call.input_tokens > 0

        assert generation_call.input_tokens is not None
        assert generation_call.input_tokens > 0

        assert intent_call.output_tokens is not None
        assert intent_call.output_tokens > 0

        assert generation_call.output_tokens is not None
        assert generation_call.output_tokens > 0

        # Grounded answer generation should normally contain substantially
        # more prompt context than intent classification because retrieved
        # knowledge blocks are included in its prompt.
        assert (
            generation_call.input_tokens
            > intent_call.input_tokens
        )

        # ---------------------------------------------------------------
        # Intent prediction
        # ---------------------------------------------------------------

        predictions = list(
            session.scalars(
                select(IntentPredictionModel)
                .where(
                    IntentPredictionModel.ai_run_id
                    == result.ai_run_id
                )
            )
        )

        assert len(predictions) == 1

        prediction = predictions[0]

        assert prediction.intent in {
            "refund_request",
            "payment_issue",
            "general_question",
        }

        assert 0.0 <= float(
            prediction.confidence
        ) <= 1.0

        # Intent classification is provider-backed, so provenance should
        # point at the corresponding Groq call.
        assert (
            prediction.llm_call_id
            == intent_call.id
        )

        # ---------------------------------------------------------------
        # Deterministic decision
        # ---------------------------------------------------------------

        decisions = list(
            session.scalars(
                select(AIDecisionModel)
                .where(
                    AIDecisionModel.ai_run_id
                    == result.ai_run_id
                )
            )
        )

        assert len(decisions) == 1

        decision = decisions[0]

        assert (
            decision.decision_type
            == "retrieve_information"
        )

        # DecisionEngine is deterministic and therefore must not claim
        # provenance from an LLM call.
        assert decision.llm_call_id is None