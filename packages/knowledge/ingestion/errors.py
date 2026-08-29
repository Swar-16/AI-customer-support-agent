from __future__ import annotations
from typing import Any
from uuid import UUID

from packages.knowledge.domain.enums import KnowledgeSourceType


class KnowledgeIngestionError(Exception):
    """
    Base exception for failures that occur while transforming a knowledge
    document version into derived ingestion artifacts.

    These errors belong to the ingestion subsystem, not the domain model.

    Every ingestion error exposes:
        - a stable machine-readable code;
        - a human-readable message;
        - optional structured context.

    Application services may persist the code/message on a failed knowledge
    version without depending on parser-library-specific exceptions.
    """
    code = "KNOWLEDGE_INGESTION_ERROR"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = dict(context or {})

    def __str__(self) -> str:
        return self.message


# Source errors
class KnowledgeSourceError(KnowledgeIngestionError):
    """
    Base class for failures concerning the source supplied to ingestion.
    """
    code = "KNOWLEDGE_SOURCE_ERROR"

class UnsupportedKnowledgeSourceTypeError(KnowledgeSourceError):
    """
    Raised when no parser is configured for a particular source type.
    """
    code = "KNOWLEDGE_SOURCE_TYPE_UNSUPPORTED"

    def __init__(self, source_type: KnowledgeSourceType) -> None:
        self.source_type = source_type
        super().__init__(
            f"No document parser is configured for source type '{source_type.value}'.",
            context={ "source_type": source_type.value }
        )

class InvalidKnowledgeSourceError(KnowledgeSourceError):
    """
    Raised when the ingestion source itself is structurally invalid.

    Examples:
        - empty extracted source;
        - malformed source representation;
        - source metadata inconsistent with the parser contract.

    Domain-level validation should normally catch obvious version problems
    before ingestion begins. This exception covers ingestion-boundary
    validation failures.
    """
    code = "KNOWLEDGE_SOURCE_INVALID"

    def __init__(self, reason: str, *, version_id: UUID | None = None, source_type: KnowledgeSourceType | None = None) -> None:
        self.reason = reason
        self.version_id = version_id
        self.source_type = source_type

        context: dict[str, Any] = { "reason": reason, }

        if version_id is not None:
            context["version_id"] = str(version_id)

        if source_type is not None:
            context["source_type"] = source_type.value

        super().__init__(f"Knowledge source is invalid: {reason}", context=context)

# Parser resolution/configuration errors
class KnowledgeParserError(KnowledgeIngestionError):
    """
    Base class for document-parser-related failures.
    """
    code = "KNOWLEDGE_PARSER_ERROR"

class KnowledgeParserConfigurationError(KnowledgeParserError):
    """
    Raised when parser registration/configuration is internally inconsistent.

    This normally indicates a deployment or programming error rather than bad
    customer-authored knowledge.

    Examples:
        - two parsers registered for the same source type;
        - parser reports no supported source types;
        - malformed parser registration.
    """
    code = "KNOWLEDGE_PARSER_CONFIGURATION_ERROR"

    def __init__(self, reason: str, *, parser_name: str | None = None, source_type: KnowledgeSourceType | None = None) -> None:
        self.reason = reason
        self.parser_name = parser_name
        self.source_type = source_type
        context: dict[str, Any] = { "reason": reason, }

        if parser_name is not None:
            context["parser_name"] = parser_name

        if source_type is not None:
            context["source_type"] = source_type.value

        super().__init__(f"Document parser configuration is invalid: {reason}", context=context)

# Parser execution errors
class KnowledgeParsingError(KnowledgeParserError):
    """
    Base class for failures while actually parsing a document.
    """
    code = "KNOWLEDGE_PARSING_ERROR"

class KnowledgeParserExecutionError(KnowledgeParsingError):
    """
    Raised when a parser cannot successfully process its source.

    Concrete parser-library exceptions should normally be translated into
    this exception at the parser boundary so application code does not depend
    on PyMuPDF, python-docx, BeautifulSoup, etc.
    """
    code = "KNOWLEDGE_PARSER_EXECUTION_FAILED"

    def __init__(self, *, parser_name: str, parser_version: str, version_id: UUID, source_type: KnowledgeSourceType, reason: str) -> None:
        self.parser_name = parser_name
        self.parser_version = parser_version
        self.version_id = version_id
        self.source_type = source_type
        self.reason = reason
        super().__init__(
            f"Parser '{parser_name}' failed while processing knowledge version '{version_id}': {reason}",
            context={
                "parser_name": parser_name,
                "parser_version": parser_version,
                "version_id": str(version_id),
                "source_type": source_type.value,
                "reason": reason,
            },
        )

class KnowledgeParserOutputError(KnowledgeParsingError):
    """
    Raised when parser execution technically succeeds but produces an invalid
    ParsedDocument.

    Examples:
        - no segments;
        - non-contiguous segment indexes;
        - blank segment content;
        - version-id mismatch;
        - malformed structural metadata.
    """
    code = "KNOWLEDGE_PARSER_OUTPUT_INVALID"

    def __init__(self, reason: str, *, parser_name: str, version_id: UUID) -> None:
        self.reason = reason
        self.parser_name = parser_name
        self.version_id = version_id
        super().__init__(
            f"Parser '{parser_name}' produced invalid output for knowledge version '{version_id}': {reason}",
            context={
                "parser_name": parser_name,
                "version_id": str(version_id),
                "reason": reason,
            },
        )

class KnowledgeEmptyParsedDocumentError(KnowledgeParserOutputError):
    """
    Specific parser-output error for sources from which no useful textual
    content could be produced.

    This is intentionally distinct because empty output can later drive
    different operational behavior, metrics, or admin feedback.
    """
    code = "KNOWLEDGE_PARSED_DOCUMENT_EMPTY"

    def __init__(self, *, parser_name: str, version_id: UUID) -> None:
        self.parser_name = parser_name
        self.version_id = version_id
        self.reason = "No usable textual segments were produced."
        KnowledgeParsingError.__init__(
            self,
            f"Parser '{parser_name}' produced no usable textual content for knowledge version '{version_id}'.",
            context={
                "parser_name": parser_name,
                "version_id": str(version_id),
                "reason": self.reason,
            },
        )