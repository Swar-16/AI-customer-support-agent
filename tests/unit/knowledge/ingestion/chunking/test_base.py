from __future__ import annotations

from uuid import uuid4

import pytest

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.chunking.base import (
    BaseDocumentChunker,
    ChunkerDescriptor,
    DocumentChunker,
    DocumentChunkerResolver,
)
from packages.knowledge.ingestion.chunking.models import (
    ChunkCandidate,
    ChunkedDocument,
    ChunkSourceSpan,
)
from packages.knowledge.ingestion.normalization.models import (
    NormalizedDocument,
    NormalizedSegment,
)


def make_normalized_document(
    source_type: KnowledgeSourceType = KnowledgeSourceType.MARKDOWN,
) -> NormalizedDocument:
    return NormalizedDocument(
        version_id=uuid4(),
        source_type=source_type,
        segments=(
            NormalizedSegment(
                index=0,
                source_segment_index=0,
                text="hello world",
            ),
        ),
        source_parser_strategy_id="parser",
        source_parser_version="1.0.0",
        source_parser_config_fingerprint=None,
        normalizer_strategy_id="normalizer",
        normalizer_version="1.0.0",
        normalizer_config_fingerprint=None,
    )


class DummyChunker(BaseDocumentChunker):
    @property
    def descriptor(self) -> ChunkerDescriptor:
        return ChunkerDescriptor(
            strategy_id="dummy",
            version="1.0.0",
            config_fingerprint="sha256:dummy",
        )

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset(
            {
                KnowledgeSourceType.MARKDOWN,
                KnowledgeSourceType.PLAIN_TEXT,
            }
        )

    def chunk(
        self,
        document: NormalizedDocument,
    ) -> ChunkedDocument:
        segment = document.segments[0]

        return ChunkedDocument(
            version_id=document.version_id,
            source_type=document.source_type,
            chunks=(
                ChunkCandidate(
                    index=0,
                    text=segment.text,
                    source_spans=(
                        ChunkSourceSpan(
                            source_segment_index=(
                                segment.index
                            ),
                            start_offset=0,
                            end_offset=len(segment.text),
                        ),
                    ),
                ),
            ),
            source_parser_strategy_id=(
                document.source_parser_strategy_id
            ),
            source_parser_version=(
                document.source_parser_version
            ),
            source_parser_config_fingerprint=(
                document.source_parser_config_fingerprint
            ),
            source_normalizer_strategy_id=(
                document.normalizer_strategy_id
            ),
            source_normalizer_version=(
                document.normalizer_version
            ),
            source_normalizer_config_fingerprint=(
                document.normalizer_config_fingerprint
            ),
            chunker_strategy_id=(
                self.descriptor.strategy_id
            ),
            chunker_version=self.descriptor.version,
            chunker_config_fingerprint=(
                self.descriptor.config_fingerprint
            ),
        )


