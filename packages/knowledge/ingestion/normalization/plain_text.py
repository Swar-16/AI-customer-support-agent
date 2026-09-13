# AI-customer-support-agent\packages\knowledge\ingestion\normalization\plain_text.py
from __future__ import annotations

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.models import ParsedDocument, ParsedSegment
from packages.knowledge.ingestion.normalization.base import BaseDocumentNormalizer, NormalizerDescriptor
from packages.knowledge.ingestion.normalization.errors import InvalidNormalizedDocumentError, KnowledgeNormalizerOutputError
from packages.knowledge.ingestion.normalization.models import NormalizedDocument, NormalizedSegment

class PlainTextNormalizer(BaseDocumentNormalizer):
    """
    Normalize parsed plain-text segments for retrieval.

    Plain text contains no presentation syntax to remove. Normalization therefore preserves segment text
    while canonicalizing line endings and retaining source provenance.
    """
    _DESCRIPTOR = NormalizerDescriptor(
        strategy_id="plain-text-semantic",
        version="1.0.0",
        config_fingerprint=None,
    )
    _SUPPORTED_SOURCE_TYPES = frozenset({KnowledgeSourceType.PLAIN_TEXT,})

    @property
    def descriptor(self) -> NormalizerDescriptor:
        return self._DESCRIPTOR

    @property
    def supported_source_types(self) -> frozenset[KnowledgeSourceType]:
        return self._SUPPORTED_SOURCE_TYPES

    def normalize(self, document: ParsedDocument) -> NormalizedDocument:
        self._validate_document(document)
        normalized_segments: list[NormalizedSegment] = []

        for parsed_segment in document.segments:
            normalized_text = self._normalize_text(parsed_segment.text)
            if not normalized_text.strip():
                continue

            normalized_segments.append(
                NormalizedSegment(
                    index=len(normalized_segments),
                    source_segment_index=parsed_segment.index,
                    text=normalized_text,
                    section_path=parsed_segment.section_path,
                    metadata=self._build_segment_metadata(parsed_segment),
                )
            )

        if not normalized_segments:
            raise KnowledgeNormalizerOutputError(
                "Plain-text normalizer produced no normalized segments.",
                normalizer_name=self.descriptor.strategy_id,
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
                "normalized_segment_count": len(normalized_segments),
            },
        )

    def _validate_document(self, document: ParsedDocument) -> None:
        if not isinstance(document, ParsedDocument):
            raise TypeError("document must be a ParsedDocument.")

        if not self.supports(document.source_type):
            raise InvalidNormalizedDocumentError(
                f"PlainTextNormalizer cannot normalize source type '{document.source_type.value}'.",
                normalizer_name=self.descriptor.strategy_id,
                source_type=document.source_type.value,
            )

        if not document.segments:
            raise InvalidNormalizedDocumentError("Parsed document must contain at least one segment.", normalizer_name=self.descriptor.strategy_id)

    @staticmethod
    def _normalize_text(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("segment text must be a string.")

        # Produce stable ingestion output across Windows and Unix sources
        # without collapsing meaningful spaces or paragraph structure.
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()

    @staticmethod
    def _build_segment_metadata(segment: ParsedSegment) -> dict[str, object]:
        metadata: dict[str, object] = dict(segment.metadata)
        if segment.start_offset is not None:
            metadata["source_start_offset"] = segment.start_offset

        if segment.end_offset is not None:
            metadata["source_end_offset"] = segment.end_offset

        if segment.page_number is not None:
            metadata["source_page_number"] = segment.page_number

        metadata["source_segment_index"] = segment.index

        return metadata