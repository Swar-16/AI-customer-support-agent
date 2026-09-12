# AI-customer-support-agent\apps\api\app\api\v1\schemas\feedback.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

FeedbackStatus = Literal["pending", "reviewed", "actioned", "dismissed",]
FeedbackReviewTargetStatus = Literal["reviewed", "actioned", "dismissed",]
FeedbackRequesterRole = Literal["customer", "support_agent", "admin",]
FeedbackReasonCode = Literal[
    "INCORRECT_ANSWER", "INCOMPLETE_ANSWER", "IRRELEVANT_ANSWER", "OUTDATED_INFORMATION",
    "UNCLEAR_ANSWER", "MISSING_CITATION", "UNSAFE_RESPONSE", "SLOW_RESPONSE", "OTHER"
]

class FeedbackAPIModel(BaseModel):
    """
    Base model for feedback HTTP contracts.

    Unexpected fields are rejected so callers cannot silently submit unsupported review or feedback mutations.
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

# Customer submission
class SubmitFeedbackRequest(FeedbackAPIModel):
    response_message_id: uuid.UUID = Field(..., description="Assistant message being evaluated.")
    ai_run_id: uuid.UUID = Field(..., description="AI run that generated the assistant response.")
    rating: int = Field(..., ge=1, le=5, description="Customer rating from 1 to 5.", examples=[4])
    helpful: bool | None = Field(default=None, description="Whether the response was helpful.")
    comment: str | None = Field(default=None, max_length=5_000, description="Optional customer explanation.")
    reason_codes: list[FeedbackReasonCode] = Field(default_factory=list, max_length=10, description="Structured reasons for the rating.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional non-authoritative feedback context.")

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @field_validator("reason_codes")
    @classmethod
    def remove_duplicate_reason_codes(cls, values: list[FeedbackReasonCode]) -> list[FeedbackReasonCode]:
        return list(dict.fromkeys(values)) # dict preserves insertion order.

class SubmitFeedbackResponse(FeedbackAPIModel):
    feedback_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    response_message_id: uuid.UUID
    ai_run_id: uuid.UUID | None = None
    rating: int = Field(..., ge=1, le=5)
    helpful: bool | None = None
    comment: str | None = None
    reason_codes: list[FeedbackReasonCode]
    status: FeedbackStatus
    row_version: int = Field(..., ge=1)
    created: bool

# Dashboard review
class ReviewFeedbackRequest(FeedbackAPIModel):
    expected_row_version: int = Field(..., ge=1, description="Feedback row version observed by the dashboard.")
    target_status: FeedbackReviewTargetStatus
    review_notes: str | None = Field(default=None, max_length=5_000)

    @field_validator("review_notes")
    @classmethod
    def normalize_review_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

class ReviewFeedbackResponse(FeedbackAPIModel):
    feedback_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    response_message_id: uuid.UUID
    ai_run_id: uuid.UUID | None = None
    previous_status: FeedbackStatus
    current_status: FeedbackStatus
    reviewed_by_user_id: uuid.UUID | None = None
    review_notes: str | None = None
    reviewed_at: datetime | None = None
    row_version: int = Field(..., ge=1)
    updated_at: datetime
    changed: bool

# Query responses
class FeedbackResponse(FeedbackAPIModel):
    feedback_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    response_message_id: uuid.UUID
    ai_run_id: uuid.UUID | None = None
    rating: int = Field(..., ge=1, le=5)
    helpful: bool | None = None
    comment: str | None = None
    reason_codes: list[FeedbackReasonCode]
    status: FeedbackStatus
    reviewed_by_user_id: uuid.UUID | None = None
    review_notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    row_version: int = Field(..., ge=1)
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None

class FeedbackListResponse(FeedbackAPIModel):
    items: list[FeedbackResponse]
    count: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=200)
    offset: int = Field(..., ge=0)
    has_more: bool