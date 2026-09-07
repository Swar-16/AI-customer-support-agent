# AI-customer-support-agent\packages\application\feedback\review_feedback.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final
from sqlalchemy.orm.exc import StaleDataError

from packages.database.models.support.feedback import FeedbackModel
from packages.database.repositories.support.feedback_repository import FeedbackRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
Clock = Callable[[], datetime]
VALID_REVIEW_TARGET_STATUSES: Final[frozenset[str]] = frozenset({"reviewed", "actioned", "dismissed",})
ALLOWED_FEEDBACK_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "pending": frozenset({"reviewed", "actioned", "dismissed",}),
    "reviewed": frozenset({"actioned", "dismissed",}),
    "actioned": frozenset(),
    "dismissed": frozenset(),
}
MAX_REVIEW_NOTES_LENGTH: Final[int] = 5_000

class ReviewFeedbackError(RuntimeError):
    """Base application error for feedback review operations."""

class ReviewFeedbackDoesNotExistError(ReviewFeedbackError):
    def __init__(self, feedback_id: uuid.UUID) -> None:
        self.feedback_id = feedback_id
        super().__init__(f"Feedback does not exist: {feedback_id}")

class FeedbackReviewerDoesNotExistError(ReviewFeedbackError):
    def __init__(self, reviewer_id: uuid.UUID) -> None:
        self.reviewer_id = reviewer_id
        super().__init__(f"Feedback reviewer does not exist: {reviewer_id}")

class FeedbackReviewerNotAuthorizedError(ReviewFeedbackError):
    """Raised when an inactive user or unauthorized role attempts to review feedback."""

class InvalidFeedbackTransitionError(ReviewFeedbackError):
    def __init__(self, *, feedback_id: uuid.UUID, current_status: str, target_status: str) -> None:
        self.feedback_id = feedback_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(f"Invalid feedback transition for {feedback_id}: {current_status!r} -> {target_status!r}")

class FeedbackReviewConcurrencyError(ReviewFeedbackError):
    """Raised when the caller supplies a stale row version."""
    def __init__(self, *, feedback_id: uuid.UUID, expected_version: int, actual_version: int | None = None) -> None:
        self.feedback_id = feedback_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        actual_detail = f", actual version is {actual_version}" if actual_version is not None else ""
        super().__init__(f"Feedback {feedback_id} was modified concurrently; expected version {expected_version}{actual_detail}")

class FeedbackReviewPersistenceContractError(ReviewFeedbackError):
    """Raised when persistence wiring or stored state is invalid."""

@dataclass(frozen=True, slots=True)
class ReviewFeedbackCommand:
    """
    Apply a controlled dashboard review transition.

    `expected_row_version` prevents one dashboard operator from silently overwriting another operator's review.
    """
    feedback_id: uuid.UUID
    reviewer_id: uuid.UUID
    expected_row_version: int
    target_status: str
    review_notes: str | None = None

    def __post_init__(self) -> None:
        self._validate_uuid(self.feedback_id, field_name="feedback_id")
        self._validate_uuid(self.reviewer_id, field_name="reviewer_id")
        if isinstance(self.expected_row_version, bool) or not isinstance(self.expected_row_version, int):
            raise TypeError("expected_row_version must be an integer")

        if self.expected_row_version <= 0:
            raise ValueError("expected_row_version must be greater than zero")

        if not isinstance(self.target_status, str):
            raise TypeError("target_status must be a string")

        normalized_target_status = self.target_status.strip().lower()
        if not normalized_target_status:
            raise ValueError("target_status cannot be blank")

        if normalized_target_status not in VALID_REVIEW_TARGET_STATUSES:
            expected = ", ".join(sorted(VALID_REVIEW_TARGET_STATUSES))
            raise ValueError(f"target_status must be one of: {expected}")

        normalized_review_notes = self._normalize_review_notes(self.review_notes)
        if normalized_target_status in {"actioned", "dismissed"} and normalized_review_notes is None:
            raise ValueError("review_notes are required when feedback is actioned or dismissed")

        object.__setattr__(self, "target_status", normalized_target_status)
        object.__setattr__(self, "review_notes", normalized_review_notes)

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _normalize_review_notes(value: str | None) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError("review_notes must be a string or None")

        normalized = value.strip()
        if not normalized:
            return None

        if len(normalized) > MAX_REVIEW_NOTES_LENGTH:
            raise ValueError(f"review_notes exceeds {MAX_REVIEW_NOTES_LENGTH} characters")

        return normalized

@dataclass(frozen=True, slots=True)
class ReviewFeedbackResult:
    """Detached review state returned after commit."""
    feedback_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    response_message_id: uuid.UUID
    ai_run_id: uuid.UUID | None
    previous_status: str
    current_status: str
    reviewed_by_user_id: uuid.UUID | None
    review_notes: str | None
    reviewed_at: datetime | None
    row_version: int
    updated_at: datetime
    changed: bool

