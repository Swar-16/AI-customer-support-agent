# AI-customer-support-agent\packages\knowledge\application\exceptions.py
# All application related problem listed here!!
from uuid import UUID

from packages.knowledge.domain.enums import KnowledgeDocumentStatus, KnowledgeVersionStatus, KnowledgeIngestionStatus

# Get Document
class GetKnowledgeDocumentError(RuntimeError):
    """Base error for administrative document retrieval."""

class QueriedKnowledgeDocumentDoesNotExistError(GetKnowledgeDocumentError):
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(f"Knowledge document does not exist: {document_id}")

# Archive Document
class ArchiveKnowledgeDocumentError(RuntimeError):
    """Base application error for document archival."""

class ArchiveKnowledgeDocumentDoesNotExistError(ArchiveKnowledgeDocumentError):
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(f"Knowledge document does not exist: {document_id}")

class KnowledgeArchiveConflictError(ArchiveKnowledgeDocumentError):
    """Raised when persisted cross-entity state violates assumptions required for safe document archival."""

# Read Authorization
class KnowledgeReadAccessDeniedError(RuntimeError):
    """Raised when a principal cannot inspect knowledge resources."""
    
class KnowledgeMutationAccessDeniedError(RuntimeError):
    """Raised when a caller cannot initiate a KM mutation."""

# Upload Document
class KnowledgeDocumentUploadError(RuntimeError):
    """Base application error for knowledge-file upload failures."""

class KnowledgeUploadConfigurationError(KnowledgeDocumentUploadError):
    """Raised when the server-side upload policy is invalid."""

class InvalidKnowledgeUploadFilenameError(KnowledgeDocumentUploadError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)

class UnsupportedKnowledgeUploadTypeError(KnowledgeDocumentUploadError):
    def __init__(self, *, filename: str, allowed_extensions: tuple[str, ...]) -> None:
        self.filename = filename
        self.allowed_extensions = allowed_extensions
        super().__init__("Unsupported knowledge-file extension. Allowed extensions: "+ ", ".join(allowed_extensions))

class UnsupportedKnowledgeUploadMediaTypeError(KnowledgeDocumentUploadError):
    def __init__(self, *, filename: str, media_type: str | None, allowed_media_types: tuple[str, ...]) -> None:
        self.filename = filename
        self.media_type = media_type
        self.allowed_media_types = allowed_media_types
        super().__init__("The declared media type does not match the uploaded file type.")

class EmptyKnowledgeUploadError(KnowledgeDocumentUploadError):
    def __init__(self) -> None:
        super().__init__("The uploaded knowledge file is empty.")

class KnowledgeUploadTooLargeError(KnowledgeDocumentUploadError):
    def __init__(self, *, actual_bytes: int, maximum_bytes: int) -> None:
        self.actual_bytes = actual_bytes
        self.maximum_bytes = maximum_bytes
        super().__init__(f"The uploaded knowledge file exceeds the {maximum_bytes}-byte limit.")

class InvalidKnowledgeUploadEncodingError(KnowledgeDocumentUploadError):
    def __init__(self) -> None:
        super().__init__("Knowledge text files must use valid UTF-8 encoding.")

class UnsafeKnowledgeUploadContentError(KnowledgeDocumentUploadError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)

# Get Version
class GetKnowledgeVersionError(RuntimeError):
    """Base application error for knowledge-version retrieval."""

class QueriedKnowledgeVersionDoesNotExistError(GetKnowledgeVersionError):
    def __init__(self, version_id: UUID) -> None:
        self.version_id = version_id
        super().__init__(f"Knowledge document version does not exist: {version_id}")
        
# Publish Version
class PublishKnowledgeVersionError(RuntimeError):
    """Base application error for publication coordination."""

class PublishKnowledgeVersionDoesNotExistError(PublishKnowledgeVersionError):
    def __init__(self, version_id: UUID) -> None:
        self.version_id = version_id
        super().__init__(f"Knowledge document version does not exist: {version_id}")

class PublishKnowledgeDocumentDoesNotExistError(PublishKnowledgeVersionError):
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(f"Knowledge document does not exist: {document_id}")

