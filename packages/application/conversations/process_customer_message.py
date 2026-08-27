## Here no measure of individual LLM call
from __future__ import annotations
import uuid
from uuid6 import uuid7
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Final

# from packages.ai.orchestration.orchestrator import AIOrchestrator
from packages.ai.orchestration.state import AIState, PipelineStage
from packages.ai.telemetry.recorder import TelemetryRecorder
from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.message import MessageModel
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.database.repositories.ai.ai_run_repository import AIRunRepository
from packages.database.repositories.ai.decision_repository import AIDecisionRepository
from packages.database.repositories.ai.intent_prediction_repository import IntentPredictionRepository
from packages.database.repositories.ai.llm_call_repository import LLMCallRepository
from packages.database.repositories.support.conversation_repository import ConversationRepository
from packages.database.repositories.support.message_repository import MessageRepository
from packages.application.composition.ai_pipeline_factory import AIPipelineFactory, AITelemetryRepositories)


@dataclass(frozen=True, slots=True)
class _Repositories:
    conversations: ConversationRepository
    messages: MessageRepository

    ai_runs: AIRunRepository
    llm_calls: LLMCallRepository
    intent_predictions: IntentPredictionRepository
    ai_decisions: AIDecisionRepository


MAX_CUSTOMER_MESSAGE_LENGTH: Final[int] = 20_000


UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]


## Application exceptions ##
class ProcessCustomerMessageError(RuntimeError):
    """
    Base application-layer error for customer-message processing.
    """