class ReviewFeedback:
    """
    Apply a support-agent or administrator feedback-review transition.

    The feedback row is locked before validation, while row_version protects callers from making decisions using stale dashboard state.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock | None = None) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable or None")

        self._uow_factory = uow_factory
        self._clock = clock if clock is not None else self._utc_now

    def execute(self, command: ReviewFeedbackCommand) -> ReviewFeedbackResult:
        if not isinstance(command, ReviewFeedbackCommand):
            raise TypeError("command must be a ReviewFeedbackCommand")

        try:
            with self._uow_factory() as uow:
                repository = self._require_repositories(uow)
                self._validate_reviewer(reviewer_id=command.reviewer_id, uow=uow)
                feedback = repository.get_by_id_for_update(command.feedback_id)
                if feedback is None:
                    raise ReviewFeedbackDoesNotExistError(command.feedback_id)

                if feedback.row_version != command.expected_row_version:
                    raise FeedbackReviewConcurrencyError(
                        feedback_id=feedback.id,
                        expected_version=command.expected_row_version,
                        actual_version=feedback.row_version,
                    )

                previous_status = feedback.status
                if previous_status == command.target_status:
                    result = self._to_result(feedback=feedback, previous_status=previous_status, changed=False)
                    uow.commit()
                    return result

                self._validate_transition(feedback_id=feedback.id, current_status=previous_status, target_status=command.target_status)
                occurred_at = self._clock()
                self._validate_clock_value(occurred_at)
                self._apply_transition(
                    feedback=feedback,
                    reviewer_id=command.reviewer_id,
                    target_status=command.target_status,
                    review_notes=command.review_notes,
                    occurred_at=occurred_at,
                )
                
                uow.flush()
                result = self._to_result(feedback=feedback, previous_status=previous_status, changed=True)
                uow.commit()
                return result

        except StaleDataError as exc:
            raise FeedbackReviewConcurrencyError(feedback_id=command.feedback_id, expected_version=command.expected_row_version) from exc

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> FeedbackRepository:
        if uow.session is None:
            raise FeedbackReviewPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.feedback is None:
            raise FeedbackReviewPersistenceContractError("FeedbackRepository unavailable")

        if uow.users is None:
            raise FeedbackReviewPersistenceContractError("UserRepository unavailable")

        return uow.feedback

    @staticmethod
    def _validate_reviewer(*, reviewer_id: uuid.UUID, uow: SqlAlchemyUnitOfWork) -> None:
        if uow.users is None:
            raise FeedbackReviewPersistenceContractError("UserRepository unavailable")

        reviewer = uow.users.get_by_id(reviewer_id)
        if reviewer is None:
            raise FeedbackReviewerDoesNotExistError(reviewer_id)

        if reviewer.status != "active":
            raise FeedbackReviewerNotAuthorizedError(f"Reviewer {reviewer_id} is not active: status={reviewer.status!r}")

        if reviewer.role not in {"support_agent", "admin"}:
            raise FeedbackReviewerNotAuthorizedError(f"User {reviewer_id} cannot review feedback: role={reviewer.role!r}")

    @staticmethod
    def _validate_transition(*, feedback_id: uuid.UUID, current_status: str, target_status: str) -> None:
        allowed_targets = ALLOWED_FEEDBACK_TRANSITIONS.get(current_status)
        if allowed_targets is None or target_status not in allowed_targets:
            raise InvalidFeedbackTransitionError(feedback_id=feedback_id, current_status=current_status, target_status=target_status)

    @staticmethod
    def _apply_transition(*, feedback: FeedbackModel, reviewer_id: uuid.UUID, target_status: str, review_notes: str | None, occurred_at: datetime) -> None:
        feedback.status = target_status
        feedback.updated_at = occurred_at

        # Preserve who first reviewed the feedback and when.
        if feedback.reviewed_at is None:
            feedback.reviewed_at = occurred_at

        if feedback.reviewed_by_user_id is None:
            feedback.reviewed_by_user_id = reviewer_id

        if review_notes is not None:
            feedback.review_notes = review_notes

    @staticmethod
    def _to_result(*, feedback: FeedbackModel, previous_status: str, changed: bool) -> ReviewFeedbackResult:
        if feedback.id is None:
            raise FeedbackReviewPersistenceContractError("Persisted feedback has no ID")

        return ReviewFeedbackResult(
            feedback_id=feedback.id,
            conversation_id=feedback.conversation_id,
            customer_id=feedback.customer_id,
            response_message_id=feedback.response_message_id,
            ai_run_id=feedback.ai_run_id,
            previous_status=previous_status,
            current_status=feedback.status,
            reviewed_by_user_id=feedback.reviewed_by_user_id,
            review_notes=feedback.review_notes,
            reviewed_at=feedback.reviewed_at,
            row_version=feedback.row_version,
            updated_at=feedback.updated_at,
            changed=changed,
        )

    @staticmethod
    def _validate_clock_value(value: datetime) -> None:
        if not isinstance(value, datetime):
            raise TypeError("clock must return a datetime")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)