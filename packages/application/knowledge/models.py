from __future__ import annotations
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from packages.knowledge.retrieval.models import RetrievalFilters


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalRequest:
    """
    Application-level request for customer-facing knowledge retrieval.

    This object sits at the boundary between the AI/application workflow and the knowledge subsystem.

    `entities` are semantic hints extracted from customer language. They are untrusted retrieval hints and
    MUST NOT be interpreted as authorization or database-scope filters.

    `filters` are trusted application-controlled retrieval constraints, such as tenant, product, region, visibility, or content type.
    """
    customer_message: str
    intent_key: str
    entities: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    conversation_context: str | None = None

    def __post_init__(self) -> None:
        customer_message = self._normalize_required_text(
            self.customer_message,
            field_name="customer_message",
        )

        intent_key = self._normalize_required_text(
            self.intent_key,
            field_name="intent_key",
        )

        if not isinstance(self.entities, Mapping):
            raise TypeError("entities must be a mapping.")

        normalized_entities: dict[str, str] = {}
        for key, value in self.entities.items():
            if not isinstance(key, str):
                raise TypeError("entity keys must be strings.")

            if not isinstance(value, str):
                raise TypeError("entity values must be strings.")

            normalized_key = key.strip()
            normalized_value = value.strip()

            if not normalized_key:
                raise ValueError("entity keys must not be empty.")

            if not normalized_value:
                continue

            normalized_entities[normalized_key] = normalized_value

        if not isinstance(self.filters, RetrievalFilters):
            raise TypeError("filters must be a RetrievalFilters instance.")

        conversation_context = self.conversation_context
        if conversation_context is not None:
            if not isinstance(conversation_context, str):
                raise TypeError("conversation_context must be a string or None.")

            conversation_context = conversation_context.strip()
            if not conversation_context:
                conversation_context = None

        object.__setattr__(self, "customer_message", customer_message)
        object.__setattr__(self, "intent_key", intent_key)
        object.__setattr__(self, "entities", MappingProxyType(normalized_entities))
        object.__setattr__(self, "conversation_context", conversation_context)

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string.")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be empty.")

        return normalized