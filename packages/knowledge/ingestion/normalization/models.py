from __future__ import annotations
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from packages.knowledge.domain.enums import KnowledgeSourceType


def _freeze_metadata(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(metadata))


@dataclass(frozen=True, slots=True)
class NormalizedSegment:
    """
    Retrieval-oriented representation of one ParsedSegment.

    A normalized segment is still NOT a retrieval chunk.

    Normalization is intentionally one-to-one with parsed segments.
    Combining or splitting segments belongs to the chunking stage.

    `source_segment_index` maintains deterministic provenance back to
    the exact ParsedSegment from which this representation originated.
    """
    index: int
    source_segment_index: int
    text: str
    section_path: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_index()
        self._validate_source_segment_index()
        self._validate_text()
        self._validate_section_path()
        self._validate_metadata()

    def _validate_index(self) -> None:
        if not isinstance(self.index, int):
            raise TypeError("index must be an integer.")

        if self.index < 0:
            raise ValueError("index must be non-negative.")

    def _validate_source_segment_index(self) -> None:
        if not isinstance(self.source_segment_index, int):
            raise TypeError("source_segment_index must be an integer.")

        if self.source_segment_index < 0:
            raise ValueError("source_segment_index must be non-negative.")

    def _validate_text(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string.")

        if not self.text.strip():
            raise ValueError("Normalized segment text must not be blank.")

    def _validate_section_path(self) -> None:
        if not isinstance(self.section_path, tuple):
            raise TypeError("section_path must be a tuple of strings.")

        if not all(isinstance(section, str) and section.strip() for section in self.section_path):
            raise ValueError("section_path entries must be non-empty strings.")

    def _validate_metadata(self) -> None:
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        object.__setattr__(self,"metadata",_freeze_metadata(self.metadata))

    @property
    def section_title(self,) -> str | None:
        if not self.section_path:
            return None

        return self.section_path[-1]


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    """
    Output produced by a DocumentNormalizer.

    Keeps both upstream parser provenance and normalization provenance
    so the complete transformation history can be reconstructed.

    This object remains format-independent for downstream chunking.
    """
    version_id: UUID
    source_type: KnowledgeSourceType
    segments: tuple[NormalizedSegment, ...]
    source_parser_strategy_id: str
    source_parser_version: str
    source_parser_config_fingerprint: str | None
    normalizer_strategy_id: str
    normalizer_version: str
    normalizer_config_fingerprint: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_version_id()
        self._validate_source_type()
        self._validate_segments()

        self._validate_component_provenance(
            component_name="source parser",
            strategy_id=self.source_parser_strategy_id,
            version=self.source_parser_version,
            config_fingerprint=self.source_parser_config_fingerprint,
        )

        self._validate_component_provenance(
            component_name="normalizer",
            strategy_id=self.normalizer_strategy_id,
            version=self.normalizer_version,
            config_fingerprint=self.normalizer_config_fingerprint
        )

        self._validate_metadata()

    def _validate_version_id(self) -> None:
        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")

    def _validate_source_type(self) -> None:
        if not isinstance(self.source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType.")

    def _validate_segments(self) -> None:
        if not isinstance(self.segments, tuple):
            raise TypeError("segments must be a tuple.")

        if not self.segments:
            raise ValueError("Normalized document must contain at least one segment.")

        if not all(isinstance(segment, NormalizedSegment) for segment in self.segments):
            raise TypeError("Every segment must be a NormalizedSegment.")

        indexes = [segment.index for segment in self.segments]
        if indexes != list(range(len(self.segments))):
            raise ValueError("Normalized segment indexes must be contiguous, ordered, and zero-based.")

        source_indexes = [segment.source_segment_index for segment in self.segments]
        if len(source_indexes) != len(set(source_indexes)):
            raise ValueError("Normalized segments must not reference the same source segment more than once.")

    @staticmethod
    def _validate_component_provenance(*, component_name: str, strategy_id: str, version: str, config_fingerprint: str | None) -> None:
        if not isinstance(strategy_id, str):
            raise TypeError(f"{component_name} strategy_id must be a string.")

        if not strategy_id.strip():
            raise ValueError(f"{component_name} strategy_id must not be blank.")

        if not isinstance(version, str):
            raise TypeError(f"{component_name} version must be a string.")

        if not version.strip():
            raise ValueError(f"{component_name} version must not be blank.")

        if config_fingerprint is not None and not isinstance(config_fingerprint,str):
            raise TypeError(f"{component_name} config_fingerprint must be a string or None.")

        if config_fingerprint is not None and not config_fingerprint.strip():
            raise ValueError(f"{component_name} config_fingerprint must not be blank.")

    def _validate_metadata(self) -> None:
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @property
    def text(self) -> str:
        return "\n\n".join(segment.text for segment in self.segments)

    @property
    def normalizer_identity(self) -> str:
        return (f"{self.normalizer_strategy_id}@{self.normalizer_version}")