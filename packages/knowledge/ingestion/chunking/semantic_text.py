from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.chunking.base import BaseDocumentChunker, ChunkerDescriptor
from packages.knowledge.ingestion.chunking.errors import InvalidChunkingInputError, KnowledgeChunkerOutputError, KnowledgeChunkingError, KnowledgeChunkingExecutionError
from packages.knowledge.ingestion.chunking.models import ChunkCandidate, ChunkedDocument, ChunkSourceSpan
from packages.knowledge.ingestion.normalization.models import NormalizedDocument, NormalizedSegment


@dataclass(frozen=True, slots=True)
class StructuralTextChunkerConfig:
    """
    Output-affecting configuration for StructuralTextChunker.

    target_chars:
        Soft preferred chunk size.

    max_chars:
        Hard upper bound for every produced chunk.

    overlap_chars:
        Approximate amount of source-backed text carried from the end of one chunk into the next.

    min_chunk_chars:
        Soft lower bound used when deciding whether a chunk should be finalized before adding another piece.

        This is deliberately not a hard invariant. A short standalone section may legitimately produce a smaller chunk.

    preserve_section_boundaries:
        When True, content from different section paths is not merged into one chunk.

    separator:
        Synthetic separator inserted between source pieces when they are combined into one chunk.
    """
    target_chars: int = 1200
    max_chars: int = 1800
    overlap_chars: int = 200
    min_chunk_chars: int = 200
    preserve_section_boundaries: bool = True
    separator: str = "\n\n"

    def __post_init__(self) -> None:
        self._validate_positive_int("target_chars", self.target_chars)
        self._validate_positive_int("max_chars", self.max_chars)
        self._validate_non_negative_int("overlap_chars", self.overlap_chars)
        self._validate_non_negative_int( "min_chunk_chars", self.min_chunk_chars)

        if not isinstance(self.preserve_section_boundaries, bool):
            raise TypeError("preserve_section_boundaries must be a boolean.")

        if not isinstance(self.separator, str):
            raise TypeError("separator must be a string.")

        if self.target_chars > self.max_chars:
            raise ValueError("target_chars must not exceed max_chars.")

        if self.min_chunk_chars > self.target_chars:
            raise ValueError("min_chunk_chars must not exceed target_chars.")

        if self.overlap_chars >= self.max_chars:
            raise ValueError("overlap_chars must be smaller than max_chars.")

        if len(self.separator) >= self.max_chars:
            raise ValueError("separator must be shorter than max_chars.")

    @staticmethod
    def _validate_positive_int(field_name: str, value: object) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer.")

        if value <= 0:
            raise ValueError(f"{field_name} must be greater than zero.")

    @staticmethod
    def _validate_non_negative_int(field_name: str, value: object) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer.")

        if value < 0:
            raise ValueError(f"{field_name} must be non-negative.")

    @property
    def fingerprint(self) -> str:
        """
        Deterministic fingerprint of all output-affecting settings.
        """
        payload = {
            "max_chars": self.max_chars,
            "min_chunk_chars": self.min_chunk_chars,
            "overlap_chars": self.overlap_chars,
            "preserve_section_boundaries": self.preserve_section_boundaries,
            "separator": self.separator,
            "target_chars": self.target_chars,
        }
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        return f"sha256:{digest}"

@dataclass(frozen=True, slots=True)
class _SourcePiece:
    """
    Internal source-backed unit used while constructing chunks.

    text must correspond exactly to:

        normalized_segment.text[start_offset:end_offset]

    The offsets are relative to NormalizedSegment.text.
    """
    source_segment_index: int
    start_offset: int
    end_offset: int
    text: str
    section_path: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_segment_index, int):
            raise TypeError("source_segment_index must be an integer.")

        if self.source_segment_index < 0:
            raise ValueError("source_segment_index must be non-negative.")

        if not isinstance(self.start_offset, int):
            raise TypeError("start_offset must be an integer.")

        if not isinstance(self.end_offset, int):
            raise TypeError("end_offset must be an integer.")

        if self.start_offset < 0:
            raise ValueError("start_offset must be non-negative.")

        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset.")

        if not isinstance(self.text, str):
            raise TypeError("text must be a string.")

        if not self.text:
            raise ValueError("Source piece text must not be empty.")

    @property
    def char_count(self) -> int:
        return len(self.text)


