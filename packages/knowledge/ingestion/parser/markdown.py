from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from markdown_it import MarkdownIt
from markdown_it.token import Token

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.errors import InvalidKnowledgeSourceError, KnowledgeParserExecutionError, KnowledgeParserOutputError, UnsupportedKnowledgeSourceTypeError
from packages.knowledge.ingestion.models import IngestionSource, ParsedDocument, ParsedSegment
from packages.knowledge.ingestion.parser.base import BaseDocumentParser, ParserDescriptor


@dataclass(frozen=True, slots=True)
class _LineIndex:
    """
    Maps Markdown parser line numbers to character offsets in the
    original source.

    markdown-it uses zero-based line ranges while ParsedSegment keeps
    source character offsets.
    """
    starts: tuple[int, ...]
    source_length: int
    
    @classmethod
    def build(cls, content: str) -> "_LineIndex":
        starts = [0]
        for index, character in enumerate(content):
            if character == "\n":
                starts.append(index + 1)

        return cls(starts=tuple(starts), source_length=len(content))

    def offset_for_line(self, line_number: int) -> int:
        if line_number < 0:
            raise ValueError("line_number must be non-negative.")

        if line_number >= len(self.starts):
            return self.source_length

        return self.starts[line_number]

    def span_for_lines(self, start_line: int, end_line: int) -> tuple[int, int]:
        """
        Convert markdown-it's half-open line range:

            [start_line, end_line)

        into a half-open character range.
        """
        if start_line < 0:
            raise ValueError("start_line must be non-negative.")

        if end_line < start_line:
            raise ValueError("end_line must not precede start_line.")

        return (self.offset_for_line(start_line), self.offset_for_line(end_line),)

@dataclass(frozen=True, slots=True)
class _StructuralBlock:
    """
    Internal representation of one source-backed Markdown block.

    This is intentionally not a KnowledgeChunk. It represents source structure discovered during parsing.
    """
    start_line: int
    end_line: int
    section_path: tuple[str, ...]
    block_type: str


