from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from uuid import UUID


class KnowledgeDomainError(Exception):
    """
    Base exception for all knowledge-domain rule violations.

    Domain errors represent violations of business invariants or invalid
    domain operations. They should not contain HTTP status codes, database
    exceptions, provider-specific failures, or transport concerns.

    Application and API layers may translate these exceptions into their own
    error representations.
    """
    code = "KNOWLEDGE_DOMAIN_ERROR"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = dict(context or {})

    def __str__(self) -> str:
        return self.message

# Document errors
class KnowledgeDocumentError(KnowledgeDomainError):
    """Base class for errors related to a logical knowledge document."""
    
    code = "KNOWLEDGE_DOCUMENT_ERROR"

class KnowledgeDocumentNotFoundError(KnowledgeDocumentError):
    """
    Raised when a requested logical knowledge document cannot be found.

    Whether this is ultimately treated as a 404, ignored, retried, etc. is an
    application-layer concern.
    """
    code = "KNOWLEDGE_DOCUMENT_NOT_FOUND"

    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(
            f"Knowledge document '{document_id}' was not found.",
            context={
                "document_id": str(document_id),
            },
        )

class KnowledgeDocumentAlreadyArchivedError(KnowledgeDocumentError):
    """Raised when an already archived document is archived again."""

    code = "KNOWLEDGE_DOCUMENT_ALREADY_ARCHIVED"

    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(
            f"Knowledge document '{document_id}' is already archived.",
            context={
                "document_id": str(document_id),
            },
        )

class KnowledgeDocumentDeletedError(KnowledgeDocumentError):
    """
    Raised when an operation is attempted on a logically deleted document.

    Logical deletion is intentionally treated differently from archival:
    archived documents may remain administratively accessible, whereas deleted
    documents should normally reject mutating business operations.
    """
    code = "KNOWLEDGE_DOCUMENT_DELETED"

    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(
            f"Knowledge document '{document_id}' has been deleted.",
            context={
                "document_id": str(document_id),
            },
        )

class KnowledgeDocumentTitleError(KnowledgeDocumentError):
    """Raised when a document title violates domain requirements."""

    code = "KNOWLEDGE_DOCUMENT_INVALID_TITLE"

    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(
            "Knowledge document title is invalid.",
            context={
                "reason": reason,
            },
        )

# Version errors
class KnowledgeVersionError(KnowledgeDomainError):
    """Base class for errors related to knowledge document versions."""

    code = "KNOWLEDGE_VERSION_ERROR"


class KnowledgeVersionNotFoundError(KnowledgeVersionError):
    """Raised when a requested document version cannot be found."""

    code = "KNOWLEDGE_VERSION_NOT_FOUND"

    def __init__(self, version_id: UUID, *, document_id: UUID | None = None) -> None:
        self.version_id = version_id
        self.document_id = document_id
        context: dict[str, Any] = { "version_id": str(version_id) }
        if document_id is not None:
            context["document_id"] = str(document_id)

        super().__init__(
            f"Knowledge document version '{version_id}' was not found.",
            context=context,
        )

class KnowledgeVersionConflictError(KnowledgeVersionError):
    """
    Raised when creating or assigning a version would violate uniqueness or
    sequencing rules.
    """
    code = "KNOWLEDGE_VERSION_CONFLICT"

    def __init__(self, *, document_id: UUID, version_number: int) -> None:
        self.document_id = document_id
        self.version_number = version_number
        super().__init__(
            f"Knowledge document '{document_id}' already has version '{version_number}'.",
            context={
                "document_id": str(document_id),
                "version_number": version_number,
            },
        )

class InvalidKnowledgeVersionNumberError(KnowledgeVersionError):
    """Raised when a version number violates domain constraints."""

    code = "KNOWLEDGE_VERSION_INVALID_NUMBER"

    def __init__(self, version_number: int) -> None:
        self.version_number = version_number
        super().__init__(
            "Knowledge version number must be a positive integer.",
            context={
                "version_number": version_number,
            },
        )

class KnowledgeVersionContentError(KnowledgeVersionError):
    """Raised when source content for a knowledge version is invalid."""

    code = "KNOWLEDGE_VERSION_INVALID_CONTENT"

    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(
            "Knowledge version content is invalid.",
            context={
                "reason": reason,
            },
        )

# Lifecycle / transition errors
@dataclass(frozen=True, slots=True)
class KnowledgeStateTransition:
    """
    Small value object describing an attempted lifecycle transition.

    Kept generic so it can be reused for document, version, ingestion,
    publication, or other knowledge-domain state machines.
    """
    current_state: str
    target_state: str

