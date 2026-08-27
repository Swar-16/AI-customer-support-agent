from __future__ import annotations
import uuid
from uuid6 import uuid7
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from packages.ai.intent.schemas import IntentEntities
from packages.ai.providers.mock import MockLLMProvider, MockProviderConfig
from packages.application.composition.ai_pipeline_factory import AIPipelineFactory
from packages.application.conversations.process_customer_message import ProcessCustomerMessage, ProcessCustomerMessageCommand
from packages.database.models.ai.decision import AIDecisionModel
from packages.database.models.ai.intent_prediction import IntentPredictionModel
from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.conversation import ConversationModel
from packages.database.models.support.message import MessageModel
from packages.database.models.support.user import UserModel
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.config.settings import get_settings
from packages.ai.orchestration.state import PipelineStage

# Test DB
test_settings = get_settings("test")
TEST_DATABASE_URL = test_settings.database_url.render_as_string(hide_password=False)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


@pytest.fixture(scope="session")
def test_engine():
    assert TEST_DATABASE_URL is not None

    engine = create_engine(
        TEST_DATABASE_URL,
        pool_pre_ping=True,
    )
    yield engine
    engine.dispose()

@pytest.fixture(scope="session")
def test_session_factory(test_engine):
    return sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
        autoflush=False,
    )


