from __future__ import annotations
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator


# Shared configuration
class APIModel(BaseModel):
    """
    Base model for versioned HTTP API schemas.

    Design goals:
    - reject unexpected request fields
    - provide stable serialization behavior
    - keep API contracts independent from ORM/domain models
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ## It means: for example like:
    ## {
    ##   "message": "Where is my order?",
    ##   "admin": true
    ## }
    ## is rejected instead of silently ignoring admin giving a stricter API boundary.


# Send message
class SendMessageRequest(APIModel):
    """
    Request body for:

        POST /v1/conversations/{conversation_id}/messages

    The conversation ID belongs in the URL path, not duplicated in the body.
    """

    message: str = Field(
        ...,
        min_length=1,
        max_length=20_000,
        description="Customer-authored support message.",
        examples=["I was charged twice for order ORD-123."]
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message cannot be empty")

        return normalized


class SendMessageResponse(APIModel):
    """
    HTTP response after the customer message and AI processing run have
    successfully completed at the application layer.

    This intentionally exposes stable identifiers and semantic outcomes,
    not SQLAlchemy models or internal AIState objects.
    """
    conversation_id: uuid.UUID
    customer_message_id: uuid.UUID
    ai_run_id: uuid.UUID
    trace_id: uuid.UUID

    pipeline_stage: str = Field(..., description="Final pipeline stage reached during processing.")
    intent: str | None = Field(default=None, description="Canonical intent classification, if available.")
    decision: str | None = Field(default=None, description="Canonical routing/decision outcome, if available.")
    succeeded: bool