from __future__ import annotations
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from packages.knowledge.retrieval.models import RetrievalFilters
from packages.knowledge.retrieval.query.errors import InvalidConversationContextError, InvalidCustomerMessageError, InvalidEntityHintsError
from packages.knowledge.retrieval.query.errors import InvalidIntentHintError, InvalidLexicalQueryError, InvalidOriginalQueryError
from packages.knowledge.retrieval.query.errors import InvalidSemanticQueryError, InvalidTrustedFiltersError, MissingLexicalQueriesError

def _normalize_text(value: str, *, field_name: str, error_type: type[Exception]) -> str:
    if not isinstance(value, str):
        raise error_type(f"{field_name} must be a string")

    normalized = " ".join(value.split())
    if not normalized:
        raise error_type(f"{field_name} cannot be empty")

    return normalized

def _normalize_optional_text(value: str | None, *, field_name: str, error_type: type[Exception]) -> str | None:
    if value is None:
        return None

    return _normalize_text(value, field_name=field_name, error_type=error_type)

def _normalize_entities(entities: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(entities, Mapping):
        raise InvalidEntityHintsError("entities must be a mapping")

    normalized: dict[str, str] = {}
    for key, value in entities.items():
        normalized_key = _normalize_text(key, field_name="entity key", error_type=InvalidEntityHintsError)
        normalized_value = _normalize_text(value, field_name=f"entity value for {normalized_key!r}", error_type=InvalidEntityHintsError)
        normalized[normalized_key] = normalized_value

    return MappingProxyType(normalized)

@dataclass(frozen=True, slots=True)
class RetrievalQueryContext:
    """
    Semantic input used to prepare retrieval queries.

    This object is intentionally independent from the AI intent-domain classes.

    `intent_key` is a stable semantic hint such as:
        "refund_request"
        "payment_issue"
        "general_question"

    The retrieval layer therefore does not need to import IntentType.

    Entities are semantic hints only. They MUST NOT automatically become hard retrieval filters.

    Hard filters belong in `filters` and must come from trusted application context.
    """
    customer_message: str
    intent_key: str | None = None
    entities: Mapping[str, str] = MappingProxyType({})
    filters: RetrievalFilters = RetrievalFilters()
    conversation_context: str | None = None

    def __post_init__(self) -> None:
        normalized_message = _normalize_text(self.customer_message, field_name="customer_message", error_type=InvalidCustomerMessageError)
        normalized_intent = _normalize_optional_text(self.intent_key, field_name="intent_key", error_type=InvalidIntentHintError)
        normalized_context = _normalize_optional_text(self.conversation_context, field_name="conversation_context", error_type=InvalidConversationContextError)
        normalized_entities = _normalize_entities(self.entities)

        if not isinstance(self.filters, RetrievalFilters):
            raise InvalidTrustedFiltersError("filters must be a RetrievalFilters instance")

        object.__setattr__(self, "customer_message", normalized_message)
        object.__setattr__(self, "intent_key", normalized_intent)
        object.__setattr__(self, "conversation_context", normalized_context)
        object.__setattr__(self, "entities", normalized_entities)

@dataclass(frozen=True, slots=True)
class PreparedRetrievalQuery:
    """
    Retrieval-specific representation of one customer request.

    `original_query`
        Canonical normalized customer message.

    `semantic_query`
        Natural-language representation intended for embedding/vector retrieval.

    `lexical_queries`
        Compact lexical variants intended for full-text retrieval.

    `filters`
        Trusted retrieval scope. These are copied from application context rather than inferred automatically from customer-controlled data.
    """
    original_query: str
    semantic_query: str
    lexical_queries: tuple[str, ...]
    filters: RetrievalFilters = RetrievalFilters()

    def __post_init__(self) -> None:
        original_query = _normalize_text(self.original_query, field_name="original_query", error_type=InvalidOriginalQueryError)
        semantic_query = _normalize_text(self.semantic_query, field_name="semantic_query", error_type=InvalidSemanticQueryError)

        if not isinstance(self.lexical_queries, tuple):
            raise InvalidLexicalQueryError("lexical_queries must be a tuple")

        lexical_queries: list[str] = []
        seen: set[str] = set()

        for query in self.lexical_queries:
            normalized = _normalize_text(query, field_name="lexical query", error_type=InvalidLexicalQueryError)
            dedupe_key = normalized.casefold()
            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)
            lexical_queries.append(normalized)

        if not lexical_queries:
            raise MissingLexicalQueriesError("lexical_queries must contain at least one usable query")

        if not isinstance(self.filters, RetrievalFilters):
            raise InvalidTrustedFiltersError("filters must be a RetrievalFilters instance")

        object.__setattr__(self, "original_query", original_query)
        object.__setattr__(self, "semantic_query", semantic_query)
        object.__setattr__(self, "lexical_queries", tuple(lexical_queries))