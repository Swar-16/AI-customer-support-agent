from __future__ import annotations

from dataclasses import dataclass

import pytest

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.errors import (
    KnowledgeParserConfigurationError,
    UnsupportedKnowledgeSourceTypeError,
)
from packages.knowledge.ingestion.models import (
    IngestionSource,
    ParsedDocument,
    ParsedSegment,
)
from packages.knowledge.ingestion.parser.base import (
    BaseDocumentParser,
    DocumentParser,
    ParserDescriptor
)
from packages.knowledge.ingestion.parser.resolver import (
    DefaultDocumentParserResolver,
)


@dataclass(frozen=True)
class StubParser(BaseDocumentParser):
    parser_descriptor: ParserDescriptor
    source_types: frozenset[KnowledgeSourceType]

    @property
    def descriptor(self) -> ParserDescriptor:
        return self.parser_descriptor

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return self.source_types

    def parse(
        self,
        source: IngestionSource,
    ) -> ParsedDocument:
        descriptor = self.descriptor

        return ParsedDocument(
            version_id=source.version_id,
            segments=(
                ParsedSegment(
                    index=0,
                    text=source.content,
                ),
            ),
            parser_strategy_id=descriptor.strategy_id,
            parser_version=descriptor.version,
            parser_config_fingerprint=(
                descriptor.config_fingerprint
            ),
        )


class InvalidParser:
    pass


class InconsistentSupportsParser(BaseDocumentParser):
    @property
    def descriptor(self) -> ParserDescriptor:
        return ParserDescriptor(
            strategy_id="inconsistent-parser",
            version="1.0.0",
        )

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset({
            KnowledgeSourceType.PLAIN_TEXT,
        })

    def supports(
        self,
        source_type: KnowledgeSourceType,
    ) -> bool:
        return False

    def parse(
        self,
        source: IngestionSource,
    ) -> ParsedDocument:
        raise NotImplementedError


