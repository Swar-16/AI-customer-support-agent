# AI-customer-support-agent\packages\application\feedback\query_feedback.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from packages.database.models.support.feedback import FeedbackModel
from packages.database.repositories.support.feedback_repository import FeedbackRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
AUTHORIZED_REQUESTER_ROLES = frozenset({"customer", "support_agent", "admin",})
VALID_FEEDBACK_STATUSES = frozenset({"pending", "reviewed", "actioned", "dismissed",})

class FeedbackQueryError(RuntimeError):
    """Base application error for feedback queries."""

class FeedbackDoesNotExistError(FeedbackQueryError):
    def __init__(self, feedback_id: uuid.UUID) -> None:
        self.feedback_id = feedback_id
        super().__init__(f"Feedback does not exist: {feedback_id}")

class FeedbackRequesterDoesNotExistError(FeedbackQueryError):
    def __init__(self, requester_id: uuid.UUID) -> None:
        self.requester_id = requester_id
        super().__init__(f"Requester does not exist: {requester_id}")

class FeedbackRequesterNotActiveError(FeedbackQueryError):
    """Raised when an inactive user requests feedback."""

class FeedbackRequesterRoleMismatchError(FeedbackQueryError):
    """Raised when the declared role differs from the persisted role."""

class FeedbackAccessDeniedError(FeedbackQueryError):
    """Raised when a requester cannot access the feedback."""

class FeedbackQueryContractError(FeedbackQueryError):
    """Raised when Unit of Work wiring is incomplete."""

@dataclass(frozen=True, slots=True)
class FeedbackView:
    """
    Detached feedback representation.

    Internal metadata and review notes are removed from customer-facing results.
    """
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
    reviewed_by_user_id: uuid.UUID | None
    review_notes: str | None
    metadata: Mapping[str, Any]
    row_version: int
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

@dataclass(frozen=True, slots=True)
class GetFeedbackQuery:
    feedback_id: uuid.UUID
    requester_id: uuid.UUID
    requester_role: str

    def __post_init__(self) -> None:
        _validate_uuid(self.feedback_id, field_name="feedback_id")
        _validate_uuid(self.requester_id, field_name="requester_id")
        object.__setattr__(self, "requester_role", _normalize_requester_role(self.requester_role))

@dataclass(frozen=True, slots=True)
class ListFeedbackQuery:
    """
    List customer-owned feedback or the dashboard feedback queue.

    Customer restrictions:
    - results are restricted to requester_id;
    - only conversation filtering is permitted;
    - review metadata is hidden.

    Agent/admin behavior:
    - all dashboard filters are available;
    - internal review fields and metadata are included.
    """
    requester_id: uuid.UUID
    requester_role: str
    status: str | None = None
    rating: int | None = None
    helpful: bool | None = None
    reason_code: str | None = None
    customer_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        _validate_uuid(self.requester_id, field_name="requester_id")
        requester_role = _normalize_requester_role(self.requester_role)
        status = _normalize_optional_status(self.status)
        reason_code = _normalize_optional_reason_code(self.reason_code)
        if self.rating is not None:
            _validate_rating(self.rating)

        if self.helpful is not None and not isinstance(self.helpful, bool):
            raise TypeError("helpful must be a boolean or None")

        if self.customer_id is not None:
            _validate_uuid(self.customer_id, field_name="customer_id")

        if self.conversation_id is not None:
            _validate_uuid(self.conversation_id, field_name="conversation_id")

        _validate_datetime_range(created_from=self.created_from, created_to=self.created_to)
        _validate_pagination(limit=self.limit, offset=self.offset)
        if requester_role == "customer":
            self._validate_customer_filters(status=status, reason_code=reason_code)

        object.__setattr__(self, "requester_role", requester_role)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reason_code", reason_code)

    def _validate_customer_filters(self, *, status: str | None, reason_code: str | None) -> None:
        if status is not None:
            raise FeedbackAccessDeniedError("Customers cannot filter feedback by review status")

        if self.rating is not None:
            raise FeedbackAccessDeniedError("Customers cannot filter feedback by rating")

        if self.helpful is not None:
            raise FeedbackAccessDeniedError("Customers cannot filter feedback by helpful value")

        if reason_code is not None:
            raise FeedbackAccessDeniedError("Customers cannot filter feedback by reason code")

        if self.customer_id is not None and self.customer_id != self.requester_id:
            raise FeedbackAccessDeniedError("Customers cannot request another customer's feedback")

        if self.created_from is not None or self.created_to is not None:
            raise FeedbackAccessDeniedError("Customers cannot use dashboard time-range filters")

@dataclass(frozen=True, slots=True)
class FeedbackPage:
    items: tuple[FeedbackView, ...]
    limit: int
    offset: int
    has_more: bool

    @property
    def count(self) -> int:
        return len(self.items)

