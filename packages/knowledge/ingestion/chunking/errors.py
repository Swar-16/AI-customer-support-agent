from __future__ import annotations
from typing import Any, Mapping


class KnowledgeChunkingError(Exception):
    """
    Base exception for failures in the knowledge chunking layer.

    Chunking errors belong to ingestion/application boundaries and should remain independent of transport and persistence concerns.

    Attributes:
        code:
            Stable machine-readable error identifier.

        message:
            Human-readable explanation.

        context:
            Structured diagnostic information useful for telemetry, logging, application-layer translation, and tests.
    """
    code = "KNOWLEDGE_CHUNKING_ERROR"

    def __init__(self, message: str, **context: Any) -> None:
        if not isinstance(message, str):
            raise TypeError("message must be a string.")

        if not message.strip():
            raise ValueError("message must not be blank.")

        self.message = message
        self.context: Mapping[str, Any] = dict(context)
        super().__init__(message)

    def __str__(self) -> str:
        return self.message

class KnowledgeChunkerConfigurationError(KnowledgeChunkingError):
    """
    Raised when a chunker or chunker resolver has invalid composition or configuration.

    Examples:
        - duplicate source-type registrations
        - malformed chunker contract
        - empty supported-source-type declaration
        - inconsistent supports(...) behavior
        - invalid concrete chunker configuration

    This generally represents a programming or deployment configuration problem rather than malformed knowledge content.
    """
    code = "KNOWLEDGE_CHUNKER_CONFIGURATION_ERROR"

    def __init__(self, message: str, *, chunker_name: str | None = None, source_type: Any | None = None, **context: Any) -> None:
        if chunker_name is not None:
            context.setdefault("chunker_name", chunker_name)

        if source_type is not None:
            normalized_source_type = getattr(source_type, "value", source_type)
            context.setdefault("source_type", normalized_source_type)

        self.chunker_name = chunker_name
        self.source_type = source_type
        super().__init__(message, **context)

class UnsupportedKnowledgeChunkingSourceTypeError(KnowledgeChunkingError):
    """
    Raised when no configured chunker supports the requested source type.
    """
    code = "KNOWLEDGE_CHUNKING_SOURCE_TYPE_UNSUPPORTED"
    
    def __init__(self, source_type: Any, *, available_source_types: tuple[str, ...] = ()) -> None:
        normalized_source_type = getattr(source_type, "value", source_type)
        message = f"No knowledge chunker is configured for source type '{normalized_source_type}'."
        self.source_type = source_type
        self.available_source_types = available_source_types
        context: dict[str, Any] = {"source_type": normalized_source_type}
        if available_source_types:
            context["available_source_types"] = available_source_types

        super().__init__(message, **context)

class InvalidChunkingInputError(KnowledgeChunkingError):
    """
    Raised when the object supplied to a chunker violates the chunking stage's input contract.

    Examples:
        - unsupported normalized source type
        - structurally inconsistent normalized artifact
        - provenance required by the chunker is missing

    Ordinary Python type misuse may still be represented by TypeError where appropriate.
    This exception is for validly typed ingestion artifacts that are semantically invalid for chunking.
    """
    code = "KNOWLEDGE_CHUNKING_INPUT_INVALID"

    def __init__(self, message: str, *, chunker_name: str | None = None,
                 version_id: Any | None = None, source_type: Any | None = None, **context: Any
    ) -> None:
        if chunker_name is not None:
            context.setdefault("chunker_name", chunker_name)

        if version_id is not None:
            context.setdefault("version_id", str(version_id))

        if source_type is not None:
            context.setdefault(
                "source_type",
                getattr(source_type, "value", source_type),
            )

        self.chunker_name = chunker_name
        self.version_id = version_id
        self.source_type = source_type
        super().__init__(message, **context)

class KnowledgeChunkingExecutionError(KnowledgeChunkingError):
    """
    Raised when a chunking strategy fails while processing otherwise acceptable input.

    Intended primarily as an exception-translation boundary around lower-level implementation failures 
    such as sentence segmentation or internal splitting logic.

    The original exception should be retained via exception chaining:

        raise KnowledgeChunkingExecutionError(...) from exc
    """
    code = "KNOWLEDGE_CHUNKING_EXECUTION_ERROR"

    def __init__(self, message: str, *, chunker_name: str | None = None, version_id: Any | None = None,
                 source_segment_index: int | None = None, **context: Any
    ) -> None:
        if chunker_name is not None:
            context.setdefault("chunker_name", chunker_name)

        if version_id is not None:
            context.setdefault("version_id", str(version_id))

        if source_segment_index is not None:
            context.setdefault("source_segment_index", source_segment_index)

        self.chunker_name = chunker_name
        self.version_id = version_id
        self.source_segment_index = source_segment_index
        super().__init__(message, **context)

class KnowledgeChunkerOutputError(KnowledgeChunkingError):
    """
    Raised when a chunker completes its algorithm but produces output that violates the chunking contract.

    Examples:
        - no chunks produced from a valid normalized document
        - blank chunk
        - invalid provenance spans
        - non-contiguous chunk indexes
        - chunk exceeds a hard strategy limit unexpectedly
        - source content is silently lost when the strategy promises loss-resistant chunking
    """
    code = "KNOWLEDGE_CHUNKER_OUTPUT_ERROR"

    def __init__(self, message: str, *, chunker_name: str | None = None, version_id: Any | None = None,
                 chunk_index: int | None = None, source_segment_index: int | None = None, **context: Any
    ) -> None:
        if chunker_name is not None:
            context.setdefault("chunker_name", chunker_name)

        if version_id is not None:
            context.setdefault("version_id", str(version_id))

        if chunk_index is not None:
            context.setdefault("chunk_index", chunk_index)

        if source_segment_index is not None:
            context.setdefault("source_segment_index", source_segment_index)

        self.chunker_name = chunker_name
        self.version_id = version_id
        self.chunk_index = chunk_index
        self.source_segment_index = source_segment_index
        super().__init__(message, **context)