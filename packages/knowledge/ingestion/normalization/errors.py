from __future__ import annotations
from typing import Any

from packages.knowledge.domain.enums import KnowledgeSourceType


class KnowledgeNormalizationError(Exception):
    code = "KNOWLEDGE_NORMALIZATION_ERROR"

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = dict(context)

    def __str__(self) -> str:
        return self.message

class KnowledgeNormalizerConfigurationError(KnowledgeNormalizationError):
    code = "KNOWLEDGE_NORMALIZER_CONFIGURATION_ERROR"

    def __init__(self, message: str, *, normalizer_name: str | None = None, source_type: KnowledgeSourceType | None = None) -> None:
        context: dict[str, Any] = {}

        if normalizer_name is not None:
            context["normalizer_name"] = normalizer_name

        if source_type is not None:
            context["source_type"] = source_type.value

        super().__init__(message, **context)
        self.normalizer_name = normalizer_name
        self.source_type = source_type

class UnsupportedKnowledgeNormalizationSourceTypeError(KnowledgeNormalizationError):
    code = "KNOWLEDGE_NORMALIZATION_SOURCE_TYPE_UNSUPPORTED"

    def __init__(self, source_type: KnowledgeSourceType) -> None:
        super().__init__(f"No active normalizer is configured for source type '{source_type.value}'.", source_type=source_type.value)
        self.source_type = source_type

class InvalidNormalizedDocumentError(KnowledgeNormalizationError):
    code = "KNOWLEDGE_NORMALIZED_DOCUMENT_INVALID"

class KnowledgeNormalizationExecutionError(KnowledgeNormalizationError):
    code = "KNOWLEDGE_NORMALIZATION_EXECUTION_ERROR"

class KnowledgeNormalizerOutputError(KnowledgeNormalizationError):
    code = "KNOWLEDGE_NORMALIZER_OUTPUT_ERROR"