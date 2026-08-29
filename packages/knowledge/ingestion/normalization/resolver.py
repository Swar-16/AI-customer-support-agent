from __future__ import annotations
from collections.abc import Iterable
from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.normalization.base import DocumentNormalizer, DocumentNormalizerResolver, NormalizerDescriptor
from packages.knowledge.ingestion.normalization.errors import KnowledgeNormalizerConfigurationError, UnsupportedKnowledgeNormalizationSourceTypeError


class DefaultDocumentNormalizerResolver(DocumentNormalizerResolver):
    """
    Immutable registry of active normalization strategies.

    Exactly one active normalizer may own a given source type.
    Strategy selection happens in composition/configuration.
    """
    def __init__(self,  normalizers: Iterable[DocumentNormalizer]) -> None:
        self._normalizers_by_source_type = self._build_registry(normalizers)

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        return frozenset(self._normalizers_by_source_type)

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        self._validate_source_type(source_type)

        return source_type in self._normalizers_by_source_type

    def resolve(self, source_type: KnowledgeSourceType) -> DocumentNormalizer:
        self._validate_source_type(source_type)
        normalizer = self._normalizers_by_source_type.get(source_type)
        if normalizer is None:
            raise UnsupportedKnowledgeNormalizationSourceTypeError(source_type)

        return normalizer

    @classmethod
    def _build_registry(cls, normalizers: Iterable[DocumentNormalizer]) -> dict[KnowledgeSourceType, DocumentNormalizer]:
        registry: dict[KnowledgeSourceType, DocumentNormalizer] = {}

        for normalizer in normalizers:
            cls._validate_normalizer(normalizer)
            descriptor = normalizer.descriptor

            for source_type in normalizer.supported_source_types:
                if source_type in registry:
                    raise KnowledgeNormalizerConfigurationError(
                        f"Multiple active document normalizers are registered for source type '{source_type.value}'.",
                        normalizer_name=descriptor.strategy_id,
                        source_type=source_type,
                    )

                registry[source_type] = normalizer

        return registry

    @staticmethod
    def _validate_normalizer(normalizer: DocumentNormalizer) -> None:
        if not isinstance(normalizer, DocumentNormalizer):
            raise KnowledgeNormalizerConfigurationError("Registered normalizer does not satisfy the DocumentNormalizer contract.")

        descriptor = normalizer.descriptor
        if not isinstance(descriptor, NormalizerDescriptor):
            raise KnowledgeNormalizerConfigurationError("Normalizer descriptor must be a NormalizerDescriptor.")

        supported_source_types = normalizer.supported_source_types

        if not isinstance(supported_source_types, frozenset):
            raise KnowledgeNormalizerConfigurationError("supported_source_types must be a frozenset.", normalizer_name=descriptor.strategy_id)

        if not supported_source_types:
            raise KnowledgeNormalizerConfigurationError("Normalizer must support at least one knowledge source type.", normalizer_name=descriptor.strategy_id)

        for source_type in supported_source_types:
            if not isinstance(source_type, KnowledgeSourceType):
                raise KnowledgeNormalizerConfigurationError("Normalizer contains an invalid supported source type.", normalizer_name=descriptor.strategy_id,)

            if not normalizer.supports(source_type):
                raise KnowledgeNormalizerConfigurationError(
                    "Normalizer reports a source type in supported_source_types but supports() returns False for that same type.",
                    normalizer_name=descriptor.strategy_id,
                    source_type=source_type
                )

    @staticmethod
    def _validate_source_type(source_type: KnowledgeSourceType) -> None:
        if not isinstance(source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType.")