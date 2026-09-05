from __future__ import annotations

from uuid6 import uuid7

import pytest

from packages.knowledge.domain.enums import (
    KnowledgeSourceType,
)
from packages.knowledge.ingestion.models import (
    ParsedDocument,
    ParsedSegment,
)
from packages.knowledge.ingestion.normalization.base import (
    BaseDocumentNormalizer,
    DocumentNormalizer,
    NormalizerDescriptor,
)
from packages.knowledge.ingestion.normalization.models import (
    NormalizedDocument,
    NormalizedSegment,
)


class TestNormalizerDescriptor:
    def test_valid_descriptor(self):
        descriptor = NormalizerDescriptor(
            strategy_id="markdown-semantic",
            version="1.0.0",
            config_fingerprint="abc123",
        )

        assert (
            descriptor.strategy_id
            == "markdown-semantic"
        )
        assert descriptor.version == "1.0.0"
        assert (
            descriptor.config_fingerprint
            == "abc123"
        )

    def test_config_fingerprint_is_optional(
        self,
    ):
        descriptor = NormalizerDescriptor(
            strategy_id="markdown-semantic",
            version="1.0.0",
        )

        assert (
            descriptor.config_fingerprint
            is None
        )

    @pytest.mark.parametrize(
        "strategy_id",
        [
            "",
            " ",
            "\t",
            "\n",
        ],
    )
    def test_blank_strategy_id_rejected(
        self,
        strategy_id,
    ):
        with pytest.raises(
            ValueError,
            match=(
                "strategy_id must not be blank"
            ),
        ):
            NormalizerDescriptor(
                strategy_id=strategy_id,
                version="1.0.0",
            )

    @pytest.mark.parametrize(
        "version",
        [
            "",
            " ",
            "\t",
            "\n",
        ],
    )
    def test_blank_version_rejected(
        self,
        version,
    ):
        with pytest.raises(
            ValueError,
            match="version must not be blank",
        ):
            NormalizerDescriptor(
                strategy_id="markdown-semantic",
                version=version,
            )

    @pytest.mark.parametrize(
        "fingerprint",
        [
            "",
            " ",
            "\t",
            "\n",
        ],
    )
    def test_blank_fingerprint_rejected(
        self,
        fingerprint,
    ):
        with pytest.raises(
            ValueError,
            match=(
                "config_fingerprint must "
                "not be blank"
            ),
        ):
            NormalizerDescriptor(
                strategy_id="markdown-semantic",
                version="1.0.0",
                config_fingerprint=fingerprint,
            )

    def test_non_string_strategy_id_rejected(
        self,
    ):
        with pytest.raises(TypeError):
            NormalizerDescriptor(
                strategy_id=123,  # type: ignore[arg-type]
                version="1.0.0",
            )

    def test_non_string_version_rejected(
        self,
    ):
        with pytest.raises(TypeError):
            NormalizerDescriptor(
                strategy_id="markdown-semantic",
                version=123,  # type: ignore[arg-type]
            )

    def test_non_string_fingerprint_rejected(
        self,
    ):
        with pytest.raises(TypeError):
            NormalizerDescriptor(
                strategy_id="markdown-semantic",
                version="1.0.0",
                config_fingerprint=123,  # type: ignore[arg-type]
            )


class StubNormalizer(
    BaseDocumentNormalizer
):
    @property
    def descriptor(
        self,
    ) -> NormalizerDescriptor:
        return NormalizerDescriptor(
            strategy_id="stub-normalizer",
            version="1.0.0",
        )

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset({
            KnowledgeSourceType.MARKDOWN,
        })

    def normalize(
        self,
        document: ParsedDocument,
    ) -> NormalizedDocument:
        return NormalizedDocument(
            version_id=document.version_id,
            source_type=document.source_type,
            segments=tuple(
                NormalizedSegment(
                    index=index,
                    source_segment_index=(
                        segment.index
                    ),
                    text=segment.text,
                    section_path=(
                        segment.section_path
                    ),
                )
                for index, segment
                in enumerate(
                    document.segments
                )
            ),
            source_parser_strategy_id=(
                document.parser_strategy_id
            ),
            source_parser_version=(
                document.parser_version
            ),
            source_parser_config_fingerprint=(
                document.parser_config_fingerprint
            ),
            normalizer_strategy_id=(
                self.descriptor.strategy_id
            ),
            normalizer_version=(
                self.descriptor.version
            ),
            normalizer_config_fingerprint=(
                self.descriptor.config_fingerprint
            ),
        )


class TestDocumentNormalizerContract:
    def test_base_normalizer_satisfies_protocol(
        self,
    ):
        normalizer = StubNormalizer()

        assert isinstance(
            normalizer,
            DocumentNormalizer,
        )

    def test_supports_registered_source_type(
        self,
    ):
        normalizer = StubNormalizer()

        assert normalizer.supports(
            KnowledgeSourceType.MARKDOWN
        )

    def test_does_not_support_unregistered_source_type(
        self,
    ):
        normalizer = StubNormalizer()

        assert not normalizer.supports(
            KnowledgeSourceType.PDF
        )

    def test_normalizer_can_produce_document(
        self,
    ):
        parsed = ParsedDocument(
            version_id=uuid7(),
            source_type=(
                KnowledgeSourceType.MARKDOWN
            ),
            segments=(
                ParsedSegment(
                    index=0,
                    text="**Refund policy**",
                    section_path=(
                        "Refunds",
                    ),
                ),
            ),
            parser_strategy_id=(
                "markdown-structural"
            ),
            parser_version="1.0.0",
            parser_config_fingerprint=None,
        )

        normalized = (
            StubNormalizer().normalize(
                parsed
            )
        )

        assert isinstance(
            normalized,
            NormalizedDocument,
        )

        assert (
            normalized.version_id
            == parsed.version_id
        )

        assert (
            normalized.source_parser_strategy_id
            == parsed.parser_strategy_id
        )

        assert (
            normalized.segments[0]
            .source_segment_index
            == 0
        )