class KnowledgeStateTransitionError(KnowledgeDomainError):
    """
    Raised when a requested lifecycle transition is not allowed.

    Example:
        published -> processing
        superseded -> published
        deleted -> active
    """
    code = "KNOWLEDGE_INVALID_STATE_TRANSITION"

    def __init__(self, *, entity_type: str, entity_id: UUID, current_state: str, target_state: str) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.transition = KnowledgeStateTransition(current_state=current_state, target_state=target_state)
        super().__init__(
            f"Cannot transition {entity_type} '{entity_id}' from '{current_state}' to '{target_state}'.",
            context={
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "current_state": current_state,
                "target_state": target_state,
            },
        )

class KnowledgeVersionNotReadyError(KnowledgeVersionError):
    """Raised when publication is attempted before processing is complete."""

    code = "KNOWLEDGE_VERSION_NOT_READY"

    def __init__(self, version_id: UUID, *, current_status: str) -> None:
        self.version_id = version_id
        self.current_status = current_status
        super().__init__(
            f"Knowledge version '{version_id}' cannot be published while in status '{current_status}'.",
            context={
                "version_id": str(version_id),
                "current_status": current_status,
            },
        )

class KnowledgeVersionAlreadyPublishedError(KnowledgeVersionError):
    """Raised when publication is requested for an already published version."""

    code = "KNOWLEDGE_VERSION_ALREADY_PUBLISHED"

    def __init__(self, version_id: UUID) -> None:
        self.version_id = version_id
        super().__init__(
            f"Knowledge version '{version_id}' is already published.",
            context={
                "version_id": str(version_id),
            },
        )

class PublishedVersionConflictError(KnowledgeVersionError):
    """
    Raised when an operation would violate the invariant that a logical
    document has at most one currently published version.
    """
    code = "KNOWLEDGE_PUBLISHED_VERSION_CONFLICT"

    def __init__(self, *, document_id: UUID, existing_version_id: UUID, requested_version_id: UUID) -> None:
        self.document_id = document_id
        self.existing_version_id = existing_version_id
        self.requested_version_id = requested_version_id
        super().__init__(
            f"Knowledge document '{document_id}' already has a published version.",
            context={
                "document_id": str(document_id),
                "existing_version_id": str(existing_version_id),
                "requested_version_id": str(requested_version_id),
            },
        )

# Chunk errors
class KnowledgeChunkError(KnowledgeDomainError):
    """Base class for knowledge chunk domain errors."""

    code = "KNOWLEDGE_CHUNK_ERROR"


class InvalidKnowledgeChunkError(KnowledgeChunkError):
    """Raised when a chunk violates content or ordering invariants."""

    code = "KNOWLEDGE_CHUNK_INVALID"

    def __init__(self, *, reason: str, chunk_index: int | None = None) -> None:
        self.reason = reason
        self.chunk_index = chunk_index
        context: dict[str, Any] = { "reason": reason }
        if chunk_index is not None:
            context["chunk_index"] = chunk_index

        super().__init__("Knowledge chunk is invalid.", context=context)


class DuplicateKnowledgeChunkIndexError(KnowledgeChunkError):
    """
    Raised when two chunks within the same version use the same logical index.
    """

    code = "KNOWLEDGE_CHUNK_DUPLICATE_INDEX"

    def __init__(self, *, version_id: UUID, chunk_index: int) -> None:
        self.version_id = version_id
        self.chunk_index = chunk_index
        super().__init__(
            f"Knowledge version '{version_id}' contains more than one chunk with index '{chunk_index}'.",
            context={
                "version_id": str(version_id),
                "chunk_index": chunk_index,
            },
        )

# Publication / operational invariants
class KnowledgePublicationError(KnowledgeDomainError):
    """Base class for publication-related domain failures."""

    code = "KNOWLEDGE_PUBLICATION_ERROR"


class KnowledgeVersionHasNoChunksError(KnowledgePublicationError):
    """
    Raised when publication is attempted for a version with no usable chunks.
    """
    code = "KNOWLEDGE_VERSION_HAS_NO_CHUNKS"

    def __init__(self, version_id: UUID) -> None:
        self.version_id = version_id
        super().__init__(
            f"Knowledge version '{version_id}' cannot be published because it contains no knowledge chunks.",
            context={
                "version_id": str(version_id),
            },
        )


class KnowledgeVersionProcessingFailedError(KnowledgeVersionError):
    """
    Represents a version whose ingestion/processing lifecycle ended in failure.

    The actual underlying parser, embedding provider, or infrastructure error
    belongs to a lower layer and should not be exposed through this exception.
    """

    code = "KNOWLEDGE_VERSION_PROCESSING_FAILED"

    def __init__(self, version_id: UUID, *, failure_code: str | None = None) -> None:
        self.version_id = version_id
        self.failure_code = failure_code
        context: dict[str, Any] = { "version_id": str(version_id) }
        if failure_code is not None:
            context["failure_code"] = failure_code

        super().__init__(f"Processing failed for knowledge version '{version_id}'.", context=context)