# AI-customer-support-agent\packages\ai\intent\schemas.py
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from enum import StrEnum

from packages.ai.intent.taxonomy import IntentType

class EscalationSignal(StrEnum):
    """
    Allowlisted classifier signals that may require human support.

    These are semantic observations only. They do not create escalations or set priority by themselves.
    The deterministic decision layer remains responsible for routing.

    Values may be persisted in sanitized AI telemetry and therefore must not be renamed casually.
    """
    EXPLICIT_HUMAN_REQUEST = "explicit_human_request"
    SEVERE_CUSTOMER_DISSATISFACTION = "severe_customer_dissatisfaction"

class IntentEntities(BaseModel):
    """
    Structured entities extracted while classifying customer intent.

    This model is conservative.

    Only fields that are useful across multiple downstream workflows live here.
    Intent-specific details can be stored inside `attributes` until they justify becoming first-class fields.
    """
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    order_id: str | None = Field(
        default=None,
        max_length=128,
        description="Customer/order identifier if explicitly provided.",
    )
    transaction_id: str | None = Field(
        default=None,
        max_length=128,
        description="Payment or transaction identifier if explicitly provided.",
    )
    subscription_id: str | None = Field(
        default=None,
        max_length=128,
        description="Subscription identifier if explicitly provided.",
    )
    account_id: str | None = Field(
        default=None,
        max_length=128,
        description="Account identifier if explicitly provided.",
    )
    issue_type: str | None = Field(
        default=None,
        max_length=100,
        description="Optional normalized subtype such as duplicate_charge, payment_declined, delayed_delivery, or account_locked."
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional low-risk extracted attributes that do not yet deserve first-class schema fields."
    )

    @field_validator("order_id", "transaction_id", "subscription_id", "account_id", "issue_type",)
    @classmethod
    def normalize_optional_strings(cls, value: str | None, ) -> str | None:
        """
        Convert empty/whitespace-only strings into None.

        LLMs frequently emit empty strings instead of null values.
        Normalizing here prevents downstream code from needing to handle both representations.
        """
        if value is None:
            return None

        value = value.strip()
        return value or None
    
class IntentResult(BaseModel):
    """
    Validated result of customer intent classification.

    This object is the canonical boundary between:
        `probabilistic classification` & `deterministic routing/business logic`.

    Downstream components should consume IntentResult rather than raw model/provider responses.
    """
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True, validate_assignment=True)
    intent: IntentType = Field(description="Canonical intent selected from the supported taxonomy.")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Classifier confidence in [0, 1]. This is a model-produced confidence signal and should not automatically be treated as a calibrated probability.",
    )
    entities: IntentEntities = Field(default_factory=IntentEntities)
    needs_clarification: bool = Field(
        default=False,
        description="Whether the current customer request lacks information required for safe downstream handling."
    )
    escalation_signals: tuple[EscalationSignal, ...] = Field(
        default_factory=tuple,
        description="Allowlisted semantic signals indicating that the request may require human support. These signals are interpreted only by the deterministic decision layer.",
    )
    reason_summary: str = Field(
        min_length=1,
        max_length=500,
        description="Concise, audit-friendly rationale for the classification. This must not contain hidden chain-of-thought.",
    )

    @field_validator("reason_summary")
    @classmethod
    def normalize_reason_summary(cls, value: str, ) -> str:
        """Collapse excessive whitespace and reject effectively empty output."""
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("reason_summary cannot be empty")

        return normalized

    @model_validator(mode="after")
    def validate_semantics(self) -> IntentResult:
        """Validate relationships between fields rather than validating individual fields in isolation.        """
        if self.intent is IntentType.UNKNOWN:
            if not self.needs_clarification:
                raise ValueError("UNKNOWN intent must require clarification")
            
        if len(self.escalation_signals) != len(set(self.escalation_signals)):
            raise ValueError("escalation_signals cannot contain duplicates")

        return self