class TestChunkerDescriptor:
    def test_valid_descriptor(self) -> None:
        descriptor = ChunkerDescriptor(
            strategy_id="structural-text",
            version="1.0.0",
            config_fingerprint="sha256:abc",
        )

        assert descriptor.strategy_id == "structural-text"
        assert descriptor.version == "1.0.0"
        assert descriptor.config_fingerprint == "sha256:abc"
        assert descriptor.identity == (
            "structural-text@1.0.0"
        )

    def test_none_fingerprint_allowed(
        self,
    ) -> None:
        descriptor = ChunkerDescriptor(
            strategy_id="static",
            version="1",
        )

        assert descriptor.config_fingerprint is None

    @pytest.mark.parametrize(
        "field_name",
        [
            "strategy_id",
            "version",
        ],
    )
    @pytest.mark.parametrize(
        "value",
        [None, 123, object()],
    )
    def test_required_fields_must_be_strings(
        self,
        field_name: str,
        value,
    ) -> None:
        kwargs = {
            "strategy_id": "dummy",
            "version": "1.0.0",
        }
        kwargs[field_name] = value

        with pytest.raises(TypeError):
            ChunkerDescriptor(**kwargs)

    @pytest.mark.parametrize(
        "field_name",
        [
            "strategy_id",
            "version",
        ],
    )
    @pytest.mark.parametrize(
        "value",
        ["", " ", "\n"],
    )
    def test_required_fields_must_not_be_blank(
        self,
        field_name: str,
        value: str,
    ) -> None:
        kwargs = {
            "strategy_id": "dummy",
            "version": "1.0.0",
        }
        kwargs[field_name] = value

        with pytest.raises(ValueError):
            ChunkerDescriptor(**kwargs)

    def test_fingerprint_must_be_string_or_none(
        self,
    ) -> None:
        with pytest.raises(TypeError):
            ChunkerDescriptor(
                strategy_id="dummy",
                version="1",
                config_fingerprint=123,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "value",
        ["", " ", "\n"],
    )
    def test_fingerprint_must_not_be_blank(
        self,
        value: str,
    ) -> None:
        with pytest.raises(ValueError):
            ChunkerDescriptor(
                strategy_id="dummy",
                version="1",
                config_fingerprint=value,
            )

    def test_descriptor_is_immutable(
        self,
    ) -> None:
        descriptor = ChunkerDescriptor(
            strategy_id="dummy",
            version="1",
        )

        with pytest.raises(Exception):
            descriptor.version = "2"  # type: ignore[misc]


class TestBaseDocumentChunker:
    def test_supports_declared_source_type(
        self,
    ) -> None:
        chunker = DummyChunker()

        assert chunker.supports(
            KnowledgeSourceType.MARKDOWN
        )
        assert chunker.supports(
            KnowledgeSourceType.PLAIN_TEXT
        )

    def test_does_not_support_undeclared_source_type(
        self,
    ) -> None:
        chunker = DummyChunker()

        assert not chunker.supports(
            KnowledgeSourceType.PDF
        )

    @pytest.mark.parametrize(
        "value",
        [
            "markdown",
            None,
            123,
        ],
    )
    def test_supports_rejects_invalid_source_type(
        self,
        value,
    ) -> None:
        chunker = DummyChunker()

        with pytest.raises(
            TypeError,
            match="source_type must be a KnowledgeSourceType",
        ):
            chunker.supports(value)

    def test_concrete_chunker_satisfies_runtime_protocol(
        self,
    ) -> None:
        chunker = DummyChunker()

        assert isinstance(
            chunker,
            DocumentChunker,
        )

    def test_chunk_returns_chunked_document(
        self,
    ) -> None:
        chunker = DummyChunker()
        document = make_normalized_document()

        result = chunker.chunk(document)

        assert isinstance(
            result,
            ChunkedDocument,
        )
        assert result.chunk_count == 1
        assert result.chunks[0].text == "hello world"
        assert result.chunker_identity == (
            "dummy@1.0.0"
        )


class StructuralProtocolChunker:
    @property
    def descriptor(self) -> ChunkerDescriptor:
        return ChunkerDescriptor(
            strategy_id="structural",
            version="1",
        )

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset(
            {
                KnowledgeSourceType.MARKDOWN,
            }
        )

    def supports(
        self,
        source_type: KnowledgeSourceType,
    ) -> bool:
        return source_type in self.supported_source_types

    def chunk(
        self,
        document: NormalizedDocument,
    ) -> ChunkedDocument:
        raise NotImplementedError


def test_runtime_protocol_supports_structural_typing() -> None:
    chunker = StructuralProtocolChunker()

    assert isinstance(
        chunker,
        DocumentChunker,
    )


class StructuralResolver:
    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset(
            {
                KnowledgeSourceType.MARKDOWN,
            }
        )

    def supports(
        self,
        source_type: KnowledgeSourceType,
    ) -> bool:
        return (
            source_type
            in self.supported_source_types
        )

    def resolve(
        self,
        source_type: KnowledgeSourceType,
    ) -> DocumentChunker:
        return DummyChunker()


def test_resolver_protocol_supports_structural_typing() -> None:
    resolver = StructuralResolver()

    assert isinstance(
        resolver,
        DocumentChunkerResolver,
    )