from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid6 import uuid7

import pytest

from packages.knowledge.domain.enums import (
    KnowledgeSourceType,
)
from packages.knowledge.ingestion.models import (
    ParsedDocument,
    ParsedSegment,
)
from packages.knowledge.ingestion.normalization.errors import (
    InvalidNormalizedDocumentError,
    KnowledgeNormalizationExecutionError,
)
from packages.knowledge.ingestion.normalization.markdown import (
    MarkdownNormalizer,
    MarkdownNormalizerConfig,
)
from packages.knowledge.ingestion.normalization.models import (
    NormalizedDocument,
    NormalizedSegment,
)


def make_segment(
    text: str,
    *,
    index: int = 0,
    section_path: tuple[str, ...] = (),
    page_number: int | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
    metadata: dict | None = None,
) -> ParsedSegment:
    return ParsedSegment(
        index=index,
        text=text,
        section_path=section_path,
        page_number=page_number,
        start_offset=start_offset,
        end_offset=end_offset,
        metadata=metadata or {},
    )


def make_document(
    *segments: ParsedSegment,
    source_type: KnowledgeSourceType = KnowledgeSourceType.MARKDOWN,
    metadata: dict | None = None,
    parser_strategy_id: str = "markdown-structural",
    parser_version: str = "1.0.0",
    parser_config_fingerprint: str | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        version_id=uuid7(),
        source_type=source_type,
        segments=tuple(segments),
        parser_strategy_id=parser_strategy_id,
        parser_version=parser_version,
        parser_config_fingerprint=parser_config_fingerprint,
        metadata=metadata or {},
    )


class TestMarkdownNormalizerDescriptor:
    def test_descriptor_is_stable(self):
        normalizer = MarkdownNormalizer()

        assert (
            normalizer.descriptor.strategy_id
            == "markdown-semantic"
        )
        assert (
            normalizer.descriptor.version
            == "1.0.0"
        )
        assert (
            normalizer.descriptor.config_fingerprint
            is not None
        )

    def test_supports_markdown_only(self):
        normalizer = MarkdownNormalizer()

        assert normalizer.supports(
            KnowledgeSourceType.MARKDOWN
        )

        assert not normalizer.supports(
            KnowledgeSourceType.PLAIN_TEXT
        )

        assert not normalizer.supports(
            KnowledgeSourceType.HTML
        )

        assert not normalizer.supports(
            KnowledgeSourceType.PDF
        )

    def test_supported_source_types_is_frozenset(self):
        normalizer = MarkdownNormalizer()

        assert (
            normalizer.supported_source_types
            == frozenset({
                KnowledgeSourceType.MARKDOWN
            })
        )

    def test_same_config_produces_same_fingerprint(self):
        first = MarkdownNormalizer(
            MarkdownNormalizerConfig(
                include_link_destinations=True
            )
        )

        second = MarkdownNormalizer(
            MarkdownNormalizerConfig(
                include_link_destinations=True
            )
        )

        assert (
            first.descriptor.config_fingerprint
            == second.descriptor.config_fingerprint
        )

    def test_different_config_changes_fingerprint(self):
        first = MarkdownNormalizer(
            MarkdownNormalizerConfig(
                include_link_destinations=False
            )
        )

        second = MarkdownNormalizer(
            MarkdownNormalizerConfig(
                include_link_destinations=True
            )
        )

        assert (
            first.descriptor.config_fingerprint
            != second.descriptor.config_fingerprint
        )

    def test_config_is_immutable(self):
        config = MarkdownNormalizerConfig()

        with pytest.raises(
            FrozenInstanceError
        ):
            config.preserve_code_blocks = False  # type: ignore[misc]


class TestMarkdownNormalizerConfigValidation:
    @pytest.mark.parametrize(
        "field_name",
        [
            "preserve_code_blocks",
            "preserve_inline_code",
            "include_link_destinations",
            "include_image_destinations",
            "preserve_table_structure",
            "collapse_internal_whitespace",
        ],
    )
    def test_boolean_fields_reject_non_boolean(
        self,
        field_name,
    ):
        kwargs = {
            field_name: 1,
        }

        with pytest.raises(
            TypeError,
            match="must be a boolean",
        ):
            MarkdownNormalizerConfig(
                **kwargs
            )

    def test_max_consecutive_newlines_rejects_non_integer(
        self,
    ):
        with pytest.raises(
            TypeError,
            match=(
                "max_consecutive_newlines "
                "must be an integer"
            ),
        ):
            MarkdownNormalizerConfig(
                max_consecutive_newlines="2"  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "value",
        [
            0,
            -1,
            -100,
        ],
    )
    def test_max_consecutive_newlines_must_be_positive(
        self,
        value,
    ):
        with pytest.raises(
            ValueError,
            match="greater than zero",
        ):
            MarkdownNormalizerConfig(
                max_consecutive_newlines=value
            )


