# AI-customer-support-agent\packages\database\repositories\support\feedback_repository.py
from __future__ import annotations
import uuid
from collections.abc import Sequence
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.support.feedback import FeedbackModel

VALID_FEEDBACK_STATUSES = frozenset({"pending", "reviewed", "actioned", "dismissed",})

class FeedbackRepository:
    """
    Persistence adapter for customer feedback.

    Responsibilities:
    - stage and flush feedback records;
    - retrieve feedback by identity and response provenance;
    - lock feedback before review-state mutations;
    - return bounded customer and conversation histories;
    - provide dashboard-oriented filtering.

    Transaction ownership remains with the surrounding Unit of Work.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, feedback: FeedbackModel) -> None:
        """
        Stage a feedback record in the current transaction.

        This method does not flush or commit.
        """
        self._validate_feedback_instance(feedback)
        self._session.add(feedback)

    def flush(self) -> None:
        """Flush pending changes without committing the transaction."""
        self._session.flush()

    # Primary lookups
    def get_by_id(self, feedback_id: uuid.UUID) -> FeedbackModel | None:
        self._validate_uuid(feedback_id, field_name="feedback_id")
        statement = (select(FeedbackModel)
                     .where(FeedbackModel.id == feedback_id)
        )

        return self._session.scalar(statement)

    def get_by_id_for_update(self, feedback_id: uuid.UUID) -> FeedbackModel | None:
        """
        Retrieve feedback while acquiring a row-level write lock.

        Use this before changing review status, reviewer, or review notes.
        """
        self._validate_uuid(feedback_id, field_name="feedback_id")
        statement = (select(FeedbackModel)
                     .where(FeedbackModel.id == feedback_id)
                     .with_for_update()
        )

        return self._session.scalar(statement)

    def get_by_response_message(self, response_message_id: uuid.UUID) -> FeedbackModel | None:
        """
        Return feedback for one assistant response.

        The database unique constraint guarantees at most one result. This lookup supports idempotent feedback submission.
        """
        self._validate_uuid(response_message_id, field_name="response_message_id")
        statement = (select(FeedbackModel)
                     .where(FeedbackModel.response_message_id == response_message_id)
        )

        return self._session.scalar(statement)

    def get_by_ai_run(self, ai_run_id: uuid.UUID) -> FeedbackModel | None:
        """
        Return feedback associated with an AI run.

        The current message-processing flow produces at most one visible assistant response per AI run.
        """
        self._validate_uuid(ai_run_id, field_name="ai_run_id")
        statement = (select(FeedbackModel)
                     .where(FeedbackModel.ai_run_id == ai_run_id)
                     .order_by(FeedbackModel.created_at.desc(),
                               FeedbackModel.id.desc())
                     .limit(1)
        )

        return self._session.scalar(statement)

    # Ownership-oriented queries
    def list_for_conversation(self, conversation_id: uuid.UUID, *, limit: int = 100, offset: int = 0) -> Sequence[FeedbackModel]:
        self._validate_uuid(conversation_id, field_name="conversation_id")
        self._validate_pagination(limit=limit, offset=offset)
        statement = (select(FeedbackModel)
                     .where(FeedbackModel.conversation_id == conversation_id)
                     .order_by(FeedbackModel.created_at.desc(),
                               FeedbackModel.id.desc(),)
                     .offset(offset)
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_for_customer(self, customer_id: uuid.UUID, *, limit: int = 100, offset: int = 0) -> Sequence[FeedbackModel]:
        self._validate_uuid(customer_id, field_name="customer_id")
        self._validate_pagination(limit=limit, offset=offset)
        statement = (select(FeedbackModel)
                     .where(FeedbackModel.customer_id == customer_id)
                     .order_by(FeedbackModel.created_at.desc(),
                               FeedbackModel.id.desc())
                     .offset(offset)
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Dashboard queries
    def list_recent(self, *, status: str | None = None, rating: int | None = None, helpful: bool | None = None, 
                    reason_code: str | None = None, customer_id: uuid.UUID | None = None, conversation_id: uuid.UUID | None = None,
                    created_from: datetime | None = None, created_to: datetime | None = None, limit: int = 100, offset: int = 0
    ) -> Sequence[FeedbackModel]:
        """
        Return filtered feedback ordered newest first.

        This query supports the MVP dashboard feedback table. Aggregate analytics such as average rating and
        helpful percentage should be implemented separately rather than calculated from a paginated result.
        """
        self._validate_pagination(limit=limit, offset=offset)
        normalized_status = self._normalize_optional_status(status)
        normalized_reason_code = self._normalize_optional_reason_code(reason_code)
        if rating is not None:
            self._validate_rating(rating)

        if helpful is not None and not isinstance(helpful, bool):
            raise TypeError("helpful must be a boolean or None")

        if customer_id is not None:
            self._validate_uuid(customer_id, field_name="customer_id")

        if conversation_id is not None:
            self._validate_uuid(conversation_id, field_name="conversation_id")

        self._validate_datetime_range(created_from=created_from, created_to=created_to)
        statement = select(FeedbackModel)
        if normalized_status is not None:
            statement = statement.where(FeedbackModel.status == normalized_status)

        if rating is not None:
            statement = statement.where(FeedbackModel.rating == rating)

        if helpful is not None:
            statement = statement.where(FeedbackModel.helpful.is_(helpful))

        if normalized_reason_code is not None:
            statement = statement.where(FeedbackModel.reason_codes.contains([normalized_reason_code]))

        if customer_id is not None:
            statement = statement.where(FeedbackModel.customer_id == customer_id)

        if conversation_id is not None:
            statement = statement.where(FeedbackModel.conversation_id == conversation_id)

        if created_from is not None:
            statement = statement.where(FeedbackModel.created_at >= created_from)

        if created_to is not None:
            statement = statement.where(FeedbackModel.created_at <= created_to)

        statement = (statement.order_by(FeedbackModel.created_at.desc(),
                                        FeedbackModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Validation helpers
    @staticmethod
    def _validate_feedback_instance(feedback: FeedbackModel) -> None:
        if not isinstance(feedback, FeedbackModel):
            raise TypeError("feedback must be a FeedbackModel")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_rating(rating: int) -> None:
        if isinstance(rating, bool) or not isinstance(rating, int):
            raise TypeError("rating must be an integer")

        if rating < 1 or rating > 5:
            raise ValueError("rating must be between 1 and 5")

    @staticmethod
    def _validate_pagination(*, limit: int, offset: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if limit > 500:
            raise ValueError("limit must not exceed 500")

        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")

        if offset < 0:
            raise ValueError("offset must not be negative")

    @staticmethod
    def _normalize_optional_status(status: str | None) -> str | None:
        normalized = FeedbackRepository._normalize_optional_text(status, field_name="status")

        if normalized is not None and normalized not in VALID_FEEDBACK_STATUSES:
            expected = ", ".join(sorted(VALID_FEEDBACK_STATUSES))
            raise ValueError(f"status must be one of: {expected}")

        return normalized

    @staticmethod
    def _normalize_optional_reason_code(reason_code: str | None) -> str | None:
        normalized = FeedbackRepository._normalize_optional_text(reason_code, field_name="reason_code")
        if normalized is None:
            return None

        return normalized.upper()

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        return normalized.lower()

    @staticmethod
    def _validate_datetime_range(*, created_from: datetime | None, created_to: datetime | None) -> None:
        for field_name, value in (("created_from", created_from), ("created_to", created_to)):
            if value is None:
                continue

            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime or None")

            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")

        if created_from is not None and created_to is not None and created_from > created_to:
            raise ValueError("created_from cannot be later than created_to")