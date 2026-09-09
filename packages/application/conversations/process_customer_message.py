# AI-customer-support-agent\packages\application\conversations\process_customer_message.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Final
from uuid6 import uuid7

from packages.ai.generation.generator import GroundedResponseGenerator
from packages.ai.orchestration.state import AIState, PipelineStage
from packages.ai.telemetry.recorder import TelemetryRecorder
from packages.ai.providers.base import LLMProvider
from packages.application.ai.answer_service import AnswerService
from packages.application.composition.ai_pipeline_factory import AIPipelineFactory, AITelemetryRepositories
from packages.application.composition.answer_service_factory import create_answer_service_components
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.message import MessageModel
from packages.database.repositories.ai.ai_run_repository import AIRunRepository
from packages.database.repositories.ai.decision_repository import AIDecisionRepository
from packages.database.repositories.ai.intent_prediction_repository import IntentPredictionRepository
from packages.database.repositories.ai.llm_call_repository import LLMCallRepository
from packages.database.repositories.support.conversation_repository import ConversationRepository
from packages.database.repositories.support.message_repository import MessageRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.knowledge.embeddings.provider.base import EmbeddingProvider
from packages.knowledge.retrieval.context.models import GroundingContextBudget
from packages.knowledge.retrieval.profiles import RetrievalProfile
from packages.knowledge.embeddings.models import EmbeddingInputDescriptor
from packages.application.escalations.create_escalation import CreateEscalation, CreateEscalationCommand
from packages.database.repositories.support.escalation_repository import EscalationRepository
from packages.database.models.support.conversation import ConversationModel
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository
from packages.ai.telemetry.transactional_embedding_recorder import TransactionalEmbeddingTelemetryRecorder
from packages.database.repositories.ai.embedding_call_repository import EmbeddingCallRepository
from packages.knowledge.embeddings.provider.instrumented import EmbeddingCallContext, InstrumentedEmbeddingProvider
from packages.ai.telemetry.retrieval_recorder import RetrievalTelemetryRecorder
from packages.database.repositories.ai.retrieval_repository import RetrievalRepository
from packages.ai.telemetry.reranker_recorder import RerankerTelemetryRecorder
from packages.database.repositories.ai.reranker_call_repository import RerankerCallRepository
from packages.database.repositories.ai.stage_event_repository import AIStageEventRepository


# Internal repository bundle
@dataclass(frozen=True, slots=True)
class _Repositories:
    conversations: ConversationRepository
    messages: MessageRepository
    escalations: EscalationRepository
    audit_events: AuditEventRepository
    ai_runs: AIRunRepository
    llm_calls: LLMCallRepository
    embedding_calls: EmbeddingCallRepository
    retrieval: RetrievalRepository
    reranker_calls: RerankerCallRepository
    stage_events: AIStageEventRepository
    intent_predictions: IntentPredictionRepository
    ai_decisions: AIDecisionRepository

MAX_CUSTOMER_MESSAGE_LENGTH: Final[int] = 20_000
UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

# Application exceptions
class ProcessCustomerMessageError(RuntimeError):
    """Base application-layer error for customer-message processing."""

class ConversationDoesNotExistError(ProcessCustomerMessageError):
    def __init__(self, conversation_id: uuid.UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation does not exist: {conversation_id}")

class ConversationNotProcessableError(ProcessCustomerMessageError):
    """Raised when the conversation exists but its current lifecycle state does not permit another customer message."""

class CustomerMessageValidationError(ProcessCustomerMessageError):
    pass

class PersistenceContractError(ProcessCustomerMessageError):
    """Indicates an internal application/UoW wiring problem rather than a customer-originated problem."""

# Command / result contracts
@dataclass(frozen=True, slots=True)
class ProcessCustomerMessageCommand:
    """
    Input contract for processing one customer-authored message.
    """
    conversation_id: uuid.UUID
    customer_message: str
    trace_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, uuid.UUID):
            raise TypeError("conversation_id must be UUID")

        if self.trace_id is not None and not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be UUID or None")

        if not isinstance(self.customer_message, str):
            raise TypeError("customer_message must be a string")