class TestBasicMarkdownNormalization:
    def test_plain_text_is_preserved(self):
        document = make_document(
            make_segment(
                "Refunds are available within 30 days."
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Refunds are available within 30 days."
        )

    def test_bold_markup_removed(self):
        document = make_document(
            make_segment(
                "Refunds are **available**."
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Refunds are available."
        )

    def test_italic_markup_removed(self):
        document = make_document(
            make_segment(
                "Refunds are *available*."
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Refunds are available."
        )

    def test_nested_emphasis_is_normalized(self):
        document = make_document(
            make_segment(
                "This is ***very important***."
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "This is very important."
        )

    def test_strikethrough_markup_removed(self):
        document = make_document(
            make_segment(
                "Old ~~policy~~ rule."
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Old policy rule."
        )

    def test_inline_code_preserved_by_default(self):
        document = make_document(
            make_segment(
                "Call `refund_order()`."
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Call refund_order()."
        )

    def test_inline_code_can_be_removed(self):
        normalizer = MarkdownNormalizer(
            MarkdownNormalizerConfig(
                preserve_inline_code=False
            )
        )

        document = make_document(
            make_segment(
                "Call `refund_order()` now."
            )
        )

        result = normalizer.normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Call now."
        )

    def test_heading_marker_removed(self):
        document = make_document(
            make_segment(
                "# Refund Policy"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Refund Policy"
        )

    def test_setext_heading_normalized(self):
        document = make_document(
            make_segment(
                "Refund Policy\n============="
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Refund Policy"
        )

    def test_escaped_markdown_character_preserved_semantically(
        self,
    ):
        document = make_document(
            make_segment(
                r"\*Not italic\*"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "*Not italic*"
        )

    def test_html_entity_decoded(self):
        document = make_document(
            make_segment(
                "Terms &amp; Conditions"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Terms & Conditions"
        )


class TestLinks:
    def test_link_keeps_label_by_default(self):
        document = make_document(
            make_segment(
                "[Refund policy](https://example.com/refunds)"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Refund policy"
        )

    def test_link_destination_can_be_included(self):
        normalizer = MarkdownNormalizer(
            MarkdownNormalizerConfig(
                include_link_destinations=True
            )
        )

        document = make_document(
            make_segment(
                "[Refund policy](https://example.com/refunds)"
            )
        )

        result = normalizer.normalize(
            document
        )

        assert (
            result.segments[0].text
            == (
                "Refund policy "
                "(https://example.com/refunds)"
            )
        )

    def test_formatted_link_label_preserved(self):
        document = make_document(
            make_segment(
                "[**Refund policy**](https://example.com)"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Refund policy"
        )

    def test_reference_style_link_normalized(self):
        document = make_document(
            make_segment(
                "[Refund policy][refunds]\n\n"
                "[refunds]: https://example.com/refunds"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert "Refund policy" in (
            result.segments[0].text
        )


class TestImages:
    def test_image_keeps_alt_text(self):
        document = make_document(
            make_segment(
                "![Payment flow](diagram.png)"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Payment flow"
        )

    def test_image_destination_can_be_included(self):
        normalizer = MarkdownNormalizer(
            MarkdownNormalizerConfig(
                include_image_destinations=True
            )
        )

        document = make_document(
            make_segment(
                "![Payment flow](diagram.png)"
            )
        )

        result = normalizer.normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Payment flow (diagram.png)"
        )

    def test_empty_image_alt_does_not_crash(self):
        document = make_document(
            make_segment(
                "![](diagram.png)"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert isinstance(
            result,
            NormalizedDocument,
        )


class TestLists:
    def test_unordered_list(self):
        document = make_document(
            make_segment(
                "- Refund requested\n"
                "- Refund approved\n"
                "- Refund completed"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        text = result.segments[0].text

        assert "Refund requested" in text
        assert "Refund approved" in text
        assert "Refund completed" in text

    def test_ordered_list(self):
        document = make_document(
            make_segment(
                "1. Submit request\n"
                "2. Review request\n"
                "3. Issue refund"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        text = result.segments[0].text

        assert "Submit request" in text
        assert "Review request" in text
        assert "Issue refund" in text

    def test_nested_list_content_preserved(self):
        document = make_document(
            make_segment(
                "- Payments\n"
                "  - Cards\n"
                "  - UPI\n"
                "- Refunds"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        text = result.segments[0].text

        assert "Payments" in text
        assert "Cards" in text
        assert "UPI" in text
        assert "Refunds" in text

    def test_task_list_style_content_tolerated(self):
        document = make_document(
            make_segment(
                "- [x] Refund approved\n"
                "- [ ] Refund pending"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        text = result.segments[0].text

        assert "Refund approved" in text
        assert "Refund pending" in text


class TestBlockQuotes:
    def test_blockquote_content_preserved(self):
        document = make_document(
            make_segment(
                "> Refunds may take five business days."
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Refunds may take five business days."
        )

    def test_nested_blockquote_content_preserved(self):
        document = make_document(
            make_segment(
                "> Primary note\n"
                ">> Secondary note"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        text = result.segments[0].text

        assert "Primary note" in text
        assert "Secondary note" in text


class TestCodeBlocks:
    def test_fenced_code_preserved_by_default(self):
        document = make_document(
            make_segment(
                "```python\n"
                "refund(order_id)\n"
                "```"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "refund(order_id)"
        )

    def test_tilde_fence_preserved(self):
        document = make_document(
            make_segment(
                "~~~python\n"
                "refund(order_id)\n"
                "~~~"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "refund(order_id)"
        )

    def test_indented_code_preserved(self):
        document = make_document(
            make_segment(
                "    refund(order_id)"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "refund(order_id)"
        )

    def test_code_block_can_be_removed(self):
        normalizer = MarkdownNormalizer(
            MarkdownNormalizerConfig(
                preserve_code_blocks=False
            )
        )

        document = make_document(
            make_segment(
                "Before\n\n"
                "```python\n"
                "refund(order_id)\n"
                "```\n\n"
                "After"
            )
        )

        result = normalizer.normalize(
            document
        )

        text = result.segments[0].text

        assert "Before" in text
        assert "After" in text
        assert "refund(order_id)" not in text

    def test_markdown_inside_code_is_not_interpreted(
        self,
    ):
        document = make_document(
            make_segment(
                "```text\n"
                "# Not a heading\n"
                "**not bold**\n"
                "[not link](example.com)\n"
                "```"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        text = result.segments[0].text

        assert "# Not a heading" in text
        assert "**not bold**" in text
        assert "[not link](example.com)" in text


class TestTables:
    def test_table_content_preserved(self):
        document = make_document(
            make_segment(
                "| Method | Delay |\n"
                "| --- | --- |\n"
                "| Card | 5 days |\n"
                "| UPI | 2 days |"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        text = result.segments[0].text

        assert "Method" in text
        assert "Delay" in text
        assert "Card" in text
        assert "5 days" in text
        assert "UPI" in text
        assert "2 days" in text

    def test_table_structure_separator_used_by_default(
        self,
    ):
        document = make_document(
            make_segment(
                "| A | B |\n"
                "| --- | --- |\n"
                "| X | Y |"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert "|" in (
            result.segments[0].text
        )

    def test_table_structure_can_be_flattened(self):
        normalizer = MarkdownNormalizer(
            MarkdownNormalizerConfig(
                preserve_table_structure=False
            )
        )

        document = make_document(
            make_segment(
                "| A | B |\n"
                "| --- | --- |\n"
                "| X | Y |"
            )
        )

        result = normalizer.normalize(
            document
        )

        assert "A" in result.segments[0].text
        assert "B" in result.segments[0].text
        assert "X" in result.segments[0].text
        assert "Y" in result.segments[0].text


class TestHTMLInsideMarkdown:
    def test_inline_html_text_preserved(self):
        document = make_document(
            make_segment(
                "Refunds are <strong>not available</strong> "
                "after 30 days."
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert "not available" in (
            result.segments[0].text
        )

    def test_html_block_visible_text_preserved(self):
        document = make_document(
            make_segment(
                "<div>\n"
                "Enterprise refund policy applies.\n"
                "</div>"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            "Enterprise refund policy applies."
            in result.segments[0].text
        )

    def test_script_content_not_exposed(self):
        document = make_document(
            make_segment(
                "<script>"
                "alert('secret')"
                "</script>"
                "<p>Visible policy</p>"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        text = result.segments[0].text

        assert "Visible policy" in text
        assert "alert('secret')" not in text

    def test_style_content_not_exposed(self):
        document = make_document(
            make_segment(
                "<style>"
                ".hidden { display:none; }"
                "</style>"
                "<p>Visible policy</p>"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        text = result.segments[0].text

        assert "Visible policy" in text
        assert "display:none" not in text

    def test_malformed_html_does_not_crash(self):
        document = make_document(
            make_segment(
                "<div><strong>Refund policy"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert isinstance(
            result,
            NormalizedDocument,
        )


class TestWhitespaceHandling:
    def test_crlf_normalized_to_lf(self):
        document = make_document(
            make_segment(
                "First\r\n\r\nSecond"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert "\r" not in (
            result.segments[0].text
        )

    def test_old_mac_line_endings_normalized(self):
        document = make_document(
            make_segment(
                "First\rSecond"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert "\r" not in (
            result.segments[0].text
        )

    def test_horizontal_whitespace_collapsed_by_default(
        self,
    ):
        document = make_document(
            make_segment(
                "Refunds     are\t\tavailable."
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Refunds are available."
        )

    def test_leading_and_trailing_whitespace_removed(
        self,
    ):
        document = make_document(
            make_segment(
                "   Refund policy.   "
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "Refund policy."
        )

    def test_excessive_newlines_collapsed(self):
        document = make_document(
            make_segment(
                "First\n\n\n\n\nSecond"
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert "\n\n\n" not in (
            result.segments[0].text
        )

    def test_custom_max_newline_count(self):
        normalizer = MarkdownNormalizer(
            MarkdownNormalizerConfig(
                max_consecutive_newlines=1
            )
        )

        document = make_document(
            make_segment(
                "First\n\n\nSecond"
            )
        )

        result = normalizer.normalize(
            document
        )

        assert "\n\n" not in (
            result.segments[0].text
        )


class TestUnicodeAndInternationalText:
    @pytest.mark.parametrize(
        "text",
        [
            "রিফান্ড ৩০ দিনের মধ্যে পাওয়া যাবে।",
            "रिफंड 30 दिनों के भीतर उपलब्ध है।",
            "退款将在30天内完成。",
            "返金は30日以内に処理されます。",
            "سيتم رد المبلغ خلال 30 يومًا.",
            "Refund available ✅",
            "Café résumé naïve",
            "Price: ₹1,999",
        ],
    )
    def test_unicode_content_preserved(
        self,
        text,
    ):
        document = make_document(
            make_segment(text)
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert text in (
            result.segments[0].text
        )


class TestStructuralProvenance:
    def test_section_path_preserved(self):
        document = make_document(
            make_segment(
                "**Refund terms**",
                section_path=(
                    "Payments",
                    "Refunds",
                ),
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].section_path
            == (
                "Payments",
                "Refunds",
            )
        )

    def test_source_segment_index_preserved(self):
        document = make_document(
            make_segment(
                "First",
                index=0,
            ),
            make_segment(
                "Second",
                index=1,
            ),
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert [
            segment.source_segment_index
            for segment in result.segments
        ] == [
            0,
            1,
        ]

    def test_normalized_indexes_are_contiguous(self):
        document = make_document(
            make_segment(
                "First",
                index=0,
            ),
            make_segment(
                "Second",
                index=1,
            ),
            make_segment(
                "Third",
                index=2,
            ),
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert [
            segment.index
            for segment in result.segments
        ] == [
            0,
            1,
            2,
        ]

    def test_parser_provenance_preserved(self):
        document = make_document(
            make_segment("Refund policy"),
            parser_strategy_id="custom-md-parser",
            parser_version="7.2.1",
            parser_config_fingerprint="parser-hash",
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.source_parser_strategy_id
            == "custom-md-parser"
        )
        assert (
            result.source_parser_version
            == "7.2.1"
        )
        assert (
            result.source_parser_config_fingerprint
            == "parser-hash"
        )

    def test_normalizer_provenance_recorded(self):
        normalizer = MarkdownNormalizer()

        document = make_document(
            make_segment("Refund policy")
        )

        result = normalizer.normalize(
            document
        )

        assert (
            result.normalizer_strategy_id
            == normalizer.descriptor.strategy_id
        )
        assert (
            result.normalizer_version
            == normalizer.descriptor.version
        )
        assert (
            result.normalizer_config_fingerprint
            == normalizer.descriptor.config_fingerprint
        )

    def test_document_metadata_carried_forward(self):
        document = make_document(
            make_segment("Refund policy"),
            metadata={
                "language": "en",
                "tenant_id": "tenant-1",
            },
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.metadata["language"]
            == "en"
        )
        assert (
            result.metadata["tenant_id"]
            == "tenant-1"
        )

    def test_normalized_from_metadata_added(self):
        document = make_document(
            make_segment("Refund policy")
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.metadata["normalized_from"]
            == document.parser_identity
        )

    def test_segment_metadata_carried_forward(self):
        document = make_document(
            make_segment(
                "Refund policy",
                metadata={
                    "markdown_block_type": "paragraph",
                    "custom": "value",
                },
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        metadata = (
            result.segments[0].metadata
        )

        assert (
            metadata["markdown_block_type"]
            == "paragraph"
        )
        assert (
            metadata["custom"]
            == "value"
        )

    def test_source_offsets_preserved_as_provenance_metadata(
        self,
    ):
        text = "Refund policy"

        document = make_document(
            make_segment(
                text,
                start_offset=100,
                end_offset=100 + len(text),
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        metadata = (
            result.segments[0].metadata
        )

        assert (
            metadata["source_start_offset"]
            == 100
        )

        assert (
            metadata["source_end_offset"]
            == 100 + len(text)
        )

    def test_page_number_preserved_as_provenance_metadata(
        self,
    ):
        document = make_document(
            make_segment(
                "Refund policy",
                page_number=4,
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0]
            .metadata["source_page_number"]
            == 4
        )


class TestImmutability:
    def test_source_segment_not_mutated(self):
        segment = make_segment(
            "**Refund policy**",
            metadata={
                "original": True,
            },
        )

        document = make_document(
            segment
        )

        MarkdownNormalizer().normalize(
            document
        )

        assert (
            segment.text
            == "**Refund policy**"
        )
        assert (
            segment.metadata["original"]
            is True
        )

    def test_source_document_not_mutated(self):
        document = make_document(
            make_segment(
                "**Refund policy**"
            ),
            metadata={
                "language": "en",
            },
        )

        original_metadata = dict(
            document.metadata
        )

        MarkdownNormalizer().normalize(
            document
        )

        assert (
            dict(document.metadata)
            == original_metadata
        )

    def test_normalized_segment_metadata_is_frozen(
        self,
    ):
        document = make_document(
            make_segment(
                "Refund policy",
                metadata={
                    "foo": "bar"
                },
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        with pytest.raises(TypeError):
            result.segments[0].metadata[
                "foo"
            ] = "changed"  # type: ignore[index]


class TestMultipleSegments:
    def test_all_segments_normalized_independently(
        self,
    ):
        document = make_document(
            make_segment(
                "**First**",
                index=0,
            ),
            make_segment(
                "*Second*",
                index=1,
            ),
            make_segment(
                "`Third`",
                index=2,
            ),
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert [
            segment.text
            for segment in result.segments
        ] == [
            "First",
            "Second",
            "Third",
        ]

    def test_normalization_does_not_merge_segments(
        self,
    ):
        document = make_document(
            make_segment(
                "First paragraph.",
                index=0,
            ),
            make_segment(
                "Second paragraph.",
                index=1,
            ),
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert len(
            result.segments
        ) == 2


class TestLossResistance:
    def test_thematic_break_does_not_disappear_entirely(
        self,
    ):
        document = make_document(
            make_segment("---")
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "---"
        )

    def test_markdown_with_only_nonsemantic_structure_falls_back(
        self,
    ):
        document = make_document(
            make_segment("***")
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
            == "***"
        )

    def test_malformed_markdown_does_not_crash(
        self,
    ):
        document = make_document(
            make_segment(
                "**unclosed emphasis "
                "[broken link("
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        assert (
            result.segments[0].text
        )


class TestValidation:
    def test_non_parsed_document_rejected(self):
        with pytest.raises(
            TypeError,
            match=(
                "document must be a ParsedDocument"
            ),
        ):
            MarkdownNormalizer().normalize(
                "not-a-document"  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "source_type",
        [
            KnowledgeSourceType.PLAIN_TEXT,
            KnowledgeSourceType.HTML,
            KnowledgeSourceType.PDF,
            KnowledgeSourceType.DOCX,
        ],
    )
    def test_non_markdown_document_rejected(
        self,
        source_type,
    ):
        document = make_document(
            make_segment(
                "Refund policy"
            ),
            source_type=source_type,
        )

        with pytest.raises(
            InvalidNormalizedDocumentError
        ) as exc_info:
            MarkdownNormalizer().normalize(
                document
            )

        assert (
            exc_info.value.context[
                "source_type"
            ]
            == source_type.value
        )


class TestExceptionTranslation:
    def test_markdown_parser_failure_is_translated(
        self,
        monkeypatch,
    ):
        normalizer = MarkdownNormalizer()

        document = make_document(
            make_segment(
                "Refund policy"
            )
        )

        def explode(*args, **kwargs):
            raise RuntimeError(
                "markdown engine failed"
            )

        monkeypatch.setattr(
            normalizer._markdown,
            "parse",
            explode,
        )

        with pytest.raises(
            KnowledgeNormalizationExecutionError
        ) as exc_info:
            normalizer.normalize(
                document
            )

        assert (
            "segment 0"
            in str(exc_info.value)
        )

        assert isinstance(
            exc_info.value.__cause__,
            RuntimeError,
        )

    def test_failure_identifies_correct_segment(
        self,
        monkeypatch,
    ):
        normalizer = MarkdownNormalizer()

        document = make_document(
            make_segment(
                "First",
                index=0,
            ),
            make_segment(
                "Second",
                index=1,
            ),
        )

        original_parse = (
            normalizer._markdown.parse
        )

        call_count = 0

        def parse_with_failure(text):
            nonlocal call_count

            call_count += 1

            if call_count == 2:
                raise RuntimeError(
                    "second segment failed"
                )

            return original_parse(text)

        monkeypatch.setattr(
            normalizer._markdown,
            "parse",
            parse_with_failure,
        )

        with pytest.raises(
            KnowledgeNormalizationExecutionError
        ) as exc_info:
            normalizer.normalize(
                document
            )

        assert (
            exc_info.value.context[
                "source_segment_index"
            ]
            == 1
        )


class TestComplexRealWorldMarkdown:
    def test_realistic_policy_document_segment(
        self,
    ):
        text = """
## Refund Eligibility

Customers are eligible for a **full refund** when:

1. The request is submitted within **30 days**.
2. The transaction has not already been reversed.
3. The order is not marked as `final_sale`.

For additional details, see the
[refund policy](https://example.com/refunds).

> Enterprise customers may have negotiated terms.

| Payment Method | Typical Delay |
| --- | --- |
| Card | 5-7 business days |
| UPI | 2-3 business days |

```python
if order.final_sale:
    reject_refund()
""".strip()

        document = make_document(
            make_segment(
                text,
                section_path=(
                    "Payments",
                    "Refund Eligibility",
                ),
            )
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        normalized = (
            result.segments[0].text
        )

        assert "Refund Eligibility" in normalized
        assert "full refund" in normalized
        assert "30 days" in normalized
        assert "final_sale" in normalized
        assert "refund policy" in normalized
        assert (
            "Enterprise customers may have "
            "negotiated terms."
            in normalized
        )
        assert "Payment Method" in normalized
        assert "Card" in normalized
        assert "UPI" in normalized
        assert "reject_refund()" in normalized

        assert "**full refund**" not in normalized
        assert (
            "[refund policy]"
            not in normalized
        )

    def test_mixed_unicode_markdown(
        self,):
        text = """
        Refunds 🌍

    भारत: रिफंड 30 दिनों के भीतर उपलब्ध है।

    বাংলা: রিফান্ড ৩০ দিনের মধ্যে পাওয়া যাবে।

    日本: 返金は30日以内です。

    Contact: Support
    """.strip()

        document = make_document(
            make_segment(text)
        )

        result = MarkdownNormalizer().normalize(
            document
        )

        normalized = (
            result.segments[0].text
        )

        assert "Refunds 🌍" in normalized
        assert "भारत" in normalized
        assert "বাংলা" in normalized
        assert "日本" in normalized
        assert "Support" in normalized
    