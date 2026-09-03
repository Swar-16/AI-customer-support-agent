from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from uuid import UUID

from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalQuery


@dataclass(frozen=True, slots=True)
class RerankerDescriptor:
    """
    Immutable identity of a reranking implementation.

    The descriptor is intentionally infrastructure-agnostic. A reranker may later be backed by Jina, a local cross-encoder,
    another external provider, or a deterministic passthrough implementation.
    """
    reranker_id: str
    provider: str
    model: str | None = None
    revision: str | None = None

    def __post_init__(self) -> None:
        reranker_id = _normalize_required_string(self.reranker_id, field_name="reranker_id")
        provider = _normalize_required_string(self.provider, field_name="provider")
        model = _normalize_optional_string(self.model, field_name="model")
        revision = _normalize_optional_string(self.revision, field_name="revision")

        object.__setattr__(self, "reranker_id", reranker_id)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "revision", revision)

    @property
    def identity(self) -> str:
        parts = [self.reranker_id, self.provider]
        if self.model is not None:
            parts.append(self.model)

        if self.revision is not None:
            parts.append(self.revision)

        return ":".join(parts)

@dataclass(frozen=True, slots=True)
class RerankingRequest:
    """
    Input supplied to a reranking strategy.

    Candidate ordering is meaningful: it represents the ordering produced by the previous retrieval/fusion stage.

    Rerankers may use that ordering as a fallback, but must not mutate the candidates or the input tuple.
    """
    query: RetrievalQuery
    candidates: tuple[RetrievalCandidate, ...]
    limit: int

    def __post_init__(self) -> None:
        if not isinstance(self.query, RetrievalQuery):
            raise TypeError("query must be a RetrievalQuery instance.")

        if not isinstance(self.candidates, tuple):
            raise TypeError("candidates must be a tuple.")

        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer.")

        if self.limit <= 0:
            raise ValueError("limit must be greater than zero.")

        seen_chunk_ids: set[UUID] = set()
        for candidate in self.candidates:
            if not isinstance(candidate, RetrievalCandidate):
                raise TypeError("candidates must contain RetrievalCandidate instances.")

            if candidate.chunk_id in seen_chunk_ids:
                raise ValueError("reranking request must not contain duplicate chunk IDs.")

            seen_chunk_ids.add(candidate.chunk_id)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def is_empty(self) -> bool:
        return not self.candidates

@dataclass(frozen=True, slots=True)
class RerankedCandidate:
    """
    Provider-independent reranking output for one candidate.

    Keeping the score outside RetrievalCandidate at this boundary is intentional. External rerankers should report 
    their result first; the reranking service will validate it and then attach the score to RetrievalScores.reranker_score.
    """
    chunk_id: UUID
    score: float | None

    def __post_init__(self) -> None:
        if self.score is None:
            return

        if not isinstance(self.chunk_id, UUID):
            raise TypeError("chunk_id must be a UUID.")

        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise TypeError("score must be numeric.")

        normalized_score = float(self.score)
        if not isfinite(normalized_score):
            raise ValueError("score must be finite.")

        object.__setattr__(self, "score", normalized_score)

@dataclass(frozen=True, slots=True)
class RerankingResponse:
    """
    Raw response returned by a reranking implementation.

    Results are ordered from highest relevance to lowest relevance.

    Every result must refer to a unique candidate from the original RerankingRequest. Request/response cardinality and 
    membership are validated by the orchestration/service boundary where both objects are available.
    """
    results: tuple[RerankedCandidate, ...]
    descriptor: RerankerDescriptor

    def __post_init__(self) -> None:
        if not isinstance(self.results, tuple):
            raise TypeError("results must be a tuple.")

        if not isinstance(self.descriptor, RerankerDescriptor):
            raise TypeError("descriptor must be a RerankerDescriptor instance.")

        seen_chunk_ids: set[UUID] = set()
        for result in self.results:
            if not isinstance(result, RerankedCandidate):
                raise TypeError("results must contain RerankedCandidate instances.")

            if result.chunk_id in seen_chunk_ids:
                raise ValueError("reranking response must not contain duplicate chunk IDs.")

            seen_chunk_ids.add(result.chunk_id)

    @property
    def count(self) -> int:
        return len(self.results)

    @property
    def is_empty(self) -> bool:
        return not self.results

def _normalize_required_string(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank.")

    return normalized

def _normalize_optional_string(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None.")

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank when provided.")

    return normalized