# AI-customer-support-agent\apps\api\app\api\v1\schemas\conversations.py
from __future__ import annotations
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal
from datetime import datetime

ConversationChannel = Literal["web", "mobile", "email", "api",]
ConversationStatus = Literal["open", "waiting_for_customer", "waiting_for_agent", "escalated", "resolved", "closed",]


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


# Conversation creation
class CreateConversationRequest(APIModel):
    channel: ConversationChannel = Field(default="web", description="Channel through which the conversation begins.")
    title: str | None = Field(default=None, max_length=500, description="Optional customer-visible conversation title.")

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = " ".join(value.split())
        return normalized or None

class CreateConversationResponse(APIModel):
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    status: ConversationStatus
    channel: ConversationChannel
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    
class ConversationResponse(APIModel):
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    status: ConversationStatus
    channel: ConversationChannel
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    closed_at: datetime | None = None

class ConversationListResponse(APIModel):
    items: list[ConversationResponse]
    total: int = Field(..., ge=0)
    count: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=200)
    offset: int = Field(..., ge=0)
    has_more: bool
    next_offset: int | None = Field(default=None, ge=0)
    
class ConversationMessageResponse(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["customer", "assistant", "support_agent",]
    content: str
    sequence_number: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ConversationMessageListResponse(BaseModel):
    items: list[ConversationMessageResponse]
    total: int
    count: int
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None

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
    Result of processing one customer-authored message.

    A successful application execution does not always produce an assistant response:

    - grounded answer:
        assistant_message_id and response are populated;

    - clarification/action workflow not yet producing customer text:
        both may be None;

    - human escalation:
        escalation_id is populated and an unapproved generated candidate is never exposed;

    - failed pipeline:
        succeeded is False.
    """
    conversation_id: uuid.UUID
    customer_message_id: uuid.UUID
    ai_run_id: uuid.UUID
    trace_id: uuid.UUID
    pipeline_stage: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Final pipeline stage reached during processing.",
        examples=["guardrails_completed"],
    )

    intent: str | None = Field(
        default=None,
        max_length=100,
        description="Canonical intent classification, if available.",
        examples=["refund_request"],
    )

    decision: str | None = Field(
        default=None,
        max_length=100,
        description="Canonical routing decision, if available.",
        examples=["retrieve_information"],
    )

    assistant_message_id: uuid.UUID | None = Field(
        default=None,
        description="Persisted customer-visible assistant message ID. Present only when an approved response was created.",
    )

    escalation_id: uuid.UUID | None = Field(
        default=None,
        description="Persistent human-review escalation ID. Present when the pipeline ended in escalation.",
    )

    response: str | None = Field(
        default=None,
        max_length=30_000,
        description="Guardrail-approved customer-visible assistant response. An internal generated candidate is never returned when guardrails escalate or reject it.",
    )

    succeeded: bool = Field(
        ...,
        description="Whether the application pipeline completed without entering the failed stage. An escalation is a successful workflow outcome and therefore may return true.",
    )
    
# Close Conversation
class CloseConversationResponse(APIModel):
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    status: Literal["closed"]
    resolved_at: datetime | None
    closed_at: datetime
    updated_at: datetime
    changed: bool