from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.ai.decision.schemas import DecisionResult
from packages.ai.intent.schemas import IntentResult


class PipelineStage(StrEnum):
    """
    Canonical execution stages for the AI workflow.

    These values are useful for:
    - orchestration
    - tracing
    - structured logging
    - failure analysis
    - dashboards
    """
    RECEIVED = "received"
    CONTEXT_BUILT = "context_built"
    INTENT_CLASSIFIED = "intent_classified"
    DECISION_MADE = "decision_made"

    RETRIEVAL_COMPLETED = "retrieval_completed"
    RESPONSE_GENERATED = "response_generated"
    GUARDRAILS_COMPLETED = "guardrails_completed"

    ACTION_PROPOSED = "action_proposed"
    ACTION_COMPLETED = "action_completed"

    ESCALATED = "escalated"

    COMPLETED = "completed"
    FAILED = "failed"


class PipelineError(BaseModel):
    """
    Structured representation of an error encountered during orchestration.

    Avoid passing raw exceptions throughout the pipeline.
    The orchestrator should convert exceptions into structured errors
    for observability and persistence.
    """
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    code: str = Field(
        min_length=1,
        max_length=100,
    )

    message: str = Field(
        min_length=1,
        max_length=1000,
    )

    stage: PipelineStage

    retryable: bool = False

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class EvidenceSourceType(StrEnum):
    """
    Broad origin of evidence used by the AI workflow.

    The orchestration layer deliberately models evidence by source category
    rather than by concrete infrastructure.

    KNOWLEDGE:
        Versioned support knowledge such as policies, FAQs, procedures,
        guides, and other published reference material.

    OPERATIONAL:
        Runtime business facts such as order state, payment state,
        subscription state, or account information.

    SYSTEM:
        Trusted system-produced evidence that does not belong to either
        customer-facing knowledge or an operational business system.
    """

    KNOWLEDGE = "knowledge"
    OPERATIONAL = "operational"
    SYSTEM = "system"


