# AI-customer-support-agent\packages\application\conversations\start_conversation.py
from __future__ import annotations
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid6 import uuid7
import logging

from packages.ai.orchestration.state import PipelineStage
from packages.application.auth.models import AuthenticatedPrincipal
from packages.application.conversations.accept_conversation_start import AcceptConversationStart, AcceptConversationStartCommand
from packages.application.conversations.process_customer_message import ProcessAcceptedCustomerMessageCommand, ProcessCustomerMessage, ProcessCustomerMessageResult
from packages.application.conversations.start_conversation_errors import ConversationStartLeaseLostError, ConversationStartPersistenceContractError
from packages.application.conversations.start_conversation_errors import ConversationStartProcessingInProgressError, ConversationStartReplayUnavailableError
from packages.database.models.support.conversation_start_request import ConversationStartRequestModel
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.application.conversations.assign_conversation_title import AssignConversationTitle, AssignConversationTitleCommand

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
logger = logging.getLogger(__name__)

@dataclass(frozen=True, slots=True)
class StartConversationCommand:
    principal: AuthenticatedPrincipal
    idempotency_key: str
    customer_message: str
    trace_id: uuid.UUID
    channel: str = "web"
    title: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if not isinstance(self.idempotency_key, str):
            raise TypeError("idempotency_key must be a string")

        if not isinstance(self.customer_message, str):
            raise TypeError("customer_message must be a string")

        if not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID")

        if not isinstance(self.channel, str):
            raise TypeError("channel must be a string")

        if self.title is not None and not isinstance(self.title, str):
            raise TypeError("title must be a string or None")

@dataclass(frozen=True, slots=True)
class StartConversationResult:
    request_id: uuid.UUID
    status: str
    created: bool
    replayed: bool
    message_result: ProcessCustomerMessageResult

    def __post_init__(self) -> None:
        expected_status = "completed" if self.message_result.succeeded else "failed"
        if self.status != expected_status:
            raise ValueError("status does not match the message result")

