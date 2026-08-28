from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TypeVar
from pydantic import BaseModel

from packages.ai.providers.types import LLMResponse, StructuredLLMResponse

T = TypeVar("T", bound=BaseModel)

class LLMProvider(ABC):
    """
    Provider-neutral interface for LLM backends.

    Concrete implementations may wrap:
    - Groq
    - OpenAI
    - Gemini
    - Anthropic
    - local models
    - MockLLMProvider

    Callers depend only on this contract.
    """
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Canonical provider identifier."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Configured model identifier."""
        ...

    @abstractmethod
    def generate(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        """
        Generate a plain-text model response with normalized provider metadata.
        """
        ...

    @abstractmethod
    def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model: type[T]) -> StructuredLLMResponse[T]:
        """
        Generate output validated against a Pydantic response model.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """
        Return whether the provider is currently usable.

        Implementations should keep this lightweight and avoid mutating
        normal request state.
        """
        ...