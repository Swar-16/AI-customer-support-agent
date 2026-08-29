from __future__ import annotations
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from packages.knowledge.domain.enums import KnowledgeSourceType


def _freeze_metadata(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    """
    Create an immutable shallow copy of metadata.

    Ingestion models are value objects. A caller modifying the original
    dictionary after construction must not mutate the ingestion artifact.
    """
    return MappingProxyType(dict(metadata))


@dataclass(frozen=True, slots=True)
class IngestionSource:
    """
    Immutable source passed into the document parsing layer.

    `content` is the exact source content stored for the knowledge version.
    Parsers must never modify this object.

    Binary formats such as PDF/DOCX will eventually use an extracted/raw
    representation before reaching this boundary. We deliberately keep this
    contract textual for now because KnowledgeDocumentVersion currently stores
    source_content as text.
    """
    version_id: UUID
    source_type: KnowledgeSourceType
    content: str
    source_name: str | None = None
    source_uri: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")

        if not isinstance(self.source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType.")

        if not isinstance(self.content, str):
            raise TypeError("content must be a string.")

        if not self.content.strip():
            raise ValueError("content must contain non-whitespace text.")

        if self.source_name is not None and not isinstance(self.source_name, str):
            raise TypeError("source_name must be a string or None.")

        if self.source_uri is not None and not isinstance(self.source_uri, str):
            raise TypeError("source_uri must be a string or None.")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class ParsedSegment:
    """
    One ordered structural unit extracted from a source document.

    A segment is NOT yet a retrieval chunk.

    Examples:
        - a Markdown paragraph under a heading
        - a PDF paragraph on page 4
        - a DOCX list item
        - a section of an HTML document

    Chunking happens later and may combine or split parsed segments.
    """
    index: int
    text: str
    section_path: tuple[str, ...] = ()
    page_number: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.index, int):
            raise TypeError("index must be an integer.")

        if self.index < 0:
            raise ValueError("index must be non-negative.")

        if not isinstance(self.text, str):
            raise TypeError("text must be a string.")

        if not self.text.strip():
            raise ValueError("Parsed segment text must not be blank.")

        if not isinstance(self.section_path, tuple):
            raise TypeError("section_path must be a tuple of strings.")

        if not all(isinstance(section, str) and section.strip() for section in self.section_path):
            raise ValueError("section_path entries must be non-empty strings.")

        if self.page_number is not None:
            if not isinstance(self.page_number, int):
                raise TypeError("page_number must be an integer or None.")

            if self.page_number <= 0:
                raise ValueError("page_number must be greater than zero.")

        self._validate_offsets()

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    def _validate_offsets(self) -> None:
        start = self.start_offset
        end = self.end_offset

        if (start is None) != (end is None):
            raise ValueError("start_offset and end_offset must either both be present or both be None.")

        if start is None:
            return

        if not isinstance(start, int) or not isinstance(end, int):
            raise TypeError("Source offsets must be integers.")

        if start < 0:
            raise ValueError("start_offset must be non-negative.")

        if end <= start:
            raise ValueError("end_offset must be greater than start_offset.")

    @property
    def section_title(self) -> str | None:
        if not self.section_path:
            return None

        return self.section_path[-1]


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """
    Format-independent result produced by a DocumentParser.

    Parser provenance is stored as primitive values rather than depending on
    ParserDescriptor directly. This keeps ingestion models independent from
    concrete parser abstractions and makes provenance easy to persist.

    `parser_strategy_id` identifies the parsing strategy.
    `parser_version` identifies the behavior/version of that strategy.
    `parser_config_fingerprint` identifies output-affecting configuration.

    Downstream normalization and chunking operate on this representation
    rather than on PDF, Markdown, DOCX, HTML, etc.
    """
    version_id: UUID
    segments: tuple[ParsedSegment, ...]
    parser_strategy_id: str
    parser_version: str
    parser_config_fingerprint: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_version_id()
        self._validate_segments()
        self._validate_parser_provenance()
        self._validate_metadata()

    def _validate_version_id(self) -> None:
        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")
        
    def _validate_segments(self) -> None:
        if not isinstance(self.segments, tuple):
            raise TypeError("segments must be a tuple.")
        
        if not self.segments:
            raise ValueError("Parsed document must contain at least one segment.")

        if not all(isinstance(segment, ParsedSegment) for segment in self.segments):
            raise TypeError("Every segment must be a ParsedSegment.")

        indexes = [segment.index for segment in self.segments]
        expected_indexes = list(range(len(self.segments)))
        if indexes != expected_indexes:
            raise ValueError("Parsed segment indexes must be contiguous, ordered, and zero-based.")
        
    def _validate_parser_provenance(self) -> None:
        if not isinstance(self.parser_strategy_id, str):
            raise TypeError("parser_strategy_id must be a string.")

        if not self.parser_strategy_id.strip():
            raise ValueError("parser_strategy_id must not be blank.")

        if not isinstance(self.parser_version, str):
            raise TypeError("parser_version must be a string.")

        if not self.parser_version.strip():
            raise ValueError("parser_version must not be blank.")

        fingerprint = self.parser_config_fingerprint
        if fingerprint is not None and not isinstance(fingerprint, str):
            raise TypeError("parser_config_fingerprint must be a string or None.")

        if fingerprint is not None and not fingerprint.strip():
            raise ValueError("parser_config_fingerprint must not be blank.")
        
    def _validate_metadata(self) -> None:
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @property
    def text(self) -> str:
        """
        Convenience representation only.

        Structural information remains available through `segments`.
        """
        return "\n\n".join(segment.text for segment in self.segments)
    
    @property
    def parser_identity(self) -> str:
        """
        Human-readable parser identity useful for diagnostics and
        observability.

        This is not intended to be used as a database identity.
        """
        return (f"{self.parser_strategy_id}@{self.parser_version}")