from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from packages.knowledge.domain.enums import KnowledgeIngestionStatus, KnowledgeSourceType, KnowledgeVersionStatus
from packages.knowledge.domain.errors import InvalidKnowledgeVersionError, InvalidKnowledgeVersionNumberError, KnowledgeStateTransitionError, KnowledgeVersionAlreadyPublishedError
from packages.knowledge.domain.errors import KnowledgeVersionContentError, KnowledgeVersionNotReadyError, KnowledgeVersionProcessingFailedError

MAX_SOURCE_NAME_LENGTH = 500
MAX_SOURCE_URI_LENGTH = 2_000
MAX_VERSION_METADATA_KEYS = 100
MAX_METADATA_KEY_LENGTH = 100
MAX_FAILURE_CODE_LENGTH = 200
MAX_FAILURE_MESSAGE_LENGTH = 2_000

@dataclass(frozen=True, slots=True)
class KnowledgeDocumentVersion:
    """
    Domain representation of one immutable revision of a knowledge document.

    A logical KnowledgeDocument may have many versions:

        Refund Policy
            ├── v1
            ├── v2
            └── v3

    This entity owns the lifecycle of one version, including ingestion,
    readiness, publication, supersession, and processing failure state.

    The original source content is retained so the version remains auditable
    and can be reprocessed if the ingestion strategy changes.

    Chunks and embeddings are derived artifacts and do not live directly on
    this entity.
    """
    id: UUID
    document_id: UUID
    version_number: int
    source_type: KnowledgeSourceType
    source_content: str
    content_hash: str
    status: KnowledgeVersionStatus = KnowledgeVersionStatus.DRAFT
    ingestion_status: KnowledgeIngestionStatus = KnowledgeIngestionStatus.PENDING
    source_name: str | None = None
    source_uri: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    ready_at: datetime | None = None
    published_at: datetime | None = None
    superseded_at: datetime | None = None
    archived_at: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        self._validate_ids()
        self._validate_version_number()
        self._validate_enums()
        self._validate_source_content()
        self._validate_content_hash()
        self._validate_source_metadata()
        self._validate_metadata()
        self._validate_failure_fields()
        self._validate_timestamps()
        self._validate_lifecycle_consistency()

        object.__setattr__(self, "source_content", self.source_content.strip())
        object.__setattr__(self, "content_hash", self.content_hash.strip())

        if self.source_name is not None:
            normalized_source_name = self.source_name.strip()
            object.__setattr__(self, "source_name", normalized_source_name or None)

        if self.source_uri is not None:
            normalized_source_uri = self.source_uri.strip()
            object.__setattr__(self, "source_uri", normalized_source_uri or None)

        object.__setattr__(self, "metadata", dict(self.metadata))

    # Queries
    @property
    def is_draft(self) -> bool:
        return self.status is KnowledgeVersionStatus.DRAFT

    @property
    def is_processing(self) -> bool:
        return self.status is KnowledgeVersionStatus.PROCESSING

    @property
    def is_ready(self) -> bool:
        return self.status is KnowledgeVersionStatus.READY

    @property
    def is_published(self) -> bool:
        return self.status is KnowledgeVersionStatus.PUBLISHED

    @property
    def is_superseded(self) -> bool:
        return self.status is KnowledgeVersionStatus.SUPERSEDED

    @property
    def is_failed(self) -> bool:
        return self.status is KnowledgeVersionStatus.FAILED

    @property
    def is_archived(self) -> bool:
        return self.status is KnowledgeVersionStatus.ARCHIVED

    @property
    def ingestion_completed(self) -> bool:
        return self.ingestion_status is KnowledgeIngestionStatus.COMPLETED

    @property
    def ingestion_failed(self) -> bool:
        return self.ingestion_status is KnowledgeIngestionStatus.FAILED

    # Metadata mutation
    def replace_metadata(self, metadata: Mapping[str, Any], *, occurred_at: datetime | None = None) -> KnowledgeDocumentVersion:
        """
        Replace administrative metadata.

        Source content itself is intentionally immutable. If the actual knowledge content changes,
        a new KnowledgeDocumentVersion should be created instead.
        """
        self._ensure_editable()
        normalized_metadata = self._normalize_metadata(metadata)
        if normalized_metadata == dict(self.metadata):
            return self

        return replace(self, metadata=normalized_metadata, updated_at=self._resolve_mutation_time(occurred_at))

    def change_source_reference(self, *, source_name: str | None = None, source_uri: str | None = None, occurred_at: datetime | None = None) -> KnowledgeDocumentVersion:
        """
        Update external source-reference metadata without changing content.

        This can be useful when a file is relocated while its authoritative
        content remains identical.
        """
        self._ensure_editable()
        normalized_name = self._normalize_optional_text(source_name, field_name="source_name", max_length=MAX_SOURCE_NAME_LENGTH)
        normalized_uri = self._normalize_optional_text(source_uri, field_name="source_uri", max_length=MAX_SOURCE_URI_LENGTH)

        if normalized_name == self.source_name and normalized_uri == self.source_uri:
            return self

        return replace(self, source_name=normalized_name, source_uri=normalized_uri, updated_at=self._resolve_mutation_time(occurred_at))

    # Processing lifecycle
    def start_processing(self, *, occurred_at: datetime | None = None) -> KnowledgeDocumentVersion:
        """
        Move a draft or failed version into processing.

        Retrying a failed version is intentionally permitted.
        """
        changed_at = self._resolve_mutation_time(occurred_at)
        if self.status not in {
            KnowledgeVersionStatus.DRAFT,
            KnowledgeVersionStatus.FAILED,
        }:
            raise KnowledgeStateTransitionError(
                entity_type="knowledge_document_version",
                entity_id=self.id,
                current_state=self.status.value,
                target_state=KnowledgeVersionStatus.PROCESSING.value,
            )

        return replace(
            self,
            status=KnowledgeVersionStatus.PROCESSING,
            ingestion_status=KnowledgeIngestionStatus.RUNNING,
            processing_started_at=changed_at,
            processing_completed_at=None,
            ready_at=None,
            failure_code=None,
            failure_message=None,
            updated_at=changed_at,
        )

    def mark_processing_completed(self, *, occurred_at: datetime | None = None) -> KnowledgeDocumentVersion:
        """
        Mark ingestion as successfully completed and make the version ready.

        Publication is still a separate operation.
        """
        if self.status is not KnowledgeVersionStatus.PROCESSING:
            raise KnowledgeStateTransitionError(
                entity_type="knowledge_document_version",
                entity_id=self.id,
                current_state=self.status.value,
                target_state=KnowledgeVersionStatus.READY.value,
            )

        if self.ingestion_status is not KnowledgeIngestionStatus.RUNNING:
            raise InvalidKnowledgeVersionError(reason="A processing version must have running ingestion status before completion.")
        
        changed_at = self._resolve_mutation_time(occurred_at)

        return replace(
            self,
            status=KnowledgeVersionStatus.READY,
            ingestion_status=KnowledgeIngestionStatus.COMPLETED,
            processing_completed_at=changed_at,
            ready_at=changed_at,
            failure_code=None,
            failure_message=None,
            updated_at=changed_at,
        )

    def mark_processing_failed(self, *, failure_code: str | None = None, failure_message: str | None = None, occurred_at: datetime | None = None) -> KnowledgeDocumentVersion:
        """
        Record an ingestion failure.

        Provider/parser exceptions themselves should remain outside the domain.
        Only sanitized failure information is stored here.
        """
        if self.status is not KnowledgeVersionStatus.PROCESSING:
            raise KnowledgeStateTransitionError(
                entity_type="knowledge_document_version",
                entity_id=self.id,
                current_state=self.status.value,
                target_state=KnowledgeVersionStatus.FAILED.value,
            )

        normalized_failure_code = self._normalize_optional_text(failure_code, field_name="failure_code", max_length=MAX_FAILURE_CODE_LENGTH)
        normalized_failure_message = self._normalize_optional_text(failure_message, field_name="failure_message", max_length=MAX_FAILURE_MESSAGE_LENGTH)
        changed_at = self._resolve_mutation_time(occurred_at)

        return replace(
            self,
            status=KnowledgeVersionStatus.FAILED,
            ingestion_status=KnowledgeIngestionStatus.FAILED,
            processing_completed_at=changed_at,
            ready_at=None,
            failure_code=normalized_failure_code,
            failure_message=normalized_failure_message,
            updated_at=changed_at,
        )

    # Publication lifecycle
    def publish(self, *, occurred_at: datetime | None = None) -> KnowledgeDocumentVersion:
        """
        Publish a ready version.

        Cross-version coordination is NOT handled here. The application layer
        must ensure another version is superseded atomically when required.
        """
        if self.is_published:
            raise KnowledgeVersionAlreadyPublishedError(self.id)

        if not self.is_ready:
            raise KnowledgeVersionNotReadyError(self.id, current_status=self.status.value)

        if not self.ingestion_completed:
            raise KnowledgeVersionNotReadyError(self.id, current_status=self.ingestion_status.value)

        changed_at = self._resolve_mutation_time(occurred_at)

        return replace(self, status=KnowledgeVersionStatus.PUBLISHED, published_at=changed_at, updated_at=changed_at)

    def supersede(self, *, occurred_at: datetime | None = None) -> KnowledgeDocumentVersion:
        """
        Supersede a currently published version.

        This is normally coordinated by the publish-version application
        service when a newer version becomes active.
        """
        if not self.is_published:
            raise KnowledgeStateTransitionError(
                entity_type="knowledge_document_version",
                entity_id=self.id,
                current_state=self.status.value,
                target_state=KnowledgeVersionStatus.SUPERSEDED.value,
            )

        changed_at = self._resolve_mutation_time(occurred_at)

        return replace(self, status=KnowledgeVersionStatus.SUPERSEDED, superseded_at=changed_at, updated_at=changed_at)

    def archive(self, *, occurred_at: datetime | None = None) -> KnowledgeDocumentVersion:
        """
        Archive a non-processing version.

        Published versions should normally be superseded before archival so
        active retrieval is never silently removed by this entity alone.
        """
        if self.is_archived:
            return self

        if self.is_processing:
            raise KnowledgeStateTransitionError(
                entity_type="knowledge_document_version",
                entity_id=self.id,
                current_state=self.status.value,
                target_state=KnowledgeVersionStatus.ARCHIVED.value,
            )

        if self.is_published:
            raise KnowledgeStateTransitionError(
                entity_type="knowledge_document_version",
                entity_id=self.id,
                current_state=self.status.value,
                target_state=KnowledgeVersionStatus.ARCHIVED.value,
            )

        changed_at = self._resolve_mutation_time(occurred_at)

        return replace(self, status=KnowledgeVersionStatus.ARCHIVED, archived_at=changed_at, updated_at=changed_at)

    # Guards
    def _ensure_editable(self) -> None:
        if self.status not in {
            KnowledgeVersionStatus.DRAFT,
            KnowledgeVersionStatus.FAILED,
        }:
            raise KnowledgeStateTransitionError(
                entity_type="knowledge_document_version",
                entity_id=self.id,
                current_state=self.status.value,
                target_state="editable",
            )

    # Validation
    def _validate_ids(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("id must be a UUID.")

        if not isinstance(self.document_id, UUID):
            raise TypeError("document_id must be a UUID.")

    def _validate_version_number(self) -> None:
        if not isinstance(self.version_number, int) or isinstance(self.version_number, bool) or self.version_number <= 0:
            raise InvalidKnowledgeVersionNumberError(self.version_number)

    def _validate_enums(self) -> None:
        if not isinstance(self.source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType.")

        if not isinstance(self.status, KnowledgeVersionStatus):
            raise TypeError("status must be a KnowledgeVersionStatus.")

        if not isinstance(self.ingestion_status, KnowledgeIngestionStatus):
            raise TypeError("Ingestion_status must be a KnowledgeIngestionStatus.")

    def _validate_source_content(self) -> None:
        if not isinstance(self.source_content, str):
            raise TypeError("source_content must be a string.")

        if not self.source_content.strip():
            raise KnowledgeVersionContentError(reason="Source content cannot be empty.")

    def _validate_content_hash(self) -> None:
        if not isinstance(self.content_hash, str):
            raise TypeError("content_hash must be a string.")

        if not self.content_hash.strip():
            raise KnowledgeVersionContentError(reason="Content hash cannot be empty.")

    def _validate_source_metadata(self) -> None:
        self._normalize_optional_text(self.source_name, field_name="source_name", max_length=MAX_SOURCE_NAME_LENGTH)
        self._normalize_optional_text(self.source_uri, field_name="source_uri", max_length=MAX_SOURCE_URI_LENGTH)

    def _validate_metadata(self) -> None:
        self._normalize_metadata(self.metadata)

    def _validate_failure_fields(self) -> None:
        self._normalize_optional_text(self.failure_code, field_name="failure_code", max_length=MAX_FAILURE_CODE_LENGTH)
        self._normalize_optional_text(self.failure_message, field_name="failure_message", max_length=MAX_FAILURE_MESSAGE_LENGTH)

    def _validate_timestamps(self) -> None:
        timestamp_fields = {
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "processing_started_at": self.processing_started_at,
            "processing_completed_at": self.processing_completed_at,
            "ready_at": self.ready_at,
            "published_at": self.published_at,
            "superseded_at": self.superseded_at,
            "archived_at": self.archived_at,
        }

        for field_name, value in timestamp_fields.items():
            if value is not None:
                self._ensure_aware_datetime(field_name, value)

        if self.updated_at < self.created_at:
            raise InvalidKnowledgeVersionError(reason=("Updated_at cannot be earlier than created_at."))

        for field_name, value in timestamp_fields.items():
            if field_name not in {"created_at", "updated_at"} and value is not None and value < self.created_at:
                raise InvalidKnowledgeVersionError(reason=f"{field_name} cannot be earlier than created_at.")

    def _validate_lifecycle_consistency(self) -> None:
        if self.status is KnowledgeVersionStatus.DRAFT and self.ingestion_status is not KnowledgeIngestionStatus.PENDING:
            raise InvalidKnowledgeVersionError(reason="A draft version must have pending ingestion status.")

        if self.status is KnowledgeVersionStatus.PROCESSING:
            if self.ingestion_status is not KnowledgeIngestionStatus.RUNNING:
                raise InvalidKnowledgeVersionError(reason="A processing version must have running ingestion status.")

            if self.processing_started_at is None:
                raise InvalidKnowledgeVersionError(reason="A processing version must have processing_started_at.")

        if self.status is KnowledgeVersionStatus.READY:
            if not self.ingestion_completed:
                raise InvalidKnowledgeVersionError(reason="A ready version must have completed ingestion.")

            if self.ready_at is None:
                raise InvalidKnowledgeVersionError(reason="A ready version must have ready_at.")

        if self.status is KnowledgeVersionStatus.PUBLISHED:
            if not self.ingestion_completed:
                raise InvalidKnowledgeVersionError(reason="A published version must have completed ingestion.")

            if self.published_at is None:
                raise InvalidKnowledgeVersionError(reason="A published version must have published_at.")

        if self.status is KnowledgeVersionStatus.SUPERSEDED:
            if self.published_at is None:
                raise InvalidKnowledgeVersionError(reason="A superseded version must previously have been published.")

            if self.superseded_at is None:
                raise InvalidKnowledgeVersionError(reason="A superseded version must have superseded_at.")

        if self.status is KnowledgeVersionStatus.FAILED:
            if not self.ingestion_failed:
                raise InvalidKnowledgeVersionError(reason="A failed version must have failed ingestion status.")

        if self.status is KnowledgeVersionStatus.ARCHIVED and self.archived_at is None:
            raise InvalidKnowledgeVersionError(reason="An archived version must have archived_at.")

        if self.status is not KnowledgeVersionStatus.ARCHIVED and self.archived_at is not None:
            raise InvalidKnowledgeVersionError(reason="A non-archived version cannot have archived_at.")

        if self.status is not KnowledgeVersionStatus.FAILED:
            if self.failure_code is not None or self.failure_message is not None:
                raise InvalidKnowledgeVersionError(reason="Failure details may only be retained for failed versions.")

    # Normalization
    @staticmethod
    def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        if len(metadata) > MAX_VERSION_METADATA_KEYS:
            raise InvalidKnowledgeVersionError(reason=f"Metadata cannot contain more than {MAX_VERSION_METADATA_KEYS} keys.")

        normalized: dict[str, Any] = {}

        for key, value in metadata.items():
            if not isinstance(key, str):
                raise TypeError("metadata keys must be strings.")

            normalized_key = key.strip()
            if not normalized_key:
                raise InvalidKnowledgeVersionError(reason="Metadata keys cannot be empty.")

            if len(normalized_key) > MAX_METADATA_KEY_LENGTH:
                raise InvalidKnowledgeVersionError(reason=f"Metadata keys cannot exceed {MAX_METADATA_KEY_LENGTH} characters.")

            if normalized_key in normalized:
                raise InvalidKnowledgeVersionError(reason="Metadata contains duplicate keys after normalization.")

            normalized[normalized_key] = value

        return normalized

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str, max_length: int) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None.")

        normalized = value.strip()
        if not normalized:
            return None

        if len(normalized) > max_length:
            raise InvalidKnowledgeVersionError(reason=f"{field_name} cannot exceed {max_length} characters.")

        return normalized

    # Time handling
    def _resolve_mutation_time(self, occurred_at: datetime | None) -> datetime:
        value = occurred_at or datetime.now(timezone.utc)
        self._ensure_aware_datetime("occurred_at", value)
        if value < self.created_at:
            raise InvalidKnowledgeVersionError(reason="Mutation time cannot be earlier than created_at.")

        if value < self.updated_at:
            raise InvalidKnowledgeVersionError(reason="Mutation time cannot be earlier than updated_at.")

        return value

    @staticmethod
    def _ensure_aware_datetime(field_name: str, value: datetime) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime.")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware.")