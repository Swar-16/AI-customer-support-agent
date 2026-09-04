from __future__ import annotations
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from packages.knowledge.retrieval.models import RetrievalFilters

@dataclass(frozen=True, slots=True)
class RetrievalEvaluationInput:
    """
    Production retrieval inputs attached to an evaluation case.

    This object contains only information that would legitimately be available to the real application before retrieval.

    Ground-truth relevance annotations must never appear here.
    """
    entities: Mapping[str, str] = field(default_factory=dict)
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    conversation_context: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.entities, Mapping):
            raise TypeError("entities must be a mapping.")

        normalized_entities: dict[str, str] = {}

        for key, value in self.entities.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError("entity keys and values must be strings.")

            normalized_key = key.strip()
            normalized_value = value.strip()
            if not normalized_key:
                raise ValueError("entity keys must not be empty.")

            if not normalized_value:
                raise ValueError("entity values must not be empty.")

            normalized_entities[normalized_key] = normalized_value

        object.__setattr__(self, "entities", MappingProxyType(normalized_entities))
        if not isinstance(self.filters, RetrievalFilters):
            raise TypeError("filters must be a RetrievalFilters instance.")

        if self.conversation_context is not None:
            if not isinstance(self.conversation_context, str):
                raise TypeError("conversation_context must be a string or None.")

            normalized_context = self.conversation_context.strip()
            object.__setattr__(self, "conversation_context", normalized_context or None)

@dataclass(frozen=True, slots=True)
class RetrievalEvaluationCase:
    """
    One retrieval benchmark case.

    Relevance is defined through stable semantic targets rather than chunk IDs, because chunk identifiers may change when the knowledge base is rechunked.

    Target IDs are generated deterministically from:
        document:<title>
        topic:<topic>
        section:<title>
    """
    case_id: str
    query: str
    intent_key: str | None = None
    expected_document_titles: tuple[str, ...] = ()
    expected_topics: tuple[str, ...] = ()
    expected_section_titles: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    retrieval_input: RetrievalEvaluationInput = field(default_factory=RetrievalEvaluationInput)

    def __post_init__(self) -> None:
        case_id = self._normalize_required_text(self.case_id, field_name="case_id")
        query = self._normalize_required_text(self.query, field_name="query")
        intent_key = self.intent_key
        if intent_key is not None:
            if not isinstance(intent_key, str):
                raise TypeError("intent_key must be a string or None.")

            intent_key = intent_key.strip() or None
            
        if not isinstance(self.retrieval_input, RetrievalEvaluationInput):
            raise TypeError("retrieval_input must be a RetrievalEvaluationInput instance.")

        expected_document_titles = self._normalize_tuple(self.expected_document_titles, field_name="expected_document_titles")
        expected_topics = self._normalize_tuple(self.expected_topics, field_name="expected_topics")
        expected_section_titles = self._normalize_tuple(self.expected_section_titles, field_name="expected_section_titles")

        if not expected_document_titles and not expected_topics and not expected_section_titles:
            raise ValueError("At least one expected relevance target must be provided.")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        normalized_metadata: dict[str, str] = {}
        for key, value in self.metadata.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError("metadata keys and values must be strings.")

            normalized_key = key.strip()
            normalized_value = value.strip()
            if not normalized_key:
                raise ValueError("metadata keys must not be empty.")

            if normalized_value:
                normalized_metadata[normalized_key] = normalized_value

        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "intent_key", intent_key)
        object.__setattr__(self, "expected_document_titles", expected_document_titles)
        object.__setattr__(self, "expected_topics", expected_topics)
        object.__setattr__(self, "expected_section_titles", expected_section_titles)
        object.__setattr__(self, "metadata", MappingProxyType(normalized_metadata))

    @property
    def relevance_target_ids(self) -> frozenset[str]:
        targets: set[str] = set()
        targets.update(self._make_target_id("document", title) for title in self.expected_document_titles)
        targets.update(self._make_target_id("topic", topic) for topic in self.expected_topics)
        targets.update(self._make_target_id("section", title) for title in self.expected_section_titles)

        return frozenset(targets)

    @property
    def relevance_target_count(self) -> int:
        return len(self.relevance_target_ids)

    @staticmethod
    def make_document_target_id(title: str) -> str:
        return RetrievalEvaluationCase._make_target_id("document", title,)

    @staticmethod
    def make_topic_target_id(topic: str, ) -> str:
        return RetrievalEvaluationCase._make_target_id("topic", topic)

    @staticmethod
    def make_section_target_id(title: str) -> str:
        return RetrievalEvaluationCase._make_target_id("section", title)

    @staticmethod
    def _make_target_id(target_type: str, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("target value must be a string.")

        normalized = " ".join(value.strip().lower().split())
        if not normalized:
            raise ValueError("target value must not be empty.")

        return f"{target_type}:{normalized}"

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string.")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be empty.")

        return normalized

    @staticmethod
    def _normalize_tuple(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
        if not isinstance(values, tuple):
            raise TypeError(f"{field_name} must be a tuple.")

        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                raise TypeError(f"{field_name} entries must be strings.")

            item = value.strip()
            if not item:
                continue

            dedupe_key = " ".join(item.lower().split())
            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)
            normalized.append(item)

        return tuple(normalized)

