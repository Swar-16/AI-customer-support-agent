from __future__ import annotations

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.errors import InvalidKnowledgeSourceError, KnowledgeParserOutputError, UnsupportedKnowledgeSourceTypeError
from packages.knowledge.ingestion.models import IngestionSource, ParsedDocument, ParsedSegment
from packages.knowledge.ingestion.parser.base import BaseDocumentParser, ParserDescriptor


class PlainTextStructuralParser(BaseDocumentParser):
    """
    Structure-preserving parser for plain-text knowledge sources.

    Responsibilities:
    - validate that the source is plain text
    - preserve source ordering
    - split text into paragraph-like structural segments
    - preserve exact source offsets
    - attach parser provenance

    Non-responsibilities:
    - semantic normalization
    - retrieval chunking
    - token-budget splitting
    - embeddings
    - document classification
    """
    _DESCRIPTOR = ParserDescriptor(strategy_id="plain-text-structural", version="1.0.0")
    _SUPPORTED_SOURCE_TYPES = frozenset({KnowledgeSourceType.PLAIN_TEXT,})

    @property
    def descriptor(self) -> ParserDescriptor:
        return self._DESCRIPTOR

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        return self._SUPPORTED_SOURCE_TYPES

    def parse(self, source: IngestionSource) -> ParsedDocument:
        self._validate_source(source)
        segments = tuple(self._extract_segments(source.content))
        if not segments:
            raise KnowledgeParserOutputError("Plain-text parser produced no segments.", parser_name=self.descriptor.strategy_id)
        
        descriptor = self.descriptor

        return ParsedDocument(
            version_id=source.version_id,
            source_type=source.source_type,
            segments=segments,
            parser_strategy_id=descriptor.strategy_id,
            parser_version=descriptor.version,
            parser_config_fingerprint=descriptor.config_fingerprint,
            metadata={ "source_type": source.source_type.value, },
        )

    def _validate_source(self, source: IngestionSource) -> None:
        if not isinstance(source, IngestionSource):
            raise TypeError("source must be an IngestionSource.")

        if not self.supports(source.source_type):
            raise UnsupportedKnowledgeSourceTypeError(source.source_type)

        # IngestionSource should already enforce this invariant,
        # but keeping the parser boundary defensive is useful.
        if not source.content.strip():
            raise InvalidKnowledgeSourceError("Plain-text source content must not be blank.")

    @staticmethod
    def _extract_segments(content: str):
        """
        Yield paragraph-like ParsedSegments.

        Blank lines delimit structural blocks.

        Offsets are half-open:
            content[start_offset:end_offset] == segment.text

        Leading/trailing whitespace surrounding each block is excluded
        from the recorded source span.
        """
        segment_index = 0
        block_start: int | None = None
        block_end: int | None = None
        offset = 0

        for line in content.splitlines(keepends=True):
            line_start = offset
            line_end = line_start + len(line)
            offset = line_end

            # Remove only newline characters when deciding whether the
            # line contains meaningful content.
            logical_line = line.rstrip("\r\n")
            if logical_line.strip():
                if block_start is None:
                    block_start = line_start

                block_end = line_end
                continue

            if block_start is not None and block_end is not None:
                segment = PlainTextStructuralParser._build_segment(
                    content=content,
                    segment_index=segment_index,
                    raw_start=block_start,
                    raw_end=block_end
                )

                if segment is not None:
                    yield segment
                    segment_index += 1

                block_start = None
                block_end = None

        # splitlines(keepends=True) handles most input, but the final
        # accumulated block still needs flushing.
        if block_start is not None and block_end is not None:
            segment = PlainTextStructuralParser._build_segment(
                content=content,
                segment_index=segment_index,
                raw_start=block_start,
                raw_end=block_end,
            )

            if segment is not None:
                yield segment

    @staticmethod
    def _build_segment(*, content: str, segment_index: int, raw_start: int, raw_end: int) -> ParsedSegment | None:
        """
        Trim whitespace around a structural block while keeping offsets
        exactly aligned with the returned text.
        """
        raw_text = content[raw_start:raw_end]
        if not raw_text.strip():
            return None

        left_trimmed = raw_text.lstrip()
        leading_trim = len(raw_text) - len(left_trimmed)
        trimmed_text = left_trimmed.rstrip()
        trailing_trim = len(left_trimmed) - len(trimmed_text)
        start_offset = raw_start + leading_trim
        end_offset = raw_end - trailing_trim

        return ParsedSegment(
            index=segment_index,
            text=trimmed_text,
            start_offset=start_offset,
            end_offset=end_offset,
        )