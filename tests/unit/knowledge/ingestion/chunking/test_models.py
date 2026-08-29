from __future__ import annotations

from types import MappingProxyType
from uuid import uuid4

import pytest

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.chunking.models import (
    ChunkCandidate,
    ChunkedDocument,
    ChunkSourceSpan,
)


def make_span(
    *,
    source_segment_index: int = 0,
    start_offset: int = 0,
    end_offset: int = 10,
) -> ChunkSourceSpan:
    return ChunkSourceSpan(
        source_segment_index=source_segment_index,
        start_offset=start_offset,
        end_offset=end_offset,
    )


def make_chunk(
    *,
    index: int = 0,
    text: str = "hello world",
    source_spans: tuple[ChunkSourceSpan, ...] | None = None,
    section_path: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> ChunkCandidate:
    if source_spans is None:
        source_spans = (
            make_span(
                source_segment_index=0,
                start_offset=0,
                end_offset=1,
            ),
        )

    return ChunkCandidate(
        index=index,
        text=text,
        source_spans=source_spans,
        section_path=section_path,
        metadata=metadata or {},
    )


def make_chunked_document(
    *,
    chunks: tuple[ChunkCandidate, ...] | None = None,
    source_type: KnowledgeSourceType = KnowledgeSourceType.MARKDOWN,
    metadata: dict | None = None,
) -> ChunkedDocument:
    if chunks is None:
        chunks = (
            make_chunk(index=0),
        )

    return ChunkedDocument(
        version_id=uuid4(),
        source_type=source_type,
        chunks=chunks,
        source_parser_strategy_id="markdown-structural",
        source_parser_version="1.0.0",
        source_parser_config_fingerprint="sha256:parser",
        source_normalizer_strategy_id="markdown-semantic",
        source_normalizer_version="1.0.0",
        source_normalizer_config_fingerprint="sha256:normalizer",
        chunker_strategy_id="structural-text",
        chunker_version="1.0.0",
        chunker_config_fingerprint="sha256:chunker",
        metadata=metadata or {},
    )


class TestChunkSourceSpan:
    def test_valid_span(self) -> None:
        span = ChunkSourceSpan(
            source_segment_index=3,
            start_offset=5,
            end_offset=15,
        )

        assert span.source_segment_index == 3
        assert span.start_offset == 5
        assert span.end_offset == 15
        assert span.length == 10

    @pytest.mark.parametrize(
        "value",
        ["0", 1.2, None, object()],
    )
    def test_source_segment_index_must_be_int(
        self,
        value,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="source_segment_index must be an integer",
        ):
            ChunkSourceSpan(
                source_segment_index=value,
                start_offset=0,
                end_offset=1,
            )

    def test_source_segment_index_must_be_non_negative(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="source_segment_index must be non-negative",
        ):
            ChunkSourceSpan(
                source_segment_index=-1,
                start_offset=0,
                end_offset=1,
            )

    @pytest.mark.parametrize(
        "value",
        ["0", 1.2, None],
    )
    def test_start_offset_must_be_int(
        self,
        value,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="start_offset must be an integer",
        ):
            ChunkSourceSpan(
                source_segment_index=0,
                start_offset=value,
                end_offset=5,
            )

    @pytest.mark.parametrize(
        "value",
        ["1", 1.2, None],
    )
    def test_end_offset_must_be_int(
        self,
        value,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="end_offset must be an integer",
        ):
            ChunkSourceSpan(
                source_segment_index=0,
                start_offset=0,
                end_offset=value,
            )

    def test_start_offset_must_be_non_negative(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="start_offset must be non-negative",
        ):
            ChunkSourceSpan(
                source_segment_index=0,
                start_offset=-1,
                end_offset=2,
            )

    @pytest.mark.parametrize(
        ("start", "end"),
        [
            (0, 0),
            (5, 5),
            (5, 4),
        ],
    )
    def test_end_offset_must_be_greater_than_start(
        self,
        start: int,
        end: int,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="end_offset must be greater than start_offset",
        ):
            ChunkSourceSpan(
                source_segment_index=0,
                start_offset=start,
                end_offset=end,
            )

    def test_is_immutable(self) -> None:
        span = make_span()

        with pytest.raises(Exception):
            span.start_offset = 99  # type: ignore[misc]


class TestChunkCandidate:
    def test_valid_candidate(self) -> None:
        chunk = ChunkCandidate(
            index=0,
            text="refund policy",
            source_spans=(
                make_span(
                    source_segment_index=2,
                    start_offset=0,
                    end_offset=13,
                ),
            ),
            section_path=("Payments", "Refunds"),
            metadata={"language": "en"},
        )

        assert chunk.index == 0
        assert chunk.text == "refund policy"
        assert chunk.section_path == (
            "Payments",
            "Refunds",
        )
        assert chunk.section_title == "Refunds"
        assert chunk.char_count == 13
        assert chunk.source_segment_indexes == (2,)
        assert chunk.metadata["language"] == "en"

    def test_section_title_none_when_path_empty(
        self,
    ) -> None:
        chunk = make_chunk()

        assert chunk.section_title is None

    @pytest.mark.parametrize(
        "value",
        ["0", 1.5, None],
    )
    def test_index_must_be_integer(
        self,
        value,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="index must be an integer",
        ):
            make_chunk(index=value)

    def test_index_must_be_non_negative(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="index must be non-negative",
        ):
            make_chunk(index=-1)

    @pytest.mark.parametrize(
        "value",
        [None, 123, object()],
    )
    def test_text_must_be_string(
        self,
        value,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="text must be a string",
        ):
            make_chunk(text=value)

    @pytest.mark.parametrize(
        "value",
        ["", " ", "\n\t"],
    )
    def test_text_must_not_be_blank(
        self,
        value: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="text must not be blank",
        ):
            make_chunk(text=value)

    def test_source_spans_must_be_tuple(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="source_spans must be a tuple",
        ):
            ChunkCandidate(
                index=0,
                text="hello",
                source_spans=[make_span()],  # type: ignore[arg-type]
            )

    def test_source_spans_cannot_be_empty(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="must reference at least one source span",
        ):
            ChunkCandidate(
                index=0,
                text="hello",
                source_spans=(),
            )

    def test_source_spans_must_contain_span_objects(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="Every source span must be a ChunkSourceSpan",
        ):
            ChunkCandidate(
                index=0,
                text="hello",
                source_spans=("bad",),  # type: ignore[arg-type]
            )

    def test_source_spans_must_be_strictly_ordered(
        self,
    ) -> None:
        first = make_span(
            source_segment_index=1,
            start_offset=10,
            end_offset=20,
        )
        second = make_span(
            source_segment_index=0,
            start_offset=0,
            end_offset=5,
        )

        with pytest.raises(
            ValueError,
            match="strictly ordered",
        ):
            make_chunk(
                source_spans=(first, second),
            )

    def test_duplicate_source_spans_rejected(
        self,
    ) -> None:
        span = make_span()

        with pytest.raises(
            ValueError,
            match="strictly ordered",
        ):
            make_chunk(
                source_spans=(span, span),
            )

    def test_overlapping_spans_from_same_segment_rejected(
        self,
    ) -> None:
        first = make_span(
            source_segment_index=0,
            start_offset=0,
            end_offset=10,
        )
        second = make_span(
            source_segment_index=0,
            start_offset=8,
            end_offset=20,
        )

        with pytest.raises(
            ValueError,
            match="must not overlap",
        ):
            make_chunk(
                source_spans=(first, second),
            )

    def test_adjacent_spans_from_same_segment_allowed(
        self,
    ) -> None:
        chunk = make_chunk(
            source_spans=(
                make_span(
                    source_segment_index=0,
                    start_offset=0,
                    end_offset=10,
                ),
                make_span(
                    source_segment_index=0,
                    start_offset=10,
                    end_offset=20,
                ),
            ),
        )

        assert len(chunk.source_spans) == 2

    def test_spans_from_different_segments_allowed(
        self,
    ) -> None:
        chunk = make_chunk(
            source_spans=(
                make_span(
                    source_segment_index=0,
                    start_offset=0,
                    end_offset=5,
                ),
                make_span(
                    source_segment_index=1,
                    start_offset=0,
                    end_offset=5,
                ),
            ),
        )

        assert chunk.source_segment_indexes == (
            0,
            1,
        )

    def test_source_segment_indexes_are_unique_and_ordered(
        self,
    ) -> None:
        chunk = make_chunk(
            source_spans=(
                make_span(
                    source_segment_index=0,
                    start_offset=0,
                    end_offset=5,
                ),
                make_span(
                    source_segment_index=0,
                    start_offset=5,
                    end_offset=10,
                ),
                make_span(
                    source_segment_index=1,
                    start_offset=0,
                    end_offset=5,
                ),
            ),
        )

        assert chunk.source_segment_indexes == (
            0,
            1,
        )

    def test_section_path_must_be_tuple(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="section_path must be a tuple",
        ):
            make_chunk(
                section_path=["Refunds"],  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "path",
        [
            ("",),
            ("   ",),
            ("Payments", ""),
            ("Payments", 123),
        ],
    )
    def test_section_path_entries_must_be_non_blank_strings(
        self,
        path,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="section_path entries",
        ):
            make_chunk(
                section_path=path,
            )

    def test_metadata_must_be_mapping(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="metadata must be a mapping",
        ):
            make_chunk(
                metadata=["bad"],  # type: ignore[arg-type]
            )

    def test_metadata_is_frozen_copy(
        self,
    ) -> None:
        original = {"language": "en"}

        chunk = make_chunk(
            metadata=original,
        )

        original["language"] = "fr"

        assert chunk.metadata["language"] == "en"
        assert isinstance(
            chunk.metadata,
            MappingProxyType,
        )

        with pytest.raises(TypeError):
            chunk.metadata["language"] = "de"  # type: ignore[index]

    def test_candidate_is_immutable(
        self,
    ) -> None:
        chunk = make_chunk()

        with pytest.raises(Exception):
            chunk.text = "changed"  # type: ignore[misc]


class TestChunkedDocument:
    def test_valid_document(self) -> None:
        document = make_chunked_document()

        assert document.chunk_count == 1
        assert document.parser_identity == (
            "markdown-structural@1.0.0"
        )
        assert document.normalizer_identity == (
            "markdown-semantic@1.0.0"
        )
        assert document.chunker_identity == (
            "structural-text@1.0.0"
        )

    def test_version_id_must_be_uuid(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="version_id must be a UUID",
        ):
            ChunkedDocument(
                version_id="bad",  # type: ignore[arg-type]
                source_type=KnowledgeSourceType.MARKDOWN,
                chunks=(make_chunk(),),
                source_parser_strategy_id="parser",
                source_parser_version="1",
                source_parser_config_fingerprint=None,
                source_normalizer_strategy_id="normalizer",
                source_normalizer_version="1",
                source_normalizer_config_fingerprint=None,
                chunker_strategy_id="chunker",
                chunker_version="1",
            )

    def test_source_type_must_be_enum(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="source_type must be a KnowledgeSourceType",
        ):
            make_chunked_document(
                source_type="markdown",  # type: ignore[arg-type]
            )

    def test_chunks_must_be_tuple(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="chunks must be a tuple",
        ):
            make_chunked_document(
                chunks=[make_chunk()],  # type: ignore[arg-type]
            )

    def test_chunks_cannot_be_empty(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="must contain at least one chunk",
        ):
            make_chunked_document(
                chunks=(),
            )

    def test_chunks_must_contain_chunk_candidates(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="Every chunk must be a ChunkCandidate",
        ):
            make_chunked_document(
                chunks=("bad",),  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "chunks",
        [
            (
                make_chunk(index=1),
            ),
            (
                make_chunk(index=0),
                make_chunk(index=2),
            ),
            (
                make_chunk(index=1),
                make_chunk(index=0),
            ),
        ],
    )
    def test_chunk_indexes_must_be_contiguous_ordered_zero_based(
        self,
        chunks,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="contiguous, ordered, and zero-based",
        ):
            make_chunked_document(
                chunks=chunks,
            )

    @pytest.mark.parametrize(
        "field_name",
        [
            "source_parser_strategy_id",
            "source_parser_version",
            "source_normalizer_strategy_id",
            "source_normalizer_version",
            "chunker_strategy_id",
            "chunker_version",
        ],
    )
    def test_required_provenance_fields_reject_non_string(
        self,
        field_name: str,
    ) -> None:
        kwargs = {
            "version_id": uuid4(),
            "source_type": KnowledgeSourceType.MARKDOWN,
            "chunks": (make_chunk(),),
            "source_parser_strategy_id": "parser",
            "source_parser_version": "1",
            "source_parser_config_fingerprint": None,
            "source_normalizer_strategy_id": "normalizer",
            "source_normalizer_version": "1",
            "source_normalizer_config_fingerprint": None,
            "chunker_strategy_id": "chunker",
            "chunker_version": "1",
        }

        kwargs[field_name] = 123

        with pytest.raises(TypeError):
            ChunkedDocument(**kwargs)

    @pytest.mark.parametrize(
        "field_name",
        [
            "source_parser_strategy_id",
            "source_parser_version",
            "source_normalizer_strategy_id",
            "source_normalizer_version",
            "chunker_strategy_id",
            "chunker_version",
        ],
    )
    @pytest.mark.parametrize(
        "value",
        ["", "   "],
    )
    def test_required_provenance_fields_reject_blank(
        self,
        field_name: str,
        value: str,
    ) -> None:
        kwargs = {
            "version_id": uuid4(),
            "source_type": KnowledgeSourceType.MARKDOWN,
            "chunks": (make_chunk(),),
            "source_parser_strategy_id": "parser",
            "source_parser_version": "1",
            "source_parser_config_fingerprint": None,
            "source_normalizer_strategy_id": "normalizer",
            "source_normalizer_version": "1",
            "source_normalizer_config_fingerprint": None,
            "chunker_strategy_id": "chunker",
            "chunker_version": "1",
        }

        kwargs[field_name] = value

        with pytest.raises(ValueError):
            ChunkedDocument(**kwargs)

    @pytest.mark.parametrize(
        "field_name",
        [
            "source_parser_config_fingerprint",
            "source_normalizer_config_fingerprint",
            "chunker_config_fingerprint",
        ],
    )
    def test_optional_fingerprint_rejects_non_string(
        self,
        field_name: str,
    ) -> None:
        kwargs = {
            "version_id": uuid4(),
            "source_type": KnowledgeSourceType.MARKDOWN,
            "chunks": (make_chunk(),),
            "source_parser_strategy_id": "parser",
            "source_parser_version": "1",
            "source_parser_config_fingerprint": None,
            "source_normalizer_strategy_id": "normalizer",
            "source_normalizer_version": "1",
            "source_normalizer_config_fingerprint": None,
            "chunker_strategy_id": "chunker",
            "chunker_version": "1",
            "chunker_config_fingerprint": None,
        }

        kwargs[field_name] = 123

        with pytest.raises(TypeError):
            ChunkedDocument(**kwargs)

    @pytest.mark.parametrize(
        "field_name",
        [
            "source_parser_config_fingerprint",
            "source_normalizer_config_fingerprint",
            "chunker_config_fingerprint",
        ],
    )
    @pytest.mark.parametrize(
        "value",
        ["", "   "],
    )
    def test_optional_fingerprint_rejects_blank_string(
        self,
        field_name: str,
        value: str,
    ) -> None:
        kwargs = {
            "version_id": uuid4(),
            "source_type": KnowledgeSourceType.MARKDOWN,
            "chunks": (make_chunk(),),
            "source_parser_strategy_id": "parser",
            "source_parser_version": "1",
            "source_parser_config_fingerprint": None,
            "source_normalizer_strategy_id": "normalizer",
            "source_normalizer_version": "1",
            "source_normalizer_config_fingerprint": None,
            "chunker_strategy_id": "chunker",
            "chunker_version": "1",
            "chunker_config_fingerprint": None,
        }

        kwargs[field_name] = value

        with pytest.raises(ValueError):
            ChunkedDocument(**kwargs)

    def test_none_fingerprints_are_allowed(
        self,
    ) -> None:
        document = ChunkedDocument(
            version_id=uuid4(),
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            chunks=(make_chunk(),),
            source_parser_strategy_id="plain-text",
            source_parser_version="1.0.0",
            source_parser_config_fingerprint=None,
            source_normalizer_strategy_id="plain-text",
            source_normalizer_version="1.0.0",
            source_normalizer_config_fingerprint=None,
            chunker_strategy_id="structural-text",
            chunker_version="1.0.0",
            chunker_config_fingerprint=None,
        )

        assert document.chunker_config_fingerprint is None

    def test_metadata_is_frozen_copy(
        self,
    ) -> None:
        original = {"tenant": "example"}

        document = make_chunked_document(
            metadata=original,
        )

        original["tenant"] = "changed"

        assert document.metadata["tenant"] == "example"

        with pytest.raises(TypeError):
            document.metadata["tenant"] = "x"  # type: ignore[index]

    def test_document_is_immutable(
        self,
    ) -> None:
        document = make_chunked_document()

        with pytest.raises(Exception):
            document.chunker_version = "2"  # type: ignore[misc]