class StartConversation:
    """
    Start a conversation from its first customer message.

    Transaction boundaries:

    1. AcceptConversationStart atomically commits the conversation, first message and idempotency record.
    2. A separate short transaction acquires a processing lease.
    3. ProcessCustomerMessage processes the already-persisted message.
    4. A short transaction stores the sanitized terminal replay snapshot.
    5. Best-effort title generation runs outside a business transaction and conditionally persists through a final short transaction.

    Clicking "New conversation" in the frontend does not invoke this use case. It is invoked only when the first valid message is submitted.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, accept_conversation_start: AcceptConversationStart, 
                 process_customer_message: ProcessCustomerMessage, assign_conversation_title: AssignConversationTitle,
                 processing_lease_duration: timedelta = timedelta(minutes=2),
    ) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if not isinstance(accept_conversation_start, AcceptConversationStart):
            raise TypeError("accept_conversation_start must be an AcceptConversationStart instance")

        if not isinstance(process_customer_message, ProcessCustomerMessage):
            raise TypeError("process_customer_message must be a ProcessCustomerMessage instance")
        
        if not isinstance(assign_conversation_title, AssignConversationTitle):
            raise TypeError("assign_conversation_title must be an AssignConversationTitle instance")

        if not isinstance(processing_lease_duration, timedelta):
            raise TypeError("processing_lease_duration must be a timedelta")

        if processing_lease_duration <= timedelta(0):
            raise ValueError("processing_lease_duration must be positive")

        self._uow_factory = uow_factory
        self._accept_conversation_start = accept_conversation_start
        self._process_customer_message = process_customer_message
        self._assign_conversation_title = assign_conversation_title
        self._processing_lease_duration = processing_lease_duration

    def execute(self, command: StartConversationCommand) -> StartConversationResult:
        if not isinstance(command, StartConversationCommand):
            raise TypeError("command must be a StartConversationCommand")

        accepted = self._accept_conversation_start.execute(
            AcceptConversationStartCommand(
                principal=command.principal,
                idempotency_key=command.idempotency_key,
                customer_message=command.customer_message,
                trace_id=command.trace_id,
                channel=command.channel,
                title=command.title,
            )
        )
        existing_terminal = self._load_terminal_result(request_id=accepted.request_id)
        if existing_terminal is not None:
            existing_message_result = existing_terminal[1]

            # A previous request may have durably completed message processing while the non-critical title attempt failed.
            # Retry title assignment only if the title remains absent.
            self._assign_title_safely(command=command, message_result=existing_message_result)
            return StartConversationResult(
                request_id=accepted.request_id,
                status=existing_terminal[0],
                created=False,
                replayed=True,
                message_result=existing_message_result,
            )

        processing_token = uuid7()
        acquired_at = datetime.now(timezone.utc)
        processing_expires_at = acquired_at + self._processing_lease_duration
        acquired = self._acquire_processing_lease(
            request_id=accepted.request_id,
            processing_token=processing_token,
            acquired_at=acquired_at,
            processing_expires_at=processing_expires_at,
        )

        if acquired is None:
            return self._resolve_unavailable_lease(
                request_id=accepted.request_id,
                fallback_conversation_id=accepted.conversation_id,
                measured_at=datetime.now(timezone.utc),
            )

        # No acceptance transaction or lease-acquisition transaction is open while this processing service runs.
        message_result = (
            self._process_customer_message.execute_accepted(
                ProcessAcceptedCustomerMessageCommand(
                    conversation_id=accepted.conversation_id,
                    customer_message_id=accepted.customer_message_id,
                    principal=command.principal,
                    trace_id=command.trace_id,
                )
            )
        )
        terminal_status = "completed" if message_result.succeeded else "failed"
        response_snapshot = _serialize_message_result(message_result)
        self._persist_terminal_result(
            request_id=accepted.request_id,
            processing_token=processing_token,
            terminal_status=terminal_status,
            message_result=message_result,
            response_snapshot=response_snapshot,
        )

        # Message acceptance, AI processing, and the terminal replay snapshot are already durable.
        # Conversation naming is intentionally best-effort and cannot change the customer-message outcome.
        self._assign_title_safely(command=command, message_result=message_result)
        
        return StartConversationResult(
            request_id=accepted.request_id,
            status=terminal_status,
            created=accepted.created,
            replayed=False,
            message_result=message_result,
        )

    def _assign_title_safely(self, *, command: StartConversationCommand, message_result: ProcessCustomerMessageResult) -> None:
        """
        Attempt non-critical conversation naming.

        This method must run only after the accepted message and terminal processing result are durable.
        Any title-subsystem failure is isolated from the customer-visible message result.

        No customer message, provider response, prompt, or exception message is written to logs.
        """
        try:
            self._assign_conversation_title.execute(
                AssignConversationTitleCommand(
                    conversation_id=message_result.conversation_id,
                    ai_run_id=message_result.ai_run_id,
                    first_customer_message=command.customer_message,
                    principal=command.principal,
                    trace_id=command.trace_id,
                    intent=message_result.intent,
                )
            )
        except Exception as exc:
            # Naming is an optional enrichment. Its failure must never turn a successfully accepted or processed customer message into
            # an API failure. Avoid logger.exception(), which may expose raw provider or database exception text through traceback formatting.
            logger.warning(
                "conversation_title_assignment_failed",
                extra={
                    "conversation_id": str(message_result.conversation_id),
                    "ai_run_id": str(message_result.ai_run_id),
                    "trace_id": str(command.trace_id),
                    "exception_type": type(exc).__name__,
                },
            )

    def _acquire_processing_lease(self, *, request_id: uuid.UUID, processing_token: uuid.UUID, acquired_at: datetime, 
                                  processing_expires_at: datetime
    ) -> ConversationStartRequestModel | None:
        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            acquired = repository.acquire_processing_lease(
                request_id=request_id,
                processing_token=processing_token,
                acquired_at=acquired_at,
                processing_expires_at=processing_expires_at,
            )

            if acquired is not None:
                uow.commit()

            return acquired

    def _persist_terminal_result(self, *, request_id: uuid.UUID, processing_token: uuid.UUID, terminal_status: str, 
                                 message_result: ProcessCustomerMessageResult, response_snapshot: dict[str, Any]
    ) -> None:
        completed_at = datetime.now(timezone.utc)
        with self._uow_factory() as uow:
            repository = self._require_repository(uow)

            if terminal_status == "completed":
                persisted = repository.mark_completed(
                    request_id=request_id,
                    processing_token=processing_token,
                    latest_ai_run_id=message_result.ai_run_id,
                    response_snapshot=response_snapshot,
                    completed_at=completed_at,
                )
            elif terminal_status == "failed":
                persisted = repository.mark_failed(
                    request_id=request_id,
                    processing_token=processing_token,
                    latest_ai_run_id=message_result.ai_run_id,
                    response_snapshot=response_snapshot,
                    completed_at=completed_at,
                )
            else:
                raise ConversationStartPersistenceContractError("Unsupported terminal status")

            if persisted is None:
                raise ConversationStartLeaseLostError(request_id)

            uow.commit()

    def _load_terminal_result(self, *, request_id: uuid.UUID) -> tuple[str, ProcessCustomerMessageResult,] | None:
        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            request = repository.get_by_id(request_id)

            if request is None:
                raise ConversationStartPersistenceContractError("Conversation-start request does not exist")

            if request.status not in {"completed", "failed",}:
                return None

            if request.response_snapshot is None:
                raise ConversationStartReplayUnavailableError(request_id)

            return (request.status, _deserialize_message_result(request.response_snapshot),)

    def _resolve_unavailable_lease(self, *, request_id: uuid.UUID, fallback_conversation_id: uuid.UUID, measured_at: datetime) -> StartConversationResult:
        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            request = repository.get_by_id(request_id)

            if request is None:
                raise ConversationStartPersistenceContractError("Conversation-start request disappeared")

            if request.status in {"completed", "failed",}:
                if request.response_snapshot is None:
                    raise ConversationStartReplayUnavailableError(request_id)

                return StartConversationResult(
                    request_id=request.id,
                    status=request.status,
                    created=False,
                    replayed=True,
                    message_result=_deserialize_message_result(request.response_snapshot),
                )

            if request.status == "processing" and request.processing_expires_at is not None and request.processing_expires_at > measured_at:
                seconds = math.ceil((request.processing_expires_at - measured_at).total_seconds())

                raise ConversationStartProcessingInProgressError(
                    request_id=request.id,
                    conversation_id=request.conversation_id,
                    retry_after_seconds=max(1, seconds),
                )

            raise ConversationStartLeaseLostError(request_id)

    @staticmethod
    def _require_repository(uow: SqlAlchemyUnitOfWork):
        if uow.session is None:
            raise ConversationStartPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.conversation_start_requests is None:
            raise ConversationStartPersistenceContractError("ConversationStartRequestRepository unavailable")

        return uow.conversation_start_requests

def _serialize_message_result(result: ProcessCustomerMessageResult) -> dict[str, Any]:
    """
    Create a sanitized, versioned replay representation.

    It deliberately excludes prompts, customer text, conversation context, retrieved content, provider errors and unrestricted metadata.
    """
    return {
        "schema_version": 1,
        "conversation_id": str(result.conversation_id),
        "customer_message_id": str(result.customer_message_id),
        "ai_run_id": str(result.ai_run_id),
        "trace_id": str(result.trace_id),
        "pipeline_stage": result.pipeline_stage.value,
        "intent": result.intent,
        "decision": result.decision,
        "assistant_message_id": str(result.assistant_message_id) if result.assistant_message_id is not None else None,
        "escalation_id": str(result.escalation_id) if result.escalation_id is not None else None,
        "response": result.response,
        "succeeded": result.succeeded,
        "failure_code": result.failure_code,
        "failure_retryable": result.failure_retryable,
    }

def _deserialize_message_result(snapshot: dict[str, Any]) -> ProcessCustomerMessageResult:
    if not isinstance(snapshot, dict):
        raise ConversationStartReplayUnavailableError(uuid.UUID(int=0))

    if snapshot.get("schema_version") != 1:
        raise ConversationStartPersistenceContractError("Unsupported conversation-start snapshot version")

    try:
        return ProcessCustomerMessageResult(
            conversation_id=uuid.UUID(snapshot["conversation_id"]),
            customer_message_id=uuid.UUID(snapshot["customer_message_id"]),
            ai_run_id=uuid.UUID(snapshot["ai_run_id"]),
            trace_id=uuid.UUID(snapshot["trace_id"]),
            pipeline_stage=PipelineStage(snapshot["pipeline_stage"]),
            intent=_optional_string(snapshot.get("intent")),
            decision=_optional_string(snapshot.get("decision")),
            assistant_message_id=_optional_uuid(snapshot.get("assistant_message_id")),
            escalation_id=_optional_uuid(snapshot.get("escalation_id")),
            response=_optional_string(snapshot.get("response")),
            succeeded=_required_bool(snapshot.get("succeeded"), field_name="succeeded"),
            failure_code=_optional_string(snapshot.get("failure_code")),
            failure_retryable=_optional_bool(snapshot.get("failure_retryable")),
        )
        
    except (KeyError, TypeError, ValueError,) as exc:
        raise ConversationStartPersistenceContractError("Stored conversation-start snapshot is invalid") from exc

def _optional_uuid(value: object) -> uuid.UUID | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError("UUID snapshot fields must be strings")

    return uuid.UUID(value)

def _optional_string(value: object) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError("String snapshot field has an invalid type")

    return value

def _required_bool(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")

    return value

def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None

    if not isinstance(value, bool):
        raise TypeError("Optional boolean snapshot field has an invalid type")

    return value