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
from packages.application.composition.ai_pipeline_factory import AIPipelineFactory
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
from packages.database.repositories.ai.embedding_call_repository import EmbeddingCallRepository
from packages.knowledge.embeddings.provider.instrumented import EmbeddingCallContext, InstrumentedEmbeddingProvider
from packages.ai.telemetry.retrieval_recorder import RetrievalTelemetryRecorder
from packages.database.repositories.ai.retrieval_repository import RetrievalRepository
from packages.ai.telemetry.reranker_recorder import RerankerTelemetryRecorder
from packages.database.repositories.ai.reranker_call_repository import RerankerCallRepository
from packages.database.repositories.ai.stage_event_repository import AIStageEventRepository
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.application.conversations.query_conversations import ConversationQueryAccessDeniedError, ConversationRequesterDoesNotExistError
from packages.application.conversations.query_conversations import ConversationRequesterNotActiveError, ConversationRequesterRoleMismatchError
from packages.database.repositories.support.user_repository import UserRepository
from packages.application.composition.knowledge_application_factory import KnowledgeApplicationComponents
from packages.application.conversations.conversation_context import ConversationContextBuilder
from packages.ai.telemetry.llm_call_recorder import LLMCallTelemetryRecorder
from packages.ai.telemetry.stage_event_sink import DatabaseStageEventSink
from packages.ai.telemetry.embedding_recorder import EmbeddingTelemetryRecorder
from packages.knowledge.embeddings.provider.query_cache import QueryEmbeddingCache


# Internal repository bundle
@dataclass(frozen=True, slots=True)
class _Repositories:
    users: UserRepository
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
    
@dataclass(frozen=True, slots=True)
class _AcceptedMessageWork:
    """
    Immutable data crossing the acceptance transaction boundary.

    No SQLAlchemy entity may be stored here because the acceptance session is closed before provider execution begins.
    """
    conversation_id: uuid.UUID
    customer_message_id: uuid.UUID
    ai_run_id: uuid.UUID
    trace_id: uuid.UUID
    customer_message: str
    conversation_context: str | None

MAX_CUSTOMER_MESSAGE_LENGTH: Final[int] = 20_000
UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

_ESCALATION_REASON_SUMMARIES: Final[dict[str, str]] = {
    "security_sensitive_request": "The customer reported a privacy or security-sensitive issue that requires human review.",
    "operational_lookup_unavailable": "The request requires access to operational business data that is not available to the automated support workflow.",
    "knowledge_unavailable": "The published support knowledge did not contain enough verified information to answer the request reliably.",
    "human_approval_required": "The requested operation requires approval from an authorized human support agent.",
    "customer_requested_human": "The customer explicitly requested assistance from a human support agent.",
    "severe_customer_dissatisfaction": "The conversation requires human review because severe customer dissatisfaction was detected.",
    "policy_conflict": "The available support policies produced a conflict that requires human interpretation.",
    "sensitive_action_claim": "The proposed response contained an unsupported claim about a sensitive business action.",
    "safety_restriction": "The automated workflow encountered a safety restriction that requires human review.",
    "unsupported_operational_claim": "The proposed response relied on an unsupported operational claim that requires human verification.",
    "missing_generated_response": "The automated workflow could not produce a safe customer response.",
    "decision_response_mismatch": "The proposed response did not match the approved support workflow.",
}

_DEFAULT_ESCALATION_REASON_SUMMARY: Final[str] = "The automated support workflow requested human review."

# Application exceptions
class ProcessCustomerMessageError(RuntimeError):
    """Base application-layer error for customer-message processing."""

