from __future__ import annotations
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from packages.knowledge.domain.enums import KnowledgeSourceType

def _freeze_metadata(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    """
    Create an immutable shallow copy of metadata.

    The copy prevents mutations to the caller's top-level mapping from changing an already-created ingestion artifact.

    This is intentionally shallow. Metadata should contain descriptive values rather than mutable domain state.
    """
    return MappingProxyType(dict(metadata))


@dataclass(frozen=True, slots=True)
class ChunkSourceSpan:
    """
    Identifies the portion of a normalized segment that contributed to a chunk.

    start_offset and end_offset are half-open character offsets into NormalizedSegment.text:

        text[start_offset:end_offset]

    They are NOT offsets into the original source document.

    This distinction is important because normalization may already have changed the original source representation.
    """
    source_segment_index: int
    start_offset: int
    end_offset: int

    def __post_init__(self) -> None:
        if not isinstance(self.source_segment_index, int):
            raise TypeError("source_segment_index must be an integer.")

        if self.source_segment_index < 0:
            raise ValueError("source_segment_index must be non-negative.")

        if not isinstance(self.start_offset, int):
            raise TypeError("start_offset must be an integer.")

        if not isinstance(self.end_offset, int):
            raise TypeError("end_offset must be an integer.")

        if self.start_offset < 0:
            raise ValueError("start_offset must be non-negative.")

        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset.")

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset

@dataclass(frozen=True, slots=True)
class ChunkCandidate:
    """
    One retrieval-oriented chunk produced by a document chunker.

    A candidate is still an ingestion artifact. It is deliberately independent of the database 
    KnowledgeChunk model so that chunking remains testable and persistence-agnostic.

    source_spans provide traceability back to normalized segments.
    Multiple chunks may reference the same normalized segment because splitting and overlap are legitimate chunking operations.
    """
    index: int
    text: str
    source_spans: tuple[ChunkSourceSpan, ...]
    section_path: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_index()
        self._validate_text()
        self._validate_source_spans()
        self._validate_section_path()
        self._validate_metadata()

    def _validate_index(self) -> None:
        if not isinstance(self.index, int):
            raise TypeError("index must be an integer.")

        if self.index < 0:
            raise ValueError("index must be non-negative.")

    def _validate_text(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string.")

        if not self.text.strip():
            raise ValueError("Chunk candidate text must not be blank.")

    def _validate_source_spans(self) -> None:
        if not isinstance(self.source_spans, tuple):
            raise TypeError("source_spans must be a tuple.")

        if not self.source_spans:
            raise ValueError("Chunk candidate must reference at least one source span.")

        if not all(isinstance(span, ChunkSourceSpan) for span in self.source_spans):
            raise TypeError("Every source span must be a ChunkSourceSpan.")

        previous: ChunkSourceSpan | None = None

        for span in self.source_spans:
            if previous is not None:
                previous_key = (
                    previous.source_segment_index,
                    previous.start_offset,
                    previous.end_offset,
                )
                current_key = (
                    span.source_segment_index,
                    span.start_offset,
                    span.end_offset,
                )

                if current_key <= previous_key:
                    raise ValueError("source_spans must be strictly ordered and must not contain duplicates.")

                if span.source_segment_index == previous.source_segment_index and span.start_offset < previous.end_offset:
                    raise ValueError("Source spans within the same normalized segment must not overlap inside one chunk.")

            previous = span

    def _validate_section_path(self) -> None:
        if not isinstance(self.section_path, tuple):
            raise TypeError("section_path must be a tuple of strings.")

        if not all(isinstance(section, str) and section.strip() for section in self.section_path):
            raise ValueError("section_path entries must be non-empty strings.")

    def _validate_metadata(self) -> None:
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    @property
    def source_segment_indexes(self) -> tuple[int, ...]:
        """
        Ordered unique normalized-segment indexes represented by this chunk.

        This is derived from source_spans so we do not maintain two independent provenance representations that could disagree.
        """
        indexes: list[int] = []
        previous_index: int | None = None

        for span in self.source_spans:
            if span.source_segment_index != previous_index:
                indexes.append(span.source_segment_index)
                previous_index = span.source_segment_index

        return tuple(indexes)

    @property
    def section_title(self) -> str | None:
        if not self.section_path:
            return None

        return self.section_path[-1]

    @property
    def char_count(self) -> int:
        return len(self.text)

@dataclass(frozen=True, slots=True)
class ChunkedDocument:
    """
    Complete output of one chunking operation.

    Carries the full transformation provenance chain:

        Parser
          -> Normalizer
          -> Chunker

    Embedding provenance intentionally does not belong here. Embeddings are model-dependent artifacts created after chunking.
    """
    version_id: UUID
    source_type: KnowledgeSourceType
    chunks: tuple[ChunkCandidate, ...]
    source_parser_strategy_id: str
    source_parser_version: str
    source_parser_config_fingerprint: str | None
    source_normalizer_strategy_id: str
    source_normalizer_version: str
    source_normalizer_config_fingerprint: str | None
    chunker_strategy_id: str
    chunker_version: str
    chunker_config_fingerprint: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_version_id()
        self._validate_source_type()
        self._validate_chunks()
        self._validate_provenance(
            component="source_parser",
            strategy_id=self.source_parser_strategy_id,
            version=self.source_parser_version,
            config_fingerprint=self.source_parser_config_fingerprint,
        )
        self._validate_provenance(
            component="source_normalizer",
            strategy_id=self.source_normalizer_strategy_id,
            version=self.source_normalizer_version,
            config_fingerprint=self.source_normalizer_config_fingerprint,
        )
        self._validate_provenance(
            component="chunker",
            strategy_id=self.chunker_strategy_id,
            version=self.chunker_version,
            config_fingerprint=self.chunker_config_fingerprint,
        )
        self._validate_metadata()

    def _validate_version_id(self) -> None:
        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")

    def _validate_source_type(self) -> None:
        if not isinstance(self.source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType.")

    def _validate_chunks(self) -> None:
        if not isinstance(self.chunks, tuple):
            raise TypeError("chunks must be a tuple.")

        if not self.chunks:
            raise ValueError("Chunked document must contain at least one chunk.")

        if not all(isinstance(chunk, ChunkCandidate) for chunk in self.chunks):
            raise TypeError("Every chunk must be a ChunkCandidate.")

        expected_indexes = tuple(range(len(self.chunks)))
        actual_indexes = tuple(chunk.index for chunk in self.chunks)
        if actual_indexes != expected_indexes:
            raise ValueError("Chunk indexes must be contiguous, ordered, and zero-based.")

    @staticmethod
    def _validate_provenance(*, component: str, strategy_id: str, version: str, config_fingerprint: str | None) -> None:
        if not isinstance(strategy_id, str):
            raise TypeError(f"{component}_strategy_id must be a string.")

        if not strategy_id.strip():
            raise ValueError(f"{component}_strategy_id must not be blank.")

        if not isinstance(version, str):
            raise TypeError(f"{component}_version must be a string.")

        if not version.strip():
            raise ValueError(f"{component}_version must not be blank.")

        if config_fingerprint is not None:
            if not isinstance(config_fingerprint, str):
                raise TypeError(f"{component}_config_fingerprint must be a string or None.")

            if not config_fingerprint.strip():
                raise ValueError(f"{component}_config_fingerprint must not be blank.")

    def _validate_metadata(self) -> None:
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def chunker_identity(self) -> str:
        return f"{self.chunker_strategy_id}@{self.chunker_version}"

    @property
    def normalizer_identity(self) -> str:
        return f"{self.source_normalizer_strategy_id}@{self.source_normalizer_version}"

    @property
    def parser_identity(self) -> str:
        return f"{self.source_parser_strategy_id}@{self.source_parser_version}"