@dataclass(frozen=True, slots=True)
class ProcessCustomerMessageResult:
    """
    Application result returned after the transaction is committed.

    IDs are returned instead of live ORM objects so callers do not receive entities bound to a Session that has already been closed.

    ``assistant_message_id`` and ``response`` are populated only when the pipeline produced a customer-visible assistant response.
    
    ``escalation_id`` is populated when the pipeline requests human review.
    """
    conversation_id: uuid.UUID
    customer_message_id: uuid.UUID
    ai_run_id: uuid.UUID
    trace_id: uuid.UUID
    pipeline_stage: PipelineStage
    intent: str | None
    decision: str | None
    assistant_message_id: uuid.UUID | None
    escalation_id: uuid.UUID | None
    response: str | None
    succeeded: bool

# Application service
class ProcessCustomerMessage:
    """
    Application use case for processing one customer message.

    Transactional flow:

        load conversation
              ↓
        allocate message sequence
              ↓
        persist customer message
              ↓
        create AI run
              ↓
        compose request-scoped AI/RAG pipeline
              ↓
        execute orchestrator
              ↓
        persist classification + decision evidence
              ↓
        finalize AI run
              ↓
        commit once

    Long-lived dependencies such as the embedding provider, retrieval profile, grounding budget, and
    AIPipelineFactory are supplied by application composition.

    Request-scoped dependencies such as the active SQLAlchemy Session, telemetry recorder, instrumented LLM providers,
    grounded response generator, AnswerService, and orchestrator are created for the current request/run.

    Known AI pipeline failures are persisted as failed AI runs.

    Unexpected infrastructure/programming exceptions escape this service so the UnitOfWork rolls the complete transaction back.
    """
    PROCESSABLE_CONVERSATION_STATUSES: Final[frozenset[str]] = frozenset(
        {"open", "waiting_for_customer", "waiting_for_agent", "escalated"})
    
    CUSTOMER_RESPONSE_STAGES: Final[frozenset[PipelineStage]] = frozenset({PipelineStage.GUARDRAILS_COMPLETED,})

    def __init__(self, *, uow_factory: UnitOfWorkFactory, pipeline_factory: AIPipelineFactory, embedding_provider: EmbeddingProvider,
                 embedding_input_descriptor: EmbeddingInputDescriptor, retrieval_profile: RetrievalProfile, grounding_context_budget: GroundingContextBudget,
    ) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if pipeline_factory is None:
            raise TypeError("pipeline_factory cannot be None")

        if not isinstance(pipeline_factory, AIPipelineFactory):
            raise TypeError("pipeline_factory must be an AIPipelineFactory")

        if embedding_provider is None:
            raise TypeError("embedding_provider cannot be None")

        if not isinstance(embedding_provider, EmbeddingProvider):
            raise TypeError("embedding_provider must implement EmbeddingProvider")
            
        if embedding_input_descriptor is None:
            raise TypeError("embedding_input_descriptor cannot be None")

        if not isinstance(embedding_input_descriptor, EmbeddingInputDescriptor):
            raise TypeError("embedding_input_descriptor must be an EmbeddingInputDescriptor")

        if retrieval_profile is None:
            raise TypeError("retrieval_profile cannot be None")

        if not isinstance(retrieval_profile, RetrievalProfile):
            raise TypeError("retrieval_profile must be a RetrievalProfile")

        if grounding_context_budget is None:
            raise TypeError("grounding_context_budget cannot be None")

        if not isinstance(grounding_context_budget, GroundingContextBudget):
            raise TypeError("grounding_context_budget must be a GroundingContextBudget")

        self._uow_factory = uow_factory
        self._pipeline_factory = pipeline_factory
        self._embedding_provider = embedding_provider
        self._embedding_input_descriptor = embedding_input_descriptor
        self._retrieval_profile = retrieval_profile
        self._grounding_context_budget = grounding_context_budget

    # Public API
    def execute(self, command: ProcessCustomerMessageCommand) -> ProcessCustomerMessageResult:
        """
        Process one customer message as one application transaction.

        Known AI pipeline failures are represented by PipelineStage.FAILED and persisted as failed AI runs.

        Unexpected exceptions propagate out of the UnitOfWork context, causing rollback.
        """
        if not isinstance(command, ProcessCustomerMessageCommand):
            raise TypeError("command must be a ProcessCustomerMessageCommand")

        normalized_message = self._normalize_customer_message(command.customer_message)
        trace_id = command.trace_id if command.trace_id is not None else uuid7()
        with self._uow_factory() as uow:
            repositories = self._require_repositories(uow)

            # Load + validate conversation
            conversation = repositories.conversations.get_by_id(command.conversation_id)
            if conversation is None:
                raise ConversationDoesNotExistError(command.conversation_id)

            self._validate_conversation_status(conversation.status)

            # Persist triggering customer message
            sequence_number = repositories.conversations.allocate_message_sequence(command.conversation_id)
            customer_message = MessageModel(
                conversation_id=command.conversation_id,
                role="customer",
                content=normalized_message,
                sequence_number=sequence_number,
                metadata={},
            )

            repositories.messages.add(customer_message)
            # We need the generated message UUID before creating ai.runs.
            repositories.messages.flush()

            if customer_message.id is None:
                raise PersistenceContractError("Customer message ID was not generated after flush")

            # Create AI run
            ai_run = AIRunModel(
                trace_id=trace_id,
                conversation_id=command.conversation_id,
                trigger_message_id=customer_message.id,
                pipeline_version=self._pipeline_factory.pipeline_version,
                status="running",
            )

            repositories.ai_runs.add(ai_run)
            repositories.ai_runs.flush()
            if ai_run.id is None:
                raise PersistenceContractError("AI run ID was not generated after flush")

            # Request-scoped AnswerService composition
            def build_answer_service(response_generator: GroundedResponseGenerator) -> AnswerService:
                """
                Build the AnswerService only after AIPipelineFactory has created this run's GroundedResponseGenerator.

                The active UoW Session is reused by retrieval repositories. No second SQLAlchemy Session / transaction is opened.
                """
                session = uow.session
                if session is None:
                    raise PersistenceContractError("Active SQLAlchemy Session unavailable while composing AnswerService")
                
                embedding_recorder = TransactionalEmbeddingTelemetryRecorder(repository=repositories.embedding_calls)
                retrieval_recorder = RetrievalTelemetryRecorder(
                    repository=repositories.retrieval, ai_run_id=ai_run.id, trace_id=trace_id, conversation_id=command.conversation_id,
                    profile=self._retrieval_profile,
                )
                reranker_recorder = RerankerTelemetryRecorder(
                    repository=repositories.reranker_calls,
                    retrieval_run_id=lambda: retrieval_recorder.retrieval_run_id,
                    trace_id=trace_id,
                    metadata={
                        "workflow": "customer_support_retrieval",
                        "conversation_id": str(command.conversation_id),
                        "ai_run_id": str(ai_run.id),
                    },
                )
                instrumented_embedding_provider = InstrumentedEmbeddingProvider(
                    provider=self._embedding_provider,
                    recorder=embedding_recorder,
                    context=EmbeddingCallContext(
                        purpose="query",
                        ai_run_id=ai_run.id,
                        trace_id=trace_id,
                        metadata={
                            "workflow": "customer_support_retrieval",
                            "conversation_id": str(command.conversation_id),
                        },
                    ),
                )

                components = create_answer_service_components(
                    session=session,
                    profile=self._retrieval_profile,
                    default_context_budget=self._grounding_context_budget,
                    response_generator=response_generator,
                    embedding_provider=instrumented_embedding_provider,
                    embedding_input_descriptor=self._embedding_input_descriptor,
                    retrieval_telemetry_recorder=retrieval_recorder,
                    reranker_telemetry_recorder=reranker_recorder
                )

                return components.answer_service

            # Request-scoped AI pipeline composition
            pipeline = self._pipeline_factory.create(
                ai_run_id=ai_run.id,
                repositories=AITelemetryRepositories(
                    llm_calls=repositories.llm_calls,
                    intent_predictions=repositories.intent_predictions,
                    ai_decisions=repositories.ai_decisions,
                    stage_events=repositories.stage_events,
                ),
                answer_service_builder=build_answer_service,
            )

            # Execute AI pipeline
            started_perf = perf_counter()
            state = pipeline.orchestrator.process_message(
                ai_run_id=ai_run.id,
                trace_id=trace_id,
                conversation_id=command.conversation_id,
                trigger_message_id=customer_message.id,
                customer_message=normalized_message,
                conversation_context=None,
            )
            total_latency_ms = self._elapsed_ms(started_perf)

            # Persist orchestration artifacts
            self._persist_pipeline_artifacts(
                recorder=pipeline.telemetry_recorder,
                state=state,
                ai_run_id=ai_run.id,
                intent_llm_call_id=pipeline.intent_provider.last_call_id,
            )
            
            # Persist human-review escalation when requested by orchestration.
            escalation_id: uuid.UUID | None = None

            if state.stage is PipelineStage.ESCALATED:
                escalation_id = self._persist_escalation(
                    repositories=repositories,
                    conversation=conversation,
                    state=state,
                    trace_id=trace_id,
                )

            # Persist customer-visible assistant response
            assistant_message: MessageModel | None = None
            if state.stage in self.CUSTOMER_RESPONSE_STAGES:
                assistant_message = self._persist_assistant_response(
                    repositories=repositories,
                    conversation_id=command.conversation_id,
                    state=state,
                )
                
            # Capture primitives before commit/session lifecycle ends.
            assistant_message_id = assistant_message.id if assistant_message is not None else None
            response = assistant_message.content if assistant_message is not None else None

            # Finalize AI run
            if state.stage is PipelineStage.FAILED:
                self._mark_run_failed(repositories=repositories, run=ai_run, state=state, total_latency_ms=total_latency_ms)

            else:
                self._mark_run_completed(
                    repositories=repositories,
                    run=ai_run,
                    response_message_id=assistant_message_id,
                    total_latency_ms=total_latency_ms,
                )
            
            # Commit once
            uow.commit()

            return ProcessCustomerMessageResult(
                conversation_id=command.conversation_id,
                customer_message_id=customer_message.id,
                ai_run_id=ai_run.id,
                trace_id=trace_id,
                pipeline_stage=state.stage,
                intent=state.intent_result.intent.value if state.intent_result is not None else None,
                decision=state.decision_result.decision.value if state.decision_result is not None else None,
                assistant_message_id=assistant_message_id,
                escalation_id=escalation_id,
                response=response,
                succeeded=state.stage is not PipelineStage.FAILED,
            )

    # Persistence
    @staticmethod
    def _persist_pipeline_artifacts(*, recorder: TelemetryRecorder, state: AIState, ai_run_id: uuid.UUID, intent_llm_call_id: uuid.UUID | None) -> None:
        """
        Persist domain-level AI artifacts.

        Provider-call telemetry is already persisted by the instrumented providers.

        IntentPrediction is associated specifically with the intent provider's LLM call.

        DecisionEngine is deterministic, therefore AIDecision deliberately has no llm_call_id.
        """
        now = datetime.now(timezone.utc)
        if state.intent_result is not None:
            recorder.record_intent_prediction(
                ai_run_id=ai_run_id,
                result=state.intent_result,
                llm_call_id=intent_llm_call_id,
                created_at=now,
            )

        if state.decision_result is not None:
            recorder.record_decision(
                ai_run_id=ai_run_id,
                result=state.decision_result,
                llm_call_id=None,
                created_at=now,
            )

    @staticmethod
    def _mark_run_completed(*, repositories: _Repositories, run: AIRunModel, response_message_id: uuid.UUID | None, total_latency_ms: int) -> None:
        """
        Complete the AI run and associate it with the customer-visible response when one was produced.

        A completed run may legitimately have no response message yet. For example, some workflow decisions can complete before
        their dedicated clarification, action, or escalation response stage exists.
        """
        repositories.ai_runs.mark_completed(
            run,
            response_message_id=response_message_id,
            completed_at=datetime.now(timezone.utc),
            total_latency_ms=total_latency_ms,
        )

    @staticmethod
    def _mark_run_failed(*, repositories: _Repositories, run: AIRunModel, state: AIState, total_latency_ms: int) -> None:
        if not state.errors:
            raise PersistenceContractError("FAILED AIState must contain at least one PipelineError")

        error = state.errors[-1]
        repositories.ai_runs.mark_failed(
            run,
            completed_at=datetime.now(timezone.utc),
            total_latency_ms=total_latency_ms,
            error_code=error.code,
            error_message=error.message,
        )
        
    @staticmethod
    def _persist_assistant_response(*, repositories: _Repositories, conversation_id: uuid.UUID, state: AIState) -> MessageModel:
        """
        Persist an approved customer-visible assistant response.

        This method may only be called after response guardrails completed successfully.

        ``generated_response`` represents the generated candidate while RESPONSE_GENERATED. It becomes eligible for customer
        persistence only after the orchestration state reaches GUARDRAILS_COMPLETED.

        Message sequencing is allocated through ConversationRepository so customer and assistant messages share one concurrency-safe sequence.
        """
        if state.stage is not PipelineStage.GUARDRAILS_COMPLETED:
            raise PersistenceContractError("Assistant response may only be persisted after guardrails complete successfully")

        response = state.generated_response
        if response is None:
            raise PersistenceContractError("GUARDRAILS_COMPLETED state must contain a generated response")

        normalized_response = response.strip()
        if not normalized_response:
            raise PersistenceContractError("GUARDRAILS_COMPLETED state contains a blank generated response")

        sequence_number = repositories.conversations.allocate_message_sequence(conversation_id)
        assistant_message = MessageModel(
            conversation_id=conversation_id,
            role="assistant",
            content=normalized_response,
            sequence_number=sequence_number,
            metadata={},
        )

        repositories.messages.add(assistant_message)
        repositories.messages.flush()

        if assistant_message.id is None:
            raise PersistenceContractError("Assistant message ID was not generated after flush")

        return assistant_message
    
    @staticmethod
    def _persist_escalation(*, repositories: _Repositories, conversation: ConversationModel, state: AIState, trace_id: uuid.UUID) -> uuid.UUID:
        """
        Persist an orchestration-requested escalation and move the conversation into the escalated state.

        Both mutations occur through repositories sharing the current Unit of Work, so they are committed or rolled back 
        together with the customer message, AI run, and telemetry.
        """
        if state.stage is not PipelineStage.ESCALATED:
            raise PersistenceContractError("Escalation may only be persisted from an ESCALATED AIState")

        if state.escalation_source is None:
            raise PersistenceContractError("ESCALATED state must contain escalation_source")

        if state.escalation_reason_code is None:
            raise PersistenceContractError("ESCALATED state must contain escalation_reason_code")

        if state.decision_result is None:
            raise PersistenceContractError("ESCALATED state must contain decision_result")

        create_escalation = CreateEscalation(repository=repositories.escalations, audit_repository=repositories.audit_events)
        result = create_escalation.execute(
            CreateEscalationCommand(
                conversation_id=state.conversation_id,
                trace_id=trace_id,
                ai_run_id=state.ai_run_id,
                trigger_message_id=state.trigger_message_id,
                source=state.escalation_source.value,
                reason_code=state.escalation_reason_code,
                reason_summary=state.decision_result.reason_summary,
                priority=ProcessCustomerMessage._resolve_escalation_priority(state),
                handoff_summary=ProcessCustomerMessage._build_handoff_summary(state),
                metadata={
                    "pipeline_stage": state.stage.value,
                    "intent": state.intent_result.intent.value if state.intent_result is not None else None,
                    "decision": state.decision_result.decision.value,
                },
            )
        )

        repositories.conversations.mark_escalated(conversation)

        return result.escalation_id

    # Validation
    @staticmethod
    def _normalize_customer_message(message: str) -> str:
        if not isinstance(message, str):
            raise CustomerMessageValidationError("customer_message must be a string")

        normalized = message.strip()
        if not normalized:
            raise CustomerMessageValidationError("customer_message cannot be empty")

        if len(normalized) > MAX_CUSTOMER_MESSAGE_LENGTH:
            raise CustomerMessageValidationError(f"customer_message exceeds {MAX_CUSTOMER_MESSAGE_LENGTH} characters")

        return normalized

    def _validate_conversation_status(self, status: str) -> None:
        if status not in self.PROCESSABLE_CONVERSATION_STATUSES:
            raise ConversationNotProcessableError(f"Conversation cannot accept customer messages while status={status!r}")

    # Misc helpers
    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        elapsed = perf_counter() - started_at
        return max(0, int(round(elapsed * 1000)))

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> _Repositories:
        """
        Validate the active UnitOfWork contract before beginning the request.

        In addition to repositories, AnswerService composition now requires access to the exact active SQLAlchemy Session.
        """
        if uow.session is None:
            raise PersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.conversations is None:
            raise PersistenceContractError("ConversationRepository unavailable")

        if uow.messages is None:
            raise PersistenceContractError("MessageRepository unavailable")
        
        if uow.escalations is None:
            raise PersistenceContractError("EscalationRepository unavailable")
        
        if uow.audit_events is None:
            raise PersistenceContractError("AuditEventRepository unavailable")

        if uow.ai_runs is None:
            raise PersistenceContractError("AIRunRepository unavailable")

        if uow.llm_calls is None:
            raise PersistenceContractError("LLMCallRepository unavailable")
        
        if uow.embedding_calls is None:
            raise PersistenceContractError("EmbeddingCallRepository unavailable")
        
        if uow.retrieval is None:
            raise PersistenceContractError("RetrievalRepository unavailable")
        
        if uow.reranker_calls is None:
            raise PersistenceContractError("RerankerCallRepository unavailable")
        
        if uow.stage_events is None:
            raise PersistenceContractError("AIStageEventRepository unavailable")

        if uow.intent_predictions is None:
            raise PersistenceContractError("IntentPredictionRepository unavailable")

        if uow.ai_decisions is None:
            raise PersistenceContractError("AIDecisionRepository unavailable")

        return _Repositories(
            conversations=uow.conversations,
            messages=uow.messages,
            escalations=uow.escalations,
            audit_events=uow.audit_events,
            ai_runs=uow.ai_runs,
            llm_calls=uow.llm_calls,
            embedding_calls=uow.embedding_calls,
            retrieval=uow.retrieval,
            reranker_calls=uow.reranker_calls,
            stage_events=uow.stage_events,
            intent_predictions=uow.intent_predictions,
            ai_decisions=uow.ai_decisions,
        )
        
    @staticmethod
    def _resolve_escalation_priority(state: AIState) -> str:
        """
        Assign a deterministic initial escalation priority.

        Priority is derived only from trusted reason codes. Arbitrary LLM metadata must never control support priority.
        """
        reason_code = state.escalation_reason_code

        if reason_code is None:
            raise PersistenceContractError("Cannot resolve escalation priority without a reason code")

        urgent_reasons = {"SECURITY_SENSITIVE_REQUEST", "SENSITIVE_ACTION_CLAIM", "SAFETY_RESTRICTION",}
        high_reasons = {"HUMAN_APPROVAL_REQUIRED", "POLICY_CONFLICT", "UNSUPPORTED_OPERATIONAL_CLAIM",}
        if reason_code in urgent_reasons:
            return "urgent"

        if reason_code in high_reasons:
            return "high"

        return "normal"


    @staticmethod
    def _build_handoff_summary(state: AIState) -> str:
        """
        Build a deterministic, bounded summary for a support agent.

        This is not generated by an additional LLM call. It contains only already-available structured pipeline information.
        """
        if state.escalation_source is None:
            raise PersistenceContractError("Cannot build handoff summary without escalation_source")

        if state.escalation_reason_code is None:
            raise PersistenceContractError("Cannot build handoff summary without escalation_reason_code")

        if state.decision_result is None:
            raise PersistenceContractError("Cannot build handoff summary without decision_result")

        intent = state.intent_result.intent.value if state.intent_result is not None else "unknown"

        return f"Human review requested by {state.escalation_source.value}. Intent: {intent}. Reason: {state.escalation_reason_code}. {state.decision_result.reason_summary}"