from __future__ import annotations

from uuid import uuid4

import pytest

from packages.knowledge.domain.enums import (
    KnowledgeSourceType,
)
from packages.knowledge.ingestion.errors import (
    UnsupportedKnowledgeSourceTypeError,
)
from packages.knowledge.ingestion.models import (
    IngestionSource,
    ParsedDocument,
)
from packages.knowledge.ingestion.parser.base import (
    DocumentParser,
)
from packages.knowledge.ingestion.parser.plain_text import (
    PlainTextStructuralParser,
)


class TestPlainTextStructuralParserContract:
    def test_satisfies_document_parser_protocol(self):
        parser = PlainTextStructuralParser()

        assert isinstance(
            parser,
            DocumentParser,
        )

    def test_descriptor_is_stable(self):
        parser = PlainTextStructuralParser()

        descriptor = parser.descriptor

        assert (
            descriptor.strategy_id
            == "plain-text-structural"
        )
        assert descriptor.version == "1.0.0"
        assert descriptor.config_fingerprint is None

    def test_supports_only_plain_text(self):
        parser = PlainTextStructuralParser()

        assert parser.supported_source_types == frozenset({
            KnowledgeSourceType.PLAIN_TEXT,
        })

        assert parser.supports(
            KnowledgeSourceType.PLAIN_TEXT
        )

        assert not parser.supports(
            KnowledgeSourceType.MARKDOWN
        )

        assert not parser.supports(
            KnowledgeSourceType.PDF
        )


class TestPlainTextStructuralParserParsing:
    def test_parses_single_paragraph(self):
        version_id = uuid4()

        source = IngestionSource(
            version_id=version_id,
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content="Refunds are processed within five business days.",
        )

        parser = PlainTextStructuralParser()

        result = parser.parse(source)

        assert isinstance(
            result,
            ParsedDocument,
        )

        assert result.version_id == version_id
        assert result.segment_count == 1

        segment = result.segments[0]

        assert segment.index == 0
        assert (
            segment.text
            == "Refunds are processed within five business days."
        )

    def test_parses_multiple_paragraphs(self):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content=(
                "First paragraph."
                "\n\n"
                "Second paragraph."
                "\n\n"
                "Third paragraph."
            ),
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        assert result.segment_count == 3

        assert [
            segment.text
            for segment in result.segments
        ] == [
            "First paragraph.",
            "Second paragraph.",
            "Third paragraph.",
        ]

    def test_multiple_blank_lines_do_not_create_empty_segments(
        self,
    ):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content=(
                "First paragraph."
                "\n\n\n\n"
                "Second paragraph."
            ),
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        assert result.segment_count == 2

        assert [
            segment.text
            for segment in result.segments
        ] == [
            "First paragraph.",
            "Second paragraph.",
        ]

    def test_whitespace_only_lines_delimit_paragraphs(
        self,
    ):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content=(
                "First paragraph."
                "\n   \n"
                "Second paragraph."
            ),
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        assert result.segment_count == 2

        assert result.segments[0].text == (
            "First paragraph."
        )

        assert result.segments[1].text == (
            "Second paragraph."
        )

    def test_leading_and_trailing_whitespace_is_removed(
        self,
    ):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content=(
                "   First paragraph.   "
                "\n\n"
                "\tSecond paragraph.\t"
            ),
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        assert [
            segment.text
            for segment in result.segments
        ] == [
            "First paragraph.",
            "Second paragraph.",
        ]

    def test_preserves_internal_line_structure_within_block(
        self,
    ):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content=(
                "Refund conditions:\n"
                "- Item must be unused.\n"
                "- Request within 30 days."
            ),
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        assert result.segment_count == 1

        assert result.segments[0].text == (
            "Refund conditions:\n"
            "- Item must be unused.\n"
            "- Request within 30 days."
        )

    def test_preserves_segment_order(self):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content=(
                "Alpha."
                "\n\n"
                "Beta."
                "\n\n"
                "Gamma."
            ),
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        assert [
            segment.text
            for segment in result.segments
        ] == [
            "Alpha.",
            "Beta.",
            "Gamma.",
        ]

    def test_segment_indexes_are_contiguous_and_zero_based(
        self,
    ):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content=(
                "One."
                "\n\n"
                "Two."
                "\n\n"
                "Three."
            ),
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        assert [
            segment.index
            for segment in result.segments
        ] == [
            0,
            1,
            2,
        ]

    def test_offsets_match_exact_segment_text(self):
        content = (
            "   First paragraph.   "
            "\n\n"
            "\tSecond paragraph.\t"
        )

        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content=content,
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        for segment in result.segments:
            assert segment.start_offset is not None
            assert segment.end_offset is not None

            assert (
                content[
                    segment.start_offset:
                    segment.end_offset
                ]
                == segment.text
            )

    def test_offsets_are_half_open(self):
        content = "  Refund policy.  "

        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content=content,
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        segment = result.segments[0]

        assert segment.start_offset == 2
        assert segment.end_offset == 16

        assert (
            content[
                segment.start_offset:
                segment.end_offset
            ]
            == "Refund policy."
        )

    def test_handles_crlf_line_endings(self):
        content = (
            "First paragraph.\r\n"
            "\r\n"
            "Second paragraph."
        )

        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content=content,
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        assert result.segment_count == 2

        assert [
            segment.text
            for segment in result.segments
        ] == [
            "First paragraph.",
            "Second paragraph.",
        ]

        for segment in result.segments:
            assert (
                content[
                    segment.start_offset:
                    segment.end_offset
                ]
                == segment.text
            )

    def test_final_block_without_trailing_newline_is_flushed(
        self,
    ):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content=(
                "First."
                "\n\n"
                "Final paragraph."
            ),
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        assert result.segment_count == 2
        assert (
            result.segments[-1].text
            == "Final paragraph."
        )


