# AI-customer-support-agent\apps\api\app\api\v1\schemas\escalations.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.api.app.api.v1.schemas.tickets import TicketStatus

EscalationStatus = Literal["open", "in_review", "resolved", "dismissed"]
EscalationPriority = Literal["low", "normal", "high", "urgent"]

class LinkedEscalationTicketResponse(BaseModel):
    """Ticket currently linked to an escalation."""
    model_config = ConfigDict(extra="forbid")
    ticket_id: uuid.UUID
    ticket_number: int = Field(ge=1)
    ticket_reference: str = Field(min_length=1, max_length=32)
    status: TicketStatus

class EscalationResponse(BaseModel):
    """API representation of one support escalation."""
    model_config = ConfigDict(extra="forbid")
    escalation_id: uuid.UUID
    conversation_id: uuid.UUID
    ai_run_id: uuid.UUID | None = None
    trigger_message_id: uuid.UUID | None = None
    source: Literal["decision", "guardrail", "system", "manual"]
    reason_code: str = Field(min_length=1, max_length=100)
    reason_summary: str | None = Field(default=None, max_length=2_000)
    priority: EscalationPriority
    status: EscalationStatus
    handoff_summary: str | None = Field(default=None, max_length=5_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None

class EscalationDetailResponse(EscalationResponse):
    """
    Detailed escalation representation including its linked ticket.

    Queue responses deliberately omit this relationship to avoid an additional ticket lookup for every queue item.
    """
    linked_ticket: LinkedEscalationTicketResponse | None = None

class EscalationListResponse(BaseModel):
    """Paginated escalation queue response."""
    model_config = ConfigDict(extra="forbid")
    items: list[EscalationResponse]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    has_more: bool

class UpdateEscalationRequest(BaseModel):
    """
    Request to transition an escalation.

    Terminal transitions require a customer-visible explanation so the customer is never left with an unexplained resolution or dismissal.
    This field must not contain internal notes, diagnostic information, provider errors, or unrestricted metadata.
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: EscalationStatus
    customer_message: str | None = Field(
        default=None,
        min_length=1,
        max_length=2_000,
        description=(
            "Customer-visible explanation required when status is 'resolved' or 'dismissed'. It must be omitted for non-terminal transitions."
        ),
    )

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("customer_message")
    @classmethod
    def normalize_customer_message(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("customer_message cannot be blank")

        return normalized

    @model_validator(mode="after")
    def validate_customer_message(self) -> "UpdateEscalationRequest":
        terminal_statuses = {"resolved", "dismissed",}
        if self.status in terminal_statuses and self.customer_message is None:
            raise ValueError("customer_message is required when status is 'resolved' or 'dismissed'")

        if self.status not in terminal_statuses and self.customer_message is not None:
            raise ValueError("customer_message may only be supplied when status is 'resolved' or 'dismissed'")

        return self

class UpdateEscalationResponse(BaseModel):
    """
    Result of an escalation lifecycle update.

    `notification_message_id` identifies the deterministic customer-visible conversation notice created by a successful state
    transition. It is null for an idempotent replay that made no change.
    """
    model_config = ConfigDict(extra="forbid")
    escalation_id: uuid.UUID
    conversation_id: uuid.UUID
    ai_run_id: uuid.UUID | None = None
    previous_status: EscalationStatus
    current_status: EscalationStatus
    resolved_at: datetime | None = None
    updated_at: datetime
    changed: bool
    notification_message_id: uuid.UUID | None = Field(
        default=None,
        description="Customer-visible lifecycle notification created for this transition. Null when no state change occurred.",
    )

class CustomerLinkedTicketResponse(BaseModel):
    """
    Minimal ticket relationship exposed to the customer.

    The customer can use `ticket_id` with the authorized ticket-detail endpoint to retrieve customer-visible comments.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)
    ticket_id: uuid.UUID
    ticket_reference: str = Field(min_length=1, max_length=32)
    status: TicketStatus
    
class CustomerEscalationStatusResponse(BaseModel):
    """
    Sanitized escalation status visible to the customer who owns the associated conversation.

    Internal AI, guardrail, handoff, and diagnostic details are excluded.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)
    escalation_id: uuid.UUID
    conversation_id: uuid.UUID
    status: EscalationStatus
    priority: EscalationPriority
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    linked_ticket: CustomerLinkedTicketResponse | None = Field(
        default=None,
        description="Customer-safe linked ticket summary when the escalation has been converted into a support ticket.",
    )