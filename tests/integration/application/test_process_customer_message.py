# tests/integration/application/test_process_customer_message.py

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from uuid6 import uuid7

from packages.ai.generation.models import GroundedGenerationResult
from packages.ai.intent.schemas import IntentResult
from packages.ai.orchestration.state import PipelineStage
from packages.ai.providers.mock import MockLLMProvider, MockProviderConfig

from packages.application.composition.ai_pipeline_factory import (
    AIPipelineFactory,
)
from packages.application.conversations.process_customer_message import (
    ProcessCustomerMessage,
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

from packages.database.unit_of_work.sqlalchemy_uow import (
    SqlAlchemyUnitOfWork,
)

from packages.knowledge.embeddings.models import (
    EmbeddingInputDescriptor,
)
from packages.knowledge.embeddings.provider.base import (
    EmbeddingProvider,
    EmbeddingProviderDescriptor,
)
from packages.knowledge.retrieval.context.models import (
    GroundingContextBudget,
)
from packages.knowledge.retrieval.profiles import RetrievalProfile
from packages.database.models.ai.stage_event import AIStageEventModel
from packages.database.models.ai.retrieval_run import RetrievalRunModel
from packages.database.models.ai.reranker_call import RerankerCallModel
from packages.application.auth.models import (
    AuthenticatedPrincipal,
    AuthRole,
)


# ---------------------------------------------------------------------------
# Test database
# ---------------------------------------------------------------------------


test_settings = get_settings("test")

TEST_DATABASE_URL = (
    test_settings.database_url.render_as_string(
        hide_password=False
    )
)


pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL is required for "
        "PostgreSQL integration tests"
    ),
)