class TestPlainTextStructuralParserProvenance:
    def test_parser_provenance_is_added_to_result(self):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content="Knowledge content.",
        )

        parser = PlainTextStructuralParser()

        result = parser.parse(source)

        assert (
            result.parser_strategy_id
            == parser.descriptor.strategy_id
        )

        assert (
            result.parser_version
            == parser.descriptor.version
        )

        assert (
            result.parser_config_fingerprint
            == parser.descriptor.config_fingerprint
        )

        assert (
            result.parser_identity
            == "plain-text-structural@1.0.0"
        )

    def test_result_contains_source_type_metadata(self):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content="Knowledge content.",
        )

        result = PlainTextStructuralParser().parse(
            source
        )

        assert (
            result.metadata["source_type"]
            == KnowledgeSourceType.PLAIN_TEXT.value
        )


class TestPlainTextStructuralParserValidation:
    def test_rejects_wrong_source_object_type(self):
        parser = PlainTextStructuralParser()

        with pytest.raises(
            TypeError,
            match="source must be an IngestionSource",
        ):
            parser.parse(  # type: ignore[arg-type]
                "plain text"
            )

    @pytest.mark.parametrize(
        "source_type",
        [
            KnowledgeSourceType.MARKDOWN,
            KnowledgeSourceType.PDF,
            KnowledgeSourceType.DOCX,
            KnowledgeSourceType.HTML,
        ],
    )
    def test_rejects_unsupported_source_types(
        self,
        source_type,
    ):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=source_type,
            content="Some content.",
        )

        parser = PlainTextStructuralParser()

        with pytest.raises(
            UnsupportedKnowledgeSourceTypeError
        ) as exc_info:
            parser.parse(source)

        assert (
            exc_info.value.source_type
            is source_type
        )

    def test_parse_does_not_modify_source(self):
        source = IngestionSource(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            content="  Original content.  ",
            metadata={
                "origin": "admin",
            },
        )

        original_content = source.content
        original_metadata = dict(source.metadata)

        PlainTextStructuralParser().parse(
            source
        )

        assert source.content == original_content
        assert dict(source.metadata) == original_metadata