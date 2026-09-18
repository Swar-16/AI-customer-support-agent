# AI-customer-support-agent\packages\ai\conversation_title\models.py
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from pydantic import BaseModel, ConfigDict, Field, field_validator

GENERATED_TITLE_MAX_LENGTH: Final[int] = 80

# The provider boundary accepts slightly more text than the final persisted contract.
# The sanitizer is responsible for removing quotes, Markdown, labels, and other harmless formatting before enforcing the final limit.
PROVIDER_TITLE_MAX_LENGTH: Final[int] = 500

class ConversationTitleSource(StrEnum):
    """
    Origin of a validated conversation title.

    These values are safe, low-cardinality telemetry and audit metadata. They contain no customer-authored content.
    """
    PROVIDER = "provider"
    FALLBACK = "fallback"

class ConversationTitleOutput(BaseModel):
    """
    Structured output requested from the LLM provider.

    This is only the provider boundary. A successfully parsed value must still pass through the deterministic
    title sanitizer before it can be persisted or returned to another application component.
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(
        ...,
        min_length=1,
        max_length=PROVIDER_TITLE_MAX_LENGTH,
        description="A concise plain-text title describing the customer's support request.",
    )

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("title cannot be blank")

        return normalized

@dataclass(frozen=True, slots=True)
class ConversationTitleResult:
    """
    Final safe title produced by the title-generation subsystem.

    Invariants:

    - title is normalized single-line plain text;
    - title fits the generated-title persistence policy;
    - source is safe to record in audit and telemetry metadata;
    - no raw provider response or customer message is retained here.
    """
    title: str
    source: ConversationTitleSource

    def __post_init__(self) -> None:
        if not isinstance(self.title, str):
            raise TypeError("title must be a string")

        normalized = " ".join(self.title.split())
        if not normalized:
            raise ValueError("title cannot be blank")

        if len(normalized) > GENERATED_TITLE_MAX_LENGTH:
            raise ValueError(f"title must not exceed {GENERATED_TITLE_MAX_LENGTH} characters")

        if not isinstance(self.source, ConversationTitleSource):
            raise TypeError("source must be a ConversationTitleSource")

        object.__setattr__(self, "title", normalized)