class GetFeedback:
    """Retrieve one feedback record for an authorized requester."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, query: GetFeedbackQuery) -> FeedbackView:
        if not isinstance(query, GetFeedbackQuery):
            raise TypeError("query must be a GetFeedbackQuery")

        with self._uow_factory() as uow:
            repository = _require_repositories(uow)
            _validate_requester(requester_id=query.requester_id, requester_role=query.requester_role, uow=uow)
            feedback = repository.get_by_id(query.feedback_id)
            if feedback is None:
                raise FeedbackDoesNotExistError(query.feedback_id)

            _authorize_feedback_access(feedback=feedback, requester_id=query.requester_id, requester_role=query.requester_role)
            include_internal = query.requester_role in {"support_agent", "admin"}

            return _to_feedback_view(feedback, include_internal=include_internal)

class ListFeedback:
    """Retrieve customer feedback history or the dashboard queue."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = _validate_uow_factory(uow_factory)

    def execute(self, query: ListFeedbackQuery) -> FeedbackPage:
        if not isinstance(query, ListFeedbackQuery):
            raise TypeError("query must be a ListFeedbackQuery")

        fetch_limit = query.limit + 1
        with self._uow_factory() as uow:
            repository = _require_repositories(uow)
            _validate_requester(requester_id=query.requester_id, requester_role=query.requester_role, uow=uow)
            include_internal = query.requester_role in {"support_agent", "admin"}
            if query.requester_role == "customer":
                records = repository.list_recent(
                    customer_id=query.requester_id,
                    conversation_id=query.conversation_id,
                    limit=fetch_limit,
                    offset=query.offset,
                )
            else:
                records = repository.list_recent(
                    status=query.status,
                    rating=query.rating,
                    helpful=query.helpful,
                    reason_code=query.reason_code,
                    customer_id=query.customer_id,
                    conversation_id=query.conversation_id,
                    created_from=query.created_from,
                    created_to=query.created_to,
                    limit=fetch_limit,
                    offset=query.offset,
                )

            has_more = len(records) > query.limit
            visible_records = records[:query.limit]

            return FeedbackPage(
                items=tuple(_to_feedback_view(feedback, include_internal=include_internal) for feedback in visible_records),
                limit=query.limit,
                offset=query.offset,
                has_more=has_more,
            )

def _validate_uow_factory(uow_factory: UnitOfWorkFactory) -> UnitOfWorkFactory:
    if uow_factory is None:
        raise TypeError("uow_factory cannot be None")

    if not callable(uow_factory):
        raise TypeError("uow_factory must be callable")

    return uow_factory

def _require_repositories(uow: SqlAlchemyUnitOfWork) -> FeedbackRepository:
    if uow.session is None:
        raise FeedbackQueryContractError("Active SQLAlchemy Session unavailable")

    if uow.feedback is None:
        raise FeedbackQueryContractError("FeedbackRepository unavailable")

    if uow.users is None:
        raise FeedbackQueryContractError("UserRepository unavailable")

    return uow.feedback

def _validate_requester(*, requester_id: uuid.UUID, requester_role: str, uow: SqlAlchemyUnitOfWork) -> None:
    if uow.users is None:
        raise FeedbackQueryContractError("UserRepository unavailable")

    requester = uow.users.get_by_id(requester_id)
    if requester is None:
        raise FeedbackRequesterDoesNotExistError(requester_id)

    if requester.status != "active":
        raise FeedbackRequesterNotActiveError(f"Requester {requester_id} is not active: status={requester.status!r}")

    if requester.role != requester_role:
        raise FeedbackRequesterRoleMismatchError(f"Declared requester role {requester_role!r} does not match persisted role {requester.role!r}")

def _authorize_feedback_access(*, feedback: FeedbackModel, requester_id: uuid.UUID, requester_role: str) -> None:
    if requester_role in {"support_agent", "admin"}:
        return

    if requester_role == "customer" and feedback.customer_id == requester_id:
        return

    raise FeedbackAccessDeniedError(f"Requester {requester_id} cannot access feedback {feedback.id}")

def _to_feedback_view(feedback: FeedbackModel, *, include_internal: bool) -> FeedbackView:
    if feedback.id is None:
        raise FeedbackQueryContractError("Persisted feedback has no ID")

    return FeedbackView(
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
        reviewed_by_user_id=feedback.reviewed_by_user_id if include_internal else None,
        review_notes=feedback.review_notes if include_internal else None,
        metadata=dict(feedback.metadata_) if include_internal else {},
        row_version=feedback.row_version,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
        reviewed_at=feedback.reviewed_at if include_internal else None,
    )

def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
    if not isinstance(value, uuid.UUID):
        raise TypeError(f"{field_name} must be a UUID")

def _normalize_requester_role(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("requester_role must be a string")

    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("requester_role cannot be blank")

    if normalized not in AUTHORIZED_REQUESTER_ROLES:
        expected = ", ".join(sorted(AUTHORIZED_REQUESTER_ROLES))
        raise ValueError(f"requester_role must be one of: {expected}")

    return normalized

def _normalize_optional_status(value: str | None) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError("status must be a string or None")

    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("status cannot be blank")

    if normalized not in VALID_FEEDBACK_STATUSES:
        expected = ", ".join(sorted(VALID_FEEDBACK_STATUSES))
        raise ValueError(f"status must be one of: {expected}")

    return normalized

def _normalize_optional_reason_code(value: str | None) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError("reason_code must be a string or None")

    normalized = value.strip().upper()
    if not normalized:
        raise ValueError("reason_code cannot be blank")

    return normalized

def _validate_rating(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("rating must be an integer")

    if value < 1 or value > 5:
        raise ValueError("rating must be between 1 and 5")

def _validate_pagination(*, limit: int, offset: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")

    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    if limit > 200:
        raise ValueError("limit must not exceed 200")

    if isinstance(offset, bool) or not isinstance(offset, int):
        raise TypeError("offset must be an integer")

    if offset < 0:
        raise ValueError("offset must not be negative")

def _validate_datetime_range(*, created_from: datetime | None, created_to: datetime | None) -> None:
    for field_name, value in (("created_from", created_from), ("created_to", created_to),):
        if value is None:
            continue

        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime or None")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")

    if created_from is not None and created_to is not None and created_from > created_to:
        raise ValueError("created_from cannot be later than created_to")