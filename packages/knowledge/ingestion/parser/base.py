from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.models import IngestionSource, ParsedDocument


@runtime_checkable
class DocumentParser(Protocol):
    """
    Contract implemented by every knowledge-document parser.

    A parser converts a format-specific source representation into the
    format-independent ParsedDocument model used by downstream ingestion
    stages.

    Implementations must be deterministic with respect to the same source
    content and parser version.
    """
    @property
    def name(self) -> str:
        """
        Stable parser identifier used for provenance and observability.

        Examples:
            "markdown-parser"
            "plain-text-parser"
            "pymupdf-parser"
        """
        ...

    @property
    def version(self) -> str:
        """
        Parser implementation/version identifier.

        This value should change whenever parser behavior changes in a way
        that could alter the produced ParsedDocument.
        """
        ...

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        """
        Source types this parser can process.

        A parser may support more than one source type where doing so is
        semantically appropriate.
        """
        ...

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        """
        Return whether this parser supports the supplied source type.

        Implementations normally do not need to override this method when
        using a concrete base class. Protocol implementations may provide
        equivalent behavior themselves.
        """
        ...

    def parse(self, source: IngestionSource) -> ParsedDocument:
        """
        Parse a source document into a format-independent representation.

        Implementations should:
        - preserve source ordering;
        - preserve meaningful document structure where possible;
        - preserve provenance such as sections/pages/offsets when available;
        - never perform retrieval chunking;
        - never generate embeddings;
        - never persist anything.

        Parsing failures should be raised as ingestion/parser-specific
        exceptions rather than silently returning partial or empty output.
        """
        ...


class BaseDocumentParser(ABC):
    """
    Convenience base class for concrete parser implementations.

    The application layer should depend on DocumentParser, not on this class.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        raise NotImplementedError

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        return source_type in self.supported_source_types

    @abstractmethod
    def parse(self, source: IngestionSource) -> ParsedDocument:
        raise NotImplementedError


@runtime_checkable
class DocumentParserResolver(Protocol):
    """
    Resolves the parser responsible for a particular source type.

    Application services depend on this abstraction rather than knowing
    individual parser implementations.
    """
    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        ...

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        ...
    
    def resolve(self, source_type: KnowledgeSourceType) -> DocumentParser:
        """
        Return the parser configured for the requested source type.

        Raises:
            An ingestion-specific error when no parser is configured for the
            supplied source type.
        """
        ...