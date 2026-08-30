from __future__ import annotations
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Iterable
from markdown_it import MarkdownIt
from markdown_it.token import Token

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.models import ParsedDocument, ParsedSegment
from packages.knowledge.ingestion.normalization.base import BaseDocumentNormalizer, NormalizerDescriptor
from packages.knowledge.ingestion.normalization.errors import InvalidNormalizedDocumentError, KnowledgeNormalizationExecutionError, KnowledgeNormalizerOutputError
from packages.knowledge.ingestion.normalization.models import NormalizedDocument, NormalizedSegment


@dataclass(frozen=True, slots=True)
class MarkdownNormalizerConfig:
    """
    Output-affecting configuration for Markdown normalization.

    Any option added here that can change normalized output must participate in the configuration fingerprint.
    """
    preserve_code_blocks: bool = True
    preserve_inline_code: bool = True
    include_link_destinations: bool = False
    include_image_destinations: bool = False
    preserve_table_structure: bool = True
    collapse_internal_whitespace: bool = True
    max_consecutive_newlines: int = 2
    preserve_list_markers: bool = True

    def __post_init__(self) -> None:
        boolean_fields = (
            "preserve_code_blocks",
            "preserve_inline_code",
            "include_link_destinations",
            "include_image_destinations",
            "preserve_table_structure",
            "collapse_internal_whitespace",
            "preserve_list_markers",
        )

        for field_name in boolean_fields:
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a boolean.")

        if not isinstance(self.max_consecutive_newlines, int):
            raise TypeError("max_consecutive_newlines must be an integer.")

        if self.max_consecutive_newlines < 1:
            raise ValueError("max_consecutive_newlines must be greater than zero.")

    def fingerprint(self) -> str:
        """
        Deterministic fingerprint for output-affecting configuration.

        Canonical JSON avoids dependence on dictionary ordering.
        """
        canonical = json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        return f"sha256:{digest}"