# ---------------------------------------------------------------------------
# Deterministic embedding provider
# ---------------------------------------------------------------------------


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic embedding provider used only at the external embedding
    boundary.

    The application/retrieval stack above this provider remains real.

    This provider deliberately performs no network I/O.
    """

    _DESCRIPTOR = EmbeddingProviderDescriptor(
        provider="integration-test",
        model="deterministic-v1",
        revision="1",
        dimensions=3,
    )

    @property
    def descriptor(self) -> EmbeddingProviderDescriptor:
        return self._DESCRIPTOR

    def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        return [
            [1.0, 0.0, 0.0]
            for _ in texts
        ]

    def embed_query(
        self,
        text: str,
    ) -> list[float]:
        return [1.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture
def seeded_conversation(test_session_factory):
    """
    Create one isolated customer + conversation.

    ProcessCustomerMessage commits its own transaction, therefore cleanup is
    explicit rather than transaction-rollback based.
    """

    external_id = (
        f"integration-user-{uuid7()}"
    )

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

    # ------------------------------------------------------------------
    # Explicit cleanup
    # ------------------------------------------------------------------

    with test_session_factory() as session:
        run_ids = tuple(
            session.scalars(
                select(AIRunModel.id)
                .where(
                    AIRunModel.conversation_id
                    == conversation_id
                )
            )
        )

        if run_ids:
            session.execute(
                delete(AIDecisionModel)
                .where(
                    AIDecisionModel.ai_run_id.in_(
                        run_ids
                    )
                )
            )

            session.execute(
                delete(IntentPredictionModel)
                .where(
                    IntentPredictionModel.ai_run_id.in_(
                        run_ids
                    )
                )
            )

            session.execute(
                delete(LLMCallModel)
                .where(
                    LLMCallModel.ai_run_id.in_(
                        run_ids
                    )
                )
            )

            session.execute(
                delete(AIRunModel)
                .where(
                    AIRunModel.id.in_(
                        run_ids
                    )
                )
            )

        session.execute(
            delete(MessageModel)
            .where(
                MessageModel.conversation_id
                == conversation_id
            )
        )

        session.execute(
            delete(ConversationModel)
            .where(
                ConversationModel.id
                == conversation_id
            )
        )

        session.execute(
            delete(UserModel)
            .where(
                UserModel.id == user_id
            )
        )

        session.commit()


# ---------------------------------------------------------------------------
# Deterministic AI dependencies
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_provider():
    """
    Mock only the external LLM provider.

    Intent classification and grounded generation therefore still execute
    through the real classifier/generator/instrumentation stack.
    """

    def structured_resolver(
        system_prompt: str,
        user_prompt: str,
        response_model,
    ):
        if response_model is IntentResult:
            return {
                "intent": "payment_issue",
                "confidence": 0.97,
                "entities": {
                    "order_id": "ORD-123",
                    "transaction_id": None,
                    "subscription_id": None,
                    "account_id": None,
                    "issue_type": "duplicate_charge",
                    "attributes": {},
                },
                "needs_clarification": False,
                "reason_summary": (
                    "Customer reports a duplicate charge "
                    "for order ORD-123."
                ),
            }

        if response_model is GroundedGenerationResult:
            return {
                "answer": (
                    "I don't have enough verified information "
                    "in the available knowledge to answer "
                    "this reliably."
                ),
                "grounding_status": "insufficient_evidence",
                "citations": [],
            }

        raise AssertionError(
            "Unexpected structured response model: "
            f"{response_model!r}"
        )

    return MockLLMProvider(
        config=MockProviderConfig(
            input_tokens=180,
            output_tokens=42,
            cached_input_tokens=20,
            estimated_cost_usd=Decimal(
                "0.00001234"
            ),
            provider_request_id=(
                "mock-integration-request-001"
            ),
        ),
        structured_resolver=structured_resolver,
    )


@pytest.fixture
def embedding_provider():
    return DeterministicEmbeddingProvider()


@pytest.fixture
def embedding_input_descriptor():
    return EmbeddingInputDescriptor(
        strategy_id="integration-contextual",
        version="1",
        config_fingerprint=(
            "a" * 64
        ),
    )


@pytest.fixture
def retrieval_profile():
    """
    Lexical-only integration profile.

    The ProcessCustomerMessage -> AnswerService -> retrieval composition
    remains real, while the test does not depend on seeded vector artifacts.

    Empty retrieval is a valid semantic result and exercises grounded
    generation's insufficient-evidence path.
    """

    return RetrievalProfile(
        profile_id="process-message-integration",
        vector_enabled=False,
        lexical_enabled=True,
        reranking_enabled=False,
        lexical_candidate_limit=20,
        fused_candidate_limit=20,
        final_candidate_limit=8,
        rrf_k=60,
    )


@pytest.fixture
def grounding_context_budget():
    return GroundingContextBudget(
        max_tokens=2_000,
        max_blocks=8,
    )


@pytest.fixture
def service(
    test_session_factory,
    mock_llm_provider,
    embedding_provider,
    embedding_input_descriptor,
    retrieval_profile,
    grounding_context_budget,
):
    pipeline_factory = AIPipelineFactory(
        base_provider=mock_llm_provider
    )

    def uow_factory():
        return SqlAlchemyUnitOfWork(
            session_factory=test_session_factory
        )

    return ProcessCustomerMessage(
        uow_factory=uow_factory,
        pipeline_factory=pipeline_factory,
        embedding_provider=embedding_provider,
        embedding_input_descriptor=(
            embedding_input_descriptor
        ),
        retrieval_profile=retrieval_profile,
        grounding_context_budget=(
            grounding_context_budget
        ),
    )
    
def _customer_principal(
    seeded_conversation: dict,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=seeded_conversation["user_id"],
        session_id=uuid7(),
        role=AuthRole.CUSTOMER,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_customer_message_persists_complete_ai_trace_and_assistant_response(
    service,
    test_session_factory,
    seeded_conversation,
):
    conversation_id = (
        seeded_conversation["conversation_id"]
    )

    trace_id = uuid7()

    customer_text = (
        "I was charged twice for order ORD-123. "
        "Can you help?"
    )

    result = service.execute(
        ProcessCustomerMessageCommand(
            conversation_id=conversation_id,
            customer_message=customer_text,
            principal=_customer_principal(seeded_conversation),
            trace_id=trace_id,
        )
    )

    # ------------------------------------------------------------------
    # Application result
    # ------------------------------------------------------------------

    assert result.succeeded is True
    assert result.conversation_id == conversation_id
    assert result.trace_id == trace_id

    assert (
        result.pipeline_stage
        is PipelineStage.GUARDRAILS_COMPLETED
    )

    assert result.intent == "payment_issue"
    assert result.decision == "retrieve_information"

    assert result.customer_message_id is not None
    assert result.assistant_message_id is not None

    assert result.response == (
        "I don't have enough verified information "
        "in the available knowledge to answer "
        "this reliably."
    )

    assert (
        result.assistant_message_id
        != result.customer_message_id
    )

    # ------------------------------------------------------------------
    # Verify persisted database state
    # ------------------------------------------------------------------

    with test_session_factory() as session:
        messages = tuple(
            session.scalars(
                select(MessageModel)
                .where(
                    MessageModel.conversation_id
                    == conversation_id
                )
                .order_by(
                    MessageModel.sequence_number
                )
            )
        )

        # --------------------------------------------------------------
        # Conversation message ordering
        # --------------------------------------------------------------

        assert len(messages) == 2

        customer_message = messages[0]
        assistant_message = messages[1]

        assert (
            customer_message.id
            == result.customer_message_id
        )

        assert customer_message.role == "customer"
        assert customer_message.content == customer_text
        assert customer_message.sequence_number == 1

        assert (
            assistant_message.id
            == result.assistant_message_id
        )

        assert assistant_message.role == "assistant"
        assert (
            assistant_message.content
            == result.response
        )
        assert assistant_message.sequence_number == 2

        assert (
            assistant_message.conversation_id
            == conversation_id
        )

        # --------------------------------------------------------------
        # AI run
        # --------------------------------------------------------------

        ai_run = session.get(
            AIRunModel,
            result.ai_run_id,
        )

        assert ai_run is not None

        assert ai_run.trace_id == trace_id
        assert (
            ai_run.trigger_message_id
            == customer_message.id
        )
        assert (
            ai_run.response_message_id
            == assistant_message.id
        )

        assert (
            ai_run.conversation_id
            == conversation_id
        )

        assert ai_run.status == "completed"
        assert ai_run.completed_at is not None
        assert ai_run.total_latency_ms is not None
        assert ai_run.total_latency_ms >= 0

        # --------------------------------------------------------------
        # LLM calls
        #
        # One call belongs to intent classification and one to grounded
        # response generation.
        # --------------------------------------------------------------

        llm_calls = tuple(
            session.scalars(
                select(LLMCallModel)
                .where(
                    LLMCallModel.ai_run_id
                    == ai_run.id
                )
                .order_by(
                    LLMCallModel.started_at
                )
            )
        )

        assert len(llm_calls) == 2

        purposes = {
            call.purpose
            for call in llm_calls
        }

        assert purposes == {
            "intent_classification",
            "answer_generation",
        }

        for llm_call in llm_calls:
            assert llm_call.status == "success"
            assert llm_call.provider == "mock"
            assert llm_call.model == "mock-llm-v1"

            assert llm_call.input_tokens == 180
            assert llm_call.output_tokens == 42
            assert llm_call.cached_input_tokens == 20
            assert llm_call.total_tokens == 222

            assert (
                llm_call.provider_request_id
                == "mock-integration-request-001"
            )

            assert (
                llm_call.estimated_cost_usd
                == Decimal("0.00001234")
            )

            assert llm_call.completed_at is not None
            assert llm_call.latency_ms is not None
            assert llm_call.latency_ms >= 0

        intent_call = next(
            call
            for call in llm_calls
            if call.purpose
            == "intent_classification"
        )

        # --------------------------------------------------------------
        # Intent prediction
        # --------------------------------------------------------------

        predictions = tuple(
            session.scalars(
                select(IntentPredictionModel)
                .where(
                    IntentPredictionModel.ai_run_id
                    == ai_run.id
                )
            )
        )

        assert len(predictions) == 1

        prediction = predictions[0]

        assert prediction.intent == "payment_issue"

        assert (
            float(prediction.confidence)
            == pytest.approx(0.97)
        )

        assert (
            prediction.needs_clarification
            is False
        )

        # Intent provenance must point specifically to the
        # intent-classification provider call, not generation.
        assert (
            prediction.llm_call_id
            == intent_call.id
        )

        assert (
            prediction.entities["order_id"]
            == "ORD-123"
        )

        assert (
            prediction.entities["issue_type"]
            == "duplicate_charge"
        )

        # --------------------------------------------------------------
        # Deterministic decision
        # --------------------------------------------------------------

        decisions = tuple(
            session.scalars(
                select(AIDecisionModel)
                .where(
                    AIDecisionModel.ai_run_id
                    == ai_run.id
                )
            )
        )

        assert len(decisions) == 1

        decision = decisions[0]

        assert (
            decision.decision_type
            == "retrieve_information"
        )

        assert decision.reason_code is not None

        # DecisionEngine is deterministic and therefore has no LLM call.
        assert decision.llm_call_id is None
        
        # --------------------------------------------------------------
        # Retrieval telemetry
        # --------------------------------------------------------------

        retrieval_runs = tuple(
            session.scalars(
                select(RetrievalRunModel).where(
                    RetrievalRunModel.ai_run_id == ai_run.id
                )
            )
        )

        assert len(retrieval_runs) == 1

        retrieval_run = retrieval_runs[0]

        assert retrieval_run.ai_run_id == ai_run.id
        assert retrieval_run.trace_id == trace_id
        assert retrieval_run.conversation_id == conversation_id
        assert retrieval_run.status == "success"
        assert retrieval_run.retrieval_mode == "lexical"
        assert retrieval_run.embedding_call_id is None
        assert retrieval_run.vector_candidate_count == 0
        assert retrieval_run.reranker_used is False
        reranker_calls = tuple(
            session.scalars(
                select(RerankerCallModel).where(
                    RerankerCallModel.retrieval_run_id
                    == retrieval_run.id
                )
            )
        )

        assert reranker_calls == ()
        assert retrieval_run.zero_result is True
        assert retrieval_run.completed_at is not None
        assert retrieval_run.total_latency_ms is not None
        assert retrieval_run.total_latency_ms >= 0

        # --------------------------------------------------------------
        # Orchestration stage telemetry
        # --------------------------------------------------------------

        stage_events = tuple(
            session.scalars(
                select(AIStageEventModel)
                .where(AIStageEventModel.ai_run_id == ai_run.id)
                .order_by(
                    AIStageEventModel.occurred_at.asc(),
                    AIStageEventModel.id.asc(),
                )
            )
        )

        assert stage_events

        assert all(
            event.trace_id == trace_id
            for event in stage_events
        )

        assert all(
            event.conversation_id == conversation_id
            for event in stage_events
        )

        assert all(
            event.trigger_message_id == result.customer_message_id
            for event in stage_events
        )

        started_stages = {
            event.stage
            for event in stage_events
            if event.event_type == "stage_started"
        }

        completed_stages = {
            event.stage
            for event in stage_events
            if event.event_type == "stage_completed"
        }

        expected_stages = {
            "intent_classified",
            "decision_made",
            "retrieval_completed",
            "response_generated",
            "guardrails_completed",
        }

        assert started_stages == expected_stages
        assert completed_stages == expected_stages

        assert not any(
            event.event_type == "stage_failed"
            for event in stage_events
        )

        for event in stage_events:
            if event.event_type == "stage_started":
                assert event.duration_ms is None
                assert event.error_code is None
                assert event.retryable is None

            elif event.event_type == "stage_completed":
                assert event.duration_ms is not None
                assert event.duration_ms >= 0
                assert event.error_code is None
                assert event.retryable is None

        serialized_stage_metadata = " ".join(
            str(event.metadata_)
            for event in stage_events
        )

        assert customer_text not in serialized_stage_metadata
        assert result.response not in serialized_stage_metadata


# ---------------------------------------------------------------------------
# No-generated-response path
# ---------------------------------------------------------------------------


def test_clarification_decision_completes_without_assistant_message(
    test_session_factory,
    seeded_conversation,
    embedding_provider,
    embedding_input_descriptor,
    retrieval_profile,
    grounding_context_budget,
):
    """
    A successful workflow decision does not imply that an assistant message
    exists.

    The current pipeline can stop at DECISION_MADE for clarification because
    dedicated clarification-response generation has not yet been added.
    """

    def structured_resolver(
        system_prompt: str,
        user_prompt: str,
        response_model,
    ):
        if response_model is IntentResult:
            return {
                "intent": "unknown",
                "confidence": 0.95,
                "entities": {
                    "order_id": None,
                    "transaction_id": None,
                    "subscription_id": None,
                    "account_id": None,
                    "issue_type": None,
                    "attributes": {},
                },
                "needs_clarification": True,
                "reason_summary": (
                    "The request is too ambiguous "
                    "to determine the customer's intent."
                ),
            }

        raise AssertionError(
            "Generation must not be invoked "
            "for this clarification path."
        )

    provider = MockLLMProvider(
        structured_resolver=structured_resolver
    )

    pipeline_factory = AIPipelineFactory(
        base_provider=provider
    )

    def uow_factory():
        return SqlAlchemyUnitOfWork(
            session_factory=test_session_factory
        )

    service = ProcessCustomerMessage(
        uow_factory=uow_factory,
        pipeline_factory=pipeline_factory,
        embedding_provider=embedding_provider,
        embedding_input_descriptor=(
            embedding_input_descriptor
        ),
        retrieval_profile=retrieval_profile,
        grounding_context_budget=(
            grounding_context_budget
        ),
    )

    conversation_id = (
        seeded_conversation["conversation_id"]
    )

    result = service.execute(
        ProcessCustomerMessageCommand(
            conversation_id=conversation_id,
            customer_message="Can you help me with this?",
            principal=_customer_principal(seeded_conversation),
        )
    )

    assert result.succeeded is True

    assert (
        result.pipeline_stage
        is PipelineStage.DECISION_MADE
    )

    assert result.decision == "ask_clarification"

    assert result.assistant_message_id is None
    assert result.response is None

    with test_session_factory() as session:
        messages = tuple(
            session.scalars(
                select(MessageModel)
                .where(
                    MessageModel.conversation_id
                    == conversation_id
                )
            )
        )

        # Only the triggering customer message exists.
        assert len(messages) == 1
        assert messages[0].role == "customer"

        ai_run = session.get(
            AIRunModel,
            result.ai_run_id,
        )

        assert ai_run is not None
        assert ai_run.status == "completed"

        assert ai_run.response_message_id is None


# ---------------------------------------------------------------------------
# Provider timeout path
# ---------------------------------------------------------------------------


def test_provider_timeout_persists_failed_run_without_assistant_message(
    test_session_factory,
    seeded_conversation,
    embedding_provider,
    embedding_input_descriptor,
    retrieval_profile,
    grounding_context_budget,
):
    provider = MockLLMProvider()

    provider.queue_timeout()

    pipeline_factory = AIPipelineFactory(
        base_provider=provider
    )

    def uow_factory():
        return SqlAlchemyUnitOfWork(
            session_factory=test_session_factory
        )

    service = ProcessCustomerMessage(
        uow_factory=uow_factory,
        pipeline_factory=pipeline_factory,
        embedding_provider=embedding_provider,
        embedding_input_descriptor=(
            embedding_input_descriptor
        ),
        retrieval_profile=retrieval_profile,
        grounding_context_budget=(
            grounding_context_budget
        ),
    )

    conversation_id = (
        seeded_conversation["conversation_id"]
    )

    result = service.execute(
        ProcessCustomerMessageCommand(
            conversation_id=conversation_id,
            customer_message="Where is my payment?",
            principal=_customer_principal(seeded_conversation),
        )
    )

    # ------------------------------------------------------------------
    # Application result
    # ------------------------------------------------------------------

    assert result.succeeded is False
    assert result.intent is None
    assert result.decision is None

    assert (
        result.pipeline_stage
        is PipelineStage.FAILED
    )

    assert result.assistant_message_id is None
    assert result.response is None

    with test_session_factory() as session:
        # --------------------------------------------------------------
        # Failed AI run remains auditable
        # --------------------------------------------------------------

        ai_run = session.get(
            AIRunModel,
            result.ai_run_id,
        )

        assert ai_run is not None
        assert ai_run.status == "failed"

        assert ai_run.response_message_id is None

        assert ai_run.completed_at is not None
        assert ai_run.total_latency_ms is not None
        assert ai_run.total_latency_ms >= 0

        assert (
            ai_run.error_code
            == "INTENT_PROVIDER_TIMEOUT"
        )

        assert ai_run.error_message is not None

        # --------------------------------------------------------------
        # Customer message remains persisted
        # --------------------------------------------------------------

        messages = tuple(
            session.scalars(
                select(MessageModel)
                .where(
                    MessageModel.conversation_id
                    == conversation_id
                )
            )
        )

        assert len(messages) == 1
        assert messages[0].role == "customer"

        # --------------------------------------------------------------
        # Failed provider call remains persisted
        # --------------------------------------------------------------

        llm_calls = tuple(
            session.scalars(
                select(LLMCallModel)
                .where(
                    LLMCallModel.ai_run_id
                    == result.ai_run_id
                )
            )
        )

        assert len(llm_calls) == 1

        llm_call = llm_calls[0]

        assert llm_call.status == "timeout"
        assert llm_call.error_code == "TIMEOUT"

        assert llm_call.completed_at is not None
        assert llm_call.latency_ms is not None
        assert llm_call.latency_ms >= 0

        assert llm_call.input_tokens == 0
        assert llm_call.output_tokens == 0
        assert llm_call.total_tokens == 0

        # --------------------------------------------------------------
        # No semantic output exists because intent classification failed
        # --------------------------------------------------------------

        predictions = tuple(
            session.scalars(
                select(IntentPredictionModel)
                .where(
                    IntentPredictionModel.ai_run_id
                    == result.ai_run_id
                )
            )
        )

        assert predictions == ()

        decisions = tuple(
            session.scalars(
                select(AIDecisionModel)
                .where(
                    AIDecisionModel.ai_run_id
                    == result.ai_run_id
                )
            )
        )

        assert decisions == ()