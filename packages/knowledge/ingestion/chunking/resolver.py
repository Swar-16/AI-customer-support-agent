from __future__ import annotations
from collections.abc import Iterable
from types import MappingProxyType
from typing import Mapping

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.chunking.base import ChunkerDescriptor, DocumentChunker
from packages.knowledge.ingestion.chunking.errors import KnowledgeChunkerConfigurationError, UnsupportedKnowledgeChunkingSourceTypeError


class DefaultDocumentChunkerResolver:
    """
    Immutable composition-time resolver for document chunkers.

    Exactly one active chunker may be configured for each supported KnowledgeSourceType.

    The resolver validates chunker contracts eagerly during construction so runtime resolution remains deterministic and inexpensive.

    Runtime mutation is intentionally unsupported. Selecting a different chunking strategy 
    should happen by rebuilding the application composition with different configuration.
    """
    def __init__(self, chunkers: Iterable[DocumentChunker]) -> None:
        if isinstance(chunkers, (str, bytes)):
            raise TypeError("chunkers must be an iterable of DocumentChunker instances.")

        try:
            chunker_list = tuple(chunkers)
        except TypeError as exc:
            raise TypeError("chunkers must be an iterable of DocumentChunker instances.") from exc

        if not chunker_list:
            raise KnowledgeChunkerConfigurationError("At least one document chunker must be configured.")

        resolved: dict[KnowledgeSourceType, DocumentChunker] = {}
        for chunker in chunker_list:
            self._validate_chunker_contract(chunker)
            descriptor = chunker.descriptor
            for source_type in chunker.supported_source_types:
                if source_type in resolved:
                    existing = resolved[source_type]
                    raise KnowledgeChunkerConfigurationError(
                        "Multiple document chunkers are configured for the same source type.",
                        chunker_name=descriptor.strategy_id,
                        source_type=source_type,
                        conflicting_chunker_name=existing.descriptor.strategy_id,
                    )

                resolved[source_type] = chunker

        self._chunkers: Mapping[KnowledgeSourceType, DocumentChunker] = MappingProxyType(resolved)
        self._supported_source_types = frozenset(resolved.keys())

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        return self._supported_source_types

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        self._validate_source_type(source_type)

        return source_type in self._chunkers

    def resolve(self, source_type: KnowledgeSourceType) -> DocumentChunker:
        self._validate_source_type(source_type)
        chunker = self._chunkers.get(source_type)
        if chunker is None:
            available_source_types = tuple(sorted(source.value for source in self._supported_source_types))
            raise UnsupportedKnowledgeChunkingSourceTypeError(source_type, available_source_types=available_source_types,)

        return chunker

    @staticmethod
    def _validate_source_type(source_type: KnowledgeSourceType) -> None:
        if not isinstance(source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType.")

    @classmethod
    def _validate_chunker_contract(cls, chunker: object) -> None:
        """
        Validate all assumptions required by the resolver.

        Validation happens once during application composition rather than repeatedly while processing knowledge versions.
        """
        if not isinstance(chunker, DocumentChunker):
            raise KnowledgeChunkerConfigurationError(
                "Configured chunker does not satisfy the DocumentChunker protocol.",
                chunker_name=cls._safe_chunker_name(chunker)
            )

        descriptor = cls._read_descriptor(chunker)
        supported_source_types = cls._read_supported_source_types(chunker, descriptor)
        for source_type in supported_source_types:
            cls._validate_supports_consistency(chunker, descriptor, source_type)

    @staticmethod
    def _read_descriptor(chunker: DocumentChunker) -> ChunkerDescriptor:
        try:
            descriptor = chunker.descriptor
        except Exception as exc:
            raise KnowledgeChunkerConfigurationError(
                "Unable to read document chunker descriptor.",
                chunker_name=type(chunker).__name__,
            ) from exc

        if not isinstance(descriptor, ChunkerDescriptor):
            raise KnowledgeChunkerConfigurationError(
                "Document chunker descriptor must be a ChunkerDescriptor.",
                chunker_name=type(chunker).__name__,
                actual_descriptor_type=type(descriptor).__name__,
            )

        return descriptor

    @staticmethod
    def _read_supported_source_types(chunker: DocumentChunker, descriptor: ChunkerDescriptor) -> frozenset[KnowledgeSourceType]:
        try:
            supported = chunker.supported_source_types
        except Exception as exc:
            raise KnowledgeChunkerConfigurationError(
                "Unable to read document chunker supported source types.",
                chunker_name=descriptor.strategy_id,
            ) from exc

        if not isinstance(supported, frozenset):
            raise KnowledgeChunkerConfigurationError(
                "Document chunker supported_source_types must be a frozenset.",
                chunker_name=descriptor.strategy_id,
                actual_type=type(supported).__name__
            )

        if not supported:
            raise KnowledgeChunkerConfigurationError(
                "Document chunker must support at least one source type.",
                chunker_name=descriptor.strategy_id
            )

        invalid_source_types = tuple(item for item in supported if not isinstance(item, KnowledgeSourceType))
        if invalid_source_types:
            raise KnowledgeChunkerConfigurationError(
                "Document chunker supported_source_types contains values that are not KnowledgeSourceType members.",
                chunker_name=descriptor.strategy_id,
                invalid_source_types=tuple(repr(item) for item in invalid_source_types),
            )

        return supported

    @staticmethod
    def _validate_supports_consistency(chunker: DocumentChunker, descriptor: ChunkerDescriptor, source_type: KnowledgeSourceType) -> None:
        """
        Ensure the declarative supported_source_types property and behavioral supports(...) method agree.

        A disagreement would otherwise create subtle routing bugs:
        composition could register one capability while the chunker itself reports another.
        """
        try:
            result = chunker.supports(source_type)
        except Exception as exc:
            raise KnowledgeChunkerConfigurationError(
                "Document chunker supports(...) failed for a declared source type.",
                chunker_name=descriptor.strategy_id,
                source_type=source_type,
            ) from exc

        if not isinstance(result, bool):
            raise KnowledgeChunkerConfigurationError(
                "Document chunker supports(...) must return a boolean.",
                chunker_name=descriptor.strategy_id,
                source_type=source_type,
                actual_type=type(result).__name__,
            )

        if not result:
            raise KnowledgeChunkerConfigurationError(
                "Document chunker declares support for a source type but supports(...) returns False.",
                chunker_name=descriptor.strategy_id,
                source_type=source_type,
            )

    @staticmethod
    def _safe_chunker_name(chunker: object) -> str:
        """
        Obtain diagnostic identity without assuming the malformed
        object satisfies the chunker contract.
        """
        return type(chunker).__name__