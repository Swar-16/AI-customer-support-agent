from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.chunking.base import (
    ChunkerDescriptor,
)
from packages.knowledge.ingestion.chunking.errors import (
    InvalidChunkingInputError,
    KnowledgeChunkerOutputError,
    KnowledgeChunkingExecutionError,
)
from packages.knowledge.ingestion.chunking.models import (
    ChunkCandidate,
    ChunkedDocument,
    ChunkSourceSpan,
)
from packages.knowledge.ingestion.chunking.semantic_text import (
    StructuralTextChunker,
    StructuralTextChunkerConfig,
)
from packages.knowledge.ingestion.normalization.models import (
    NormalizedDocument,
    NormalizedSegment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_segment(
    text: str,
    *,
    index: int = 0,
    source_segment_index: int | None = None,
    section_path: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> NormalizedSegment:
    if source_segment_index is None:
        source_segment_index = index

    return NormalizedSegment(
        index=index,
        source_segment_index=source_segment_index,
        text=text,
        section_path=section_path,
        metadata=metadata or {},
    )


def make_document(
    *segments: NormalizedSegment,
    version_id: UUID | None = None,
    source_type: KnowledgeSourceType = KnowledgeSourceType.MARKDOWN,
    metadata: dict | None = None,
) -> NormalizedDocument:
    if not segments:
        segments = (
            make_segment(
                "Default normalized content.",
                index=0,
            ),
        )

    return NormalizedDocument(
        version_id=version_id or uuid4(),
        source_type=source_type,
        segments=tuple(segments),
        source_parser_strategy_id="test-parser",
        source_parser_version="2.1.0",
        source_parser_config_fingerprint="sha256:parser",
        normalizer_strategy_id="test-normalizer",
        normalizer_version="3.4.0",
        normalizer_config_fingerprint="sha256:normalizer",
        metadata=metadata or {},
    )


def make_config(
    *,
    target_chars: int = 100,
    max_chars: int = 140,
    overlap_chars: int = 20,
    min_chunk_chars: int = 20,
    preserve_section_boundaries: bool = True,
    separator: str = "\n\n",
) -> StructuralTextChunkerConfig:
    return StructuralTextChunkerConfig(
        target_chars=target_chars,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        min_chunk_chars=min_chunk_chars,
        preserve_section_boundaries=preserve_section_boundaries,
        separator=separator,
    )


def make_chunker(
    **config_overrides,
) -> StructuralTextChunker:
    return StructuralTextChunker(
        make_config(**config_overrides)
    )


def reconstruct_span_text(
    document: NormalizedDocument,
    chunk: ChunkCandidate,
) -> tuple[str, ...]:
    """
    Resolve every ChunkSourceSpan against the normalized source.

    This deliberately ignores synthetic separators inserted by the
    chunker and verifies only source-backed provenance.
    """
    segments = {
        segment.index: segment
        for segment in document.segments
    }

    return tuple(
        segments[span.source_segment_index].text[
            span.start_offset:span.end_offset
        ]
        for span in chunk.source_spans
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestStructuralTextChunkerConfig:
    def test_defaults_are_valid(self) -> None:
        config = StructuralTextChunkerConfig()

        assert config.target_chars == 1200
        assert config.max_chars == 1800
        assert config.overlap_chars == 200
        assert config.min_chunk_chars == 200
        assert config.preserve_section_boundaries is True
        assert config.separator == "\n\n"

    @pytest.mark.parametrize(
        "field_name",
        [
            "target_chars",
            "max_chars",
        ],
    )
    @pytest.mark.parametrize(
        "value",
        [
            None,
            "100",
            1.5,
            True,
            False,
        ],
    )
    def test_positive_integer_fields_reject_non_integers_and_bool(
        self,
        field_name: str,
        value,
    ) -> None:
        kwargs = {
            "target_chars": 100,
            "max_chars": 150,
        }
        kwargs[field_name] = value

        with pytest.raises(TypeError):
            StructuralTextChunkerConfig(**kwargs)

    @pytest.mark.parametrize(
        "field_name",
        [
            "target_chars",
            "max_chars",
        ],
    )
    @pytest.mark.parametrize(
        "value",
        [0, -1, -100],
    )
    def test_positive_integer_fields_must_be_positive(
        self,
        field_name: str,
        value: int,
    ) -> None:
        kwargs = {
            "target_chars": 100,
            "max_chars": 150,
        }
        kwargs[field_name] = value

        with pytest.raises(ValueError):
            StructuralTextChunkerConfig(**kwargs)

    @pytest.mark.parametrize(
        "field_name",
        [
            "overlap_chars",
            "min_chunk_chars",
        ],
    )
    @pytest.mark.parametrize(
        "value",
        [
            None,
            "10",
            1.5,
            True,
            False,
        ],
    )
    def test_non_negative_integer_fields_reject_non_integers_and_bool(
        self,
        field_name: str,
        value,
    ) -> None:
        kwargs = {
            "target_chars": 100,
            "max_chars": 150,
            "overlap_chars": 10,
            "min_chunk_chars": 10,
        }
        kwargs[field_name] = value

        with pytest.raises(TypeError):
            StructuralTextChunkerConfig(**kwargs)

    @pytest.mark.parametrize(
        "field_name",
        [
            "overlap_chars",
            "min_chunk_chars",
        ],
    )
    @pytest.mark.parametrize(
        "value",
        [-1, -100],
    )
    def test_non_negative_integer_fields_reject_negative_values(
        self,
        field_name: str,
        value: int,
    ) -> None:
        kwargs = {
            "target_chars": 100,
            "max_chars": 150,
            "overlap_chars": 10,
            "min_chunk_chars": 10,
        }
        kwargs[field_name] = value

        with pytest.raises(ValueError):
            StructuralTextChunkerConfig(**kwargs)

    def test_zero_overlap_is_valid(self) -> None:
        config = make_config(
            overlap_chars=0
        )

        assert config.overlap_chars == 0

    def test_zero_minimum_chunk_size_is_valid(self) -> None:
        config = make_config(
            min_chunk_chars=0
        )

        assert config.min_chunk_chars == 0

    def test_target_must_not_exceed_max(self) -> None:
        with pytest.raises(
            ValueError,
            match="target_chars must not exceed max_chars",
        ):
            StructuralTextChunkerConfig(
                target_chars=101,
                max_chars=100,
            )

    def test_minimum_must_not_exceed_target(self) -> None:
        with pytest.raises(
            ValueError,
            match="min_chunk_chars must not exceed target_chars",
        ):
            StructuralTextChunkerConfig(
                target_chars=100,
                max_chars=150,
                min_chunk_chars=101,
            )

    def test_overlap_must_be_smaller_than_max(self) -> None:
        with pytest.raises(
            ValueError,
            match="overlap_chars must be smaller than max_chars",
        ):
            StructuralTextChunkerConfig(
                target_chars=100,
                max_chars=150,
                overlap_chars=150,
                min_chunk_chars=20,
            )

    def test_overlap_one_below_max_is_allowed(self) -> None:
        config = StructuralTextChunkerConfig(
            target_chars=100,
            max_chars=150,
            overlap_chars=149,
            min_chunk_chars=10,
        )

        assert config.overlap_chars == 149

    @pytest.mark.parametrize(
        "value",
        [None, 1, [], object()],
    )
    def test_separator_must_be_string(
        self,
        value,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="separator must be a string",
        ):
            StructuralTextChunkerConfig(
                target_chars=100,
                max_chars=150,
                separator=value,
            )

    def test_empty_separator_is_allowed(self) -> None:
        config = make_config(
            separator=""
        )

        assert config.separator == ""

    def test_separator_must_be_shorter_than_max_chars(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="separator must be shorter than max_chars",
        ):
            StructuralTextChunkerConfig(
                target_chars=5,
                max_chars=10,
                overlap_chars=0,
                min_chunk_chars=0,
                separator="x" * 10,
            )

    @pytest.mark.parametrize(
        "value",
        [None, 1, "true"],
    )
    def test_preserve_section_boundaries_must_be_boolean(
        self,
        value,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="preserve_section_boundaries must be a boolean",
        ):
            StructuralTextChunkerConfig(
                preserve_section_boundaries=value,
            )

    def test_config_is_immutable(self) -> None:
        config = make_config()

        with pytest.raises(FrozenInstanceError):
            config.max_chars = 500  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Fingerprint / descriptor
# ---------------------------------------------------------------------------


class TestStructuralTextChunkerDescriptor:
    def test_descriptor_has_expected_identity(self) -> None:
        chunker = make_chunker()

        assert isinstance(
            chunker.descriptor,
            ChunkerDescriptor,
        )
        assert (
            chunker.descriptor.strategy_id
            == "structural-text"
        )
        assert (
            chunker.descriptor.version
            == "1.0.0"
        )
        assert (
            chunker.descriptor.identity
            == "structural-text@1.0.0"
        )

    def test_descriptor_has_config_fingerprint(
        self,
    ) -> None:
        chunker = make_chunker()

        fingerprint = (
            chunker.descriptor.config_fingerprint
        )

        assert fingerprint is not None
        assert fingerprint.startswith(
            "sha256:"
        )
        assert len(
            fingerprint.removeprefix("sha256:")
        ) == 64

    def test_same_config_produces_same_fingerprint(
        self,
    ) -> None:
        first = make_config()
        second = make_config()

        assert (
            first.fingerprint
            == second.fingerprint
        )

    @pytest.mark.parametrize(
        ("field_name", "new_value"),
        [
            ("target_chars", 101),
            ("max_chars", 141),
            ("overlap_chars", 21),
            ("min_chunk_chars", 21),
            (
                "preserve_section_boundaries",
                False,
            ),
            ("separator", "\n"),
        ],
    )
    def test_output_affecting_config_changes_fingerprint(
        self,
        field_name: str,
        new_value,
    ) -> None:
        base = make_config()

        kwargs = {
            "target_chars": base.target_chars,
            "max_chars": base.max_chars,
            "overlap_chars": base.overlap_chars,
            "min_chunk_chars": base.min_chunk_chars,
            "preserve_section_boundaries": (
                base.preserve_section_boundaries
            ),
            "separator": base.separator,
        }
        kwargs[field_name] = new_value

        changed = StructuralTextChunkerConfig(
            **kwargs
        )

        assert (
            changed.fingerprint
            != base.fingerprint
        )

    def test_chunker_rejects_invalid_config_type(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="config must be a StructuralTextChunkerConfig",
        ):
            StructuralTextChunker(
                config="bad"  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Supported formats
# ---------------------------------------------------------------------------


class TestSupportedSourceTypes:
    @pytest.mark.parametrize(
        "source_type",
        [
            KnowledgeSourceType.MARKDOWN,
            KnowledgeSourceType.PLAIN_TEXT,
            KnowledgeSourceType.PDF,
            KnowledgeSourceType.DOCX,
            KnowledgeSourceType.HTML,
            KnowledgeSourceType.RICH_TEXT,
        ],
    )
    def test_supports_all_normalized_textual_source_types(
        self,
        source_type: KnowledgeSourceType,
    ) -> None:
        chunker = make_chunker()

        assert chunker.supports(
            source_type
        )

    def test_supported_source_types_is_frozenset(
        self,
    ) -> None:
        chunker = make_chunker()

        assert isinstance(
            chunker.supported_source_types,
            frozenset,
        )


# ---------------------------------------------------------------------------
# Basic chunking
# ---------------------------------------------------------------------------


class TestBasicChunking:
    def test_single_short_segment_produces_one_chunk(
        self,
    ) -> None:
        document = make_document(
            make_segment(
                "Refunds are processed within five days."
            )
        )

        result = make_chunker().chunk(
            document
        )

        assert result.chunk_count == 1
        assert result.chunks[0].text == (
            "Refunds are processed within five days."
        )

    def test_exact_max_size_segment_remains_one_chunk(
        self,
    ) -> None:
        text = "x" * 140

        document = make_document(
            make_segment(text)
        )

        result = make_chunker().chunk(
            document
        )

        assert result.chunk_count == 1
        assert result.chunks[0].text == text
        assert len(result.chunks[0].text) == 140

    def test_segment_one_character_above_max_is_split(
        self,
    ) -> None:
        text = "x" * 141

        document = make_document(
            make_segment(text)
        )

        result = make_chunker().chunk(
            document
        )

        assert result.chunk_count >= 2

        assert all(
            len(chunk.text) <= 140
            for chunk in result.chunks
        )

    def test_many_small_segments_can_be_combined(
        self,
    ) -> None:
        document = make_document(
            make_segment(
                "First paragraph.",
                index=0,
            ),
            make_segment(
                "Second paragraph.",
                index=1,
            ),
            make_segment(
                "Third paragraph.",
                index=2,
            ),
        )

        result = make_chunker(
            target_chars=100,
            max_chars=140,
            overlap_chars=0,
        ).chunk(document)

        assert result.chunk_count == 1

        assert result.chunks[0].text == (
            "First paragraph.\n\n"
            "Second paragraph.\n\n"
            "Third paragraph."
        )

        assert (
            result.chunks[0].source_segment_indexes
            == (0, 1, 2)
        )

    def test_custom_separator_is_used(
        self,
    ) -> None:
        document = make_document(
            make_segment("one", index=0),
            make_segment("two", index=1),
        )

        result = make_chunker(
            separator=" | ",
            overlap_chars=0,
        ).chunk(document)

        assert result.chunks[0].text == (
            "one | two"
        )

    def test_empty_separator_is_supported(
        self,
    ) -> None:
        document = make_document(
            make_segment("one", index=0),
            make_segment("two", index=1),
        )

        result = make_chunker(
            separator="",
            overlap_chars=0,
        ).chunk(document)

        assert result.chunks[0].text == "onetwo"


# ---------------------------------------------------------------------------
# Hard maximum guarantee
# ---------------------------------------------------------------------------


class TestHardMaximum:
    @pytest.mark.parametrize(
        "length",
        [
            141,
            200,
            500,
            1_000,
            5_000,
        ],
    )
    def test_no_chunk_exceeds_hard_max_for_long_unbroken_text(
        self,
        length: int,
    ) -> None:
        document = make_document(
            make_segment("A" * length)
        )

        result = make_chunker(
            target_chars=100,
            max_chars=140,
            overlap_chars=20,
        ).chunk(document)

        assert all(
            0 < len(chunk.text) <= 140
            for chunk in result.chunks
        )

    def test_separator_size_is_included_in_hard_limit(
        self,
    ) -> None:
        document = make_document(
            make_segment(
                "A" * 60,
                index=0,
            ),
            make_segment(
                "B" * 60,
                index=1,
            ),
        )

        result = make_chunker(
            target_chars=100,
            max_chars=125,
            overlap_chars=0,
            separator="-----",
        ).chunk(document)

        assert all(
            len(chunk.text) <= 125
            for chunk in result.chunks
        )


# ---------------------------------------------------------------------------
# Natural splitting boundaries
# ---------------------------------------------------------------------------


class TestNaturalBoundaries:
    def test_prefers_newline_boundary(
        self,
    ) -> None:
        text = (
            ("A" * 70)
            + "\n"
            + ("B" * 70)
            + "\n"
            + ("C" * 70)
        )

        result = make_chunker(
            target_chars=100,
            max_chars=150,
            overlap_chars=0,
        ).chunk(
            make_document(
                make_segment(text)
            )
        )

        assert result.chunk_count >= 2

        assert all(
            len(chunk.text) <= 150
            for chunk in result.chunks
        )

        # Splitting should not leave the newline itself as visible
        # leading/trailing whitespace.
        assert all(
            chunk.text == chunk.text.strip()
            for chunk in result.chunks
        )

    def test_prefers_english_sentence_boundary(
        self,
    ) -> None:
        first = (
            "This is the first policy sentence. "
        )
        second = (
            "This is another important policy sentence. "
        )

        text = (
            first * 3
            + second * 3
        )

        result = make_chunker(
            target_chars=100,
            max_chars=150,
            overlap_chars=0,
        ).chunk(
            make_document(
                make_segment(text)
            )
        )

        assert all(
            len(chunk.text) <= 150
            for chunk in result.chunks
        )

        # At least an intermediate chunk should naturally end at
        # sentence punctuation rather than in the middle of a word.
        assert any(
            chunk.text.endswith(".")
            for chunk in result.chunks[:-1]
        )

    @pytest.mark.parametrize(
        "punctuation",
        [
            "。",
            "！",
            "？",
            "।",
        ],
    )
    def test_unicode_sentence_boundaries_are_supported(
        self,
        punctuation: str,
    ) -> None:
        sentence = (
            ("ক" * 30)
            + punctuation
            + " "
        )

        text = sentence * 8

        result = make_chunker(
            target_chars=90,
            max_chars=130,
            overlap_chars=0,
        ).chunk(
            make_document(
                make_segment(text)
            )
        )

        assert result.chunk_count > 1

        assert all(
            len(chunk.text) <= 130
            for chunk in result.chunks
        )

    def test_falls_back_to_whitespace_boundary(
        self,
    ) -> None:
        text = (
            "word " * 100
        ).strip()

        result = make_chunker(
            target_chars=80,
            max_chars=100,
            overlap_chars=0,
        ).chunk(
            make_document(
                make_segment(text)
            )
        )

        assert all(
            len(chunk.text) <= 100
            for chunk in result.chunks
        )

        assert all(
            not chunk.text.startswith(" ")
            and not chunk.text.endswith(" ")
            for chunk in result.chunks
        )

    def test_hard_split_guarantees_progress_without_boundaries(
        self,
    ) -> None:
        text = "Z" * 1_000

        result = make_chunker(
            target_chars=100,
            max_chars=120,
            overlap_chars=0,
        ).chunk(
            make_document(
                make_segment(text)
            )
        )

        assert result.chunk_count > 1

        assert all(
            len(chunk.text) <= 120
            for chunk in result.chunks
        )


# ---------------------------------------------------------------------------
# Section boundaries
# ---------------------------------------------------------------------------


class TestSectionBoundaries:
    def test_different_sections_are_not_merged_by_default(
        self,
    ) -> None:
        document = make_document(
            make_segment(
                "Refund information.",
                index=0,
                section_path=("Policies", "Refunds"),
            ),
            make_segment(
                "Shipping information.",
                index=1,
                section_path=("Policies", "Shipping"),
            ),
        )

        result = make_chunker(
            overlap_chars=20,
        ).chunk(document)

        assert result.chunk_count == 2

        assert result.chunks[0].text == (
            "Refund information."
        )
        assert result.chunks[1].text == (
            "Shipping information."
        )

        assert result.chunks[0].section_path == (
            "Policies",
            "Refunds",
        )
        assert result.chunks[1].section_path == (
            "Policies",
            "Shipping",
        )

    def test_overlap_does_not_cross_section_boundary(
        self,
    ) -> None:
        first_text = (
            "Refund policy information that should remain "
            "inside the refund section."
        )

        second_text = (
            "Shipping policy information that belongs only "
            "to shipping."
        )

        document = make_document(
            make_segment(
                first_text,
                index=0,
                section_path=("Refunds",),
            ),
            make_segment(
                second_text,
                index=1,
                section_path=("Shipping",),
            ),
        )

        result = make_chunker(
            target_chars=100,
            max_chars=140,
            overlap_chars=40,
            preserve_section_boundaries=True,
        ).chunk(document)

        shipping_chunks = [
            chunk
            for chunk in result.chunks
            if chunk.section_path == ("Shipping",)
        ]

        assert shipping_chunks

        assert all(
            "Refund policy"
            not in chunk.text
            for chunk in shipping_chunks
        )

    def test_same_section_segments_can_be_combined(
        self,
    ) -> None:
        document = make_document(
            make_segment(
                "First refund paragraph.",
                index=0,
                section_path=("Refunds",),
            ),
            make_segment(
                "Second refund paragraph.",
                index=1,
                section_path=("Refunds",),
            ),
        )

        result = make_chunker(
            overlap_chars=0,
        ).chunk(document)

        assert result.chunk_count == 1
        assert result.chunks[0].section_path == (
            "Refunds",
        )

    def test_sections_can_be_merged_when_preservation_disabled(
        self,
    ) -> None:
        document = make_document(
            make_segment(
                "Refund information.",
                index=0,
                section_path=("Policies", "Refunds"),
            ),
            make_segment(
                "Shipping information.",
                index=1,
                section_path=("Policies", "Shipping"),
            ),
        )

        result = make_chunker(
            overlap_chars=0,
            preserve_section_boundaries=False,
        ).chunk(document)

        assert result.chunk_count == 1

        assert result.chunks[0].section_path == (
            "Policies",
        )


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------


class TestOverlap:
    def test_zero_overlap_does_not_repeat_source_ranges(
        self,
    ) -> None:
        text = "X" * 400

        document = make_document(
            make_segment(text)
        )

        result = make_chunker(
            target_chars=100,
            max_chars=120,
            overlap_chars=0,
        ).chunk(document)

        previous_end = 0

        for chunk in result.chunks:
            assert len(chunk.source_spans) == 1

            span = chunk.source_spans[0]

            assert span.start_offset >= previous_end

            previous_end = span.end_offset

    def test_overlap_creates_repeated_source_range_across_chunks(
        self,
    ) -> None:
        # Separate source pieces are required here because oversized
        # segment splitting itself is non-overlapping. Chunk overlap
        # is introduced during assembly.
        document = make_document(
            make_segment(
                "A" * 80,
                index=0,
            ),
            make_segment(
                "B" * 80,
                index=1,
            ),
            make_segment(
                "C" * 80,
                index=2,
            ),
        )

        result = make_chunker(
            target_chars=100,
            max_chars=140,
            overlap_chars=20,
            preserve_section_boundaries=False,
        ).chunk(document)

        assert result.chunk_count >= 2

        first = result.chunks[0]
        second = result.chunks[1]

        first_ranges = {
            (
                span.source_segment_index,
                span.start_offset,
                span.end_offset,
            )
            for span in first.source_spans
        }

        # The second chunk may carry either a complete source piece or
        # a sliced suffix. Verify source-range intersection rather than
        # requiring identical spans.
        has_overlap = False

        for left in first.source_spans:
            for right in second.source_spans:
                if (
                    left.source_segment_index
                    != right.source_segment_index
                ):
                    continue

                overlap_start = max(
                    left.start_offset,
                    right.start_offset,
                )
                overlap_end = min(
                    left.end_offset,
                    right.end_offset,
                )

                if overlap_start < overlap_end:
                    has_overlap = True

        assert first_ranges
        assert has_overlap

    def test_overlap_slice_has_correct_source_offsets(
        self,
    ) -> None:
        document = make_document(
            make_segment(
                "A" * 80,
                index=0,
            ),
            make_segment(
                "B" * 80,
                index=1,
            ),
        )

        result = make_chunker(
            target_chars=70,
            max_chars=100,
            overlap_chars=20,
            preserve_section_boundaries=False,
            separator="",
        ).chunk(document)

        assert result.chunk_count >= 2

        second = result.chunks[1]

        # The previous 80-character piece contributes only its final
        # 20 characters as overlap.
        overlap_span = second.source_spans[0]

        assert overlap_span.source_segment_index == 0
        assert overlap_span.start_offset == 60
        assert overlap_span.end_offset == 80
        assert second.source_spans[1].source_segment_index == 1
        
    def test_overlap_is_dropped_when_it_would_violate_hard_max(
        self,
    ) -> None:
        document = make_document(
            make_segment(
                "A" * 80,
                index=0,
            ),
            make_segment(
                "B" * 80,
                index=1,
            ),
        )

        result = make_chunker(
            target_chars=70,
            max_chars=100,
            overlap_chars=20,
            preserve_section_boundaries=False,
        ).chunk(document)

        assert result.chunk_count >= 2

        second = result.chunks[1]

        assert all(
            span.source_segment_index != 0
            for span in second.source_spans
        )

        assert len(second.text) <= 100

    def test_overlap_never_causes_hard_limit_violation(
        self,
    ) -> None:
        document = make_document(
            *[
                make_segment(
                    chr(65 + index) * 70,
                    index=index,
                )
                for index in range(5)
            ]
        )

        result = make_chunker(
            target_chars=80,
            max_chars=100,
            overlap_chars=40,
            preserve_section_boundaries=False,
        ).chunk(document)

        assert all(
            len(chunk.text) <= 100
            for chunk in result.chunks
        )


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_full_transformation_provenance_is_preserved(
        self,
    ) -> None:
        version_id = uuid4()

        document = make_document(
            make_segment(
                "Policy text.",
                index=0,
            ),
            version_id=version_id,
        )

        result = make_chunker().chunk(
            document
        )

        assert result.version_id == version_id
        assert (
            result.source_type
            == KnowledgeSourceType.MARKDOWN
        )

        assert (
            result.source_parser_strategy_id
            == "test-parser"
        )
        assert (
            result.source_parser_version
            == "2.1.0"
        )
        assert (
            result.source_parser_config_fingerprint
            == "sha256:parser"
        )

        assert (
            result.source_normalizer_strategy_id
            == "test-normalizer"
        )
        assert (
            result.source_normalizer_version
            == "3.4.0"
        )
        assert (
            result.source_normalizer_config_fingerprint
            == "sha256:normalizer"
        )

        assert (
            result.chunker_strategy_id
            == "structural-text"
        )
        assert (
            result.chunker_version
            == "1.0.0"
        )
        assert (
            result.chunker_config_fingerprint
            == make_chunker().descriptor.config_fingerprint
        )

    def test_document_metadata_is_preserved(
        self,
    ) -> None:
        document = make_document(
            make_segment("Policy."),
            metadata={
                "tenant": "acme",
                "language": "en",
            },
        )

        result = make_chunker().chunk(
            document
        )

        assert result.metadata["tenant"] == "acme"
        assert result.metadata["language"] == "en"
        assert (
            result.metadata["chunked_from"]
            == "test-normalizer@3.4.0"
        )

    def test_chunk_spans_resolve_to_exact_normalized_text(
        self,
    ) -> None:
        document = make_document(
            make_segment(
                "Refund policy paragraph.",
                index=0,
            ),
            make_segment(
                "Shipping policy paragraph.",
                index=1,
            ),
        )

        result = make_chunker(
            overlap_chars=0,
            preserve_section_boundaries=False,
        ).chunk(document)

        for chunk in result.chunks:
            resolved = reconstruct_span_text(
                document,
                chunk,
            )

            for span_text in resolved:
                assert span_text in chunk.text

    def test_split_segment_offsets_resolve_exactly(
        self,
    ) -> None:
        text = (
            "Alpha beta gamma delta epsilon. "
            * 30
        )

        document = make_document(
            make_segment(text)
        )

        result = make_chunker(
            target_chars=80,
            max_chars=100,
            overlap_chars=0,
        ).chunk(document)

        for chunk in result.chunks:
            for span in chunk.source_spans:
                source = document.segments[
                    span.source_segment_index
                ].text[
                    span.start_offset:
                    span.end_offset
                ]

                assert source in chunk.text


# ---------------------------------------------------------------------------
# Text preservation
# ---------------------------------------------------------------------------


class TestTextPreservation:
    def test_unbroken_text_is_not_lost_without_overlap(
        self,
    ) -> None:
        text = "X" * 1_000

        document = make_document(
            make_segment(text)
        )

        result = make_chunker(
            target_chars=100,
            max_chars=120,
            overlap_chars=0,
        ).chunk(document)

        reconstructed = "".join(
            chunk.text
            for chunk in result.chunks
        )

        assert reconstructed == text

    def test_words_are_not_lost_when_splitting_on_whitespace(
        self,
    ) -> None:
        words = [
            f"word{index}"
            for index in range(100)
        ]

        text = " ".join(words)

        document = make_document(
            make_segment(text)
        )

        result = make_chunker(
            target_chars=70,
            max_chars=90,
            overlap_chars=0,
        ).chunk(document)

        reconstructed_words = []

        for chunk in result.chunks:
            reconstructed_words.extend(
                chunk.text.split()
            )

        assert reconstructed_words == words

    def test_unicode_content_is_preserved(
        self,
    ) -> None:
        text = (
            "বাংলা নীতি। "
            "हिंदी नीति। "
            "中文政策。 "
            "日本語ポリシー。 "
            "سياسة الاسترداد. "
            "Refund ₹500 😊. "
        ) * 20

        document = make_document(
            make_segment(text)
        )

        result = make_chunker(
            target_chars=100,
            max_chars=140,
            overlap_chars=0,
        ).chunk(document)

        combined = " ".join(
            chunk.text
            for chunk in result.chunks
        )

        for expected in [
            "বাংলা",
            "हिंदी",
            "中文",
            "日本語",
            "سياسة",
            "₹500",
            "😊",
        ]:
            assert expected in combined


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_input_and_config_produce_identical_chunks(
        self,
    ) -> None:
        document = make_document(
            make_segment(
                (
                    "Refunds are available within thirty days. "
                    "Customers must provide proof of purchase. "
                )
                * 20
            )
        )

        first = make_chunker().chunk(
            document
        )
        second = make_chunker().chunk(
            document
        )

        assert first.chunks == second.chunks
        assert (
            first.chunker_config_fingerprint
            == second.chunker_config_fingerprint
        )


# ---------------------------------------------------------------------------
# Input immutability
# ---------------------------------------------------------------------------


class TestInputImmutability:
    def test_chunking_does_not_mutate_normalized_document(
        self,
    ) -> None:
        segment = make_segment(
            "Original normalized text.",
            metadata={"kind": "policy"},
        )

        document = make_document(
            segment,
            metadata={"tenant": "acme"},
        )

        original_text = segment.text
        original_section_path = (
            segment.section_path
        )
        original_segment_metadata = dict(
            segment.metadata
        )
        original_document_metadata = dict(
            document.metadata
        )

        make_chunker().chunk(
            document
        )

        assert segment.text == original_text
        assert (
            segment.section_path
            == original_section_path
        )
        assert (
            dict(segment.metadata)
            == original_segment_metadata
        )
        assert (
            dict(document.metadata)
            == original_document_metadata
        )


# ---------------------------------------------------------------------------
# Real-world document shape
# ---------------------------------------------------------------------------


class TestRealWorldKnowledgeDocument:
    def test_policy_document_with_multiple_sections(
        self,
    ) -> None:
        document = make_document(
            make_segment(
                (
                    "Customers may request a refund within "
                    "30 days of delivery. Proof of purchase "
                    "is required."
                ),
                index=0,
                section_path=(
                    "Policies",
                    "Refunds",
                ),
            ),
            make_segment(
                (
                    "Approved refunds are returned to the "
                    "original payment method. Processing may "
                    "take five business days."
                ),
                index=1,
                section_path=(
                    "Policies",
                    "Refunds",
                ),
            ),
            make_segment(
                (
                    "Standard shipping usually takes three "
                    "to five business days. Delays may occur "
                    "during holidays."
                ),
                index=2,
                section_path=(
                    "Policies",
                    "Shipping",
                ),
            ),
            make_segment(
                (
                    "Customers should contact support if "
                    "tracking has not updated for seven days."
                ),
                index=3,
                section_path=(
                    "Policies",
                    "Shipping",
                ),
            ),
        )

        result = make_chunker(
            target_chars=160,
            max_chars=220,
            overlap_chars=30,
        ).chunk(document)

        assert result.chunk_count >= 2

        assert all(
            len(chunk.text) <= 220
            for chunk in result.chunks
        )

        assert any(
            chunk.section_path
            == ("Policies", "Refunds")
            for chunk in result.chunks
        )

        assert any(
            chunk.section_path
            == ("Policies", "Shipping")
            for chunk in result.chunks
        )

        # Section isolation is more important than obtaining a
        # particular number of chunks.
        for chunk in result.chunks:
            if (
                chunk.section_path
                == ("Policies", "Refunds")
            ):
                assert (
                    "Standard shipping"
                    not in chunk.text
                )

            if (
                chunk.section_path
                == ("Policies", "Shipping")
            ):
                assert (
                    "Approved refunds"
                    not in chunk.text
                )


# ---------------------------------------------------------------------------
# Error translation / defensive postconditions
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.parametrize(
        "value",
        [
            None,
            "document",
            123,
            object(),
        ],
    )
    def test_non_normalized_document_rejected(
        self,
        value,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="document must be a NormalizedDocument",
        ):
            make_chunker().chunk(value)

    def test_unexpected_internal_failure_is_translated(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        chunker = make_chunker()
        document = make_document(
            make_segment("Policy.")
        )

        def explode(_segments):
            raise RuntimeError(
                "internal splitter failure"
            )

        monkeypatch.setattr(
            chunker,
            "_create_source_pieces",
            explode,
        )

        with pytest.raises(
            KnowledgeChunkingExecutionError
        ) as exc_info:
            chunker.chunk(document)

        assert isinstance(
            exc_info.value.__cause__,
            RuntimeError,
        )

        assert (
            exc_info.value.context[
                "chunker_name"
            ]
            == "structural-text"
        )

        assert (
            exc_info.value.context[
                "version_id"
            ]
            == str(document.version_id)
        )

    def test_typed_chunking_error_is_not_wrapped(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        chunker = make_chunker()
        document = make_document(
            make_segment("Policy.")
        )

        expected = KnowledgeChunkerOutputError(
            "deliberate contract failure",
            chunker_name="structural-text",
        )

        def fail(_segments):
            raise expected

        monkeypatch.setattr(
            chunker,
            "_create_source_pieces",
            fail,
        )

        with pytest.raises(
            KnowledgeChunkerOutputError
        ) as exc_info:
            chunker.chunk(document)

        assert exc_info.value is expected


# ---------------------------------------------------------------------------
# Internal postcondition checks
#
# These tests intentionally exercise private validation methods.
# They are justified here because these methods enforce safety
# invariants at the algorithm boundary rather than implementation
# convenience.
# ---------------------------------------------------------------------------


class TestOutputPostconditions:
    def test_unknown_source_segment_reference_is_rejected(
        self,
    ) -> None:
        chunker = make_chunker()
        document = make_document(
            make_segment("Policy.", index=0)
        )

        bad_chunk = ChunkCandidate(
            index=0,
            text="Policy.",
            source_spans=(
                ChunkSourceSpan(
            source_segment_index=99,
            start_offset=0,
            end_offset=7,
        ),
            ),
        )

        with pytest.raises(
            KnowledgeChunkerOutputError,
            match="unknown normalized segment",
        ):
            chunker._validate_output(
                document=document,
                chunks=[bad_chunk],
            )

    def test_span_past_segment_boundary_is_rejected(
        self,
    ) -> None:
        from packages.knowledge.ingestion.chunking.models import (
            ChunkSourceSpan,
        )

        chunker = make_chunker()
        document = make_document(
            make_segment("Policy.", index=0)
        )

        bad_chunk = ChunkCandidate(
            index=0,
            text="Policy.",
            source_spans=(
                ChunkSourceSpan(
                    source_segment_index=0,
                    start_offset=0,
                    end_offset=100,
                ),
            ),
        )

        with pytest.raises(
            KnowledgeChunkerOutputError,
            match="exceeds the normalized segment boundary",
        ):
            chunker._validate_output(
                document=document,
                chunks=[bad_chunk],
            )

    def test_non_contiguous_output_index_is_rejected(
        self,
    ) -> None:
        from packages.knowledge.ingestion.chunking.models import (
            ChunkSourceSpan,
        )

        chunker = make_chunker()
        document = make_document(
            make_segment("Policy.", index=0)
        )

        bad_chunk = ChunkCandidate(
            index=1,
            text="Policy.",
            source_spans=(
                ChunkSourceSpan(
                    source_segment_index=0,
                    start_offset=0,
                    end_offset=7,
                ),
            ),
        )

        with pytest.raises(
            KnowledgeChunkerOutputError,
            match="not contiguous",
        ):
            chunker._validate_output(
                document=document,
                chunks=[bad_chunk],
            )


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------


class TestOutputContract:
    def test_returns_chunked_document(
        self,
    ) -> None:
        result = make_chunker().chunk(
            make_document(
                make_segment("Policy.")
            )
        )

        assert isinstance(
            result,
            ChunkedDocument,
        )

    def test_chunk_indexes_are_contiguous_and_zero_based(
        self,
    ) -> None:
        result = make_chunker(
            target_chars=70,
            max_chars=100,
            overlap_chars=10,
        ).chunk(
            make_document(
                make_segment(
                    "word " * 200
                )
            )
        )

        assert [
            chunk.index
            for chunk in result.chunks
        ] == list(
            range(result.chunk_count)
        )

    def test_every_chunk_has_source_provenance(
        self,
    ) -> None:
        result = make_chunker(
            target_chars=70,
            max_chars=100,
            overlap_chars=10,
        ).chunk(
            make_document(
                make_segment(
                    "word " * 200
                )
            )
        )

        assert all(
            chunk.source_spans
            for chunk in result.chunks
        )