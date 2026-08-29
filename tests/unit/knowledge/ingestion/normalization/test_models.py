from __future__ import annotations

from uuid6 import uuid7

import pytest

from packages.knowledge.domain.enums import (
    KnowledgeSourceType,
)
from packages.knowledge.ingestion.normalization.models import (
    NormalizedDocument,
    NormalizedSegment,
)


class TestNormalizedSegment:
    def test_valid_segment(self):
        segment = NormalizedSegment(
            index=0,
            source_segment_index=2,
            text="Refunds are available within 30 days.",
            section_path=(
                "Payments",
                "Refunds",
            ),
            metadata={
                "source": "markdown",
            },
        )

        assert segment.index == 0
        assert segment.source_segment_index == 2
        assert (
            segment.text
            == "Refunds are available within 30 days."
        )
        assert segment.section_path == (
            "Payments",
            "Refunds",
        )
        assert segment.section_title == "Refunds"

    def test_section_title_is_none_without_section_path(
        self,
    ):
        segment = NormalizedSegment(
            index=0,
            source_segment_index=0,
            text="Knowledge content.",
        )

        assert segment.section_title is None

    def test_negative_index_rejected(self):
        with pytest.raises(
            ValueError,
            match="index must be non-negative",
        ):
            NormalizedSegment(
                index=-1,
                source_segment_index=0,
                text="Knowledge content.",
            )

    def test_non_integer_index_rejected(self):
        with pytest.raises(
            TypeError,
            match="index must be an integer",
        ):
            NormalizedSegment(
                index="0",  # type: ignore[arg-type]
                source_segment_index=0,
                text="Knowledge content.",
            )

    def test_negative_source_segment_index_rejected(
        self,
    ):
        with pytest.raises(
            ValueError,
            match=(
                "source_segment_index must "
                "be non-negative"
            ),
        ):
            NormalizedSegment(
                index=0,
                source_segment_index=-1,
                text="Knowledge content.",
            )

    def test_non_integer_source_segment_index_rejected(
        self,
    ):
        with pytest.raises(
            TypeError,
            match=(
                "source_segment_index must "
                "be an integer"
            ),
        ):
            NormalizedSegment(
                index=0,
                source_segment_index="0",  # type: ignore[arg-type]
                text="Knowledge content.",
            )

    @pytest.mark.parametrize(
        "text",
        [
            "",
            " ",
            "\t",
            "\n",
        ],
    )
    def test_blank_text_rejected(
        self,
        text,
    ):
        with pytest.raises(
            ValueError,
            match=(
                "Normalized segment text "
                "must not be blank"
            ),
        ):
            NormalizedSegment(
                index=0,
                source_segment_index=0,
                text=text,
            )

    def test_non_string_text_rejected(self):
        with pytest.raises(
            TypeError,
            match="text must be a string",
        ):
            NormalizedSegment(
                index=0,
                source_segment_index=0,
                text=123,  # type: ignore[arg-type]
            )

    def test_section_path_must_be_tuple(self):
        with pytest.raises(
            TypeError,
            match=(
                "section_path must be "
                "a tuple of strings"
            ),
        ):
            NormalizedSegment(
                index=0,
                source_segment_index=0,
                text="Knowledge content.",
                section_path=[
                    "Refunds",
                ],  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "section_path",
        [
            ("",),
            (" ",),
            ("Refunds", ""),
            ("Refunds", "   "),
        ],
    )
    def test_blank_section_path_entry_rejected(
        self,
        section_path,
    ):
        with pytest.raises(
            ValueError,
            match=(
                "section_path entries must "
                "be non-empty strings"
            ),
        ):
            NormalizedSegment(
                index=0,
                source_segment_index=0,
                text="Knowledge content.",
                section_path=section_path,
            )

    def test_non_string_section_path_entry_rejected(
        self,
    ):
        with pytest.raises(
            ValueError,
            match=(
                "section_path entries must "
                "be non-empty strings"
            ),
        ):
            NormalizedSegment(
                index=0,
                source_segment_index=0,
                text="Knowledge content.",
                section_path=(
                    "Refunds",
                    123,  # type: ignore[arg-type]
                ),
            )

    def test_metadata_must_be_mapping(self):
        with pytest.raises(
            TypeError,
            match="metadata must be a mapping",
        ):
            NormalizedSegment(
                index=0,
                source_segment_index=0,
                text="Knowledge content.",
                metadata=[
                    ("source", "markdown"),
                ],  # type: ignore[arg-type]
            )

    def test_metadata_is_defensively_copied_and_frozen(
        self,
    ):
        metadata = {
            "source": "markdown",
        }

        segment = NormalizedSegment(
            index=0,
            source_segment_index=0,
            text="Knowledge content.",
            metadata=metadata,
        )

        metadata["source"] = "changed"

        assert (
            segment.metadata["source"]
            == "markdown"
        )

        with pytest.raises(TypeError):
            segment.metadata["new"] = "value"  # type: ignore[index]


