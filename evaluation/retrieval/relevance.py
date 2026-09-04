from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Mapping
import unicodedata

from evaluation.retrieval.models import RetrievalEvaluationCase
from packages.knowledge.retrieval.models import RetrievalCandidate


class RetrievalRelevanceError(Exception):
    """
    Base exception for deterministic relevance matching failures.
    """

class RetrievalRelevanceConfigurationError(RetrievalRelevanceError):
    """
    Raised when relevance-matching configuration is invalid.
    """

class RetrievalRelevanceContractError(RetrievalRelevanceError):
    """
    Raised when an input violates the relevance-matching contract.
    """

@dataclass(frozen=True, slots=True)
class DeterministicRelevanceMatcherConfig:
    """
    Configuration for deterministic retrieval evaluation relevance.

    Topics are intentionally read only from explicit candidate metadata.
    Candidate body text is never searched heuristically for topic labels.

    Example supported metadata:

        {
            "topics": ["refund delay", "refund processing time"]
        }

    or:

        {
            "tags": "refund delay, refund eligibility"
        }
    """
    topic_metadata_keys: tuple[str, ...] = ("topics", "topic", "tags", "keywords",)
    split_string_topic_values: bool = True
    topic_delimiters: tuple[str, ...] = (",", ";", "|",)

    def __post_init__(self) -> None:
        if not isinstance(self.topic_metadata_keys, tuple):
            raise RetrievalRelevanceConfigurationError("topic_metadata_keys must be a tuple.")

        normalized_keys = _normalize_unique_strings(self.topic_metadata_keys, field_name="topic_metadata_keys")
        if not normalized_keys:
            raise RetrievalRelevanceConfigurationError("topic_metadata_keys must contain at least one key.")

        if not isinstance(self.split_string_topic_values, bool):
            raise RetrievalRelevanceConfigurationError("split_string_topic_values must be a boolean.")

        if not isinstance(self.topic_delimiters, tuple):
            raise RetrievalRelevanceConfigurationError("topic_delimiters must be a tuple.")

        normalized_delimiters: list[str] = []
        for delimiter in self.topic_delimiters:
            if not isinstance(delimiter, str):
                raise RetrievalRelevanceConfigurationError("topic_delimiters entries must be strings.")

            if not delimiter:
                raise RetrievalRelevanceConfigurationError("topic_delimiters entries must not be empty.")

            if delimiter not in normalized_delimiters:
                normalized_delimiters.append(delimiter)

        object.__setattr__(self, "topic_metadata_keys", normalized_keys)
        object.__setattr__(self, "topic_delimiters", tuple(normalized_delimiters))

