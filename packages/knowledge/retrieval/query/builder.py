from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Final
import regex
from abc import ABC, abstractmethod

from packages.knowledge.retrieval.query.errors import InvalidQueryPreparationConfigError, QueryConstructionError, QueryPreparationLimitError
from packages.knowledge.retrieval.query.models import PreparedRetrievalQuery, RetrievalQueryContext

# _TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", flags=re.UNICODE)
_TOKEN_PATTERN = regex.compile(r"[\p{L}\p{M}\p{N}]+(?:['’-][\p{L}\p{M}\p{N}]+)*")
_DEFAULT_STOP_WORDS: Final[frozenset[str]] = frozenset({
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "could", "did", "do", "does", "for", "from", "had", "has",
        "have", "how", "i", "if", "in", "into", "is", "it", "me", "my", "of", "on", "or", "please", "should", "that", "the", "their", "them",
        "there", "this", "to", "was", "were", "what", "when", "where", "which", "who", "why", "will", "with", "would", "you", "your"}
)


@dataclass(frozen=True, slots=True)
class RetrievalQueryBuilderConfig:
    """
    Configuration for deterministic retrieval-query preparation.

    The builder intentionally performs no LLM calls and contains no intent-specific business rules.

    `max_semantic_query_chars`
        Maximum size of the vector/semantic retrieval query.

    `max_lexical_query_chars`
        Maximum size of one lexical retrieval query.

    `max_lexical_terms`
        Maximum number of terms retained in the primary lexical query.

    `max_entity_hints`
        Safety limit for caller-supplied entity hints.

    `include_intent_hint`
        Whether the canonical intent key may contribute generic lexical vocabulary.

        Disabled by default because the customer's own wording is normally a better retrieval
        signal and intent identifiers such as "general_question" may introduce noise.

    `include_entity_hints`
        Whether non-identifier entity values may contribute lexical terms.

        Entity hints NEVER become RetrievalFilters.

    `include_issue_type_hint`
        Allows an extracted issue_type to enrich lexical retrieval.

        This remains generic because issue_type is a semantic subtype rather than a hard-coded intent branch.
    """
    max_semantic_query_chars: int = 4_000
    max_lexical_query_chars: int = 512
    max_lexical_terms: int = 24
    max_entity_hints: int = 32
    include_intent_hint: bool = False
    include_entity_hints: bool = True
    include_issue_type_hint: bool = True

    def __post_init__(self) -> None:
        positive_fields = {
            "max_semantic_query_chars": self.max_semantic_query_chars,
            "max_lexical_query_chars": self.max_lexical_query_chars,
            "max_lexical_terms": self.max_lexical_terms,
            "max_entity_hints": self.max_entity_hints,
        }

        for name, value in positive_fields.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise InvalidQueryPreparationConfigError(f"{name} must be an integer")

            if value <= 0:
                raise InvalidQueryPreparationConfigError(f"{name} must be greater than zero")

        boolean_fields = {
            "include_intent_hint": self.include_intent_hint,
            "include_entity_hints": self.include_entity_hints,
            "include_issue_type_hint": self.include_issue_type_hint,
        }

        for name, value in boolean_fields.items():
            if not isinstance(value, bool):
                raise InvalidQueryPreparationConfigError(f"{name} must be a boolean")
            
class RetrievalQueryBuilder(ABC):
    """Contract for retrieval-query preparation strategies."""
    @abstractmethod
    def build(self, *, context: RetrievalQueryContext) -> PreparedRetrievalQuery:
        raise NotImplementedError