class ConversationDoesNotExistError(ProcessCustomerMessageError):
    def __init__(self, conversation_id: uuid.UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation does not exist: {conversation_id}")

class ConversationNotProcessableError(ProcessCustomerMessageError):
    """
    Raised when the conversation exists but its current lifecycle state does not permit another customer message.
    """

class CustomerMessageValidationError(ProcessCustomerMessageError):
    pass

class PersistenceContractError(ProcessCustomerMessageError):
    """
    Indicates an internal application/UoW wiring problem rather than a customer-originated problem.
    """



## Command / result contracts ##
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
    """
    conversation_id: uuid.UUID
    customer_message_id: uuid.UUID
    ai_run_id: uuid.UUID
    trace_id: uuid.UUID
    pipeline_stage: PipelineStage
    intent: str | None
    decision: str | None
    succeeded: bool



## Application service ##
class ProcessCustomerMessage:
    """
    Application use case for processing one customer message.

    Transactional responsibilities:

        load conversation   ->   allocate sequence atomically   ->   persist customer message
                                                                                ↓
                                                                          create AI run 
                                                                                ↓
                                                                      execute AI orchestrator
                                                                                ↓
        commit <- finalize AI run <- persist decision evidence <- persist classification evidence

    The service does NOT:
        - classify intent itself
        - implement routing rules
        - invoke provider SDKs directly
        - calculate token usage
        - perform RAG
        - execute business actions
        - commit from individual repositories

    Per-provider call telemetry belongs in an instrumented LLMProvider
    decorator, which shares this UnitOfWork transaction.
    """

    PROCESSABLE_CONVERSATION_STATUSES: Final[frozenset[str]] = frozenset(
        {
            "open", "waiting_for_customer", "waiting_for_agent", "escalated"
        }
    )

    def __init__(self, *, uow_factory: UnitOfWorkFactory, pipeline_factory: AIPipelineFactory,) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if pipeline_factory is None:
            raise TypeError("pipeline_factory cannot be None")

        self._uow_factory = uow_factory
        self._pipeline_factory = pipeline_factory

    # Public API
    def execute(self, command: ProcessCustomerMessageCommand) -> ProcessCustomerMessageResult:
        """
        Process a customer message as one application transaction.

        Known AI pipeline failures are persisted as failed AI runs rather than converted into database rollbacks.

        Unexpected infrastructure/programming exceptions escape the method;
        the UnitOfWork then rolls the transaction back.
        """

        if not isinstance(command, ProcessCustomerMessageCommand):
            raise TypeError("command must be a ProcessCustomerMessageCommand")

        normalized_message = self._normalize_customer_message(command.customer_message)
        trace_id = command.trace_id if command.trace_id is not None else uuid7()

        with self._uow_factory() as uow:
            repositories = self._require_repositories(uow)
            conversation = repositories.conversations.get_by_id(command.conversation_id)
            if conversation is None:
                raise ConversationDoesNotExistError(command.conversation_id)

            self._validate_conversation_status(conversation.status)

            # Persist customer message
            sequence_number = repositories.conversations.allocate_message_sequence(command.conversation_id)

            customer_message = MessageModel(
                conversation_id=command.conversation_id,
                role="customer",
                content=normalized_message,
                sequence_number=sequence_number,
                metadata={},
            )

            repositories.messages.add(customer_message)

            # We need the DB-generated UUID before creating ai.runs.
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
            
            ## Current run gets its own: InstrumentedLLMProvider, TelemetryRecorder, IntentClassifier, AIOrchestrator
            pipeline = self._pipeline_factory.create(
                ai_run_id=ai_run.id,
                repositories=AITelemetryRepositories(
                    llm_calls=repositories.llm_calls,
                    intent_predictions=repositories.intent_predictions,
                    ai_decisions=repositories.ai_decisions,
                ),
            )

            started_perf = perf_counter()


            # Execute AI pipeline
            state = pipeline.orchestrator.process_message(
                ai_run_id=ai_run.id,
                trace_id=trace_id,
                conversation_id=command.conversation_id,
                trigger_message_id=customer_message.id,
                customer_message=normalized_message,
                conversation_context=None,
            )

            total_latency_ms = self._elapsed_ms(started_perf)
            self._persist_pipeline_artifacts(
                recorder=pipeline.telemetry_recorder,
                state=state, ai_run_id=ai_run.id,
                llm_call_id=pipeline.instrumented_provider.last_call_id
            )


            # Finalize AI run
            if state.stage is PipelineStage.FAILED:
                self._mark_run_failed(
                    repositories=repositories,
                    run=ai_run,
                    state=state,
                    total_latency_ms=total_latency_ms,
                )

            else:
                self._mark_run_completed(
                    repositories=repositories,
                    run=ai_run,
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
                intent=(
                    state.intent_result.intent.value
                    if state.intent_result is not None
                    else None
                ),
                decision=(
                    state.decision_result.decision.value
                    if state.decision_result is not None
                    else None
                ),
                succeeded=state.stage is not PipelineStage.FAILED,
            )


    # Persistence
    @staticmethod
    def _persist_pipeline_artifacts(*, recorder: TelemetryRecorder, state: AIState,
                                    ai_run_id: uuid.UUID, llm_call_id: uuid.UUID | None
    ) -> None:
        now = datetime.now(timezone.utc)

        if state.intent_result is not None:
            recorder.record_intent_prediction(
                ai_run_id=ai_run_id,
                result=state.intent_result,
                # Decision/classifier domain output is persisted separately
                # from provider-call telemetry.
                llm_call_id=llm_call_id,
                created_at=now,
            )

        if state.decision_result is not None:
            recorder.record_decision(
                ai_run_id=ai_run_id,
                result=state.decision_result,
                llm_call_id=None, ## DecisionEngine is deterministic and does not call an LLM.
                created_at=now,
            )

    @staticmethod
    def _mark_run_completed(*, repositories: _Repositories, run: AIRunModel, total_latency_ms: int) -> None:
        repositories.ai_runs.mark_completed(
            run,
            response_message_id=None,
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
        if uow.conversations is None:
            raise PersistenceContractError("ConversationRepository unavailable")

        if uow.messages is None:
            raise PersistenceContractError("MessageRepository unavailable")

        if uow.ai_runs is None:
            raise PersistenceContractError("AIRunRepository unavailable")

        if uow.llm_calls is None:
            raise PersistenceContractError("LLMCallRepository unavailable")

        if uow.intent_predictions is None:
            raise PersistenceContractError("IntentPredictionRepository unavailable")

        if uow.ai_decisions is None:
            raise PersistenceContractError("AIDecisionRepository unavailable")

        return _Repositories(
            conversations=uow.conversations,
            messages=uow.messages,
            ai_runs=uow.ai_runs,
            llm_calls=uow.llm_calls,
            intent_predictions=uow.intent_predictions,
            ai_decisions=uow.ai_decisions,
        )