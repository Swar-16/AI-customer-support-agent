# AI-customer-support-agent\packages\application\feedback\submit_feedback.py
from __future__ import annotations
import json
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final
from sqlalchemy.exc import IntegrityError

from packages.database.models.support.feedback import FeedbackModel
from packages.database.repositories.support.feedback_repository import FeedbackRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
VALID_FEEDBACK_REASON_CODES: Final[frozenset[str]] = frozenset(
    {"INCORRECT_ANSWER", "INCOMPLETE_ANSWER", "IRRELEVANT_ANSWER", "OUTDATED_INFORMATION",
     "UNCLEAR_ANSWER", "MISSING_CITATION", "UNSAFE_RESPONSE", "SLOW_RESPONSE", "OTHER"
    }
)
MAX_COMMENT_LENGTH: Final[int] = 5_000
MAX_REASON_CODES: Final[int] = 10
MAX_METADATA_KEYS: Final[int] = 100
MAX_METADATA_SERIALIZED_LENGTH: Final[int] = 20_000
UNIQUE_RESPONSE_CONSTRAINT: Final[str] = "uq_feedback_response_message"

class SubmitFeedbackError(RuntimeError):
    """Base application error for feedback submission."""

class FeedbackConversationDoesNotExistError(SubmitFeedbackError):
    def __init__(self, conversation_id: uuid.UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation does not exist: {conversation_id}")

class FeedbackCustomerDoesNotExistError(SubmitFeedbackError):
    def __init__(self, customer_id: uuid.UUID) -> None:
        self.customer_id = customer_id
        super().__init__(f"Customer does not exist: {customer_id}")

class FeedbackCustomerNotActiveError(SubmitFeedbackError):
    """Raised when an inactive customer submits feedback."""

class FeedbackCustomerRoleError(SubmitFeedbackError):
    """Raised when the submitting user is not a customer."""

class FeedbackConversationOwnershipError(SubmitFeedbackError):
    """Raised when the customer does not own the conversation."""

class FeedbackResponseMessageDoesNotExistError(SubmitFeedbackError):
    def __init__(self, response_message_id: uuid.UUID) -> None:
        self.response_message_id = response_message_id
        super().__init__(f"Assistant response message does not exist: {response_message_id}")

class FeedbackResponseMessageMismatchError(SubmitFeedbackError):
    """Raised when the response belongs to another conversation or is not an assistant-authored message."""

class FeedbackAIRunDoesNotExistError(SubmitFeedbackError):
    def __init__(self, ai_run_id: uuid.UUID) -> None:
        self.ai_run_id = ai_run_id
        super().__init__(f"AI run does not exist: {ai_run_id}")

class FeedbackAIRunMismatchError(SubmitFeedbackError):
    """Raised when the AI run does not belong to the conversation or did not generate the supplied response message."""

class FeedbackSubmissionConflictError(SubmitFeedbackError):
    """Raised when feedback already exists for the response but its submitted values differ."""

class FeedbackPersistenceContractError(SubmitFeedbackError):
    """Raised when persistence wiring or generated state is incomplete."""

@dataclass(frozen=True, slots=True)
class SubmitFeedbackCommand:
    """
    Submit customer feedback for one visible AI response.

    `ai_run_id` is supplied by the client from the message-processing response and is verified against persisted AI-run provenance.
    """
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    response_message_id: uuid.UUID
    ai_run_id: uuid.UUID
    rating: int
    helpful: bool | None = None
    comment: str | None = None
    reason_codes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_uuid(self.conversation_id, field_name="conversation_id")
        self._validate_uuid(self.customer_id, field_name="customer_id")
        self._validate_uuid(self.response_message_id, field_name="response_message_id")
        self._validate_uuid(self.ai_run_id, field_name="ai_run_id")
        if isinstance(self.rating, bool) or not isinstance(self.rating, int):
            raise TypeError("rating must be an integer")

        if self.rating < 1 or self.rating > 5:
            raise ValueError("rating must be between 1 and 5")

        if self.helpful is not None and not isinstance(self.helpful, bool):
            raise TypeError("helpful must be a boolean or None")

        normalized_comment = self._normalize_optional_comment(self.comment)
        normalized_reason_codes = self._normalize_reason_codes(self.reason_codes)
        normalized_metadata = self._normalize_metadata(self.metadata)
        object.__setattr__(self, "comment", normalized_comment)
        object.__setattr__(self, "reason_codes", normalized_reason_codes)
        object.__setattr__(self, "metadata", MappingProxyType(normalized_metadata))

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _normalize_optional_comment(value: str | None) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError("comment must be a string or None")

        normalized = value.strip()
        if not normalized:
            return None

        if len(normalized) > MAX_COMMENT_LENGTH:
            raise ValueError(f"comment exceeds {MAX_COMMENT_LENGTH} characters")

        return normalized

    @staticmethod
    def _normalize_reason_codes(values: Iterable[str]) -> tuple[str, ...]:
        if isinstance(values, (str, bytes)):
            raise TypeError("reason_codes must be an iterable of strings")

        try:
            raw_values = tuple(values)
            
        except TypeError as exc:
            raise TypeError("reason_codes must be an iterable of strings") from exc

        if len(raw_values) > MAX_REASON_CODES:
            raise ValueError(f"reason_codes must contain at most {MAX_REASON_CODES} values")

        normalized_values: list[str] = []
        seen: set[str] = set()
        for value in raw_values:
            if not isinstance(value, str):
                raise TypeError("each reason code must be a string")

            normalized = value.strip().upper()
            if not normalized:
                raise ValueError("reason codes cannot be blank")

            if normalized not in VALID_FEEDBACK_REASON_CODES:
                expected = ", ".join(sorted(VALID_FEEDBACK_REASON_CODES))
                raise ValueError(f"reason code must be one of: {expected}")

            if normalized not in seen:
                normalized_values.append(normalized)
                seen.add(normalized)

        return tuple(normalized_values)

    @staticmethod
    def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping")

        if len(metadata) > MAX_METADATA_KEYS:
            raise ValueError("metadata contains too many keys")

        normalized: dict[str, Any] = {}
        for key, value in metadata.items():
            if not isinstance(key, str):
                raise TypeError("metadata keys must be strings")

            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError("metadata keys cannot be blank")

            if normalized_key in normalized:
                raise ValueError("metadata contains duplicate keys after normalization")

            normalized[normalized_key] = value

        try:
            serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
            
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must contain only JSON-serializable values") from exc

        if len(serialized) > MAX_METADATA_SERIALIZED_LENGTH:
            raise ValueError(f"serialized metadata exceeds {MAX_METADATA_SERIALIZED_LENGTH} characters")

        return normalized

@dataclass(frozen=True, slots=True)
class SubmitFeedbackResult:
    """Detached feedback result returned after transaction commit."""
    feedback_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    response_message_id: uuid.UUID
    ai_run_id: uuid.UUID | None
    rating: int
    helpful: bool | None
    comment: str | None
    reason_codes: tuple[str, ...]
    status: str
    row_version: int
    created: bool

class SubmitFeedback:
    """
    Persist feedback after validating customer ownership and AI provenance.

    Repeating an identical submission returns the existing feedback with `created=False`. A different
    submission for the same response is rejected instead of silently overwriting the original rating.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def execute(self, command: SubmitFeedbackCommand) -> SubmitFeedbackResult:
        if not isinstance(command, SubmitFeedbackCommand):
            raise TypeError("command must be a SubmitFeedbackCommand")

        try:
            with self._uow_factory() as uow:
                repository, audit_repository = self._require_repositories(uow)
                self._validate_customer_and_conversation(command=command, uow=uow)
                self._validate_response_message(command=command, uow=uow)
                self._validate_ai_run(command=command, uow=uow)
                existing = repository.get_by_response_message(command.response_message_id)
                if existing is not None:
                    self._validate_existing_feedback(existing=existing, command=command)
                    result = self._to_result(feedback=existing, created=False)
                    uow.commit()
                    return result

                feedback = FeedbackModel(
                    conversation_id=command.conversation_id,
                    customer_id=command.customer_id,
                    response_message_id=command.response_message_id,
                    ai_run_id=command.ai_run_id,
                    rating=command.rating,
                    helpful=command.helpful,
                    comment=command.comment,
                    reason_codes=list(command.reason_codes),
                    status="pending",
                    reviewed_by_user_id=None,
                    review_notes=None,
                    metadata_=dict(command.metadata),
                    reviewed_at=None,
                )

                repository.add(feedback)
                repository.flush()
                if feedback.id is None:
                    raise FeedbackPersistenceContractError("Feedback ID was not generated after flush")

                AuditRecorder(repository=audit_repository).record(
                    RecordAuditEventCommand(
                        event_type="feedback.submitted",
                        entity_type="feedback",
                        entity_id=feedback.id,
                        action="submitted",
                        actor=AuditActor(actor_type=AuditActorType.CUSTOMER, actor_id=command.customer_id),
                        conversation_id=feedback.conversation_id,
                        ai_run_id=feedback.ai_run_id,
                        before_state=None,
                        after_state={
                            "rating": feedback.rating,
                            "helpful": feedback.helpful,
                            "reason_codes": list(feedback.reason_codes),
                            "status": feedback.status,
                            "has_comment": feedback.comment is not None,
                        },
                        metadata={
                            "response_message_id": str(feedback.response_message_id),
                            "comment_length": len(feedback.comment) if feedback.comment is not None else 0,
                        },
                    )
                )
                result = self._to_result(feedback=feedback, created=True)
                uow.commit()

                return result

        except IntegrityError as exc:
            if self._is_duplicate_response_feedback(exc):
                raise FeedbackSubmissionConflictError("Feedback already exists for the assistant response.") from exc

            raise

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> tuple[FeedbackRepository, AuditEventRepository,]:
        if uow.session is None:
            raise FeedbackPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.feedback is None:
            raise FeedbackPersistenceContractError("FeedbackRepository unavailable")

        if uow.users is None:
            raise FeedbackPersistenceContractError("UserRepository unavailable")

        if uow.conversations is None:
            raise FeedbackPersistenceContractError("ConversationRepository unavailable")

        if uow.messages is None:
            raise FeedbackPersistenceContractError("MessageRepository unavailable")

        if uow.ai_runs is None:
            raise FeedbackPersistenceContractError("AIRunRepository unavailable")

        if uow.audit_events is None:
            raise FeedbackPersistenceContractError("AuditEventRepository unavailable")

        return uow.feedback, uow.audit_events

    @staticmethod
    def _validate_customer_and_conversation(*, command: SubmitFeedbackCommand, uow: SqlAlchemyUnitOfWork) -> None:
        if uow.users is None or uow.conversations is None:
            raise FeedbackPersistenceContractError("Customer validation repositories unavailable")

        customer = uow.users.get_by_id(command.customer_id)
        if customer is None:
            raise FeedbackCustomerDoesNotExistError(command.customer_id)

        if customer.status != "active":
            raise FeedbackCustomerNotActiveError(f"Customer {customer.id} is not active: status={customer.status!r}")

        if customer.role != "customer":
            raise FeedbackCustomerRoleError(f"User {customer.id} is not a customer: role={customer.role!r}")

        conversation = uow.conversations.get_by_id(command.conversation_id)
        if conversation is None:
            raise FeedbackConversationDoesNotExistError(command.conversation_id)

        if conversation.user_id != command.customer_id:
            raise FeedbackConversationOwnershipError(f"Customer {command.customer_id} does not own conversation {command.conversation_id}")

    @staticmethod
    def _validate_response_message(*, command: SubmitFeedbackCommand, uow: SqlAlchemyUnitOfWork) -> None:
        if uow.messages is None:
            raise FeedbackPersistenceContractError("MessageRepository unavailable")

        message = uow.messages.get_by_id(command.response_message_id)
        if message is None:
            raise FeedbackResponseMessageDoesNotExistError(command.response_message_id)

        if message.conversation_id != command.conversation_id:
            raise FeedbackResponseMessageMismatchError(f"Response message {message.id} does not belong to conversation {command.conversation_id}")

        if message.role != "assistant":
            raise FeedbackResponseMessageMismatchError(f"Message {message.id} cannot receive AI-response feedback because role={message.role!r}")

    @staticmethod
    def _validate_ai_run(*, command: SubmitFeedbackCommand, uow: SqlAlchemyUnitOfWork) -> None:
        if uow.ai_runs is None:
            raise FeedbackPersistenceContractError("AIRunRepository unavailable")

        ai_run = uow.ai_runs.get_by_id(command.ai_run_id)
        if ai_run is None:
            raise FeedbackAIRunDoesNotExistError(command.ai_run_id)

        if ai_run.conversation_id != command.conversation_id:
            raise FeedbackAIRunMismatchError(f"AI run {ai_run.id} does not belong to conversation {command.conversation_id}")

        if ai_run.response_message_id != command.response_message_id:
            raise FeedbackAIRunMismatchError(f"AI run {ai_run.id} did not generate response message {command.response_message_id}")

        if ai_run.status != "completed":
            raise FeedbackAIRunMismatchError(f"AI run {ai_run.id} is not completed: status={ai_run.status!r}")

    @staticmethod
    def _validate_existing_feedback(*, existing: FeedbackModel, command: SubmitFeedbackCommand) -> None:
        conflicts: list[str] = []
        if existing.conversation_id != command.conversation_id:
            conflicts.append("conversation_id")

        if existing.customer_id != command.customer_id:
            conflicts.append("customer_id")

        if existing.ai_run_id != command.ai_run_id:
            conflicts.append("ai_run_id")

        if existing.rating != command.rating:
            conflicts.append("rating")

        if existing.helpful != command.helpful:
            conflicts.append("helpful")

        if existing.comment != command.comment:
            conflicts.append("comment")

        if tuple(existing.reason_codes) != command.reason_codes:
            conflicts.append("reason_codes")

        if dict(existing.metadata_) != dict(command.metadata):
            conflicts.append("metadata")

        if conflicts:
            raise FeedbackSubmissionConflictError("Feedback already exists for this response and conflicts on: " + ", ".join(conflicts))

    @staticmethod
    def _to_result(*, feedback: FeedbackModel, created: bool) -> SubmitFeedbackResult:
        if feedback.id is None:
            raise FeedbackPersistenceContractError("Feedback ID was not generated after flush")

        if feedback.row_version is None:
            raise FeedbackPersistenceContractError("Feedback row version is unavailable")

        return SubmitFeedbackResult(
            feedback_id=feedback.id,
            conversation_id=feedback.conversation_id,
            customer_id=feedback.customer_id,
            response_message_id=feedback.response_message_id,
            ai_run_id=feedback.ai_run_id,
            rating=feedback.rating,
            helpful=feedback.helpful,
            comment=feedback.comment,
            reason_codes=tuple(feedback.reason_codes),
            status=feedback.status,
            row_version=feedback.row_version,
            created=created,
        )

    @staticmethod
    def _is_duplicate_response_feedback(exc: IntegrityError) -> bool:
        original = getattr(exc, "orig", None)
        diagnostic = getattr(original, "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)

        return constraint_name == UNIQUE_RESPONSE_CONSTRAINT