class ConversationDoesNotExistError(ProcessCustomerMessageError):
    def __init__(self, conversation_id: uuid.UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation does not exist: {conversation_id}")

class CustomerMessagePipelineFailedError(ProcessCustomerMessageError):
    def __init__(self, *, failure_code: str) -> None:
        self.failure_code = failure_code
        super().__init__("The AI support pipeline could not complete.")

class CustomerMessagePipelineTimeoutError(CustomerMessagePipelineFailedError):
    pass

class CustomerMessagePipelineUnavailableError(CustomerMessagePipelineFailedError):
    pass

class ConversationNotProcessableError(ProcessCustomerMessageError):
    """Raised when the conversation exists but its current lifecycle state does not permit another customer message."""

class CustomerMessageValidationError(ProcessCustomerMessageError):
    pass

class PersistenceContractError(ProcessCustomerMessageError):
    """Indicates an internal application/UoW wiring problem rather than a customer-originated problem."""

# Command / result contracts
@dataclass(frozen=True, slots=True)
class ProcessCustomerMessageCommand:
    conversation_id: uuid.UUID
    customer_message: str
    principal: AuthenticatedPrincipal
    trace_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, uuid.UUID):
            raise TypeError("conversation_id must be UUID")

        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if self.trace_id is not None and not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be UUID or None")

        if not isinstance(self.customer_message, str):
            raise TypeError("customer_message must be a string")

@dataclass(frozen=True, slots=True)
class ProcessAcceptedCustomerMessageCommand:
    """
    Process a customer message that was committed by an earlier acceptance transaction.

    This command never creates or modifies the triggering customer message.
    """
    conversation_id: uuid.UUID
    customer_message_id: uuid.UUID
    principal: AuthenticatedPrincipal
    trace_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, uuid.UUID):
            raise TypeError("conversation_id must be UUID")

        if not isinstance(self.customer_message_id, uuid.UUID):
            raise TypeError("customer_message_id must be UUID")

        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if self.trace_id is not None and not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be UUID or None")

