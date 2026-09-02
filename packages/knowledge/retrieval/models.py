from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

class RetrievalMethod(str, Enum):
    """
    Retrieval mechanisms that may contribute a candidate.

    HYBRID is reserved for results produced by combining multiple retrieval mechanisms rather than by a persistence backend directly.
    """
    VECTOR = "vector"
    LEXICAL = "lexical"
    HYBRID = "hybrid"

@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    """
    Optional business-level constraints applied during knowledge retrieval.

    Lifecycle constraints such as ACTIVE documents and PUBLISHED versions are system invariants and should be
    enforced by the retrieval infrastructure, rather than exposed here as caller-controlled filters.
    """
    content_types: tuple[str, ...] = ()
    visibilities: tuple[str, ...] = ()
    document_ids: tuple[UUID, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_types", self._normalize_strings(self.content_types, field_name="content_types"))
        object.__setattr__(self, "visibilities", self._normalize_strings(self.visibilities, field_name="visibilities"))
        object.__setattr__(self, "document_ids", self._normalize_document_ids(self.document_ids))
        object.__setattr__(self, "metadata", MappingProxyType(self._normalize_metadata(self.metadata)))

    @staticmethod
    def _normalize_strings(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
        if not isinstance(values, tuple):
            raise TypeError(f"{field_name} must be a tuple.")

        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must contain only strings.")

            item = value.strip().lower()
            if not item:
                raise ValueError(f"{field_name} cannot contain blank values.")

            if item not in seen:
                seen.add(item)
                normalized.append(item)

        return tuple(normalized)

    @staticmethod
    def _normalize_document_ids(values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if not isinstance(values, tuple):
            raise TypeError("document_ids must be a tuple.")

        normalized: list[UUID] = []
        seen: set[UUID] = set()
        for value in values:
            if not isinstance(value, UUID):
                raise TypeError("document_ids must contain only UUID values.")

            if value not in seen:
                seen.add(value)
                normalized.append(value)

        return tuple(normalized)

    @staticmethod
    def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        normalized: dict[str, Any] = {}
        for key, value in metadata.items():
            if not isinstance(key, str):
                raise TypeError("metadata keys must be strings.")

            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError("metadata keys cannot be blank.")

            if normalized_key in normalized:
                raise ValueError("metadata contains duplicate keys after normalization.")

            normalized[normalized_key] = value

        return normalized


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """
    Canonical request entering the retrieval subsystem.
    """
    text: str
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    
    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string.")

        normalized = self.text.strip()

        if not normalized:
            raise ValueError("Retrieval query text cannot be blank.")

        if not isinstance(self.filters, RetrievalFilters):
            raise TypeError("filters must be a RetrievalFilters instance.")

        object.__setattr__(self, "text", normalized)


@dataclass(frozen=True, slots=True)
class RetrievalScores:
    """
    Scores accumulated while a candidate travels through retrieval.

    These values deliberately remain separate because they have different semantics and scales.

    vector_distance:
        Raw pgvector distance. Lower is better.

    vector_similarity:
        Similarity derived from the vector distance. Higher is better.

    lexical_score:
        Score produced by lexical/full-text retrieval. Higher is better.

    fusion_score:
        Score assigned by a rank-fusion algorithm. Higher is better.

    reranker_score:
        Score assigned by a downstream reranker. Higher is better.
    """
    vector_distance: float | None = None
    vector_similarity: float | None = None
    lexical_score: float | None = None
    fusion_score: float | None = None
    reranker_score: float | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("vector_distance", self.vector_distance),
            ("vector_similarity", self.vector_similarity),
            ("lexical_score", self.lexical_score),
            ("fusion_score", self.fusion_score),
            ("reranker_score", self.reranker_score),
        ):
            if value is None:
                continue

            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be a number or None.")

            numeric_value = float(value)
            if not isfinite(numeric_value):
                raise ValueError(f"{field_name} must be finite.")

            object.__setattr__(self, field_name, numeric_value)


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """
    One canonical knowledge chunk returned by retrieval.

    The candidate carries enough provenance to support grounding, observability, debugging, and 
    eventual source attribution without requiring another database lookup.
    """
    chunk_id: UUID
    version_id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    document_title: str
    section_title: str | None
    methods: frozenset[RetrievalMethod]
    scores: RetrievalScores = field(default_factory=RetrievalScores)

    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("chunk_id", self.chunk_id),
            ("version_id", self.version_id),
            ("document_id", self.document_id),
        ):
            if not isinstance(value, UUID):
                raise TypeError(f"{field_name} must be a UUID.")

        if isinstance(self.chunk_index, bool) or not isinstance(self.chunk_index, int):
            raise TypeError("chunk_index must be an integer.")

        if self.chunk_index < 0:
            raise ValueError("chunk_index cannot be negative.")

        if not isinstance(self.content, str):
            raise TypeError("content must be a string.")

        normalized_content = self.content.strip()
        if not normalized_content:
            raise ValueError("candidate content cannot be blank.")

        object.__setattr__(self, "content", normalized_content)
        if not isinstance(self.document_title, str):
            raise TypeError("document_title must be a string.")

        normalized_title = self.document_title.strip()
        if not normalized_title:
            raise ValueError("document_title cannot be blank.")

        object.__setattr__(self, "document_title", normalized_title)

        if self.section_title is not None:
            if not isinstance(self.section_title, str):
                raise TypeError("section_title must be a string or None.")

            normalized_section = self.section_title.strip()
            object.__setattr__(self, "section_title", normalized_section or None)

        if not isinstance(self.methods, frozenset):
            raise TypeError("methods must be a frozenset.")

        if not self.methods:
            raise ValueError("candidate must have at least one retrieval method.")

        if not all(isinstance(method, RetrievalMethod) for method in self.methods):
            raise TypeError("methods must contain only RetrievalMethod values.")

        if not isinstance(self.scores, RetrievalScores):
            raise TypeError("scores must be a RetrievalScores instance.")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """
    Final ranked result produced by the retrieval pipeline.
    """
    query: RetrievalQuery
    candidates: tuple[RetrievalCandidate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query, RetrievalQuery):
            raise TypeError("query must be a RetrievalQuery instance.")

        if not isinstance(self.candidates, tuple):
            raise TypeError("candidates must be a tuple.")

        seen_chunk_ids: set[UUID] = set()
        for candidate in self.candidates:
            if not isinstance(candidate, RetrievalCandidate):
                raise TypeError("candidates must contain only RetrievalCandidate instances.")

            if candidate.chunk_id in seen_chunk_ids:
                raise ValueError(f"RetrievalResult cannot contain duplicate chunk_id '{candidate.chunk_id}'.")

            seen_chunk_ids.add(candidate.chunk_id)

    @property
    def count(self) -> int:
        return len(self.candidates)

    @property
    def is_empty(self) -> bool:
        return not self.candidates