@dataclass(frozen=True, slots=True)
class RetrievalEvaluationHit:
    rank: int
    document_title: str
    section_title: str | None
    chunk_id: str
    matched_target_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.rank, bool) or not isinstance(self.rank, int):
            raise TypeError("rank must be an integer.")

        if self.rank <= 0:
            raise ValueError("rank must be greater than zero.")

        document_title = self._normalize_required_text(self.document_title, field_name="document_title")
        section_title = self.section_title
        if section_title is not None:
            if not isinstance(section_title, str):
                raise TypeError("section_title must be a string or None.")

            section_title = section_title.strip() or None

        chunk_id = self._normalize_required_text(self.chunk_id, field_name="chunk_id")
        if not isinstance(self.matched_target_ids, frozenset):
            raise TypeError("matched_target_ids must be a frozenset.")

        normalized_targets: set[str] = set()
        for target_id in self.matched_target_ids:
            if not isinstance(target_id, str):
                raise TypeError("matched_target_ids entries must be strings.")

            normalized_target = target_id.strip()
            if not normalized_target:
                raise ValueError("matched_target_ids entries must not be empty.")

            normalized_targets.add(normalized_target)

        object.__setattr__(self, "document_title", document_title)
        object.__setattr__(self, "section_title", section_title)
        object.__setattr__(self, "chunk_id", chunk_id)
        object.__setattr__(self, "matched_target_ids", frozenset(normalized_targets))

    @property
    def relevant(self) -> bool:
        return bool(self.matched_target_ids)

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string.")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be empty.")

        return normalized

@dataclass(frozen=True, slots=True)
class RetrievalEvaluationResult:
    case_id: str
    method: str
    relevance_target_ids: frozenset[str]
    hits: tuple[RetrievalEvaluationHit, ...]

    def __post_init__(self) -> None:
        case_id = self._normalize_required_text(self.case_id, field_name="case_id")
        method = self._normalize_required_text(self.method, field_name="method")
        if not isinstance(self.relevance_target_ids, frozenset):
            raise TypeError("relevance_target_ids must be a frozenset.")

        normalized_targets: set[str] = set()
        for target_id in self.relevance_target_ids:
            if not isinstance(target_id, str):
                raise TypeError("relevance_target_ids entries must be strings.")

            normalized = target_id.strip()
            if not normalized:
                raise ValueError("relevance_target_ids entries must not be empty.")

            normalized_targets.add(normalized)

        if not normalized_targets:
            raise ValueError("relevance_target_ids must contain at least one target.")

        if not isinstance(self.hits, tuple):
            raise TypeError("hits must be a tuple.")

        expected_rank = 1
        seen_chunk_ids: set[str] = set()
        for hit in self.hits:
            if not isinstance(hit, RetrievalEvaluationHit):
                raise TypeError("hits must contain RetrievalEvaluationHit instances.")

            if hit.rank != expected_rank:
                raise ValueError("hits must have contiguous ranks starting at 1.")

            if hit.chunk_id in seen_chunk_ids:
                raise ValueError("hits must not contain duplicate chunk IDs.")

            unknown_targets = hit.matched_target_ids - normalized_targets
            if unknown_targets:
                raise ValueError("hit matched_target_ids must be a subset of result relevance_target_ids.")

            seen_chunk_ids.add(hit.chunk_id)
            expected_rank += 1

        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "relevance_target_ids", frozenset(normalized_targets))

    @property
    def relevance_target_count(self) -> int:
        return len(self.relevance_target_ids)

    @property
    def matched_target_ids(self) -> frozenset[str]:
        matched: set[str] = set()
        for hit in self.hits:
            matched.update(hit.matched_target_ids)

        return frozenset(matched)

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string.")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be empty.")

        return normalized