class TestDefaultDocumentParserResolver:
    def test_resolve_returns_registered_parser(self):
        parser = StubParser(
            parser_descriptor=ParserDescriptor(
        strategy_id="markdown-structural",
        version="1.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.MARKDOWN,
    }),
        )

        resolver = DefaultDocumentParserResolver(
            [parser]
        )

        resolved = resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        )

        assert resolved is parser

    def test_resolve_preserves_parser_identity(self):
        parser = StubParser(
            
            parser_descriptor=ParserDescriptor(
        strategy_id="plain-text-structural",
        version="1.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.PLAIN_TEXT,
    }),
        )

        resolver = DefaultDocumentParserResolver(
            [parser]
        )

        first = resolver.resolve(
            KnowledgeSourceType.PLAIN_TEXT
        )
        second = resolver.resolve(
            KnowledgeSourceType.PLAIN_TEXT
        )

        assert first is parser
        assert second is parser
        assert first is second

    def test_resolver_can_register_multiple_parsers(self):
        markdown_parser = StubParser(
            
            parser_descriptor=ParserDescriptor(
        strategy_id="markdown-structural",
        version="1.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.MARKDOWN,
    }),
        )

        plain_text_parser = StubParser(
            
            parser_descriptor=ParserDescriptor(
        strategy_id="plain-text-structural",
        version="1.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.PLAIN_TEXT,
    }),
        )

        resolver = DefaultDocumentParserResolver(
            [
                markdown_parser,
                plain_text_parser,
            ]
        )

        assert resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        ) is markdown_parser

        assert resolver.resolve(
            KnowledgeSourceType.PLAIN_TEXT
        ) is plain_text_parser

    def test_single_parser_can_support_multiple_source_types(self):
        parser = StubParser(
            
            parser_descriptor=ParserDescriptor(
        strategy_id="text-family-structural",
        version="1.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.MARKDOWN,
        KnowledgeSourceType.PLAIN_TEXT,
    }),
        )

        resolver = DefaultDocumentParserResolver(
            [parser]
        )

        assert resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        ) is parser

        assert resolver.resolve(
            KnowledgeSourceType.PLAIN_TEXT
        ) is parser

    def test_supported_source_types_returns_registered_types(self):
        parser = StubParser(
            
            parser_descriptor=ParserDescriptor(
        strategy_id="text-structural",
        version="1.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.MARKDOWN,
        KnowledgeSourceType.PLAIN_TEXT,
    }),
        )

        resolver = DefaultDocumentParserResolver(
            [parser]
        )

        assert resolver.supported_source_types == frozenset({
            KnowledgeSourceType.MARKDOWN,
            KnowledgeSourceType.PLAIN_TEXT,
        })

    def test_supported_source_types_is_empty_for_empty_registry(self):
        resolver = DefaultDocumentParserResolver([])

        assert resolver.supported_source_types == frozenset()

    def test_supports_returns_true_for_registered_source_type(self):
        parser = StubParser(
            
            parser_descriptor=ParserDescriptor(
        strategy_id="markdown-structural",
        version="1.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.MARKDOWN,
    }),
            
        )

        resolver = DefaultDocumentParserResolver(
            [parser]
        )

        assert resolver.supports(
            KnowledgeSourceType.MARKDOWN
        )

    def test_supports_returns_false_for_unregistered_source_type(self):
        parser = StubParser(
            parser_descriptor=ParserDescriptor(
        strategy_id="markdown-structural",
        version="1.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.MARKDOWN,
    }),
        )

        resolver = DefaultDocumentParserResolver(
            [parser]
        )

        assert not resolver.supports(
            KnowledgeSourceType.PDF
        )

    def test_resolve_unsupported_source_type_raises(self):
        resolver = DefaultDocumentParserResolver([])

        with pytest.raises(
            UnsupportedKnowledgeSourceTypeError
        ) as exc_info:
            resolver.resolve(
                KnowledgeSourceType.PDF
            )

        error = exc_info.value

        assert (
            error.code
            == "KNOWLEDGE_SOURCE_TYPE_UNSUPPORTED"
        )
        assert error.source_type is KnowledgeSourceType.PDF
        assert error.context == {
            "source_type": "pdf",
        }

    def test_resolve_rejects_non_source_type(self):
        resolver = DefaultDocumentParserResolver([])

        with pytest.raises(
            TypeError,
            match="source_type must be a KnowledgeSourceType",
        ):
            resolver.resolve("pdf")  # type: ignore[arg-type]

    def test_supports_rejects_non_source_type(self):
        resolver = DefaultDocumentParserResolver([])

        with pytest.raises(
            TypeError,
            match="source_type must be a KnowledgeSourceType",
        ):
            resolver.supports("pdf")  # type: ignore[arg-type]

    def test_duplicate_source_type_registration_raises(self):
        first = StubParser(
            
            parser_descriptor=ParserDescriptor(
        strategy_id="first-pdf-parser",
        version="1.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.PDF,
    }),
        )

        second = StubParser(
            
            parser_descriptor=ParserDescriptor(
        strategy_id="second-pdf-parser",
        version="2.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.PDF,
    }),
        )

        with pytest.raises(
            KnowledgeParserConfigurationError
        ) as exc_info:
            DefaultDocumentParserResolver(
                [first, second]
            )

        error = exc_info.value

        assert (
            error.code
            == "KNOWLEDGE_PARSER_CONFIGURATION_ERROR"
        )
        assert error.source_type is KnowledgeSourceType.PDF
        assert error.parser_name == "second-pdf-parser"

    def test_parser_without_supported_source_types_raises(self):
        parser = StubParser(
            
            parser_descriptor=ParserDescriptor(
        strategy_id="empty",
        version="1.0.0",
    ),
    source_types=frozenset(),
        )

        with pytest.raises(
            KnowledgeParserConfigurationError,
            match="must support at least one",
        ):
            DefaultDocumentParserResolver(
                [parser]
            )

    def test_invalid_parser_contract_raises(self):
        with pytest.raises(
            KnowledgeParserConfigurationError,
            match="does not satisfy",
        ):
            DefaultDocumentParserResolver(
                [InvalidParser()]  # type: ignore[list-item]
            )

    def test_inconsistent_supports_contract_raises(self):
        parser = InconsistentSupportsParser()

        with pytest.raises(
            KnowledgeParserConfigurationError,
            match="supports\\(\\).*returns False",
        ):
            DefaultDocumentParserResolver(
                [parser]
            )

    def test_resolver_accepts_any_iterable(self):
        parser = StubParser(
            
            parser_descriptor=ParserDescriptor(
        strategy_id="markdown-structural",
        version="1.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.MARKDOWN,
    }),
        )

        parser_generator = (
            item
            for item in [parser]
        )

        resolver = DefaultDocumentParserResolver(
            parser_generator
        )

        assert resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        ) is parser

    def test_resolved_object_satisfies_document_parser_protocol(self):
        parser = StubParser(
            
            parser_descriptor=ParserDescriptor(
        strategy_id="plain-text-structural",
        version="1.0.0",
    ),
    source_types=frozenset({
        KnowledgeSourceType.PLAIN_TEXT,
    }),
        )

        resolver = DefaultDocumentParserResolver(
            [parser]
        )

        resolved = resolver.resolve(
            KnowledgeSourceType.PLAIN_TEXT
        )

        assert isinstance(
            resolved,
            DocumentParser,
        )