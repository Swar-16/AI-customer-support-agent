# AI-customer-support-agent\apps\api\app\api\v1\schemas\conversations.py
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