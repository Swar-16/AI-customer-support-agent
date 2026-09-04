from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.ai.intent.schemas import IntentResult
from packages.ai.orchestration.state import RetrievedEvidence


class GroundingStatus(StrEnum):
    """
    Describes how the generated answer relates to supplied evidence.

    GROUNDED:
        The answer is supported by retrieved evidence.

    INSUFFICIENT_EVIDENCE:
        The supplied evidence is not sufficient to answer the customer's question reliably.

    NOT_REQUIRED:
        The response does not require retrieved evidence, for example a clarification question.
    """
    GROUNDED = "grounded"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_REQUIRED = "not_required"


class Citation(BaseModel):
    """
    Reference to evidence used by the generated answer.

    `source_id` corresponds to RetrievedEvidence.source_id rather than exposing knowledge-specific chunk/document concepts.
    """
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
    source_id: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=500)
    section: str | None = Field(default=None, max_length=500)

class GroundedGenerationRequest(BaseModel):
    """
    Input contract for grounded response generation.

    The generator receives only the information necessary to formulate a response.
    It does not receive AIState itself and therefore cannot mutate or make orchestration decisions.
    """
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
    customer_message: str = Field(min_length=1, max_length=20_000)
    intent: IntentResult
    evidence: tuple[RetrievedEvidence, ...] = Field(default_factory=tuple)
    conversation_context: str | None = Field(default=None, max_length=30_000)

    @field_validator("customer_message")
    @classmethod
    def normalize_customer_message(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("customer_message cannot be empty")

        return normalized

    @field_validator("conversation_context")
    @classmethod
    def normalize_conversation_context(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

class GroundedGenerationResult(BaseModel):
    """
    Structured output returned by the response-generation layer.

    The result intentionally separates:
        - customer-visible answer;
        - grounding classification;
        - source citations.

    Guardrail evaluation happens after this stage.
    """
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
    answer: str = Field(min_length=1, max_length=30_000)
    grounding_status: GroundingStatus
    citations: tuple[Citation, ...] = Field(default_factory=tuple)

    @field_validator("answer")
    @classmethod
    def normalize_answer(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("answer cannot be empty")

        return normalized