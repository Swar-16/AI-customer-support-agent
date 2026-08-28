from __future__ import annotations
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DecisionType(StrEnum):
    ANSWER = "answer"
    RETRIEVE_INFORMATION = "retrieve_information"
    PERFORM_ACTION = "perform_action"
    ASK_CLARIFICATION = "ask_clarification"
    ESCALATE = "escalate"


class DecisionReasonCode(StrEnum):
    """
    Stable machine-readable reason codes.

    These are intentionally separate from free-text reason summaries
    because dashboards, evaluation, and routing should not depend on
    natural-language strings.
    """

    DIRECT_INFORMATIONAL_RESPONSE = "direct_informational_response"

    POLICY_RETRIEVAL_REQUIRED = "policy_retrieval_required"
    OPERATIONAL_LOOKUP_REQUIRED = "operational_lookup_required"

    MISSING_REQUIRED_INFORMATION = "missing_required_information"
    LOW_INTENT_CONFIDENCE = "low_intent_confidence"
    UNKNOWN_INTENT = "unknown_intent"

    ACTION_REQUEST_DETECTED = "action_request_detected"

    HUMAN_APPROVAL_REQUIRED = "human_approval_required"
    SECURITY_SENSITIVE_REQUEST = "security_sensitive_request"
    UNSUPPORTED_REQUEST = "unsupported_request"

    POLICY_CONFLICT = "policy_conflict"
    KNOWLEDGE_UNAVAILABLE = "knowledge_unavailable"


class DecisionResult(BaseModel):
    """
    Canonical output of the deterministic decision layer.

    This result determines what the orchestration layer should do next.
    """
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    decision: DecisionType

    reason_code: DecisionReasonCode

    reason_summary: str = Field(
        min_length=1,
        max_length=500,
    )

    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional confidence associated with the decision. For deterministic decisions this may be omitted."
    )

    required_information: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Information required before this workflow can proceed, for example order_id or transaction_id."
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-authoritative routing metadata. Sensitive business decisions must not depend on arbitrary metadata."
    )

    @field_validator("reason_summary")
    @classmethod
    def normalize_reason_summary(cls, value: str) -> str:
        normalized = " ".join(value.split())

        if not normalized:
            raise ValueError("reason_summary cannot be empty")

        return normalized

    @field_validator("required_information")
    @classmethod
    def normalize_required_information(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []

        for item in value:
            clean = item.strip()

            if not clean:
                raise ValueError(
                    "required_information cannot contain empty values"
                )

            if clean not in normalized:
                normalized.append(clean)

        return tuple(normalized)

    @model_validator(mode="after")
    def validate_semantics(self) -> DecisionResult:
        if(
            self.decision is DecisionType.ASK_CLARIFICATION
            and not self.required_information
        ):
            raise ValueError("ASK_CLARIFICATION must identify required information")

        if(
            self.decision is not DecisionType.ASK_CLARIFICATION
            and self.required_information
        ):
            raise ValueError("required_information may only be populated for ASK_CLARIFICATION")

        return self