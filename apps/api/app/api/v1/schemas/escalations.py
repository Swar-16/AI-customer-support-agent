# AI-customer-support-agent\apps\api\app\api\v1\schemas\escalations.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

EscalationStatus = Literal["open", "in_review", "resolved", "dismissed"]
EscalationPriority = Literal["low", "normal", "high", "urgent"]

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

class EscalationListResponse(BaseModel):
    """Paginated escalation queue response."""
    model_config = ConfigDict(extra="forbid")
    items: list[EscalationResponse]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    has_more: bool

class UpdateEscalationRequest(BaseModel):
    """Request to transition an escalation to another state."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: EscalationStatus

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        return value.strip().lower()


class UpdateEscalationResponse(BaseModel):
    """Result of an escalation lifecycle update."""
    model_config = ConfigDict(extra="forbid")
    escalation_id: uuid.UUID
    conversation_id: uuid.UUID
    ai_run_id: uuid.UUID | None = None
    previous_status: EscalationStatus
    current_status: EscalationStatus
    resolved_at: datetime | None = None
    updated_at: datetime
    changed: bool
    
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