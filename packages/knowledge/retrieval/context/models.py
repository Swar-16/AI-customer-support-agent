from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalQuery


@dataclass(frozen=True, slots=True)
class GroundingContextBlock:
    """
    One trusted knowledge block selected for grounding.

    The block preserves enough provenance to:
      - trace generated answers back to knowledge;
      - render citations later;
      - debug retrieval/context decisions;
      - support auditability and reproducibility.

    This is a context-layer model, not a database model and not an LLM-provider payload.
    """
    chunk_id: UUID
    version_id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    document_title: str
    section_title: str | None
    metadata: Mapping[str, object]
    retrieval_score: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, UUID):
            raise TypeError("chunk_id must be a UUID.")

        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")

        if not isinstance(self.document_id, UUID):
            raise TypeError("document_id must be a UUID.")

        if isinstance(self.chunk_index, bool) or not isinstance(self.chunk_index, int):
            raise TypeError("chunk_index must be an integer.")

        if self.chunk_index < 0:
            raise ValueError("chunk_index must not be negative.")

        normalized_content = _normalize_required_text(self.content, field_name="content")
        normalized_title = _normalize_required_text(self.document_title, field_name="document_title")
        normalized_section = _normalize_optional_text(self.section_title, field_name="section_title")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        metadata_copy = MappingProxyType(dict(self.metadata))
        retrieval_score = self.retrieval_score
        if retrieval_score is not None:
            if isinstance(retrieval_score, bool) or not isinstance(retrieval_score, (int, float)):
                raise TypeError("retrieval_score must be numeric or None.")

            retrieval_score = float(retrieval_score)
            if not isfinite(retrieval_score):
                raise ValueError("retrieval_score must be finite.")

        object.__setattr__(self, "content", normalized_content)
        object.__setattr__(self, "document_title", normalized_title)
        object.__setattr__(self, "section_title", normalized_section)
        object.__setattr__(self, "metadata", metadata_copy)
        object.__setattr__(self, "retrieval_score", retrieval_score)

    @classmethod
    def from_candidate(cls, candidate: RetrievalCandidate) -> GroundingContextBlock:
        if not isinstance(candidate, RetrievalCandidate):
            raise TypeError("candidate must be a RetrievalCandidate instance.")

        return cls(
            chunk_id=candidate.chunk_id,
            version_id=candidate.version_id,
            document_id=candidate.document_id,
            chunk_index=candidate.chunk_index,
            content=candidate.content,
            document_title=candidate.document_title,
            section_title=candidate.section_title,
            metadata=candidate.metadata,
            retrieval_score=_select_retrieval_score(candidate)
        )

@dataclass(frozen=True, slots=True)
class GroundingContext:
    """
    Final trusted context produced for grounded generation.

    This object represents the selected knowledge after retrieval, deduplication and budgeting, but before prompt formatting.
    """
    query: RetrievalQuery
    blocks: tuple[GroundingContextBlock, ...,]
    estimated_token_count: int
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.query, RetrievalQuery):
            raise TypeError("query must be a RetrievalQuery instance.")

        if not isinstance(self.blocks, tuple):
            raise TypeError("blocks must be a tuple.")

        seen_chunk_ids: set[UUID] = set()
        for block in self.blocks:
            if not isinstance(block, GroundingContextBlock):
                raise TypeError("blocks must contain GroundingContextBlock instances.")

            if block.chunk_id in seen_chunk_ids:
                raise ValueError("blocks must not contain duplicate chunk IDs.")

            seen_chunk_ids.add(block.chunk_id)

        if isinstance(self.estimated_token_count, bool) or not isinstance(self.estimated_token_count, int):
            raise TypeError("estimated_token_count must be an integer.")

        if self.estimated_token_count < 0:
            raise ValueError("estimated_token_count must not be negative.")

        if not isinstance(self.truncated, bool):
            raise TypeError("truncated must be a boolean.")

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def is_empty(self) -> bool:
        return not self.blocks

    @property
    def chunk_ids(self) -> tuple[UUID, ...]:
        return tuple(block.chunk_id for block in self.blocks)

@dataclass(frozen=True, slots=True)
class GroundingContextBudget:
    """
    Configuration controlling how much retrieved knowledge may enter the grounding context.

    The token budget is intentionally independent of any specific LLM provider.
    A future composition layer can derive it from the selected model's context window.
    """
    max_tokens: int
    max_blocks: int

    def __post_init__(self) -> None:
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int):
            raise TypeError("max_tokens must be an integer.")

        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be greater than zero.")

        if isinstance(self.max_blocks, bool) or not isinstance(self.max_blocks, int):
            raise TypeError("max_blocks must be an integer.")

        if self.max_blocks <= 0:
            raise ValueError("max_blocks must be greater than zero.")

def _select_retrieval_score(candidate: RetrievalCandidate) -> float | None:
    """
    Select the best available pipeline-level relevance score.

    Preference order reflects the latest stage that actually produced a meaningful relevance signal.

    Passthrough reranking leaves reranker_score=None, so fusion_score remains the effective retrieval score.
    """
    scores = candidate.scores
    if scores.reranker_score is not None:
        return scores.reranker_score

    if scores.fusion_score is not None:
        return scores.fusion_score

    if scores.vector_similarity is not None:
        return scores.vector_similarity

    if scores.lexical_score is not None:
        return scores.lexical_score

    return None

def _normalize_required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank.")

    return normalized

def _normalize_optional_text(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None.")

    normalized = value.strip()
    return normalized or None