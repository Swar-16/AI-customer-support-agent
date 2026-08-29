from __future__ import annotations
from collections.abc import Iterable

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.errors import KnowledgeParserConfigurationError, UnsupportedKnowledgeSourceTypeError
from packages.knowledge.ingestion.parser.base import DocumentParser, DocumentParserResolver


class DefaultDocumentParserResolver(DocumentParserResolver):
    """
    Default in-memory parser registry.

    Parsers are registered once during application composition and resolved
    later by source type.

    The resolver is intentionally immutable after construction from the
    application's perspective. Runtime mutation of parser registration would
    make ingestion behavior unpredictable and harder to reproduce.
    """
    def __init__(self, parsers: Iterable[DocumentParser]) -> None:
        self._parsers_by_source_type = self._build_registry(parsers)
        
    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        return frozenset(self._parsers_by_source_type)

    def supports(self, source_type: KnowledgeSourceType) -> bool:
        if not isinstance(source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType.")

        return source_type in self._parsers_by_source_type

    def resolve(self, source_type: KnowledgeSourceType) -> DocumentParser:
        if not isinstance(source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType.")

        parser = self._parsers_by_source_type.get(source_type)
        if parser is None:
            raise UnsupportedKnowledgeSourceTypeError(source_type)

        return parser

    def _build_registry(self, parsers: Iterable[DocumentParser]) -> dict[KnowledgeSourceType, DocumentParser]:
        registry: dict[KnowledgeSourceType, DocumentParser] = {}

        for parser in parsers:
            self._validate_parser(parser)

            for source_type in parser.supported_source_types:
                existing = registry.get(source_type)
                if existing is not None:
                    raise KnowledgeParserConfigurationError(
                        f"Multiple document parsers are registered for source type '{source_type.value}'.",
                        parser_name=parser.name,
                        source_type=source_type,
                    )

                registry[source_type] = parser

        return registry

    @staticmethod
    def _validate_parser(parser: DocumentParser) -> None:
        if not isinstance(parser, DocumentParser):
            raise KnowledgeParserConfigurationError("Registered parser does not satisfy the DocumentParser contract.")

        if not isinstance(parser.name, str):
            raise KnowledgeParserConfigurationError("Parser name must be a string.")

        if not parser.name.strip():
            raise KnowledgeParserConfigurationError("Parser name must not be blank.")

        if not isinstance(parser.version, str):
            raise KnowledgeParserConfigurationError("Parser version must be a string.", parser_name=parser.name)

        if not parser.version.strip():
            raise KnowledgeParserConfigurationError("Parser version must not be blank.", parser_name=parser.name)

        supported_source_types = parser.supported_source_types
        if not isinstance(supported_source_types, frozenset):
            raise KnowledgeParserConfigurationError("supported_source_types must be a frozenset.", parser_name=parser.name)

        if not supported_source_types:
            raise KnowledgeParserConfigurationError("Parser must support at least one knowledge source type.", parser_name=parser.name)

        for source_type in supported_source_types:
            if not isinstance(source_type, KnowledgeSourceType):
                raise KnowledgeParserConfigurationError("Parser contains an invalid supported source type.", parser_name=parser.name)

            if not parser.supports(source_type):
                raise KnowledgeParserConfigurationError(
                    "Parser reports a source type in supported_source_types but supports() returns False for that same type.",
                    parser_name=parser.name,
                    source_type=source_type,
                )