class MarkdownStructuralParser(BaseDocumentParser):
    """
    Structure-preserving Markdown parser.

    The parser understands Markdown syntax and converts source-backed
    block structure into ParsedSegments.

    Responsibilities:
    - parse CommonMark/GFM-style Markdown structure
    - recognize heading hierarchy
    - preserve section paths
    - preserve original source order
    - preserve exact source spans
    - preserve Markdown source rather than rendering to plain text
    - expose block-level metadata
    - attach parser provenance
    """
    _DESCRIPTOR = ParserDescriptor(strategy_id="markdown-structural", version="1.0.0", config_fingerprint=None)
    _SUPPORTED_SOURCE_TYPES = frozenset({KnowledgeSourceType.MARKDOWN,})

    def __init__(self) -> None:
        self._markdown = self._create_markdown_engine()

    @property
    def descriptor(self) -> ParserDescriptor:
        return self._DESCRIPTOR

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        return self._SUPPORTED_SOURCE_TYPES

    def parse(self, source: IngestionSource) -> ParsedDocument:
        self._validate_source(source)
        try:
            tokens = self._markdown.parse(source.content)
        except Exception as exc:
            # markdown-it is the adapter boundary here.
            # Library failures are translated into our ingestion
            # exception hierarchy while retaining the root cause.
            raise KnowledgeParserExecutionError(
                "Markdown parser failed while parsing source.",
                parser_name=self.descriptor.strategy_id
            ) from exc

        blocks = tuple(self._extract_structural_blocks(tokens))
        segments = self._build_segments(content=source.content, blocks=blocks)
        if not segments:
            raise KnowledgeParserOutputError(
                "Markdown parser produced no source-backed segments.",
                parser_name=self.descriptor.strategy_id
            )

        descriptor = self.descriptor

        return ParsedDocument(
            version_id=source.version_id,
            source_type=source.source_type,
            segments=segments,
            parser_strategy_id=descriptor.strategy_id,
            parser_version=descriptor.version,
            parser_config_fingerprint=descriptor.config_fingerprint,
            metadata={
                "source_type": source.source_type.value,
                "segment_count": len(segments),
            },
        )

    @staticmethod
    def _create_markdown_engine() -> MarkdownIt:
        """
        Configure the syntax engine.

        commonmark gives us predictable standards-compliant behavior.

        Table and strikethrough rules are enabled because they are common in GitHub-style documentation and knowledge bases.

        Lists, blockquotes, fenced code, indented code, inline code, links, images, HTML,
        ATX headings and Setext headings are already understood by markdown-it.
        """
        markdown = MarkdownIt(
            "commonmark",
            {
                "html": True,
                "breaks": False,
                "typographer": False,
            },
        )

        markdown.enable("table")
        markdown.enable("strikethrough")

        return markdown

    def _validate_source(self, source: IngestionSource) -> None:
        if not isinstance(source, IngestionSource):
            raise TypeError("source must be an IngestionSource.")

        if not self.supports(source.source_type):
            raise UnsupportedKnowledgeSourceTypeError(source.source_type)

        if not source.content.strip():
            raise InvalidKnowledgeSourceError("Markdown source content must not be blank.")

    def _extract_structural_blocks(self, tokens: Iterable[Token]) -> Iterable[_StructuralBlock]:
        """
        Walk top-level Markdown tokens and derive source-backed blocks.

        markdown-it exposes `Token.map` as:

            [start_line, end_line]

        using a half-open line range.

        Heading tokens update the section hierarchy. They are also
        emitted as structural blocks so no source content disappears.
        """
        token_list = tuple(tokens)
        section_stack: list[str] = []
        index = 0
        while index < len(token_list):
            token = token_list[index]
            if token.type == "heading_open" and token.map is not None:
                heading_level = self._heading_level(token)
                heading_text = self._extract_heading_text(token_list, index)
                section_stack = self._update_section_stack(section_stack, heading_level, heading_text)

                yield _StructuralBlock(
                    start_line=token.map[0],
                    end_line=token.map[1],
                    section_path=tuple(section_stack),
                    block_type="heading",
                )

                index += 1
                continue

            if self._is_source_backed_block(token):
                yield _StructuralBlock(
                    start_line=token.map[0],
                    end_line=token.map[1],
                    section_path=tuple(section_stack),
                    block_type=self._canonical_block_type(token)
                )

            index += 1

    @staticmethod
    def _heading_level(token: Token) -> int:
        tag = token.tag
        if len(tag) != 2 or not tag.startswith("h") or not tag[1].isdigit():
            raise KnowledgeParserOutputError("Markdown parser produced an invalid heading token.")

        level = int(tag[1])
        if not 1 <= level <= 6:
            raise KnowledgeParserOutputError("Markdown heading level must be between 1 and 6.")

        return level

    @staticmethod
    def _extract_heading_text(tokens: tuple[Token, ...], heading_index: int) -> str:
        """
        Heading textual content normally lives in the inline token immediately after heading_open.

        `.content` gives semantic heading text without requiring us to manually parse emphasis, links, code spans, etc.
        """
        inline_index = heading_index + 1
        if inline_index >= len(tokens):
            return ""

        inline_token = tokens[inline_index]
        if inline_token.type != "inline":
            return ""

        return inline_token.content.strip()

    @staticmethod
    def _update_section_stack(current: list[str], heading_level: int, heading_text: str) -> list[str]:
        """
        Maintain heading hierarchy while handling imperfect Markdown.

        Markdown authors frequently skip heading levels:

            # Root
            ### Details

        We must not reject such documents.

        Instead, section_path represents the hierarchy that actually exists rather than inventing missing H2 headings.
        """
        normalized_heading = (heading_text.strip() or f"Untitled H{heading_level}")
        target_depth = heading_level
        new_stack = list(current[: target_depth - 1])
        new_stack.append(normalized_heading)

        return new_stack

    @staticmethod
    def _is_source_backed_block(token: Token) -> bool:
        """
        Only tokens with real source line ranges may become segments.

        Closing tokens and inline helper tokens typically have no map.

        Containers such as blockquote/list are excluded because their
        child blocks carry the same source ranges more precisely.
        Including both would duplicate source content.
        """

        if token.map is None:
            return False

        excluded_types = {
            "heading_open",
            "blockquote_open",
            "bullet_list_open",
            "ordered_list_open",
            "list_item_open",
        }

        return token.type not in excluded_types

    @staticmethod
    def _canonical_block_type(token: Token, ) -> str:
        """
        Convert markdown-it token names into stable parser metadata.

        Do not expose every library-specific token name downstream.
        """
        mapping = {
            "paragraph_open": "paragraph",
            "fence": "fenced_code",
            "code_block": "indented_code",
            "html_block": "html",
            "hr": "thematic_break",
            "table_open": "table",
        }

        return mapping.get(token.type, token.type)

    def _build_segments(self, *, content: str, blocks: tuple[_StructuralBlock, ...]) -> tuple[ParsedSegment, ...]:
        """
        Convert structural line ranges into non-overlapping
        source-backed ParsedSegments.
        """
        line_index = _LineIndex.build(content)
        candidates: list[tuple[int,int,_StructuralBlock,]] = []

        for block in blocks:
            start, end = line_index.span_for_lines(block.start_line, block.end_line)
            start, end = self._trim_span(content, start, end)
            if start >= end:
                continue

            candidates.append((start, end, block,))

        candidates.sort(key=lambda item: (item[0], item[1],))
        selected = self._remove_overlapping_blocks(candidates)
        segments: list[ParsedSegment] = []

        for (start, end, block) in selected:
            text = content[start:end]
            if not text.strip():
                continue

            segments.append(
                ParsedSegment(
                    index=len(segments),
                    text=text,
                    section_path=block.section_path,
                    start_offset=start,
                    end_offset=end,
                    metadata={
                        "markdown_block_type": block.block_type,
                        "start_line": block.start_line + 1,
                        "end_line": block.end_line,
                    },
                )
            )

        return tuple(segments)

    @staticmethod
    def _trim_span(content: str, start: int, end: int) -> tuple[int, int]:
        """
        Remove only surrounding whitespace from a source block while preserving exact source offsets.

        Internal Markdown formatting is untouched.
        """

        raw = content[start:end]
        if not raw:
            return start, end

        left_trimmed = raw.lstrip()
        leading = len(raw) - len(left_trimmed)

        fully_trimmed = left_trimmed.rstrip()
        trailing = len(left_trimmed) - len(fully_trimmed)

        return (start + leading, end - trailing,)

    @staticmethod
    def _remove_overlapping_blocks(candidates: list[tuple[int, int, _StructuralBlock]]) -> tuple[tuple[int, int, _StructuralBlock], ...]:
        """
        markdown-it emits both structural containers and nested blocks.

        We intentionally produce non-overlapping ParsedSegments.

        If two candidates represent exactly the same source span, prefer the more 
        semantically useful block according to a small deterministic priority table.

        Nested/overlapping duplicate ranges are otherwise discarded once a more specific earlier range has been accepted.
        """
        if not candidates:
            return ()

        priority = {
            "heading": 100,
            "fenced_code": 90,
            "indented_code": 90,
            "table": 85,
            "html": 80,
            "paragraph": 70,
            "thematic_break": 60,
        }

        grouped: dict[tuple[int, int], tuple[int, int, _StructuralBlock]] = {}

        for candidate in candidates:
            start, end, block = candidate
            key = (start, end)
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = candidate
                continue

            existing_block = existing[2]
            if priority.get(block.block_type, 0) > priority.get(existing_block.block_type, 0):
                grouped[key] = candidate

        unique = sorted(grouped.values(), key=lambda item: (item[0],item[1],))
        result: list[tuple[int, int, _StructuralBlock]] = []
        last_end = -1

        for candidate in unique:
            start, end, _ = candidate
            if start < last_end:
                continue

            result.append(candidate)
            last_end = end

        return tuple(result)