@dataclass(frozen=True, slots=True)
class ProcessCustomerMessageResult:
    """
    Application result returned after the transaction is committed.

    IDs are returned instead of live ORM objects so callers do not receive entities bound to a Session that has already been closed.

    ``assistant_message_id`` and ``response`` are populated whenever the pipeline produced safe customer-visible text.

    For an approved answer, ``response`` contains the guardrail-approved generated response.

    For an escalation, ``response`` contains only an application-controlled customer notice.
    It never exposes the generated candidate that caused a guardrail or knowledge-gap escalation.

    ``escalation_id`` is populated when human review was requested.
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
    failure_code: str | None
    failure_retryable: bool | None
    
    def __post_init__(self) -> None:
        if self.succeeded:
            if self.failure_code is not None:
                raise ValueError("Successful results cannot contain failure_code.")

            if self.failure_retryable is not None:
                raise ValueError("Successful results cannot contain failure_retryable.")

            if self.pipeline_stage is PipelineStage.GUARDRAILS_COMPLETED:
                if self.assistant_message_id is None or self.response is None:
                    raise ValueError("Approved response results require assistant_message_id and response.")

                if self.escalation_id is not None:
                    raise ValueError("Approved response results cannot contain escalation_id.")

            elif self.pipeline_stage is PipelineStage.ESCALATED:
                if self.escalation_id is None:
                    raise ValueError("Escalated results require escalation_id.")

                if self.assistant_message_id is None:
                    raise ValueError("Escalated results require a persisted customer notice.")

                if self.response is None:
                    raise ValueError("Escalated results require customer-visible text.")

                if not self.response.strip():
                    raise ValueError("Escalated customer-visible text cannot be blank.")

            else:
                raise ValueError("Successful results require an approved response or escalation terminal stage.")

        else:
            if self.pipeline_stage is not PipelineStage.FAILED:
                raise ValueError("Unsuccessful results must have FAILED stage.")

            if self.failure_code is None:
                raise ValueError("Unsuccessful results require failure_code.")

            if self.failure_retryable is None:
                raise ValueError("Unsuccessful results require failure_retryable.")

            if self.assistant_message_id is not None or self.response is not None:
                raise ValueError("Failed results cannot expose an assistant response.")

            if self.escalation_id is not None:
                raise ValueError("Failed results cannot contain escalation_id.")

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
    
    CUSTOMER_RESPONSE_STAGES: Final[frozenset[PipelineStage]] = frozenset({PipelineStage.GUARDRAILS_COMPLETED, PipelineStage.ESCALATED,})
    SUCCESSFUL_TERMINAL_STAGES: Final[frozenset[PipelineStage]] = frozenset({PipelineStage.GUARDRAILS_COMPLETED, PipelineStage.ESCALATED,})
    TERMINAL_STAGES: Final[frozenset[PipelineStage]] = frozenset({*SUCCESSFUL_TERMINAL_STAGES, PipelineStage.FAILED,})

    def __init__(self, *, uow_factory: UnitOfWorkFactory, pipeline_factory: AIPipelineFactory, embedding_provider: EmbeddingProvider,
                 embedding_input_descriptor: EmbeddingInputDescriptor, retrieval_profile: RetrievalProfile,
                 grounding_context_budget: GroundingContextBudget, knowledge_application: KnowledgeApplicationComponents, 
                 conversation_context_builder: ConversationContextBuilder | None = None, query_embedding_cache: QueryEmbeddingCache | None = None
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
        
        if not isinstance(knowledge_application, KnowledgeApplicationComponents):
            raise TypeError("knowledge_application must be a KnowledgeApplicationComponents instance.")
        
        if conversation_context_builder is not None and not isinstance(conversation_context_builder, ConversationContextBuilder):
            raise TypeError("conversation_context_builder must be a ConversationContextBuilder instance or None")
        
        if query_embedding_cache is not None and not isinstance(query_embedding_cache, QueryEmbeddingCache):
            raise TypeError("query_embedding_cache must be a QueryEmbeddingCache instance or None")

        self._uow_factory = uow_factory
        self._pipeline_factory = pipeline_factory
        self._embedding_provider = embedding_provider
        self._embedding_input_descriptor = embedding_input_descriptor
        self._retrieval_profile = retrieval_profile
        self._grounding_context_budget = grounding_context_budget
        self._knowledge_application = knowledge_application
        self._query_embedding_cache = query_embedding_cache
        self._conversation_context_builder = conversation_context_builder if conversation_context_builder is not None else ConversationContextBuilder()

    # Public API
    def execute(self, command: ProcessCustomerMessageCommand) -> ProcessCustomerMessageResult:
        """
        Persist and process one new customer message.

        Existing callers retain their previous behavior. The shared private method performs the actual processing.
        """
        if not isinstance(command, ProcessCustomerMessageCommand):
            raise TypeError("command must be a ProcessCustomerMessageCommand")

        normalized_message = self._normalize_customer_message(command.customer_message)
        trace_id = command.trace_id if command.trace_id is not None else uuid7()

        return self._execute_message(
            conversation_id=command.conversation_id,
            principal=command.principal,
            trace_id=trace_id,
            new_customer_message=normalized_message,
            accepted_customer_message_id=None,
        )
    
    def execute_accepted(self, command: ProcessAcceptedCustomerMessageCommand) -> ProcessCustomerMessageResult:
        """
        Process an already-committed customer message.

        The message is loaded and validated, but never inserted again.
        """
        if not isinstance(command, ProcessAcceptedCustomerMessageCommand):
            raise TypeError("command must be a ProcessAcceptedCustomerMessageCommand")

        trace_id = command.trace_id if command.trace_id is not None else uuid7()

        return self._execute_message(
            conversation_id=command.conversation_id,
            principal=command.principal,
            trace_id=trace_id,
            new_customer_message=None,
            accepted_customer_message_id=command.customer_message_id,
        )
    
    def _execute_message(self, *, conversation_id: uuid.UUID, principal: AuthenticatedPrincipal, trace_id: uuid.UUID,
                         new_customer_message: str | None, accepted_customer_message_id: uuid.UUID | None
    ) -> ProcessCustomerMessageResult:
        if (
            new_customer_message is None
        ) == (
            accepted_customer_message_id is None
        ):
            raise PersistenceContractError("Exactly one customer-message source must be provided")

        accepted_work = self._accept_message_and_start_run(
            conversation_id=conversation_id,
            principal=principal,
            trace_id=trace_id,
            new_customer_message=new_customer_message,
            accepted_customer_message_id=accepted_customer_message_id,
        )

        try:
            return self._execute_committed_work(accepted_work)

        except Exception:
            self._mark_aborted_run_failed(ai_run_id=accepted_work.ai_run_id)
            raise
    
    def _accept_message_and_start_run(self, *, conversation_id: uuid.UUID, principal: AuthenticatedPrincipal, trace_id: uuid.UUID,
                                      new_customer_message: str | None, accepted_customer_message_id: uuid.UUID | None
    ) -> _AcceptedMessageWork:
        """
        Accept the trigger message and create its AI run.

        This transaction commits before any LLM, embedding, or reranker provider can be invoked.
        """
        with self._uow_factory() as uow:
            repositories = self._require_repositories(uow)
            self._validate_requester(principal=principal, repositories=repositories)
            conversation = repositories.conversations.get_by_id(conversation_id)
            if conversation is None:
                raise ConversationDoesNotExistError(conversation_id)

            self._validate_conversation_ownership(conversation=conversation, principal=principal)
            self._validate_conversation_status(conversation.status)
            if accepted_customer_message_id is None:
                if new_customer_message is None:
                    raise PersistenceContractError("New customer message is unavailable")

                prior_messages = repositories.messages.get_recent_by_conversation(conversation_id, limit=self._conversation_context_builder.max_messages)
                sequence_number = repositories.conversations.allocate_message_sequence(conversation_id)
                customer_message = MessageModel(
                    conversation_id=conversation_id,
                    role="customer",
                    content=new_customer_message,
                    sequence_number=sequence_number,
                    metadata_={},
                )

                repositories.messages.add(customer_message)
                repositories.messages.flush()

                if customer_message.id is None:
                    raise PersistenceContractError("Customer message ID was not generated after flush")

                normalized_message = new_customer_message

            else:
                customer_message = repositories.messages.get_by_id(accepted_customer_message_id)
                if customer_message is None:
                    raise PersistenceContractError("Accepted customer message does not exist")

                self._validate_accepted_customer_message(message=customer_message, conversation_id=conversation_id)
                normalized_message = self._normalize_customer_message(customer_message.content)
                if normalized_message != customer_message.content:
                    raise PersistenceContractError("Accepted customer message was not stored in normalized form")

                prior_messages = repositories.messages.get_recent_before_sequence(
                    conversation_id,
                    before_sequence_number=customer_message.sequence_number,
                    limit=self._conversation_context_builder.max_messages,
                )

            customer_message_id = customer_message.id
            if customer_message_id is None:
                raise PersistenceContractError("Customer message has no identifier")

            conversation_context = self._conversation_context_builder.build(messages=prior_messages)
            ai_run = AIRunModel(
                trace_id=trace_id,
                conversation_id=conversation_id,
                trigger_message_id=customer_message_id,
                pipeline_version=self._pipeline_factory.pipeline_version,
                status="running",
            )

            repositories.ai_runs.add(ai_run)
            repositories.ai_runs.flush()
            ai_run_id = ai_run.id
            if ai_run_id is None:
                raise PersistenceContractError("AI run ID was not generated after flush")

            # This commit is deliberately before provider execution.
            uow.commit()

        return _AcceptedMessageWork(
            conversation_id=conversation_id,
            customer_message_id=customer_message_id,
            ai_run_id=ai_run_id,
            trace_id=trace_id,
            customer_message=normalized_message,
            conversation_context=conversation_context,
        )
        
    def _execute_committed_work(self, work: _AcceptedMessageWork) -> ProcessCustomerMessageResult:
        """
        Execute orchestration without holding a business transaction.

        Provider telemetry and retrieval SQL use their own short-lived UoWs.
        Final business persistence begins only after orchestration returns.
        """
        llm_call_recorder = LLMCallTelemetryRecorder(uow_factory=self._uow_factory)
        retrieval_recorder = RetrievalTelemetryRecorder(
            uow_factory=self._uow_factory,
            ai_run_id=work.ai_run_id,
            trace_id=work.trace_id,
            conversation_id=work.conversation_id,
            profile=self._retrieval_profile,
        )
        reranker_recorder = RerankerTelemetryRecorder(
            uow_factory=self._uow_factory,
            retrieval_run_id=lambda: (retrieval_recorder.retrieval_run_id),
            trace_id=work.trace_id,
            metadata={
                "workflow": "customer_support_retrieval",
                "conversation_id": str(work.conversation_id),
                "ai_run_id": str(work.ai_run_id),
            },
        )
        embedding_recorder = EmbeddingTelemetryRecorder(uow_factory=self._uow_factory)
        instrumented_embedding_provider = InstrumentedEmbeddingProvider(
            provider=self._embedding_provider,
            recorder=embedding_recorder,
            context=EmbeddingCallContext(
                purpose="query",
                ai_run_id=work.ai_run_id,
                trace_id=work.trace_id,
                metadata={
                    "workflow": "customer_support_retrieval",
                    "conversation_id": str(work.conversation_id),
                },
            ),
            query_cache=self._query_embedding_cache,
        )

        def build_answer_service(response_generator: GroundedResponseGenerator) -> AnswerService:
            components = create_answer_service_components(
                retrieval_uow_factory=self._uow_factory,
                profile=self._retrieval_profile,
                default_context_budget=self._grounding_context_budget,
                response_generator=response_generator,
                embedding_provider=instrumented_embedding_provider,
                embedding_input_descriptor=self._embedding_input_descriptor,
                knowledge_application=self._knowledge_application,
                retrieval_telemetry_recorder=retrieval_recorder,
                reranker_telemetry_recorder=reranker_recorder,
            )

            return components.answer_service

        pipeline = self._pipeline_factory.create(
            ai_run_id=work.ai_run_id,
            llm_call_recorder=llm_call_recorder,
            answer_service_builder=build_answer_service,
            stage_event_sink=DatabaseStageEventSink(uow_factory=self._uow_factory),
        )

        started_perf = perf_counter()
        state = pipeline.orchestrator.process_message(
            ai_run_id=work.ai_run_id,
            trace_id=work.trace_id,
            conversation_id=work.conversation_id,
            trigger_message_id=work.customer_message_id,
            customer_message=work.customer_message,
            conversation_context=work.conversation_context,
        )
        total_latency_ms = self._elapsed_ms(started_perf)
        self._validate_terminal_state(state)

        return self._finalize_committed_work(
            work=work,
            state=state,
            total_latency_ms=total_latency_ms,
            intent_llm_call_id=pipeline.intent_provider.last_call_id,
        )
        
    def _finalize_committed_work(self, *, work: _AcceptedMessageWork, state: AIState, total_latency_ms: int, intent_llm_call_id: uuid.UUID | None) -> ProcessCustomerMessageResult:
        """
        Atomically persist the terminal business result.

        Provider execution has already finished before this transaction starts.
        """
        with self._uow_factory() as uow:
            repositories = self._require_repositories(uow)
            conversation = repositories.conversations.get_by_id(work.conversation_id)
            if conversation is None:
                raise PersistenceContractError("Accepted conversation disappeared before finalization")

            customer_message = repositories.messages.get_by_id(work.customer_message_id)
            if customer_message is None:
                raise PersistenceContractError("Accepted customer message disappeared before finalization")

            self._validate_accepted_customer_message(message=customer_message, conversation_id=work.conversation_id)
            ai_run = repositories.ai_runs.get_by_id(work.ai_run_id)
            if ai_run is None:
                raise PersistenceContractError("Accepted AI run disappeared before finalization")

            if ai_run.status != "running":
                raise PersistenceContractError("Accepted AI run is no longer running")

            if ai_run.conversation_id != work.conversation_id:
                raise PersistenceContractError("AI run conversation does not match accepted work")

            if ai_run.trigger_message_id != work.customer_message_id:
                raise PersistenceContractError("AI run trigger does not match accepted message")

            outcome_recorder = TelemetryRecorder(
                intent_predictions=repositories.intent_predictions,
                ai_decisions=repositories.ai_decisions,
            )
            self._persist_pipeline_artifacts(
                recorder=outcome_recorder,
                state=state,
                ai_run_id=work.ai_run_id,
                intent_llm_call_id=intent_llm_call_id,
            )
            escalation_id: uuid.UUID | None = None
            if state.stage is PipelineStage.ESCALATED:
                escalation_id = self._persist_escalation(repositories=repositories, conversation=conversation, state=state, trace_id=work.trace_id)

            assistant_message: MessageModel | None = None
            if state.stage in self.CUSTOMER_RESPONSE_STAGES:
                assistant_message = self._persist_assistant_response(repositories=repositories, conversation_id=work.conversation_id, state=state)

            assistant_message_id = assistant_message.id if assistant_message is not None else None
            response = assistant_message.content if assistant_message is not None else None
            if state.stage is PipelineStage.FAILED:
                self._mark_run_failed(repositories=repositories, run=ai_run, state=state, total_latency_ms=total_latency_ms)
                
            else:
                self._mark_run_completed(repositories=repositories, run=ai_run, response_message_id=assistant_message_id, total_latency_ms=total_latency_ms)

            final_error = state.errors[-1] if state.stage is PipelineStage.FAILED else None
            uow.commit()

        return ProcessCustomerMessageResult(
            conversation_id=work.conversation_id,
            customer_message_id=work.customer_message_id,
            ai_run_id=work.ai_run_id,
            trace_id=work.trace_id,
            pipeline_stage=state.stage,
            intent=state.intent_result.intent.value if state.intent_result is not None else None,
            decision=state.decision_result.decision.value if state.decision_result is not None else None,
            assistant_message_id=assistant_message_id,
            escalation_id=escalation_id,
            response=response,
            succeeded=state.stage in self.SUCCESSFUL_TERMINAL_STAGES,
            failure_code=final_error.code if final_error is not None else None,
            failure_retryable=final_error.retryable if final_error is not None else None,
        )
    
    def _mark_aborted_run_failed(self, *, ai_run_id: uuid.UUID) -> None:
        """
        Best-effort recovery for an unexpected exception escaping orchestration.

        The original exception remains authoritative and is re-raised by the caller. This method prevents an already
        committed AI run from remaining permanently marked as running whenever persistence is available.
        """
        try:
            with self._uow_factory() as uow:
                repositories = self._require_repositories(uow)
                run = repositories.ai_runs.get_by_id(ai_run_id)
                if run is None or run.status != "running":
                    return

                repositories.ai_runs.mark_failed(
                    run,
                    completed_at=datetime.now(timezone.utc),
                    total_latency_ms=0,
                    error_code="PIPELINE_EXECUTION_ABORTED",
                    error_message="The AI pipeline terminated before normal finalization.",
                )
                uow.commit()

        except Exception:
            # Never replace the original pipeline exception with a secondary recovery-persistence exception.
            return

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

        A completed run without a response message is valid only for an explicitly persisted escalation disposition.
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
        Persist safe customer-visible pipeline text.

        GUARDRAILS_COMPLETED
            Persists the approved generated response.

        ESCALATED
            Persists only the application-controlled customer notice.
            Any generated candidate retained in orchestration state remains internal and is never selected here.

        The stored metadata contains only low-cardinality, application-controlled values.
        """
        if state.stage is PipelineStage.GUARDRAILS_COMPLETED:
            response = state.generated_response
            message_kind = "assistant_response"
            feedback_eligible = True

            if response is None:
                raise PersistenceContractError("GUARDRAILS_COMPLETED state must contain a generated response")

        elif state.stage is PipelineStage.ESCALATED:
            response = state.customer_notice
            message_kind = "escalation_notice"
            feedback_eligible = False
            if response is None:
                raise PersistenceContractError("ESCALATED state must contain a customer notice")

        else:
            raise PersistenceContractError(
                "Customer-visible pipeline text may only be persisted from GUARDRAILS_COMPLETED or ESCALATED state"
            )

        normalized_response = " ".join(response.split())
        if not normalized_response:
            raise PersistenceContractError("Customer-visible pipeline text cannot be blank")

        sequence_number = repositories.conversations.allocate_message_sequence(conversation_id)
        assistant_message = MessageModel(
            conversation_id=conversation_id,
            role="assistant",
            content=normalized_response,
            sequence_number=sequence_number,
            metadata_={
                "message_kind": message_kind,
                "feedback_eligible": feedback_eligible,
            },
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
                reason_summary=ProcessCustomerMessage._resolve_escalation_reason_summary(state),
                priority=ProcessCustomerMessage._resolve_escalation_priority(state),
                handoff_summary=ProcessCustomerMessage._build_handoff_summary(state),
                metadata=ProcessCustomerMessage._build_escalation_metadata(state),
            )
        )

        repositories.conversations.mark_escalated(conversation)

        return result.escalation_id

    # Validation
    @classmethod
    def _validate_terminal_state(cls, state: AIState) -> None:
        if not isinstance(state, AIState):
            raise PersistenceContractError("Orchestrator returned an invalid state object")

        if state.stage not in cls.TERMINAL_STAGES:
            raise PersistenceContractError(f"Orchestrator returned a non-terminal pipeline state: {state.stage.value}")
        
        if state.stage is PipelineStage.ESCALATED:
            if state.customer_notice is None:
                raise PersistenceContractError("ESCALATED state must contain a customer notice")

            if state.escalation_source is None:
                raise PersistenceContractError("ESCALATED state must contain escalation source")

            if state.escalation_reason_code is None:
                raise PersistenceContractError("ESCALATED state must contain escalation reason")

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
    
    @staticmethod
    def _validate_requester(*, principal: AuthenticatedPrincipal, repositories: _Repositories) -> None:
        if principal.role is not AuthRole.CUSTOMER:
            raise ConversationQueryAccessDeniedError("Only customers may submit customer messages")

        requester = repositories.users.get_by_id(principal.user_id)
        if requester is None:
            raise ConversationRequesterDoesNotExistError(principal.user_id)

        if requester.status != "active":
            raise ConversationRequesterNotActiveError("Customer submitting the message is not active")

        if requester.role != principal.role.value:
            raise ConversationRequesterRoleMismatchError("Authenticated role does not match persisted role")

    @staticmethod
    def _validate_conversation_ownership(*, conversation: ConversationModel, principal: AuthenticatedPrincipal) -> None:
        if conversation.user_id != principal.user_id:
            # Deliberately conceal another customer's conversation.
            raise ConversationDoesNotExistError(conversation.id)

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
        
        if uow.users is None:
            raise PersistenceContractError("UserRepository unavailable")

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
            users=uow.users,
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
    def _build_escalation_metadata(state: AIState) -> dict[str, object]:
        """
        Build allowlisted low-cardinality escalation metadata.

        Customer messages, generated responses, conversation context, evidence, prompts, provider errors, 
        and unrestricted AI metadata are deliberately excluded.
        """
        if state.stage is not PipelineStage.ESCALATED:
            raise PersistenceContractError("Escalation metadata requires ESCALATED state")

        if state.escalation_source is None:
            raise PersistenceContractError("Escalation metadata requires escalation_source")

        if state.escalation_reason_code is None:
            raise PersistenceContractError("Escalation metadata requires escalation_reason_code")

        if state.decision_result is None:
            raise PersistenceContractError("Escalation metadata requires decision_result")

        metadata: dict[str, object] = {
            "pipeline_stage": state.stage.value,
            "intent": state.intent_result.intent.value if state.intent_result is not None else None,
            "decision": state.decision_result.decision.value,
            "decision_reason_code": state.decision_result.reason_code.value,
            "escalation_source": state.escalation_source.value,
            "escalation_reason_code": state.escalation_reason_code,
        }

        if state.guardrail_disposition is not None:
            metadata["guardrail_outcome"] = state.guardrail_disposition.value
            metadata["guardrail_reason_code"] = state.guardrail_reason_code
            if state.guardrail_policy_id is not None:
                metadata["guardrail_policy_id"] = state.guardrail_policy_id

        return metadata

    @staticmethod
    def _resolve_escalation_reason_summary(state: AIState) -> str:
        """
        Return an application-controlled explanation for the final escalation.

        The original decision reason may describe an earlier workflow step and can become inaccurate when retrieval or guardrails
        later redirect the run to escalation. This resolver therefore uses the final structured escalation reason code.

        Unknown future reason codes receive a safe generic summary.
        """
        reason_code = state.escalation_reason_code
        if reason_code is None:
            raise PersistenceContractError("Cannot resolve escalation summary without a reason code")

        return _ESCALATION_REASON_SUMMARIES.get(reason_code, _DEFAULT_ESCALATION_REASON_SUMMARY)
        
    @staticmethod
    def _resolve_escalation_priority(state: AIState) -> str:
        """
        Assign a deterministic initial escalation priority.

        Priority is derived only from trusted structured reason codes.
        Customer content, generated text, arbitrary metadata, and provider output must never control escalation priority.
        """
        reason_code = state.escalation_reason_code
        if reason_code is None:
            raise PersistenceContractError("Cannot resolve escalation priority without a reason code")

        urgent_reasons = {"security_sensitive_request", "sensitive_action_claim", "safety_restriction",}
        high_reasons = {"human_approval_required", "policy_conflict", "unsupported_operational_claim", "severe_customer_dissatisfaction",}
        
        if reason_code in urgent_reasons:
            return "urgent"

        if reason_code in high_reasons:
            return "high"

        return "normal"


    @staticmethod
    def _build_handoff_summary(state: AIState) -> str:
        """
        Build a deterministic and bounded human-support handoff summary.

        The summary contains only controlled structured workflow values and an allowlisted explanation.
        It does not include the customer message, generated response, provider error, prompt, or unrestricted metadata.
        """
        if state.escalation_source is None:
            raise PersistenceContractError("Cannot build handoff summary without escalation_source")

        if state.escalation_reason_code is None:
            raise PersistenceContractError("Cannot build handoff summary without escalation_reason_code")

        if state.decision_result is None:
            raise PersistenceContractError("Cannot build handoff summary without decision_result")

        intent = state.intent_result.intent.value if state.intent_result is not None else "unknown"
        reason_summary = ProcessCustomerMessage._resolve_escalation_reason_summary(state)

        return f"Human review requested by {state.escalation_source.value}. Intent: {intent}. Reason: {state.escalation_reason_code}. {reason_summary}"
    
    @staticmethod
    def _validate_accepted_customer_message(*, message: MessageModel, conversation_id: uuid.UUID) -> None:
        if message.conversation_id != conversation_id:
            raise PersistenceContractError("Accepted customer message does not belong to the target conversation")

        if message.role != "customer":
            raise PersistenceContractError("Accepted trigger message must have the customer role")

        if isinstance(message.sequence_number, bool) or not isinstance(message.sequence_number, int) or message.sequence_number <= 0:
            raise PersistenceContractError("Accepted customer message has an invalid sequence number")