class RetrievedEvidence(BaseModel):
    """
    Provider-neutral evidence made available to downstream AI stages.

    This is the orchestration boundary for retrieved information.

    It deliberately does NOT expose knowledge-specific implementation concepts such as:
        - vector distance
        - lexical rank
        - RRF score
        - embedding model
        - pgvector
        - reranker implementation

    Those remain inside the knowledge/retrieval subsystem.

    Likewise, operational tools may later produce this same contract without pretending their results are knowledge-base chunks.

    `source_id` is represented as a string because different evidence sources may use different identifier formats:
        - UUID knowledge chunk IDs
        - order IDs
        - transaction IDs
        - external system identifiers
    """
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    source_type: EvidenceSourceType
    content: str = Field(min_length=1, max_length=50_000)
    source_id: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=500)
    section: str | None = Field(default=None, max_length=500)
    relevance_score: float | None = Field(default=None, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content cannot be empty")

        return normalized

    @field_validator("source_id", "title", "section")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

class AIState(BaseModel):
    """
    Canonical execution state for one AI-support workflow.

    This object moves through the orchestration pipeline.

    Typical evolution:

    RECEIVED  ->  INTENT_CLASSIFIED  ->   DECISION_MADE  ->   RETRIEVAL_COMPLETED
                                                                        ↓
    COMPLETED <- GUARDRAILS_COMPLETED <- GUARDRAILS_COMPLETED <- RESPONSE_GENERATED

    The state stores outputs of completed stages but does not itself
    execute business logic.
    """
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )


    # Correlation / persistence identity
    ai_run_id: uuid.UUID
    trace_id: uuid.UUID
    conversation_id: uuid.UUID
    trigger_message_id: uuid.UUID

    # Input
    customer_message: str = Field(min_length=1, max_length=20_000)
    conversation_context: str | None = Field(default=None, max_length=50_000)

    # Pipeline state
    stage: PipelineStage = PipelineStage.RECEIVED
    intent_result: IntentResult | None = None
    decision_result: DecisionResult | None = None
    retrieved_evidence: tuple[RetrievedEvidence, ...] = Field(default_factory=tuple)
    generated_response: str | None = None

    # Future orchestration outputs
    proposed_action_id: uuid.UUID | None = None
    escalation_id: uuid.UUID | None = None
    response_message_id: uuid.UUID | None = None

    # Failure / diagnostic state
    errors: tuple[PipelineError, ...] = Field(default_factory=tuple)

    # Execution timestamps
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    # Free-form non-authoritative orchestration metadata
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("customer_message")
    @classmethod
    def normalize_customer_message(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("customer_message cannot be empty")

        return normalized

    @field_validator("conversation_context")
    @classmethod
    def normalize_context(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()

        return normalized or None

    @field_validator("generated_response")
    @classmethod
    def normalize_generated_response(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()

        return normalized or None

    @model_validator(mode="after")
    def validate_stage_invariants(self) -> AIState:
        """
        Enforce invariants between pipeline stage and accumulated state.

        These checks prevent impossible states such as:
            stage=DECISION_MADE
            intent_result=None
        """
        if self.stage in {
            PipelineStage.INTENT_CLASSIFIED,
            PipelineStage.DECISION_MADE,
            PipelineStage.RETRIEVAL_COMPLETED,
            PipelineStage.RESPONSE_GENERATED,
            PipelineStage.GUARDRAILS_COMPLETED,
            PipelineStage.ACTION_PROPOSED,
            PipelineStage.ACTION_COMPLETED,
            PipelineStage.ESCALATED,
            PipelineStage.COMPLETED,
        }:
            if self.intent_result is None:
            # Once we have reached INTENT_CLASSIFIED or anything after it, intent_result must exist.
                raise ValueError(f"{self.stage.value} requires intent_result")

        if self.stage in {
            PipelineStage.DECISION_MADE,
            PipelineStage.RETRIEVAL_COMPLETED,
            PipelineStage.RESPONSE_GENERATED,
            PipelineStage.GUARDRAILS_COMPLETED,
            PipelineStage.ACTION_PROPOSED,
            PipelineStage.ACTION_COMPLETED,
            PipelineStage.ESCALATED,
            PipelineStage.COMPLETED,
        }:
            if self.decision_result is None:
            # Once we've reached DECISION_MADE or anything after it, decision_result must exist.
                raise ValueError(f"{self.stage.value} requires decision_result")

        if self.stage is PipelineStage.RESPONSE_GENERATED:
            if self.generated_response is None:
                raise ValueError("RESPONSE_GENERATED requires generated_response")

        if self.stage is PipelineStage.COMPLETED:
            if self.completed_at is None:
                raise ValueError("COMPLETED requires completed_at")

        if self.stage is PipelineStage.FAILED:
            if not self.errors:
                raise ValueError("FAILED state requires at least one error")

        return self

    def with_intent(self, result: IntentResult) -> AIState:
        """
        Return a copy representing successful intent classification.
        """
        if not isinstance(result, IntentResult):
            raise TypeError(f"with_intent() expects an IntentResult, got {type(result).__name__}")
        
        return self.model_copy(
            update={
                "intent_result": result,
                "stage": PipelineStage.INTENT_CLASSIFIED,
            }
        )

    def with_decision(self, result: DecisionResult) -> AIState:
        """
        Return a copy representing successful routing decision.
        """
        if not isinstance(result, DecisionResult):
            raise TypeError(f"with_decision() expects a DecisionResult, got {type(result).__name__}")
        if self.intent_result is None:
            raise ValueError("Cannot add decision before intent classification")

        return self.model_copy(
            update={
                "decision_result": result,
                "stage": PipelineStage.DECISION_MADE,
            }
        )

    def with_retrieved_evidence(self, evidence: tuple[RetrievedEvidence, ...]) -> AIState:
        """
        Return a copy containing evidence produced by a completed retrieval stage.

        An empty tuple is valid: retrieval may complete successfully without finding sufficiently relevant evidence.
        Downstream policy/guardrails decide how that situation should be handled.
        """
        if self.decision_result is None:
            raise ValueError("Cannot attach retrieved evidence before a decision")

        if not isinstance(evidence, tuple):
            raise TypeError("with_retrieved_evidence() expects tuple[RetrievedEvidence, ...]")

        for index, item in enumerate(evidence):
            if not isinstance(item, RetrievedEvidence):
                raise TypeError(f"with_retrieved_evidence() expects every item to be RetrievedEvidence; item {index} is {type(item).__name__}")

        return self.model_copy(update={"retrieved_evidence": evidence, "stage": PipelineStage.RETRIEVAL_COMPLETED,})

    def with_generated_response(self, response: str) -> AIState:
        """
        Return a copy containing the generated assistant response.
        """
        if self.decision_result is None:
            raise ValueError("Cannot generate response before decision")

        if not isinstance(response, str):
            raise TypeError("response must be a string")

        normalized = response.strip()
        if not normalized:
            raise ValueError("Generated response cannot be empty")

        return self.model_copy(update={"generated_response": normalized, "stage": PipelineStage.RESPONSE_GENERATED,})

    def with_error(self, error: PipelineError) -> AIState:
        """
        Return a failed-state copy with the new error appended.
        """
        if not isinstance(error, PipelineError):
            raise TypeError(f"with_error() expects a PipelineError, got {type(error).__name__}")

        return self.model_copy(
            update={"errors": (*self.errors, error), "stage": PipelineStage.FAILED, "completed_at": datetime.now(timezone.utc),}
        )

    def complete(self) -> AIState:
        """
        Mark the workflow as successfully completed.
        """
        if self.intent_result is None:
            raise ValueError("Cannot complete workflow without intent_result")

        if self.decision_result is None:
            raise ValueError("Cannot complete workflow without decision_result")

        return self.model_copy(
            update={
                "stage": PipelineStage.COMPLETED,
                "completed_at": datetime.now(timezone.utc),
            }
        )