class DeterministicRetrievalQueryBuilder(RetrievalQueryBuilder):
    """
    Convert already-understood customer input into retrieval-specific queries.

    Responsibilities:
        - preserve the normalized customer message
        - prepare a semantic/vector query
        - prepare a compact lexical query
        - optionally enrich lexical retrieval using generic semantic hints
        - preserve trusted RetrievalFilters exactly

    This boundary is deliberately deterministic and independently testable.
    """
    def __init__(self, *, config: RetrievalQueryBuilderConfig | None = None, stop_words: frozenset[str] | None = None) -> None:
        self._config = config or RetrievalQueryBuilderConfig()
        if stop_words is None:
            self._stop_words = _DEFAULT_STOP_WORDS
        else:
            if not isinstance(stop_words, frozenset):
                raise InvalidQueryPreparationConfigError("stop_words must be a frozenset")

            if not all(isinstance(word, str) and word.strip() for word in stop_words):
                raise InvalidQueryPreparationConfigError("stop_words must contain only non-empty strings")

            self._stop_words = frozenset(word.casefold().strip() for word in stop_words)

    def build(self, *, context: RetrievalQueryContext) -> PreparedRetrievalQuery:
        if not isinstance(context, RetrievalQueryContext):
            raise TypeError("context must be a RetrievalQueryContext instance")

        if len(context.entities) > self._config.max_entity_hints:
            raise QueryPreparationLimitError(f"entity hint count exceeds configured maximum of {self._config.max_entity_hints}")

        semantic_query = self._build_semantic_query(context=context)
        lexical_query = self._build_lexical_query(context=context)

        try:
            return PreparedRetrievalQuery(
                original_query=context.customer_message,
                semantic_query=semantic_query,
                lexical_queries=(lexical_query,),
                filters=context.filters,
            )
        except QueryPreparationLimitError:
            raise
        except Exception as exc:
            raise QueryConstructionError("Failed to construct prepared retrieval query.") from exc

    def _build_semantic_query(self, *, context: RetrievalQueryContext) -> str:
        """
        Preserve natural language for embedding retrieval.

        We intentionally do not transform the message into keywords because embedding models generally
        benefit from the customer's natural semantic expression.
        """
        query = context.customer_message

        if len(query) > self._config.max_semantic_query_chars:
            raise QueryPreparationLimitError(f"semantic query exceeds configured maximum length of {self._config.max_semantic_query_chars} characters")

        return query

    def _build_lexical_query(self, *, context: RetrievalQueryContext) -> str:
        """
        Produce one compact lexical query.

        For V1 we deliberately produce a single lexical representation. Treating several lexical variants as independent fusion
        rankings could accidentally give the lexical branch more weight than the vector branch during reciprocal-rank fusion.
        """
        candidate_terms: list[str] = []
        candidate_terms.extend(self._extract_terms(context.customer_message))
        if self._config.include_issue_type_hint and "issue_type" in context.entities:
            candidate_terms.extend(self._extract_terms(context.entities["issue_type"]))

        if self._config.include_entity_hints:
            candidate_terms.extend(self._extract_generic_entity_terms(context))

        if self._config.include_intent_hint and context.intent_key is not None:
            candidate_terms.extend(self._extract_terms(context.intent_key.replace("_", " ")))

        terms = self._deduplicate_terms(candidate_terms)
        if not terms:
            # Important fallback:
            # Messages consisting mostly of stop words or unusual punctuation should not become 
            # unretrievable merely because lexical simplification removed everything.
            terms = self._extract_terms(context.customer_message, remove_stop_words=False)

        if not terms:
            # RetrievalQueryContext already guarantees a non-empty message.
            # This is therefore an extremely defensive fallback for text that contains no token recognized by our lexical tokenizer.
            lexical_query = context.customer_message
        else:
            terms = terms[: self._config.max_lexical_terms]
            lexical_query = " ".join(terms)

        if len(lexical_query) > self._config.max_lexical_query_chars:
            lexical_query = self._truncate_lexical_query(terms=terms, fallback=context.customer_message)

        if not lexical_query.strip():
            raise QueryConstructionError("Lexical query construction produced an empty query.")

        return lexical_query

    def _extract_generic_entity_terms(self, context: RetrievalQueryContext) -> list[str]:
        """
        Extract useful semantic values from entity hints.

        Identifier-like entities are deliberately excluded.

        Examples:
            order_id
            account_id
            transaction_id
            subscription_id

        IDs usually identify operational records rather than general knowledge and can reduce policy/FAQ retrieval quality.

        This rule is structural rather than intent-specific: every key ending in `_id` is treated as an identifier.
        """
        terms: list[str] = []
        for key, value in context.entities.items():
            normalized_key = key.casefold()
            if normalized_key == "issue_type":
                continue # Added separately so its behavior can be configured.

            if self._is_identifier_key(normalized_key):
                continue

            terms.extend(self._extract_terms(value))

        return terms

    @staticmethod
    def _is_identifier_key(key: str) -> bool:
        return (key == "id" or key.endswith("_id"))

    def _extract_terms(self, text: str, *, remove_stop_words: bool = True) -> list[str]:
        tokens = [match.group(0).casefold() for match in _TOKEN_PATTERN.finditer(text)]
        if not remove_stop_words:
            return tokens

        return [token for token in tokens if token not in self._stop_words]

    @staticmethod
    def _deduplicate_terms(terms: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for term in terms:
            dedupe_key = term.casefold()
            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)
            result.append(term)

        return result

    def _truncate_lexical_query(self, *, terms: list[str], fallback: str) -> str:
        """
        Fit a lexical query within the configured character budget without cutting a token in the middle.
        """
        max_chars = self._config.max_lexical_query_chars
        selected: list[str] = []
        current_length = 0
        for term in terms:
            additional_length = len(term)
            if selected:
                additional_length += 1

            if current_length + additional_length > max_chars:
                break

            selected.append(term)
            current_length += additional_length

        if selected:
            return " ".join(selected)

        # A single token can itself exceed the lexical budget.
        # We avoid splitting it and instead fall back to a bounded piece of the original query. This path is primarily defensive.
        bounded = fallback[:max_chars].strip()
        if not bounded:
            raise QueryPreparationLimitError("Unable to construct lexical query within configured character limit.")

        return bounded