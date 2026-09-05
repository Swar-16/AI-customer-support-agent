# packages/guardrails/models.py
from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.ai.decision.schemas import DecisionResult
from packages.ai.orchestration.state import RetrievedEvidence


class GuardrailOutcome(StrEnum):
    """
    Final disposition produced by deterministic response guardrails.

    PASS:
        The generated response may be exposed to the customer.

    REFUSE:
        The response must not be exposed and the request should receive a safe refusal response.

    ESCALATE:
        The generated response must not be exposed as authoritative and the workflow should be transferred to a human-support path.
    """
    PASS = "pass"
    REFUSE = "refuse"
    ESCALATE = "escalate"

class GuardrailReasonCode(StrEnum):
    """
    Stable machine-readable reasons emitted by guardrail evaluation.

    These values are suitable for telemetry, persistence, evaluation, dashboards, and escalation routing.
    """
    SAFE_RESPONSE = "safe_response"
    MISSING_GENERATED_RESPONSE = "missing_generated_response"
    DECISION_RESPONSE_MISMATCH = "decision_response_mismatch"
    UNSUPPORTED_KNOWLEDGE_CLAIM = "unsupported_knowledge_claim"
    UNSUPPORTED_OPERATIONAL_CLAIM = "unsupported_operational_claim"
    INVALID_CITATION_REFERENCE = "invalid_citation_reference"
    SENSITIVE_ACTION_CLAIM = "sensitive_action_claim"
    SAFETY_RESTRICTION = "safety_restriction"

class GuardrailContext(BaseModel):
    """
    Immutable input supplied to deterministic guardrail policies.

    Guardrails deliberately receive a narrow application-neutral contract instead of the entire mutable AIState.

    This prevents guardrail policies from:
        - mutating orchestration state;
        - depending on pipeline implementation details;
        - reaching into retrieval infrastructure;
        - making business workflow decisions themselves.

    `generated_response` is the customer-visible text proposed by the generation stage.

    `retrieved_evidence` contains the provider-neutral evidence that was available to generation.

    Structured grounding/citation information can be added to this contract once AIState preserves GroundedGenerationResult metadata.
    """
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
    customer_message: str = Field(min_length=1, max_length=20_000)
    decision: DecisionResult
    generated_response: str | None = Field(default=None, max_length=30_000)
    retrieved_evidence: tuple[RetrievedEvidence, ...] = Field(default_factory=tuple)

    @field_validator("customer_message")
    @classmethod
    def normalize_customer_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("customer_message cannot be empty")

        return normalized

    @field_validator("generated_response")
    @classmethod
    def normalize_generated_response(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None


class GuardrailResult(BaseModel):
    """
    Immutable result of guardrail evaluation.

    `reason_summary` is diagnostic/audit information. It is not intended to expose private chain-of-thought or internal model reasoning.
    """
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
    outcome: GuardrailOutcome
    reason_code: GuardrailReasonCode
    reason_summary: str = Field(min_length=1, max_length=1_000)
    policy_id: str | None = Field(default=None, max_length=100)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("reason_summary")
    @classmethod
    def normalize_reason_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason_summary cannot be empty")

        return normalized

    @field_validator("policy_id")
    @classmethod
    def normalize_policy_id(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @property
    def passed(self) -> bool:
        return self.outcome is GuardrailOutcome.PASS