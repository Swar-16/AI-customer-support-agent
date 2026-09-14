# AI-customer-support-agent\packages\application\composition\knowledge_ingestion_factory.py
from __future__ import annotations
from dataclasses import dataclass

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.chunking.base import DocumentChunkerResolver
from packages.knowledge.ingestion.chunking.resolver import DefaultDocumentChunkerResolver
from packages.knowledge.ingestion.chunking.semantic_text import StructuralTextChunker, StructuralTextChunkerConfig
from packages.knowledge.ingestion.normalization.base import DocumentNormalizerResolver
from packages.knowledge.ingestion.normalization.markdown import MarkdownNormalizer
from packages.knowledge.ingestion.normalization.plain_text import PlainTextNormalizer
from packages.knowledge.ingestion.normalization.resolver import DefaultDocumentNormalizerResolver
from packages.knowledge.ingestion.parser.base import DocumentParserResolver
from packages.knowledge.ingestion.parser.markdown import MarkdownStructuralParser
from packages.knowledge.ingestion.parser.plain_text import PlainTextStructuralParser
from packages.knowledge.ingestion.parser.resolver import DefaultDocumentParserResolver

SUPPORTED_UPLOAD_SOURCE_TYPES = frozenset({KnowledgeSourceType.MARKDOWN, KnowledgeSourceType.PLAIN_TEXT,})

class KnowledgeIngestionConfigurationError(RuntimeError):
    """Raised when the composed ingestion pipeline is incomplete."""

@dataclass(frozen=True, slots=True)
class KnowledgeIngestionComponents:
    """
    Complete ingestion strategy graph used by API requests and workers.

    Every source type advertised through `supported_source_types` is guaranteed to have a parser, normalizer and chunker.
    """
    parser_resolver: DocumentParserResolver
    normalizer_resolver: DocumentNormalizerResolver
    chunker_resolver: DocumentChunkerResolver
    supported_source_types: frozenset[KnowledgeSourceType]

    def __post_init__(self) -> None:
        if not isinstance(self.parser_resolver, DocumentParserResolver):
            raise TypeError("parser_resolver must satisfy DocumentParserResolver.")

        if not isinstance(self.normalizer_resolver, DocumentNormalizerResolver):
            raise TypeError("normalizer_resolver must satisfy DocumentNormalizerResolver.")

        if not isinstance(self.chunker_resolver, DocumentChunkerResolver):
            raise TypeError("chunker_resolver must satisfy DocumentChunkerResolver.")

        if not isinstance(self.supported_source_types, frozenset):
            raise TypeError("supported_source_types must be a frozenset.")

        if not self.supported_source_types:
            raise ValueError("supported_source_types must not be empty.")

        if not all(isinstance(source_type, KnowledgeSourceType) for source_type in self.supported_source_types):
            raise TypeError("supported_source_types must contain only KnowledgeSourceType values.")

        _validate_pipeline_support(
            parser_resolver=self.parser_resolver,
            normalizer_resolver=self.normalizer_resolver,
            chunker_resolver=self.chunker_resolver,
            required_source_types=self.supported_source_types,
        )

def create_knowledge_ingestion_components(*, chunker_config: StructuralTextChunkerConfig | None = None) -> KnowledgeIngestionComponents:
    """
    Construct the production ingestion graph for supported text uploads.

    Supported formats:

    - Markdown (`KnowledgeSourceType.MARKDOWN`)
    - UTF-8 plain text (`KnowledgeSourceType.PLAIN_TEXT`)

    Binary PDF/DOCX and HTML strategies are intentionally not registered.
    Their enum values exist for future expansion but must not be advertised
    as operational until complete parser and normalizer implementations exist.
    """
    if chunker_config is not None and not isinstance(chunker_config, StructuralTextChunkerConfig):
        raise TypeError("chunker_config must be a StructuralTextChunkerConfig or None.")

    parser_resolver = DefaultDocumentParserResolver((MarkdownStructuralParser(), PlainTextStructuralParser(),))
    normalizer_resolver = DefaultDocumentNormalizerResolver((MarkdownNormalizer(), PlainTextNormalizer(),))
    chunker_resolver = DefaultDocumentChunkerResolver((StructuralTextChunker(config=chunker_config),))
    components = KnowledgeIngestionComponents(
        parser_resolver=parser_resolver,
        normalizer_resolver=normalizer_resolver,
        chunker_resolver=chunker_resolver,
        supported_source_types=SUPPORTED_UPLOAD_SOURCE_TYPES,
    )

    # Resolve every strategy eagerly. A broken resolver must fail application startup, not the first administrator upload.
    _resolve_every_strategy(components)

    return components

def _validate_pipeline_support(*, parser_resolver: DocumentParserResolver, normalizer_resolver: DocumentNormalizerResolver, 
                               chunker_resolver: DocumentChunkerResolver, required_source_types: frozenset[KnowledgeSourceType]
) -> None:
    resolvers: tuple[tuple[str, object], ...,] = (("parser", parser_resolver), ("normalizer", normalizer_resolver), ("chunker", chunker_resolver),)
    for stage_name, resolver in resolvers:
        supported = getattr(resolver, "supported_source_types", None)
        if not isinstance(supported, frozenset):
            raise KnowledgeIngestionConfigurationError(f"{stage_name} resolver must expose supported_source_types as a frozenset.")

        invalid_types = tuple(source_type for source_type in supported if not isinstance(source_type, KnowledgeSourceType))
        if invalid_types:
            raise KnowledgeIngestionConfigurationError(f"{stage_name} resolver contains invalid source-type registrations.")

        missing = required_source_types - supported
        if missing:
            missing_values = ", ".join(sorted(source_type.value for source_type in missing))
            raise KnowledgeIngestionConfigurationError(f"{stage_name} resolver is missing required source types: {missing_values}.")

        supports = getattr(resolver, "supports", None)
        resolve = getattr(resolver, "resolve", None)
        if not callable(supports) or not callable(resolve):
            raise KnowledgeIngestionConfigurationError(f"{stage_name} resolver does not implement the required resolver operations.")

        for source_type in required_source_types:
            try:
                supported_result = supports(source_type)
                
            except Exception as exc:
                raise KnowledgeIngestionConfigurationError(f"{stage_name} resolver failed while checking source type '{source_type.value}'.") from exc

            if supported_result is not True:
                raise KnowledgeIngestionConfigurationError(f"{stage_name} resolver does not support '{source_type.value}'.")

def _resolve_every_strategy(components: KnowledgeIngestionComponents) -> None:
    for source_type in components.supported_source_types:
        try:
            parser = components.parser_resolver.resolve(source_type)
            normalizer = components.normalizer_resolver.resolve(source_type)
            chunker = components.chunker_resolver.resolve(source_type)
            
        except Exception as exc:
            raise KnowledgeIngestionConfigurationError(f"Knowledge ingestion strategy resolution failed for '{source_type.value}'.") from exc

        resolved_strategies = (("parser", parser), ("normalizer", normalizer), ("chunker", chunker),)
        for stage_name, strategy in resolved_strategies:
            supports = getattr(strategy, "supports", None)
            if not callable(supports):
                raise KnowledgeIngestionConfigurationError(
                    f"Resolved {stage_name} for '{source_type.value}' does not implement supports()."
                )

            try:
                supports_source = supports(source_type)
                
            except Exception as exc:
                raise KnowledgeIngestionConfigurationError(
                    f"Resolved {stage_name} failed its capability check for '{source_type.value}'.") from exc

            if supports_source is not True:
                raise KnowledgeIngestionConfigurationError(f"Resolved {stage_name} does not support '{source_type.value}'.")