class _HTMLTextExtractor(HTMLParser):
    """
    Conservative HTML-to-text extractor.

    It never executes HTML and does not attempt browser rendering.
    Its only responsibility is recovering visible textual content from embedded HTML fragments.
    """
    _BLOCK_TAGS = frozenset({
        "address", "article", "aside", "blockquote", "br", "div", "dl", "dt", "dd", "figcaption", "figure",
        "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
        "section","table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul"
    })

    _IGNORED_CONTENT_TAGS = frozenset({"script", "style", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in self._IGNORED_CONTENT_TAGS:
            self._ignored_depth += 1
            return

        if self._ignored_depth == 0 and normalized_tag in self._BLOCK_TAGS:
            self._append_boundary()

    def handle_startendtag(self, tag: str, attrs) -> None:
        normalized_tag = tag.lower()

        if self._ignored_depth == 0 and normalized_tag in self._BLOCK_TAGS:
            self._append_boundary()

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in self._IGNORED_CONTENT_TAGS:
            if self._ignored_depth > 0:
                self._ignored_depth -= 1
            return

        if self._ignored_depth == 0 and normalized_tag in self._BLOCK_TAGS:
            self._append_boundary()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._ignored_depth == 0:
            self._parts.append(unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        if self._ignored_depth == 0:
            self._parts.append(unescape(f"&#{name};"))

    def _append_boundary(self) -> None:
        if not self._parts or self._parts[-1] != "\n":
            self._parts.append("\n")

    def text(self) -> str:
        return "".join(self._parts)

class MarkdownNormalizer(BaseDocumentNormalizer):
    """
    Semantic Markdown normalizer.

    Converts source-faithful ParsedSegments into retrieval-oriented
    text while retaining structural provenance.

    Responsibilities:
      - remove Markdown presentation syntax
      - retain semantic text
      - retain code where configured
      - retain heading/list/table/blockquote content
      - resolve Markdown escapes/entities through the parser
      - safely extract visible text from embedded HTML
      - preserve segment ordering and section paths
      - preserve parser provenance
      - record normalization provenance
    """
    _STRATEGY_ID = "markdown-semantic"
    _VERSION = "1.1.0"
    _SUPPORTED_SOURCE_TYPES = frozenset({KnowledgeSourceType.MARKDOWN})

    _HORIZONTAL_WHITESPACE = re.compile(r"[^\S\r\n]+")
    _SPACE_BEFORE_NEWLINE = re.compile(r"[ \t]+\n")
    _SPACE_AFTER_NEWLINE = re.compile(r"\n[ \t]+")

    def __init__(self, config: MarkdownNormalizerConfig | None = None) -> None:
        self._config = config if config is not None else MarkdownNormalizerConfig()
        self._markdown = self._create_markdown_engine()
        self._descriptor = NormalizerDescriptor(
            strategy_id=self._STRATEGY_ID,
            version=self._VERSION,
            config_fingerprint=self._config.fingerprint(),
        )

    @property
    def config(self) -> MarkdownNormalizerConfig:
        return self._config

    @property
    def descriptor(self) -> NormalizerDescriptor:
        return self._descriptor

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        return self._SUPPORTED_SOURCE_TYPES

    def normalize(self, document: ParsedDocument) -> NormalizedDocument:
        self._validate_document(document)
        normalized_segments: list[NormalizedSegment] = []

        for parsed_segment in document.segments:
            try:
                normalized = self._normalize_segment(parsed_segment)
            except (InvalidNormalizedDocumentError, KnowledgeNormalizerOutputError,):
                raise
            except Exception as exc:
                raise KnowledgeNormalizationExecutionError(
                    f"Markdown normalization failed for parsed segment {parsed_segment.index}.",
                    normalizer_name=self.descriptor.strategy_id,
                    source_segment_index=parsed_segment.index,
                ) from exc

            if not normalized.strip():
                # A source-backed structural segment may legitimately contain no retrieval-worthy lexical content after normalization.
                #
                # Do not restore the original Markdown syntax here because doing so would undo normalization decisions.
                continue
            
            if not normalized:
                raise KnowledgeNormalizerOutputError(
                    "Markdown normalizer produced no normalized segments.",
                    normalizer_name=self.descriptor.strategy_id,
                    # source_segment_index=parsed_segment.index,
                )

            normalized_segments.append(
                NormalizedSegment(
                    index=len(normalized_segments),
                    source_segment_index=parsed_segment.index,
                    text=normalized,
                    section_path=parsed_segment.section_path,
                    metadata=self._build_segment_metadata(parsed_segment),
                )
            )

        if not normalized_segments:
            raise KnowledgeNormalizerOutputError(
                "Markdown normalizer produced no normalized segments.",
                normalizer_name=self.descriptor.strategy_id
            )

        return NormalizedDocument(
            version_id=document.version_id,
            source_type=document.source_type,
            segments=tuple(normalized_segments),
            source_parser_strategy_id=document.parser_strategy_id,
            source_parser_version=document.parser_version,
            source_parser_config_fingerprint=document.parser_config_fingerprint,
            normalizer_strategy_id=self.descriptor.strategy_id,
            normalizer_version=self.descriptor.version,
            normalizer_config_fingerprint=self.descriptor.config_fingerprint,
            metadata={
                **dict(document.metadata),
                "normalized_from": document.parser_identity,
            },
        )

    @staticmethod
    def _create_markdown_engine() -> MarkdownIt:
        markdown = MarkdownIt("commonmark", {"html": True, "breaks": False, "typographer": False})
        markdown.enable("table")
        markdown.enable("strikethrough")

        return markdown

    def _validate_document(self, document: ParsedDocument) -> None:
        if not isinstance(document, ParsedDocument):
            raise TypeError("document must be a ParsedDocument.")

        if not self.supports(document.source_type):
            raise InvalidNormalizedDocumentError(
                f"MarkdownNormalizer cannot normalize source type '{document.source_type.value}'.",
                normalizer_name=self.descriptor.strategy_id,
                source_type=document.source_type.value,
            )

        if not document.segments:
            # ParsedDocument currently protects this invariant but this boundary remains defensive.
            raise InvalidNormalizedDocumentError(
                "Parsed document must contain at least one segment.",
                normalizer_name=self.descriptor.strategy_id
            )

    def _normalize_segment(self, segment: ParsedSegment) -> str:
        tokens = self._markdown.parse(segment.text)
        rendered = self._render_tokens(tokens)

        return self._cleanup_text(rendered)

    def _render_tokens(self, tokens: Iterable[Token]) -> str:
        token_list = tuple(tokens)
        parts: list[str] = []
        ordered_stack: list[int | None] = []
        index = 0

        while index < len(token_list):
            token = token_list[index]
            token_type = token.type
            if token_type == "inline":
                parts.append(self._render_inline_tokens(token.children or []))

            elif token_type == "fence":
                parts.append(self._render_code_block(token))

            elif token_type == "code_block":
                parts.append(self._render_code_block(token))

            elif token_type == "html_block":
                parts.append(self._extract_html_text(token.content))

            elif token_type == "hr":
                # A thematic break carries structure, but no useful lexical content.
                # If this is the only token, the loss-resistant fallback later preserves source.
                parts.append("\n")

            elif token_type == "softbreak":
                parts.append("\n")

            elif token_type == "hardbreak":
                parts.append("\n")

            elif token_type == "table_open":
                parts.append("\n")

            elif token_type in {"tr_open", "tr_close"}:
                parts.append("\n")

            elif token_type in {"th_close", "td_close"}:
                if self._config.preserve_table_structure:
                    parts.append(" | ")
                else:
                    parts.append(" ")

            elif token_type in {"paragraph_close", "heading_close", "blockquote_close", "list_item_close"}:
                parts.append("\n")
                
            elif token_type == "bullet_list_open":
                ordered_stack.append(None)

            elif token_type == "ordered_list_open":
                start = token.attrGet("start")
                ordered_stack.append(int(start) if start is not None else 1)

            elif token_type in {"bullet_list_close", "ordered_list_close"}:
                if ordered_stack:
                    ordered_stack.pop()

            elif token_type == "list_item_open":
                if self._config.preserve_list_markers and ordered_stack:
                    marker = ordered_stack[-1]

                    if marker is None:
                        parts.append("- ")
                    else:
                        parts.append(f"{marker}. ")
                        ordered_stack[-1] = marker + 1

            index += 1

        return "".join(parts)

    def _render_inline_tokens(self, tokens: Iterable[Token]) -> str:
        token_list = tuple(tokens)
        parts: list[str] = []
        index = 0

        while index < len(token_list):
            token = token_list[index]
            token_type = token.type
            if token_type == "text":
                parts.append(token.content)

            elif token_type == "code_inline" and self._config.preserve_inline_code:
                parts.append(token.content)

            elif token_type in {"softbreak", "hardbreak"}:
                parts.append("\n")

            elif token_type == "html_inline":
                parts.append(self._extract_html_text(token.content))

            elif token_type == "image":
                alt_text = self._extract_image_alt_text(token)
                destination = token.attrGet("src")
                if alt_text:
                    parts.append(alt_text)

                if self._config.include_image_destinations and destination:
                    if alt_text:
                        parts.append(" ")

                    parts.append(f"({destination})")

            elif token_type == "link_open":
                # Link label is emitted by subsequent inline tokens.
                # Destination, if requested, is appended at link_close.
                pass

            elif token_type == "link_close":
                if self._config.include_link_destinations:
                    destination = self._find_link_destination(token_list, index)
                    if destination:
                        parts.append(f" ({destination})")

            elif token.children:
                parts.append(self._render_inline_tokens(token.children))

            # Formatting-only tokens such as: strong_open, strong_close, em_open, em_close, s_open, s_close
            # intentionally contribute no syntax characters.
            index += 1

        return "".join(parts)

    def _render_code_block(self, token: Token) -> str:
        if not self._config.preserve_code_blocks:
            return ""

        content = token.content.rstrip()
        if not content:
            return ""

        return f"\n{content}\n"

    @staticmethod
    def _extract_image_alt_text(token: Token) -> str:
        if token.children:
            parts: list[str] = []

            for child in token.children:
                if child.type == "text":
                    parts.append(child.content)
                elif child.content:
                    parts.append(child.content)

            alt = "".join(parts).strip()
            if alt:
                return alt
            
        return token.content.strip()

    @staticmethod
    def _find_link_destination(tokens: tuple[Token, ...], closing_index: int) -> str | None:
        """
        Locate the matching link_open for the current link_close.

        Handles nested inline formatting inside link labels.
        """
        depth = 0
        for index in range(closing_index - 1, -1, -1):
            token = tokens[index]
            if token.type == "link_close":
                depth += 1
                continue

            if token.type != "link_open":
                continue

            if depth:
                depth -= 1
                continue

            href = token.attrGet("href")

            return href.strip() if href else None

        return None

    @staticmethod
    def _extract_html_text(html: str) -> str:
        if not html:
            return ""

        parser = _HTMLTextExtractor()

        try:
            parser.feed(html)
            parser.close()
        except Exception:
            #
            # HTML embedded in Markdown is frequently malformed.
            # Failure to interpret embedded HTML should not make an
            # otherwise useful knowledge document un-ingestable.
            #
            # Return raw textual content; downstream cleanup and the
            # loss-resistant fallback keep us from silently deleting
            # data.
            #
            return html

        return parser.text()

    def _cleanup_text(
        self,
        text: str,
    ) -> str:
        if not text:
            return ""

        #
        # Normalize transport-level line endings first.
        #
        normalized = (
            text.replace(
                "\r\n",
                "\n",
            )
            .replace(
                "\r",
                "\n",
            )
        )

        #
        # Decode ordinary HTML entities that may survive parsing.
        #
        normalized = unescape(
            normalized
        )

        if (
            self._config
            .collapse_internal_whitespace
        ):
            normalized = (
                self._HORIZONTAL_WHITESPACE
                .sub(
                    " ",
                    normalized,
                )
            )

            normalized = (
                self._SPACE_BEFORE_NEWLINE
                .sub(
                    "\n",
                    normalized,
                )
            )

            normalized = (
                self._SPACE_AFTER_NEWLINE
                .sub(
                    "\n",
                    normalized,
                )
            )

        max_newlines = (
            self._config
            .max_consecutive_newlines
        )

        normalized = re.sub(
            rf"\n{{{max_newlines + 1},}}",
            "\n" * max_newlines,
            normalized,
        )

        return normalized.strip()

    @staticmethod
    def _build_segment_metadata(
        segment: ParsedSegment,
    ) -> dict[str, object]:
        """
        Carry useful structural metadata forward without mutating
        upstream metadata or pretending offsets still apply to
        normalized text.

        Parsed offsets refer to original source text and therefore are
        provenance metadata, not offsets into normalized text.
        """

        metadata = dict(
            segment.metadata
        )

        if (
            segment.start_offset
            is not None
        ):
            metadata[
                "source_start_offset"
            ] = segment.start_offset

        if (
            segment.end_offset
            is not None
        ):
            metadata[
                "source_end_offset"
            ] = segment.end_offset

        if (
            segment.page_number
            is not None
        ):
            metadata[
                "source_page_number"
            ] = segment.page_number

        return metadata