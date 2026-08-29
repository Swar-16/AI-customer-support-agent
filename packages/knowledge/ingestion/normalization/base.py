from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.models import ParsedDocument
from packages.knowledge.ingestion.normalization.models import NormalizedDocument


@dataclass(frozen=True, slots=True)
class NormalizerDescriptor:
    """
    Stable identity and provenance for a normalization strategy.
    """
    strategy_id: str
    version: str
    config_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_id, str):
            raise TypeError("strategy_id must be a string.")

        if not self.strategy_id.strip():
            raise ValueError("strategy_id must not be blank.")

        if not isinstance(self.version,str):
            raise TypeError("version must be a string.")

        if not self.version.strip():
            raise ValueError("version must not be blank.")

        if self.config_fingerprint is not None and not isinstance(self.config_fingerprint, str):
            raise TypeError("config_fingerprint must be a string or None.")

        if self.config_fingerprint is not None and not self.config_fingerprint.strip():
            raise ValueError("config_fingerprint must not be blank.")

@runtime_checkable
class DocumentNormalizer(Protocol):
    @property
    def descriptor(self) -> NormalizerDescriptor:
        ...

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        ...

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        ...

    def normalize(self, document: ParsedDocument) -> NormalizedDocument:
        ...

class BaseDocumentNormalizer(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> NormalizerDescriptor:
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        raise NotImplementedError

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        return (source_type in self.supported_source_types)

    @abstractmethod
    def normalize(self, document: ParsedDocument) -> NormalizedDocument:
        raise NotImplementedError

@runtime_checkable
class DocumentNormalizerResolver(Protocol):
    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        ...

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        ...

    def resolve(self, source_type: KnowledgeSourceType) -> DocumentNormalizer:
        ...