# Seed data
@pytest.fixture
def seeded_conversation(test_session_factory):
    """
    Create an isolated customer + conversation for one test.
    Cleanup happens explicitly because ProcessCustomerMessage itself commits.
    """
    external_id = f"integration-user-{uuid7()}"

    with test_session_factory() as session:
        user = UserModel(
            external_id=external_id,
            email=None,
            display_name="Integration Test User",
            role="customer",
            status="active",
        )

        session.add(user)
        session.flush()

        conversation = ConversationModel(
            user_id=user.id,
            status="open",
            channel="web",
            title="Integration test conversation",
        )

        session.add(conversation)
        session.commit()

        user_id = user.id
        conversation_id = conversation.id

    yield {
        "user_id": user_id,
        "conversation_id": conversation_id,
    }

    # Cleanup
    with test_session_factory() as session:
        # Most children should cascade appropriately, but explicit cleanup
        # keeps this test independent of cascade implementation details.

        run_ids = tuple(session.scalars(
                            select(AIRunModel.id)
                            .where(AIRunModel.conversation_id == conversation_id))
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


# Mock external provider
@pytest.fixture
def mock_llm_provider():
    """
    Mock only the external model.
    Everything above the provider boundary remains real.
    """

    def structured_resolver(system_prompt: str, user_prompt: str, response_model):
        return {
            "intent": "payment_issue",
            "confidence": 0.97,
            "entities": {
                "order_id": "ORD-123",
                "transaction_id": None,
                "subscription_id": None,
                "account_id": None,
                "issue_type": "duplicate_charge",
            },
            "needs_clarification": False,
            "reason_summary": "Customer reports a duplicate charge for order ORD-123.",
        }

    return MockLLMProvider(
        config=MockProviderConfig(
            input_tokens=180,
            output_tokens=42,
            cached_input_tokens=20,
            estimated_cost_usd=Decimal("0.00001234"),
            provider_request_id="mock-integration-request-001",
        ),
        structured_resolver=structured_resolver,
    )

# Application service
@pytest.fixture
def service(test_session_factory, mock_llm_provider):
    pipeline_factory = AIPipelineFactory(base_provider=mock_llm_provider)

    def uow_factory():
        return SqlAlchemyUnitOfWork(session_factory=test_session_factory)

    return ProcessCustomerMessage(uow_factory=uow_factory, pipeline_factory=pipeline_factory)


# Full happy-path integration
def test_customer_message_persists_complete_ai_trace(service, test_session_factory, seeded_conversation):
    conversation_id = seeded_conversation["conversation_id"]
    trace_id = uuid7()
    result = service.execute(
        ProcessCustomerMessageCommand(
            conversation_id=conversation_id,
            customer_message="I was charged twice for order ORD-123. Can you help?",
            trace_id=trace_id,
        )
    )

    # Application result
    assert result.succeeded is True
    assert result.conversation_id == conversation_id
    assert result.trace_id == trace_id
    assert result.intent == "payment_issue"
    assert result.decision is not None

    # Verify database state
    with test_session_factory() as session:

        # support.messages
        customer_message = session.get(MessageModel, result.customer_message_id)

        assert customer_message is not None
        assert customer_message.conversation_id == conversation_id
        assert customer_message.role == "customer"
        assert customer_message.content == "I was charged twice for order ORD-123. Can you help?"
        assert customer_message.sequence_number == 1

        # ai.runs
        ai_run = session.get(AIRunModel, result.ai_run_id)

        assert ai_run is not None
        assert ai_run.trace_id == trace_id
        assert ai_run.trigger_message_id == customer_message.id
        assert ai_run.conversation_id == conversation_id
        assert ai_run.status == "completed"
        assert ai_run.completed_at is not None
        assert ai_run.total_latency_ms is not None
        assert ai_run.total_latency_ms >= 0

        # ai.llm_calls
        llm_calls = tuple(session.scalars(
                select(LLMCallModel)
                .where(LLMCallModel.ai_run_id == ai_run.id)
                .order_by(LLMCallModel.started_at)
            )
        )

        assert len(llm_calls) == 1
        llm_call = llm_calls[0]
        assert llm_call.status == "success"
        assert llm_call.provider == "mock"
        assert llm_call.model == "mock-llm-v1"
        assert llm_call.purpose == "intent_classification"
        assert llm_call.input_tokens == 180
        assert llm_call.output_tokens == 42
        assert llm_call.cached_input_tokens == 20
        assert llm_call.total_tokens == 222
        assert llm_call.provider_request_id == "mock-integration-request-001"
        assert llm_call.estimated_cost_usd == Decimal("0.00001234")
        assert llm_call.completed_at is not None
        assert llm_call.latency_ms is not None
        assert llm_call.latency_ms >= 0

        # ai.intent_predictions
        predictions = tuple(session.scalars(
                select(IntentPredictionModel)
                .where(IntentPredictionModel.ai_run_id == ai_run.id)
            )
        )

        assert len(predictions) == 1
        prediction = predictions[0]
        assert prediction.intent == "payment_issue"
        assert float(prediction.confidence) == pytest.approx(0.97)
        assert prediction.needs_clarification is False

        # Critical FK assertion:
        assert prediction.llm_call_id == llm_call.id
        assert prediction.entities["order_id"] == "ORD-123"
        assert prediction.entities["issue_type"] == "duplicate_charge"

        # ai.decisions
        decisions = tuple(session.scalars(
                select(AIDecisionModel)
                .where(AIDecisionModel.ai_run_id == ai_run.id)
            )
        )

        assert len(decisions) == 1
        decision = decisions[0]
        assert decision.decision_type is not None
        assert decision.reason_code is not None

        # DecisionEngine is deterministic.
        assert decision.llm_call_id is None
        
## timeout-path test
def test_provider_timeout_persists_failed_run_and_timeout_call(test_session_factory, seeded_conversation) -> None:
    provider = MockLLMProvider()
    provider.queue_timeout()
    pipeline_factory = AIPipelineFactory(base_provider=provider)

    def uow_factory():
        return SqlAlchemyUnitOfWork(session_factory=test_session_factory)

    service = ProcessCustomerMessage(uow_factory=uow_factory, pipeline_factory=pipeline_factory)
    conversation_id = seeded_conversation["conversation_id"]
    result = service.execute(
        ProcessCustomerMessageCommand(
            conversation_id=conversation_id,
            customer_message="Where is my payment?",
        )
    )

    # Application-level result
    assert result.succeeded is False
    assert result.intent is None
    assert result.decision is None
    assert result.pipeline_stage is PipelineStage.FAILED

    with test_session_factory() as session:
        # AI run must be persisted as FAILED
        ai_run = session.get(AIRunModel, result.ai_run_id)

        assert ai_run is not None
        assert ai_run.status == "failed"
        assert ai_run.completed_at is not None
        assert ai_run.total_latency_ms is not None
        assert ai_run.total_latency_ms >= 0
        assert ai_run.error_code == "INTENT_PROVIDER_TIMEOUT"
        assert ai_run.error_message is not None

        # The failed provider invocation must still exist
        llm_calls = tuple(session.scalars(
                        select(LLMCallModel)
                        .where(LLMCallModel.ai_run_id == result.ai_run_id)
                    )
        )

        assert len(llm_calls) == 1
        llm_call = llm_calls[0]
        assert llm_call.status == "timeout"
        assert llm_call.error_code == "TIMEOUT"
        assert llm_call.completed_at is not None
        assert llm_call.latency_ms is not None
        assert llm_call.latency_ms >= 0

        # Provider failed before producing valid usage.
        assert llm_call.input_tokens == 0
        assert llm_call.output_tokens == 0
        assert llm_call.total_tokens == 0

        # No semantic prediction should exist
        predictions = tuple(session.scalars(
                        select(IntentPredictionModel)
                        .where(IntentPredictionModel.ai_run_id == result.ai_run_id)
                    )
        )

        assert predictions == ()

        # DecisionEngine must never have produced a decision
        decisions = tuple(session.scalars(
                        select(AIDecisionModel)
                        .where(AIDecisionModel.ai_run_id == result.ai_run_id)
                    )
        )

        assert decisions == ()