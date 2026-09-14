# AI-customer-support-agent\apps\api\app\api\v1\schemas\tickets.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TicketSource = Literal["customer", "escalation", "agent", "system",]
TicketCategory = Literal["billing", "refund", "order", "account", "technical", "security", "product", "general", "other",]
TicketPriority = Literal["low", "normal", "high", "urgent",]
TicketStatus = Literal["open", "in_progress", "waiting_for_customer", "resolved", "closed", "reopened",]
TicketRequesterRole = Literal["customer", "support_agent", "admin",]
TicketCommentAuthorRole = Literal["customer", "support_agent", "admin", "system",]
TicketCommentVisibility = Literal["customer", "internal",]

class TicketAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

# Creation
class CreateTicketRequest(TicketAPIModel):
    customer_id: uuid.UUID | None = None
    subject: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1, max_length=20_000)
    category: TicketCategory = "general"
    priority: TicketPriority = "normal"
    source_message_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("subject", "description")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")

        return normalized

class CreateTicketResponse(TicketAPIModel):
    ticket_id: uuid.UUID
    ticket_number: int
    ticket_reference: str
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    escalation_id: uuid.UUID | None = None
    status: TicketStatus
    priority: TicketPriority
    category: TicketCategory
    created: bool

# Updates
class UpdateTicketRequest(TicketAPIModel):
    expected_row_version: int = Field(..., ge=1)
    target_status: TicketStatus | None = None
    priority: TicketPriority | None = None
    category: TicketCategory | None = None
    assigned_agent_id: uuid.UUID | None = None
    unassign: bool = False
    resolution_summary: str | None = Field(default=None, max_length=5_000)

    @field_validator("resolution_summary")
    @classmethod
    def validate_resolution_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("resolution_summary cannot be blank")

        return normalized

    @model_validator(mode="after")
    def validate_mutation(self) -> UpdateTicketRequest:
        if self.assigned_agent_id is not None and self.unassign:
            raise ValueError("assigned_agent_id and unassign cannot be supplied together")

        has_mutation = any((self.target_status is not None, self.priority is not None, self.category is not None, self.assigned_agent_id is not None, self.unassign,))
        if not has_mutation:
            raise ValueError("at least one ticket mutation must be supplied")

        if self.target_status == "resolved" and self.resolution_summary is None:
            raise ValueError("resolution_summary is required when target_status='resolved'")

        if self.target_status != "resolved" and self.resolution_summary is not None:
            raise ValueError("resolution_summary may only be supplied when target_status='resolved'")

        return self

class UpdateTicketResponse(TicketAPIModel):
    ticket_id: uuid.UUID
    ticket_number: int
    ticket_reference: str
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    previous_status: TicketStatus
    current_status: TicketStatus
    priority: TicketPriority
    category: TicketCategory
    assigned_agent_id: uuid.UUID | None = None
    resolution_summary: str | None = None
    row_version: int
    assigned_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    updated_at: datetime
    changed: bool

# Comments
class AddTicketCommentRequest(TicketAPIModel):
    visibility: TicketCommentVisibility = "customer"
    content: str = Field(..., min_length=1, max_length=20_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content cannot be blank")

        return normalized

class AddTicketCommentResponse(TicketAPIModel):
    comment_id: uuid.UUID
    ticket_id: uuid.UUID
    author_id: uuid.UUID | None = None
    author_role: TicketCommentAuthorRole
    visibility: TicketCommentVisibility
    content: str
    created_at: datetime

# Queries
class TicketCommentResponse(TicketAPIModel):
    comment_id: uuid.UUID
    ticket_id: uuid.UUID
    author_id: uuid.UUID | None = None
    author_role: TicketCommentAuthorRole
    visibility: TicketCommentVisibility
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

class TicketResponse(TicketAPIModel):
    ticket_id: uuid.UUID
    ticket_number: int
    ticket_reference: str
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    source_message_id: uuid.UUID | None = None
    escalation_id: uuid.UUID | None = None
    assigned_agent_id: uuid.UUID | None = None
    source: TicketSource
    subject: str
    description: str
    category: TicketCategory
    priority: TicketPriority
    status: TicketStatus
    resolution_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    row_version: int
    created_at: datetime
    updated_at: datetime
    assigned_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None

class TicketDetailResponse(TicketAPIModel):
    ticket: TicketResponse
    comments: list[TicketCommentResponse]

class TicketListResponse(TicketAPIModel):
    items: list[TicketResponse]
    count: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=200)
    offset: int = Field(..., ge=0)
    has_more: bool