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
        Preferred chunk size. This is a soft target, never a reason to
        break a stronger semantic boundary unnecessarily.

    max_chars:
        Hard upper bound for canonical chunk text.

    min_chunk_chars:
        Soft minimum used to avoid producing tiny standalone chunks.

    overlap_chars:
        Maximum approximate overlap budget. Overlap is generated only
        from complete semantic pieces or natural text boundaries.

    preserve_section_boundaries:
        Prefer section boundaries during packing. This is not an
        unconditional instruction to produce tiny chunks.

    merge_small_sections:
        Allow undersized adjacent sections to be merged when doing so is
        structurally safe.

    max_section_depth_distance:
        Maximum hierarchy-distance allowed when merging undersized
        neighboring sections.

    separator:
        Separator between canonical source pieces.
    """
    target_chars: int = 1200
    max_chars: int = 1800
    min_chunk_chars: int = 250
    overlap_chars: int = 160
    preserve_section_boundaries: bool = True
    merge_small_sections: bool = True
    max_section_depth_distance: int = 1
    separator: str = "\n\n"

    def __post_init__(self) -> None:
        self._validate_positive_int("target_chars", self.target_chars)
        self._validate_positive_int("max_chars", self.max_chars)
        self._validate_non_negative_int("overlap_chars", self.overlap_chars)
        self._validate_non_negative_int( "min_chunk_chars", self.min_chunk_chars)
        self._validate_non_negative_int("max_section_depth_distance", self.max_section_depth_distance)
        
        if not isinstance(self.merge_small_sections, bool):
            raise TypeError("merge_small_sections must be a boolean.")

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
            "merge_small_sections": self.merge_small_sections,
            "max_section_depth_distance": self.max_section_depth_distance,
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
    block_type: str | None = None

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
    
    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def is_code(self) -> bool:
        return self.block_type in {"fenced_code", "indented_code",}

    @property
    def is_table(self) -> bool:
        return self.block_type == "table"


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
    _VERSION = "2.0.0"
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
        block_type_raw = segment.metadata.get("markdown_block_type")
        block_type = block_type_raw if isinstance(block_type_raw, str) else None
        if block_type in {"fenced_code", "indented_code"}:
            return self._split_atomic_segment(segment=segment, block_type=block_type)
        
        text = segment.text
        if len(text) <= self._config.max_chars:
            return [_SourcePiece(
                source_segment_index=segment.index,
                start_offset=0,
                end_offset=len(text),
                text=text,
                section_path=segment.section_path,
                block_type=block_type,
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
    
    def _split_atomic_segment(self, *, segment: NormalizedSegment, block_type: str | None) -> list[_SourcePiece]:
        """
        Split structurally atomic content only when the hard size limit requires it.

        Prefer line boundaries and never use sentence punctuation as a semantic signal for code/table-like content.
        """
        text = segment.text
        pieces: list[_SourcePiece] = []
        cursor = 0
        text_length = len(text)

        while cursor < text_length:
            hard_end = min(cursor + self._config.max_chars, text_length)
            
            if hard_end < text_length:
                split_at = self._rfind_newline_boundary(text=text, start=cursor + 1, end=hard_end)
                if split_at is None or split_at <= cursor:
                    split_at = hard_end
            else:
                split_at = text_length

            start, end = self._trim_range(text, cursor, split_at)
            if start < end:
                pieces.append(
                    _SourcePiece(
                        source_segment_index=segment.index,
                        start_offset=start,
                        end_offset=end,
                        text=text[start:end],
                        section_path=segment.section_path,
                        block_type=block_type,
                    )
                )

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
                current = [piece]
                continue

            if self._requires_section_break(current, piece):
                chunks.append(self._build_chunk(index=len(chunks), pieces=current,))
                # Structural boundaries should not inherit lexical overlap from the previous section.
                current = [piece]
                continue

            projected_size = self._rendered_size([*current, piece])
            if projected_size <= self._config.target_chars:
                current.append(piece)
                continue

            if projected_size <= self._config.max_chars:
                current_size = self._rendered_size(current)
                # Prefer ending at an existing semantic piece boundary once
                # the current chunk has reached a useful minimum size.
                if current_size >= self._config.min_chunk_chars:
                    chunks.append(self._build_chunk(index=len(chunks), pieces=current))
                    current = self._build_overlap(current, required_section_path=piece.section_path)
                    current = self._fit_overlap_with_piece(overlap=current, incoming=piece)

                current.append(piece)
                continue

            # Hard bound would be exceeded.
            chunks.append(self._build_chunk(index=len(chunks), pieces=current))
            current = self._build_overlap(current, required_section_path=piece.section_path)
            current = self._fit_overlap_with_piece(overlap=current, incoming=piece)
            current.append(piece)

        if current:
            chunks.append(self._build_chunk(index=len(chunks), pieces=current))

        return chunks
    
    def _fit_overlap_with_piece(self, *, overlap: list[_SourcePiece], incoming: _SourcePiece) -> list[_SourcePiece]:
        fitted = list(overlap)
        while fitted and self._rendered_size([*fitted, incoming]) > self._config.max_chars:
            fitted.pop(0)

        return fitted

    def _requires_section_break(self, current: list[_SourcePiece], incoming: _SourcePiece) -> bool:
        if not self._config.preserve_section_boundaries:
            return False

        if not current:
            return False

        current_path = current[-1].section_path
        incoming_path = incoming.section_path
        if current_path == incoming_path:
            return False

        current_size = self._rendered_size(current)
        # A sufficiently substantial chunk should respect the new section.
        if current_size >= self._config.min_chunk_chars:
            return True

        # When small-section merging is disabled, preserve the boundary even
        # if that creates an undersized chunk.
        if not self._config.merge_small_sections:
            return True

        # Small neighboring sections may be merged only when they remain
        # structurally related.
        return not self._section_paths_are_related(current_path, incoming_path)
    
    def _section_paths_are_related(self, left: tuple[str, ...], right: tuple[str, ...]) -> bool:
        if not left or not right:
            return True

        common_depth = self._common_prefix_length(left, right)
        if common_depth == 0:
            return False

        left_distance = len(left) - common_depth
        right_distance = len(right) - common_depth
        structural_distance = max(left_distance, right_distance)

        return structural_distance <= self._config.max_section_depth_distance
    
    @staticmethod
    def _common_prefix_length(left: tuple[str, ...], right: tuple[str, ...]) -> int:
        shared = 0
        for left_part, right_part in zip(left, right):
            if left_part != right_part:
                break

            shared += 1

        return shared

    def _build_overlap(self, pieces: list[_SourcePiece], *, required_section_path: tuple[str, ...] | None = None) -> list[_SourcePiece]:
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
            
            if required_section_path is not None and piece.section_path != required_section_path:
                break

            if piece.char_count <= remaining:
                selected_reversed.append(piece)
                remaining -= piece.char_count
                continue

            relative_start = self._find_overlap_start(piece.text, desired_chars=remaining)
            if relative_start >= piece.char_count:
                break
            
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
    
    @staticmethod
    def _find_overlap_start(text: str, *, desired_chars: int) -> int:
        """
        Find a natural suffix boundary for overlap.

        Prefer:
            1. paragraph/newline boundary
            2. sentence boundary
            3. whitespace boundary

        Never intentionally begin in the middle of a word.
        """
        if desired_chars <= 0:
            return len(text)

        naive_start = max(0, len(text) - desired_chars)
        if naive_start == 0:
            return 0

        # Prefer the first paragraph boundary after the approximate start.
        newline = text.find("\n", naive_start)
        if newline != -1 and newline + 1 < len(text):
            candidate = newline + 1
            while candidate < len(text) and text[candidate].isspace():
                candidate += 1

            if candidate < len(text):
                return candidate

        sentence_endings = {".", "!", "?", "。", "！", "？", "।", }
        
        for index in range(naive_start, len(text) - 1):
            if text[index] in sentence_endings and text[index + 1].isspace():
                candidate = index + 1

                while candidate < len(text) and text[candidate].isspace():
                    candidate += 1

                if candidate < len(text):
                    return candidate

        for index in range(naive_start, len(text)):
            if text[index].isspace():
                candidate = index + 1

                while candidate < len(text) and text[candidate].isspace():
                    candidate += 1

                if candidate < len(text):
                    return candidate

        # A single extremely long token may have no natural boundary.
        # In that pathological case, omit partial overlap rather than
        # manufacture malformed lexical content.
        return len(text)

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
        
        section_paths = self._ordered_unique_section_paths(piece.section_path for piece in pieces if piece.section_path)

        block_types = self._ordered_unique_strings(piece.block_type for piece in pieces if piece.block_type is not None)

        return ChunkCandidate(
            index=index,
            text=text,
            source_spans=spans,
            section_path=section_path,
            metadata={
                "char_count": len(text),
                "source_piece_count": len(pieces),
                "section_paths": [list(path) for path in section_paths],
                "block_types": list(block_types),
            },
        )
        
    @staticmethod
    def _ordered_unique_section_paths(paths: Iterable[tuple[str, ...]]) -> tuple[tuple[str, ...], ...]:
        result: list[tuple[str, ...]] = []
        seen: set[tuple[str, ...]] = set()

        for path in paths:
            if path in seen:
                continue

            seen.add(path)
            result.append(path)

        return tuple(result)


    @staticmethod
    def _ordered_unique_strings(values: Iterable[str]) -> tuple[str, ...]:
        result: list[str] = []
        seen: set[str] = set()

        for value in values:
            if value in seen:
                continue

            seen.add(value)
            result.append(value)

        return tuple(result)

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
                
            if chunk.section_title is not None and chunk.text.strip() == chunk.section_title.strip():
                raise KnowledgeChunkerOutputError(
                    "Chunk contains section heading without semantic body content.",
                    chunker_name=self.descriptor.strategy_id,
                    version_id=document.version_id,
                    chunk_index=chunk.index,
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