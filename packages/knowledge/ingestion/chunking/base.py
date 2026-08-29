from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.normalization.models import NormalizedDocument
from packages.knowledge.ingestion.chunking.models import ChunkedDocument

@dataclass(frozen=True, slots=True)
class ChunkerDescriptor:
    """
    Immutable identity and reproducibility metadata for a chunking strategy.

    strategy_id
        Stable logical identifier for the strategy implementation.

    version
        Version of the strategy's behavior.

    config_fingerprint
        Deterministic fingerprint of output-affecting configuration.

        This may be None only when the strategy truly has no output-affecting configuration.
    """
    strategy_id: str
    version: str
    config_fingerprint: str | None = None

    def __post_init__(self) -> None:
        self._validate_non_blank_string(
            value=self.strategy_id,
            field_name="strategy_id",
        )

        self._validate_non_blank_string(
            value=self.version,
            field_name="version",
        )

        if self.config_fingerprint is not None:
            self._validate_non_blank_string(
                value=self.config_fingerprint,
                field_name="config_fingerprint",
            )

    @staticmethod
    def _validate_non_blank_string(*, value: object, field_name: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string.")

        if not value.strip():
            raise ValueError(f"{field_name} must not be blank.")

    @property
    def identity(self) -> str:
        return f"{self.strategy_id}@{self.version}"


@runtime_checkable
class DocumentChunker(Protocol):
    """
    Runtime-checkable contract for document chunkers.

    A DocumentChunker transforms a fully normalized document into retrieval-oriented chunks.

    Implementations must be deterministic for the same:
        - normalized input
        - strategy version
        - output-affecting configuration
    """
    @property
    def descriptor(self) -> ChunkerDescriptor:
        ...

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        ...

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        ...

    def chunk(self, document: NormalizedDocument) -> ChunkedDocument:
        ...


class BaseDocumentChunker(ABC):
    """
    Convenience base class for concrete document chunkers.

    Concrete strategies only need to define:
        - descriptor
        - supported_source_types
        - chunk(...)
    """
    @property
    @abstractmethod
    def descriptor(self) -> ChunkerDescriptor:
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        raise NotImplementedError

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        if not isinstance(source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType.")

        return source_type in self.supported_source_types

    @abstractmethod
    def chunk(self, document: NormalizedDocument) -> ChunkedDocument:
        raise NotImplementedError

@runtime_checkable
class DocumentChunkerResolver(Protocol):
    """
    Resolves the configured chunking strategy for a source type.

    The resolver represents composition-time strategy selection.

    It should not dynamically register or replace strategies during request processing.
    """

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        ...

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        ...

    def resolve(self, source_type: KnowledgeSourceType) -> DocumentChunker:
        ...