class KnowledgeDocumentNotPublishableError(PublishKnowledgeVersionError):
    def __init__(self, *, document_id: UUID, status: KnowledgeDocumentStatus) -> None:
        self.document_id = document_id
        self.status = status
        super().__init__(f"Knowledge document does not permit publication while in status {status.value!r}: {document_id}")

class KnowledgePublicationConflictError(PublishKnowledgeVersionError):
    """Raised when persisted publication state is inconsistent."""
    
class KnowledgeVersionEmbeddingsIncompleteError(PublishKnowledgeVersionError):
    """
    Raised when publication is attempted before every required knowledge chunk has a compatible persisted embedding.
    """
    def __init__(self, *, version_id: UUID, total_chunk_count: int, embedded_chunk_count: int, provider_identity: str, input_strategy_identity: str) -> None:
        if not isinstance(version_id, UUID):
            raise TypeError("version_id must be a UUID.")

        if isinstance(total_chunk_count, bool) or not isinstance(total_chunk_count, int) or total_chunk_count < 0:
            raise ValueError("total_chunk_count must be a non-negative integer.")

        if isinstance(embedded_chunk_count, bool) or not isinstance(embedded_chunk_count, int) or embedded_chunk_count < 0:
            raise ValueError("embedded_chunk_count must be a non-negative integer.")

        if embedded_chunk_count > total_chunk_count:
            raise ValueError("embedded_chunk_count cannot exceed total_chunk_count.")

        provider_identity = provider_identity.strip()
        input_strategy_identity = input_strategy_identity.strip()
        if not provider_identity:
            raise ValueError("provider_identity must not be blank.")

        if not input_strategy_identity:
            raise ValueError("input_strategy_identity must not be blank.")

        self.version_id = version_id
        self.total_chunk_count = total_chunk_count
        self.embedded_chunk_count = embedded_chunk_count
        self.provider_identity = provider_identity
        self.input_strategy_identity = input_strategy_identity

        super().__init__(
            f"Knowledge version cannot be published because compatible embeddings are incomplete: version_id={version_id}, embedded_chunks={embedded_chunk_count}, total_chunks={total_chunk_count}."
        )
    
# Process Version
class ProcessKnowledgeVersionError(RuntimeError):
    """
    Base application-layer exception for ProcessKnowledgeVersion.

    These errors represent use-case failures, not HTTP concerns and not persistence-provider-specific failures.
    """

class KnowledgeProcessingDocumentDoesNotExistError(ProcessKnowledgeVersionError):
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(f"Knowledge document '{document_id}' does not exist.")

class KnowledgeProcessingDocumentNotActiveError(ProcessKnowledgeVersionError):
    def __init__(self, *, document_id: UUID, status: KnowledgeDocumentStatus) -> None:
        self.document_id = document_id
        self.status = status
        super().__init__(f"Knowledge document '{document_id}' cannot be processed while status='{status.value}'.")

class KnowledgeVersionNotFoundError(ProcessKnowledgeVersionError):
    def __init__(self, version_id: UUID) -> None:
        self.version_id = version_id
        super().__init__(f"Knowledge version '{version_id}' does not exist.")

class KnowledgeVersionNotProcessableError(ProcessKnowledgeVersionError):
    def __init__(self, *, version_id: UUID, version_status: KnowledgeVersionStatus, ingestion_status: KnowledgeIngestionStatus) -> None:
        self.version_id = version_id
        self.version_status = version_status
        self.ingestion_status = ingestion_status
        super().__init__(
            f"Knowledge version '{version_id}' cannot be processed while version_status='{version_status.value}' and ingestion_status='{ingestion_status.value}'."
        )

class KnowledgeVersionProcessingConflictError(ProcessKnowledgeVersionError):
    """Raised when the version changed after it was claimed but before this processing attempt could complete."""

class KnowledgeProcessingContractError(ProcessKnowledgeVersionError):
    """Raised when parser/normalizer/chunker output violates cross-stage application invariants."""

class KnowledgeProcessingPersistenceError(ProcessKnowledgeVersionError):
    """Raised when persistence fails while completing or recording failure state."""