class StructuralTextChunker(BaseDocumentChunker):
    """
    Deterministic structure-aware text chunker.

    Responsibilities:
        - combine small normalized segments
        - split oversized normalized segments
        - prefer natural textual boundaries
        - optionally preserve section boundaries
        - create bounded overlap between adjacent chunks
        - retain exact normalized-source provenance
        - enforce a hard chunk-size limit
    """
    _STRATEGY_ID = "structural-text"
    _VERSION = "1.0.0"
    _SUPPORTED_SOURCE_TYPES = frozenset(
        {
            KnowledgeSourceType.MARKDOWN,
            KnowledgeSourceType.PLAIN_TEXT,
            KnowledgeSourceType.PDF,
            KnowledgeSourceType.DOCX,
            KnowledgeSourceType.HTML,
            KnowledgeSourceType.RICH_TEXT,
        }
    )

    def __init__(self, config: StructuralTextChunkerConfig | None = None) -> None:
        self._config = (config if config is not None else StructuralTextChunkerConfig())

        if not isinstance(self._config, StructuralTextChunkerConfig):
            raise TypeError("config must be a StructuralTextChunkerConfig.")

        self._descriptor = ChunkerDescriptor(
            strategy_id=self._STRATEGY_ID,
            version=self._VERSION,
            config_fingerprint=self._config.fingerprint,
        )

    @property
    def config(self) -> StructuralTextChunkerConfig:
        return self._config

    @property
    def descriptor(self) -> ChunkerDescriptor:
        return self._descriptor

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        return self._SUPPORTED_SOURCE_TYPES

    def chunk(self, document: NormalizedDocument) -> ChunkedDocument:
        if not isinstance(document, NormalizedDocument):
            raise TypeError("document must be a NormalizedDocument.")

        if not self.supports(document.source_type):
            raise InvalidChunkingInputError(
                "StructuralTextChunker does not support the document source type.",
                chunker_name=self.descriptor.strategy_id,
                version_id=document.version_id,
                source_type=document.source_type,
            )

        try:
            pieces = self._create_source_pieces(document.segments)
            if not pieces:
                raise KnowledgeChunkerOutputError(
                    "Chunker produced no source pieces from a non-empty normalized document.",
                    chunker_name=self.descriptor.strategy_id,
                    version_id=document.version_id,
                )

            chunks = self._assemble_chunks(pieces)
            if not chunks:
                raise KnowledgeChunkerOutputError(
                    "Chunker produced no chunks from a non-empty normalized document.",
                    chunker_name=self.descriptor.strategy_id,
                    version_id=document.version_id,
                )

            self._validate_output(document=document, chunks=chunks)

            return ChunkedDocument(
                version_id=document.version_id,
                source_type=document.source_type,
                chunks=tuple(chunks),
                source_parser_strategy_id=document.source_parser_strategy_id,
                source_parser_version=document.source_parser_version,
                source_parser_config_fingerprint=document.source_parser_config_fingerprint,
                source_normalizer_strategy_id=document.normalizer_strategy_id,
                source_normalizer_version=document.normalizer_version,
                source_normalizer_config_fingerprint=document.normalizer_config_fingerprint,
                chunker_strategy_id=self.descriptor.strategy_id,
                chunker_version=self.descriptor.version,
                chunker_config_fingerprint=self.descriptor.config_fingerprint,
                metadata={
                    **dict(document.metadata),
                    "chunked_from": document.normalizer_identity,
                },
            )

        except KnowledgeChunkingError:
            raise

        except Exception as exc:
            raise KnowledgeChunkingExecutionError(
                "Unexpected failure while chunking normalized document.",
                chunker_name=self.descriptor.strategy_id,
                version_id=document.version_id,
            ) from exc

    def _create_source_pieces(self, segments: tuple[NormalizedSegment, ...]) -> list[_SourcePiece]:
        pieces: list[_SourcePiece] = []
        for segment in segments:
            segment_pieces = self._split_segment(segment)
            if not segment_pieces:
                raise KnowledgeChunkerOutputError(
                    "A normalized segment produced no chunkable source pieces.",
                    chunker_name=self.descriptor.strategy_id,
                    source_segment_index=segment.index,
                )

            pieces.extend(segment_pieces)

        return pieces

    def _split_segment(self, segment: NormalizedSegment) -> list[_SourcePiece]:
        text = segment.text
        if len(text) <= self._config.max_chars:
            return [_SourcePiece(
                source_segment_index=segment.index,
                start_offset=0,
                end_offset=len(text),
                text=text,
                section_path=segment.section_path,
            )]

        pieces: list[_SourcePiece] = []
        cursor = 0
        text_length = len(text)
        while cursor < text_length:
            remaining = text_length - cursor
            if remaining <= self._config.max_chars:
                start, end = self._trim_range(text, cursor, text_length)
                if start < end:
                    pieces.append(_SourcePiece(
                        source_segment_index=segment.index,
                        start_offset=start,
                        end_offset=end,
                        text=text[start:end],
                        section_path=segment.section_path,
                    ))

                break

            hard_end = cursor + self._config.max_chars
            split_at = self._find_best_split(text=text, start=cursor, hard_end=hard_end)
            if split_at <= cursor:
                # Defensive fallback guaranteeing progress.
                split_at = hard_end

            start, end = self._trim_range(text, cursor, split_at)

            if start < end:
                pieces.append(_SourcePiece(
                    source_segment_index=segment.index,
                    start_offset=start,
                    end_offset=end,
                    text=text[start:end],
                    section_path=segment.section_path,
                ))

            cursor = split_at
            while cursor < text_length and text[cursor].isspace():
                cursor += 1

        return pieces

    def _find_best_split(self, *, text: str, start: int, hard_end: int) -> int:
        """
        Find a natural boundary without exceeding hard_end.

        Priority:
            1. paragraph/newline boundary
            2. sentence-ending punctuation
            3. whitespace
            4. hard character boundary

        Searching is restricted to the latter portion of the candidate range so that 
        pathological early punctuation does not create excessively tiny pieces.
        """
        search_floor = max(start + 1, start + min(self._config.target_chars, self._config.max_chars) // 2)
        if search_floor >= hard_end:
            search_floor = start + 1

        paragraph_boundary = self._rfind_newline_boundary(text=text, start=search_floor, end=hard_end)
        if paragraph_boundary is not None:
            return paragraph_boundary

        sentence_boundary = self._rfind_sentence_boundary(text=text, start=search_floor, end=hard_end)
        if sentence_boundary is not None:
            return sentence_boundary

        whitespace_boundary = self._rfind_whitespace_boundary(text=text, start=search_floor, end=hard_end)
        if whitespace_boundary is not None:
            return whitespace_boundary

        return hard_end

    @staticmethod
    def _rfind_newline_boundary(*, text: str, start: int, end: int) -> int | None:
        position = text.rfind("\n", start, end)
        if position == -1:
            return None

        return position + 1

    @staticmethod
    def _rfind_sentence_boundary(*, text: str, start: int, end: int) -> int | None:
        """
        Conservative sentence-boundary heuristic.

        We intentionally avoid heavyweight NLP dependencies in this generic chunker.
        More sophisticated language-specific sentence segmentation can later be introduced as another strategy.

        A punctuation mark is treated as a preferred boundary when it is followed by whitespace or occurs at the search limit.
        """
        sentence_endings = {".", "!", "?", "。", "！", "？", "।"}
        for index in range(end - 1, start - 1, -1):
            char = text[index]
            if char not in sentence_endings:
                continue

            next_index = index + 1
            if next_index >= len(text) or next_index >= end or text[next_index].isspace():
                return next_index

        return None

    @staticmethod
    def _rfind_whitespace_boundary(*, text: str, start: int, end: int) -> int | None:
        for index in range(end - 1, start - 1, -1):
            if text[index].isspace():
                return index + 1

        return None

    @staticmethod
    def _trim_range(text: str, start: int, end: int) -> tuple[int, int]:
        """
        Trim surrounding whitespace while preserving exact offsets into the normalized source string.
        """
        while start < end and text[start].isspace():
            start += 1

        while end > start and text[end - 1].isspace():
            end -= 1

        return start, end

    def _assemble_chunks(self, pieces: list[_SourcePiece]) -> list[ChunkCandidate]:
        chunks: list[ChunkCandidate] = []
        current: list[_SourcePiece] = []
        for piece in pieces:
            if not current:
                current.append(piece)
                continue

            if self._requires_section_break(current, piece):
                chunks.append(self._build_chunk(index=len(chunks), pieces=current))
                current = self._build_overlap(current)
                # Section preservation must not carry content from the previous section into a new section.
                if current and self._config.preserve_section_boundaries and current[-1].section_path != piece.section_path:
                    current = []

            projected_size = self._rendered_size([*current, piece])
            if current and projected_size > self._config.max_chars:
                chunks.append(self._build_chunk(index=len(chunks), pieces=current))
                current = self._build_overlap(current)
                while current and self._rendered_size([*current, piece]) > self._config.max_chars:
                    current.pop(0)

            elif current and projected_size > self._config.target_chars and self._rendered_size(current) >= self._config.min_chunk_chars:
                chunks.append(self._build_chunk(index=len(chunks), pieces=current))
                current = self._build_overlap(current)
                while current and self._rendered_size([*current, piece]) > self._config.max_chars:
                    current.pop(0)

            current.append(piece)

        if current:
            chunks.append(self._build_chunk(index=len(chunks), pieces=current))

        return chunks

    def _requires_section_break(self, current: list[_SourcePiece], incoming: _SourcePiece) -> bool:
        if not self._config.preserve_section_boundaries:
            return False

        if not current:
            return False

        return current[-1].section_path != incoming.section_path

    def _build_overlap(self, pieces: list[_SourcePiece]) -> list[_SourcePiece]:
        """
        Carry a source-backed suffix into the next chunk.

        Overlap is approximate in character count and never invents provenance. When the desired 
        overlap begins inside a piece, that piece is sliced and receives adjusted source offsets.
        """
        budget = self._config.overlap_chars
        if budget <= 0 or not pieces:
            return []

        selected_reversed: list[_SourcePiece] = []
        remaining = budget
        for piece in reversed(pieces):
            if remaining <= 0:
                break

            if piece.char_count <= remaining:
                selected_reversed.append(piece)
                remaining -= piece.char_count
                continue

            relative_start = piece.char_count - remaining
            absolute_start = piece.start_offset + relative_start
            sliced_text = piece.text[relative_start:]
            if sliced_text:
                selected_reversed.append(_SourcePiece(
                    source_segment_index=piece.source_segment_index,
                    start_offset=absolute_start,
                    end_offset=piece.end_offset,
                    text=sliced_text,
                    section_path=piece.section_path,
                ))

            remaining = 0

        return list(reversed(selected_reversed))

    def _build_chunk(self, *, index: int, pieces: list[_SourcePiece]) -> ChunkCandidate:
        if not pieces:
            raise KnowledgeChunkerOutputError(
                "Cannot build a chunk from zero source pieces.",
                chunker_name=self.descriptor.strategy_id,
                chunk_index=index,
            )

        text = self._render_pieces(pieces)
        if not text.strip():
            raise KnowledgeChunkerOutputError(
                "Chunk rendering produced blank text.",
                chunker_name=self.descriptor.strategy_id,
                chunk_index=index,
            )

        if len(text) > self._config.max_chars:
            raise KnowledgeChunkerOutputError(
                "Chunk exceeds the configured hard character limit.",
                chunker_name=self.descriptor.strategy_id,
                chunk_index=index,
                actual_chars=len(text),
                max_chars=self._config.max_chars,
            )

        section_path = self._common_section_path(piece.section_path for piece in pieces)
        spans = tuple(ChunkSourceSpan(
            source_segment_index=piece.source_segment_index,
            start_offset=piece.start_offset,
            end_offset=piece.end_offset,
            )
            for piece in pieces
        )

        return ChunkCandidate(
            index=index,
            text=text,
            source_spans=spans,
            section_path=section_path,
            metadata={
                "char_count": len(text),
                "source_piece_count": len(pieces),
            },
        )

    def _render_pieces(self, pieces: Iterable[_SourcePiece]) -> str:
        return self._config.separator.join(piece.text for piece in pieces)

    def _rendered_size(self, pieces: list[_SourcePiece]) -> int:
        if not pieces:
            return 0

        source_chars = sum(piece.char_count for piece in pieces)
        separator_chars = len(self._config.separator) * (len(pieces) - 1)

        return source_chars + separator_chars

    @staticmethod
    def _common_section_path(paths: Iterable[tuple[str, ...]]) -> tuple[str, ...]:
        """
        Return the longest common section-path prefix.

        With preserve_section_boundaries=True this is normally the full section path.
        It also gives sensible metadata if callers choose to allow cross-section chunking.
        """
        path_list = list(paths)
        if not path_list:
            return ()

        common = list(path_list[0])
        for path in path_list[1:]:
            shared_length = 0
            for left, right in zip(common, path):
                if left != right:
                    break

                shared_length += 1

            common = common[:shared_length]
            if not common:
                break

        return tuple(common)

    def _validate_output(self, *, document: NormalizedDocument, chunks: list[ChunkCandidate]) -> None:
        """
        Verify postconditions that should hold regardless of internal implementation details.
        """
        if not chunks:
            raise KnowledgeChunkerOutputError(
                "Chunker output must not be empty.",
                chunker_name=self.descriptor.strategy_id,
                version_id=document.version_id,
            )

        for expected_index, chunk in enumerate(chunks):
            if chunk.index != expected_index:
                raise KnowledgeChunkerOutputError(
                    "Chunk indexes are not contiguous and zero-based.",
                    chunker_name=self.descriptor.strategy_id,
                    version_id=document.version_id,
                    chunk_index=chunk.index,
                    expected_index=expected_index,
                )

            if not chunk.text.strip():
                raise KnowledgeChunkerOutputError(
                    "Chunk text must not be blank.",
                    chunker_name=self.descriptor.strategy_id,
                    version_id=document.version_id,
                    chunk_index=chunk.index,
                )

            if len(chunk.text) > self._config.max_chars:
                raise KnowledgeChunkerOutputError(
                    "Chunk exceeds the configured hard character limit.",
                    chunker_name=self.descriptor.strategy_id,
                    version_id=document.version_id,
                    chunk_index=chunk.index,
                    actual_chars=len(chunk.text),
                    max_chars=self._config.max_chars,
                )

            self._validate_chunk_spans(document=document, chunk=chunk)

    def _validate_chunk_spans(self, *, document: NormalizedDocument, chunk: ChunkCandidate) -> None:
        segment_by_index = {segment.index: segment for segment in document.segments}
        for span in chunk.source_spans:
            segment = segment_by_index.get(span.source_segment_index)
            if segment is None:
                raise KnowledgeChunkerOutputError(
                    "Chunk references an unknown normalized segment.",
                    chunker_name=self.descriptor.strategy_id,
                    version_id=document.version_id,
                    chunk_index=chunk.index,
                    source_segment_index=span.source_segment_index,
                )

            if span.end_offset > len(segment.text):
                raise KnowledgeChunkerOutputError(
                    "Chunk source span exceeds the normalized segment boundary.",
                    chunker_name=self.descriptor.strategy_id,
                    version_id=document.version_id,
                    chunk_index=chunk.index,
                    source_segment_index=span.source_segment_index,
                    end_offset=span.end_offset,
                    segment_length=len(segment.text),
                )

            source_text = segment.text[span.start_offset:span.end_offset]
            if not source_text:
                raise KnowledgeChunkerOutputError(
                    "Chunk source span resolves to empty text.",
                    chunker_name=self.descriptor.strategy_id,
                    version_id=document.version_id,
                    chunk_index=chunk.index,
                    source_segment_index=span.source_segment_index,
                )