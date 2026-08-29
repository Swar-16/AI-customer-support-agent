from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.models import IngestionSource, ParsedDocument


@dataclass(frozen=True, slots=True)
class ParserDescriptor:
    """
    Stable identity and provenance for a parser strategy.

    strategy_id:
        Stable logical implementation identity.
        Example: "plain-text-structural", "pymupdf", "docling".

    version:
        Version of parser behavior. Change when parsing semantics change.

    config_fingerprint:
        Fingerprint of configuration that can affect parser output.
        None when the parser has no output-affecting configuration.
    """
    strategy_id: str
    version: str
    config_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_id, str):
            raise TypeError("strategy_id must be a string.")

        if not self.strategy_id.strip():
            raise ValueError("strategy_id must not be blank.")

        if not isinstance(self.version, str):
            raise TypeError("version must be a string.")

        if not self.version.strip():
            raise ValueError("version must not be blank.")

        if self.config_fingerprint is not None and not isinstance(self.config_fingerprint, str):
            raise TypeError("config_fingerprint must be a string or None.")

        if self.config_fingerprint is not None and not self.config_fingerprint.strip():
            raise ValueError("config_fingerprint must not be blank.")


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
    def descriptor(self) -> ParserDescriptor:
        ...

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        ...

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        ...

    def parse(self, source: IngestionSource) -> ParsedDocument:
        ...


class BaseDocumentParser(ABC):
    """
    Convenience base class for parser strategies.

    Application code depends on DocumentParser, not this class.
    """

    @property
    @abstractmethod
    def descriptor(self) -> ParserDescriptor:
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
        ...