class DeterministicRetrievalRelevanceMatcher:
    """
    Deterministically maps retrieved candidates to benchmark targets.

    Supported target families:

        document:<normalized document title>
        section:<normalized section title>
        topic:<normalized topic>

    Matching rules:

    DOCUMENT
        Exact normalized title equality.

    SECTION
        Exact normalized section-title equality.

    TOPIC
        Exact normalized equality against explicit metadata values stored under configured topic/tag/keyword metadata keys.

    Evaluation labels must remain deterministic and reproducible.
    """
    def __init__(self, *, config: DeterministicRelevanceMatcherConfig | None = None) -> None:
        self._config = config or DeterministicRelevanceMatcherConfig()
        if not isinstance(self._config, DeterministicRelevanceMatcherConfig):
            raise RetrievalRelevanceConfigurationError("config must be a DeterministicRelevanceMatcherConfig instance.")

        self._topic_metadata_keys = frozenset(_normalize_text(key) for key in self._config.topic_metadata_keys)

    @property
    def config(self) -> DeterministicRelevanceMatcherConfig:
        return self._config

    def match(self, *, case: RetrievalEvaluationCase, candidate: RetrievalCandidate) -> frozenset[str]:
        self._validate_case(case)
        self._validate_candidate(candidate)
        matches: set[str] = set()
        self._match_document_targets(case=case, candidate=candidate, matches=matches)
        self._match_section_targets(case=case, candidate=candidate, matches=matches)
        self._match_topic_targets(case=case, candidate=candidate, matches=matches)
        unknown_targets = matches - case.relevance_target_ids

        if unknown_targets:
            raise RetrievalRelevanceContractError("Matcher produced targets outside case ground truth.")

        return frozenset(matches)

    @staticmethod
    def _match_document_targets(*, case: RetrievalEvaluationCase, candidate: RetrievalCandidate, matches: set[str]) -> None:
        candidate_title = _normalize_text(candidate.document_title)
        for expected_title in case.expected_document_titles:
            if candidate_title == _normalize_text(expected_title):
                matches.add(RetrievalEvaluationCase.make_document_target_id(expected_title))

    @staticmethod
    def _match_section_targets(*, case: RetrievalEvaluationCase, candidate: RetrievalCandidate, matches: set[str]) -> None:
        if candidate.section_title is None:
            return

        candidate_section = _normalize_text(candidate.section_title)
        if not candidate_section:
            return

        for expected_section in case.expected_section_titles:
            if candidate_section == _normalize_text(expected_section):
                matches.add(RetrievalEvaluationCase.make_section_target_id(expected_section))

    def _match_topic_targets(self, *, case: RetrievalEvaluationCase, candidate: RetrievalCandidate, matches: set[str]) -> None:
        if not case.expected_topics:
            return

        candidate_topics = self._extract_candidate_topics(candidate.metadata)
        if not candidate_topics:
            return

        for expected_topic in case.expected_topics:
            normalized_expected = _normalize_text(expected_topic)
            if normalized_expected in candidate_topics:
                matches.add(RetrievalEvaluationCase.make_topic_target_id(expected_topic))

    def _extract_candidate_topics(self, metadata: Mapping[str, object]) -> frozenset[str]:
        if not isinstance(metadata, Mapping):
            raise RetrievalRelevanceContractError("candidate.metadata must be a mapping.")

        topics: set[str] = set()
        for raw_key, raw_value in metadata.items():
            if not isinstance(raw_key, str):
                continue

            normalized_key = _normalize_text(raw_key)
            if normalized_key not in self._topic_metadata_keys:
                continue

            topics.update(self._extract_topics_from_value(raw_value))

        return frozenset(topics)

    def _extract_topics_from_value(self, value: object) -> set[str]:
        if value is None:
            return set()

        if isinstance(value, str):
            return self._extract_topics_from_string(value)

        if isinstance(value, Mapping):
            # Arbitrary nested metadata should not accidentally become a relevance judgment.
            return set()

        if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
            topics: set[str] = set()
            for item in value:
                if not isinstance(item, str):
                    continue

                normalized = _normalize_text(item)
                if normalized:
                    topics.add(normalized)

            return topics

        # Unknown metadata representations are ignored rather than interpreted heuristically.
        return set()

    def _extract_topics_from_string(self, value: str) -> set[str]:
        normalized_value = value.strip()
        if not normalized_value:
            return set()

        if not self._config.split_string_topic_values:
            normalized = _normalize_text(normalized_value)

            return ({normalized} if normalized else set())

        fragments = [normalized_value]
        for delimiter in self._config.topic_delimiters:
            expanded: list[str] = []
            for fragment in fragments:
                expanded.extend(fragment.split(delimiter))

            fragments = expanded
            
        topics: set[str] = set()
        for fragment in fragments:
            normalized = _normalize_text(fragment)
            if normalized:
                topics.add(normalized)

        return topics

    @staticmethod
    def _validate_case(case: object) -> None:
        if not isinstance(case, RetrievalEvaluationCase):
            raise RetrievalRelevanceContractError("case must be a RetrievalEvaluationCase instance.")

    @staticmethod
    def _validate_candidate(candidate: object) -> None:
        if not isinstance(candidate, RetrievalCandidate):
            raise RetrievalRelevanceContractError("candidate must be a RetrievalCandidate instance.")

def _normalize_text(value: str) -> str:
    if not isinstance(value, str):
        raise RetrievalRelevanceContractError("Text values used for relevance matching must be strings.")

    unicode_normalized = unicodedata.normalize("NFKC", value)
    return " ".join(unicode_normalized.casefold().split())

def _normalize_unique_strings(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise RetrievalRelevanceConfigurationError(f"{field_name} entries must be strings.")

        item = _normalize_text(value)
        if not item:
            raise RetrievalRelevanceConfigurationError(f"{field_name} entries must not be empty.")

        if item in seen:
            continue

        seen.add(item)
        normalized.append(item)

    return tuple(normalized)