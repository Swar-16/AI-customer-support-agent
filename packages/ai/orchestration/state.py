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


class RetrievalContext(BaseModel):
    """
    Placeholder contract for retrieval output.

    We deliberately keep this minimal for now.
    Later this can evolve into richer retrieval objects with:
    - chunk IDs
    - document IDs
    - vector scores
    - lexical scores
    - reranker scores
    - policy versions
    """
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    chunk_id: uuid.UUID | None = None

    document_id: uuid.UUID | None = None

    content: str = Field(
        min_length=1,
    )

    score: float | None = Field(
        default=None,
        ge=0.0,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


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
    customer_message: str = Field(
        min_length=1,
        max_length=20_000,
    )
    conversation_context: str | None = Field(
        default=None,
        max_length=50_000,
    )

    # Pipeline state
    stage: PipelineStage = PipelineStage.RECEIVED
    intent_result: IntentResult | None = None
    decision_result: DecisionResult | None = None
    retrieval_context: tuple[RetrievalContext, ...] = Field(
        default_factory=tuple,
    )
    generated_response: str | None = None

    # Future orchestration outputs
    proposed_action_id: uuid.UUID | None = None
    escalation_id: uuid.UUID | None = None
    response_message_id: uuid.UUID | None = None

    # Failure / diagnostic state
    errors: tuple[PipelineError, ...] = Field(
        default_factory=tuple,
    )

    # Execution timestamps
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    completed_at: datetime | None = None

    # Free-form non-authoritative orchestration metadata
    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

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

    def with_retrieval_context(self, context: tuple[RetrievalContext, ...]) -> AIState:
        """
        Return a copy containing retrieved grounding context.
        """
        if self.decision_result is None:
            raise ValueError("Cannot attach retrieval context before a decision")

        return self.model_copy(
            update={
                "retrieval_context": context,
                "stage": PipelineStage.RETRIEVAL_COMPLETED,
            }
        )

    def with_generated_response(self, response: str) -> AIState:
        """
        Return a copy containing generated assistant response.
        """
        if self.decision_result is None:
            raise ValueError("Cannot generate response before decision")
        
        normalized = response.strip()
        if not normalized:
            raise ValueError("Generated response cannot be empty")

        return self.model_copy(
            update={
                "generated_response": normalized,
                "stage": PipelineStage.RESPONSE_GENERATED,
            }
        )

    def with_error(self, error: PipelineError) -> AIState:
        """
        Return a failed-state copy with the new error appended.
        """
        return self.model_copy(
            update={
                "errors": (*self.errors, error),
                "stage": PipelineStage.FAILED,
                "completed_at": datetime.now(timezone.utc),
            }
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