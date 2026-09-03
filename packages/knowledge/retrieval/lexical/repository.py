from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalFilters


@dataclass(frozen=True, slots=True)
class LexicalSearchRequest:
    """
    Provider-agnostic request for lexical knowledge retrieval.

    `query_text` is the natural-language query. The infrastructure repository is responsible for 
    translating it into the backend-specific full-text-search representation.

    PostgreSQL concepts such as tsquery, tsvector and regconfig must not leak into this contract.
    """
    query_text: str
    filters: RetrievalFilters
    limit: int

    def __post_init__(self) -> None:
        if not isinstance(self.query_text, str):
            raise TypeError("query_text must be a string.")

        normalized_query = self.query_text.strip()
        if not normalized_query:
            raise ValueError("query_text must not be blank.")

        if not isinstance(self.filters, RetrievalFilters):
            raise TypeError("filters must be a RetrievalFilters instance.")

        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer.")

        if self.limit <= 0:
            raise ValueError("limit must be greater than zero.")

        object.__setattr__(self, "query_text", normalized_query)


@dataclass(frozen=True, slots=True)
class LexicalSearchMatch:
    """
    One backend lexical-search result.

    `score` is deliberately treated as an opaque lexical relevance score.

    Larger score = better lexical match.

    The higher retrieval layers must not assume this score is directly comparable with vector similarity scores.
    Hybrid ranking will later use Reciprocal Rank Fusion rather than naïvely adding incompatible scores.
    """
    candidate: RetrievalCandidate
    score: float

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, RetrievalCandidate):
            raise TypeError("candidate must be a RetrievalCandidate instance.")

        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise TypeError("score must be numeric.")

        normalized_score = float(self.score)
        if not isfinite(normalized_score):
            raise ValueError("score must be finite.")

        if normalized_score < 0.0:
            raise ValueError("score must not be negative.")

        object.__setattr__(self, "score", normalized_score)


class LexicalRetrievalRepository(Protocol):
    """
    Persistence contract for lexical knowledge retrieval.

    Concrete implementations may use PostgreSQL full-text search, Elasticsearch, OpenSearch, Tantivy, 
    or another lexical engine without changing the knowledge retrieval domain.
    """
    def search(self, request: LexicalSearchRequest) -> tuple[LexicalSearchMatch, ...]:
        ...