class TestNormalizedDocument:
    @staticmethod
    def _segment(
        *,
        index: int = 0,
        source_segment_index: int = 0,
    ) -> NormalizedSegment:
        return NormalizedSegment(
            index=index,
            source_segment_index=(
                source_segment_index
            ),
            text=f"Segment {index}.",
        )

    @classmethod
    def _document(
        cls,
        **overrides,
    ) -> NormalizedDocument:
        values = {
            "version_id": uuid7(),
            "source_type": (
                KnowledgeSourceType.MARKDOWN
            ),
            "segments": (
                cls._segment(),
            ),
            "source_parser_strategy_id": (
                "markdown-structural"
            ),
            "source_parser_version": "1.0.0",
            "source_parser_config_fingerprint": (
                None
            ),
            "normalizer_strategy_id": (
                "markdown-semantic"
            ),
            "normalizer_version": "1.0.0",
            "normalizer_config_fingerprint": (
                None
            ),
            "metadata": {
                "language": "en",
            },
        }

        values.update(overrides)

        return NormalizedDocument(
            **values
        )

    def test_valid_document(self):
        document = self._document()

        assert isinstance(
            document.version_id,
            type(uuid7()),
        )
        assert (
            document.source_type
            is KnowledgeSourceType.MARKDOWN
        )
        assert document.segment_count == 1
        assert (
            document.normalizer_identity
            == "markdown-semantic@1.0.0"
        )

    def test_text_joins_segments(self):
        document = self._document(
            segments=(
                NormalizedSegment(
                    index=0,
                    source_segment_index=0,
                    text="First.",
                ),
                NormalizedSegment(
                    index=1,
                    source_segment_index=1,
                    text="Second.",
                ),
            )
        )

        assert (
            document.text
            == "First.\n\nSecond."
        )

    def test_version_id_must_be_uuid(self):
        with pytest.raises(
            TypeError,
            match="version_id must be a UUID",
        ):
            self._document(
                version_id="not-a-uuid"
            )

    def test_source_type_must_be_enum(self):
        with pytest.raises(
            TypeError,
            match=(
                "source_type must be "
                "a KnowledgeSourceType"
            ),
        ):
            self._document(
                source_type="markdown"
            )

    def test_segments_must_be_tuple(self):
        with pytest.raises(
            TypeError,
            match="segments must be a tuple",
        ):
            self._document(
                segments=[
                    self._segment(),
                ]
            )

    def test_document_requires_at_least_one_segment(
        self,
    ):
        with pytest.raises(
            ValueError,
            match=(
                "Normalized document must contain "
                "at least one segment"
            ),
        ):
            self._document(
                segments=()
            )

    def test_every_segment_must_be_normalized_segment(
        self,
    ):
        with pytest.raises(
            TypeError,
            match=(
                "Every segment must be "
                "a NormalizedSegment"
            ),
        ):
            self._document(
                segments=(
                    "bad-segment",
                )
            )

    def test_segment_indexes_must_be_contiguous(
        self,
    ):
        with pytest.raises(
            ValueError,
            match=(
                "Normalized segment indexes "
                "must be contiguous"
            ),
        ):
            self._document(
                segments=(
                    self._segment(
                        index=0,
                        source_segment_index=0,
                    ),
                    self._segment(
                        index=2,
                        source_segment_index=1,
                    ),
                )
            )

    def test_duplicate_source_segment_reference_rejected(
        self,
    ):
        with pytest.raises(
            ValueError,
            match=(
                "must not reference the same "
                "source segment more than once"
            ),
        ):
            self._document(
                segments=(
                    self._segment(
                        index=0,
                        source_segment_index=3,
                    ),
                    self._segment(
                        index=1,
                        source_segment_index=3,
                    ),
                )
            )

    @pytest.mark.parametrize(
        "field_name",
        [
            "source_parser_strategy_id",
            "normalizer_strategy_id",
        ],
    )
    def test_blank_strategy_id_rejected(
        self,
        field_name,
    ):
        with pytest.raises(
            ValueError,
            match="strategy_id must not be blank",
        ):
            self._document(
                **{
                    field_name: "   ",
                }
            )

    @pytest.mark.parametrize(
        "field_name",
        [
            "source_parser_version",
            "normalizer_version",
        ],
    )
    def test_blank_version_rejected(
        self,
        field_name,
    ):
        with pytest.raises(
            ValueError,
            match="version must not be blank",
        ):
            self._document(
                **{
                    field_name: "   ",
                }
            )

    @pytest.mark.parametrize(
        "field_name",
        [
            "source_parser_config_fingerprint",
            "normalizer_config_fingerprint",
        ],
    )
    def test_blank_config_fingerprint_rejected(
        self,
        field_name,
    ):
        with pytest.raises(
            ValueError,
            match=(
                "config_fingerprint must "
                "not be blank"
            ),
        ):
            self._document(
                **{
                    field_name: "   ",
                }
            )

    def test_metadata_is_defensively_copied_and_frozen(
        self,
    ):
        metadata = {
            "language": "en",
        }

        document = self._document(
            metadata=metadata
        )

        metadata["language"] = "fr"

        assert (
            document.metadata["language"]
            == "en"
        )

        with pytest.raises(TypeError):
            document.metadata["new"] = "value"  # type: ignore[index]