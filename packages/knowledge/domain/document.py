from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from packages.knowledge.domain.enums import KnowledgeContentType, KnowledgeDocumentStatus, KnowledgeVisibility
from packages.knowledge.domain.errors import KnowledgeDocumentAlreadyArchivedError, KnowledgeDocumentDeletedError
from packages.knowledge.domain.errors import KnowledgeDocumentTitleError, KnowledgeStateTransitionError, InvalidKnowledgeDocumentError

MAX_DOCUMENT_TITLE_LENGTH = 300
MAX_DOCUMENT_DESCRIPTION_LENGTH = 2_000
MAX_DOCUMENT_METADATA_KEYS = 100
MAX_METADATA_KEY_LENGTH = 100

@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """
    Domain representation of a logical knowledge asset.

    A KnowledgeDocument represents the stable business identity of knowledge,
    for example:

        "Refund Policy"
        "Shipping FAQ"
        "Internal Escalation Guide"

    The actual content does not live on this entity. Content belongs toKnowledgeDocumentVersion 
    objects so historical versions remain immutable and auditable.

    This entity intentionally contains no persistence, HTTP, vector-store, embedding, or ingestion concerns.
    """
    id: UUID
    title: str
    content_type: KnowledgeContentType
    visibility: KnowledgeVisibility
    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.ACTIVE
    description: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    archived_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        self._validate_id()
        self._validate_enums()
        self._validate_timestamps()
        self._validate_lifecycle_consistency()

        normalized_title = self._normalize_title(self.title)
        normalized_description = self._normalize_description(self.description)
        normalized_metadata = self._normalize_metadata(self.metadata)
        
        object.__setattr__(self, "title", normalized_title)
        object.__setattr__(self, "description", normalized_description)
        object.__setattr__(self, "metadata", normalized_metadata)

    # Queries
    @property
    def is_active(self) -> bool:
        return self.status is KnowledgeDocumentStatus.ACTIVE

    @property
    def is_archived(self) -> bool:
        return self.status is KnowledgeDocumentStatus.ARCHIVED

    @property
    def is_deleted(self) -> bool:
        return self.status is KnowledgeDocumentStatus.DELETED

    @property
    def is_customer_visible(self) -> bool:
        return self.visibility in {KnowledgeVisibility.CUSTOMER, KnowledgeVisibility.BOTH,}

    @property
    def is_internal_visible(self) -> bool:
        return self.visibility in {KnowledgeVisibility.INTERNAL, KnowledgeVisibility.BOTH,}

    def ensure_mutable(self) -> None:
        """
        Reject mutations against a logically deleted document.

        Deletion is terminal at the domain level. Archived documents may still
        participate in explicitly allowed operations such as restoration.
        """
        if self.is_deleted:
            raise KnowledgeDocumentDeletedError(self.id)

    # Mutations
    def rename(self, title: str, *, occurred_at: datetime | None = None) -> KnowledgeDocument:
        """
        Return a new document with an updated title.

        The logical document identity remains unchanged.
        """
        self.ensure_mutable()
        normalized_title = self._normalize_title(title)
        if normalized_title == self.title:
                    return self
                
        changed_at = self._resolve_mutation_time(occurred_at)

        return replace(self, title=normalized_title, updated_at=changed_at)

    def change_description(self, description: str | None, *, occurred_at: datetime | None = None) -> KnowledgeDocument:
        """Return a new document with updated descriptive metadata."""
        self.ensure_mutable()
        normalized_description = self._normalize_description(description)
        if normalized_description == self.description:
                    return self
                
        changed_at = self._resolve_mutation_time(occurred_at)

        return replace(self, description=normalized_description, updated_at=changed_at)

    def change_content_type(self, content_type: KnowledgeContentType, *, occurred_at: datetime | None = None) -> KnowledgeDocument:
        """
        Change the broad semantic classification of the document.

        This does not modify any document-version content.
        """
        self.ensure_mutable()
        if not isinstance(content_type, KnowledgeContentType):
            raise TypeError("content_type must be a KnowledgeContentType.")

        if content_type is self.content_type:
            return self

        return replace(self, content_type=content_type, updated_at=self._resolve_mutation_time(occurred_at))

    def change_visibility(self, visibility: KnowledgeVisibility, *, occurred_at: datetime | None = None) -> KnowledgeDocument:
        """
        Change who may consume the logical knowledge document.

        Retrieval still needs to enforce visibility at query time.
        """
        self.ensure_mutable()
        if not isinstance(visibility, KnowledgeVisibility):
            raise TypeError("visibility must be a KnowledgeVisibility.")

        if visibility is self.visibility:
            return self

        return replace(self, visibility=visibility, updated_at=self._resolve_mutation_time(occurred_at))

    def replace_metadata(self, metadata: Mapping[str, Any], *, occurred_at: datetime | None = None) -> KnowledgeDocument:
        """
        Replace document-level metadata.

        Metadata is intentionally generic. Business topics such as refund,
        shipping, region, product, tenant, or language should not become
        hard-coded fields unless future domain requirements justify them.
        """
        self.ensure_mutable()
        normalized_metadata = self._normalize_metadata(metadata)
        if normalized_metadata == dict(self.metadata):
            return self
        
        changed_at = self._resolve_mutation_time(occurred_at)
        
        return replace(self, metadata=normalized_metadata, updated_at=changed_at)

    def archive(self, *, occurred_at: datetime | None = None) -> KnowledgeDocument:
        """
        Archive the logical document.

        Archived documents should be excluded from normal retrieval but remain
        available for administration, history, and audit.
        """
        self.ensure_mutable()
        if self.is_archived:
            raise KnowledgeDocumentAlreadyArchivedError(self.id)

        changed_at = self._resolve_mutation_time(occurred_at)
        self._ensure_transition_allowed(KnowledgeDocumentStatus.ARCHIVED)

        return replace(self, status=KnowledgeDocumentStatus.ARCHIVED, archived_at=changed_at, updated_at=changed_at)

    def restore(self, *, occurred_at: datetime | None = None) -> KnowledgeDocument:
        """
        Restore an archived document to active administrative use.

        This does not automatically publish or restore any document version.
        """
        self.ensure_mutable()
        if self.is_active:
            return self

        changed_at = self._resolve_mutation_time(occurred_at)
        self._ensure_transition_allowed(KnowledgeDocumentStatus.ACTIVE)
        
        return replace(self, status=KnowledgeDocumentStatus.ACTIVE, archived_at=None, updated_at=changed_at)

    def delete(self, *, occurred_at: datetime | None = None) -> KnowledgeDocument:
        """
        Logically delete the document.

        Deletion is terminal in this domain model. Physical deletion and data
        retention are persistence/compliance concerns and must not happen here.
        """
        if self.is_deleted:
            raise KnowledgeDocumentDeletedError(self.id)

        changed_at = self._resolve_mutation_time(occurred_at)
        self._ensure_transition_allowed(KnowledgeDocumentStatus.DELETED)

        return replace(self, status=KnowledgeDocumentStatus.DELETED, deleted_at=changed_at, updated_at=changed_at)

    # Transition rules
    def _ensure_transition_allowed(self, target: KnowledgeDocumentStatus) -> None:
        allowed_transitions = {
            KnowledgeDocumentStatus.ACTIVE: {
                KnowledgeDocumentStatus.ARCHIVED,
                KnowledgeDocumentStatus.DELETED,
            },
            KnowledgeDocumentStatus.ARCHIVED: {
                KnowledgeDocumentStatus.ACTIVE,
                KnowledgeDocumentStatus.DELETED,
            },
            KnowledgeDocumentStatus.DELETED: set(),
        }

        if target not in allowed_transitions[self.status]:
            raise KnowledgeStateTransitionError(entity_type="knowledge_document", entity_id=self.id, current_state=self.status.value, target_state=target.value)

    # Validation
    def _validate_id(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("id must be a UUID.")

    def _validate_enums(self) -> None:
        if not isinstance(self.content_type, KnowledgeContentType):
            raise TypeError("content_type must be a KnowledgeContentType.")

        if not isinstance(self.visibility, KnowledgeVisibility):
            raise TypeError("visibility must be a KnowledgeVisibility.")

        if not isinstance(self.status, KnowledgeDocumentStatus):
            raise TypeError("status must be a KnowledgeDocumentStatus.")

    def _validate_timestamps(self) -> None:
        self._ensure_aware_datetime("created_at", self.created_at)
        self._ensure_aware_datetime("updated_at", self.updated_at)
        
        if self.archived_at is not None:
            self._ensure_aware_datetime("archived_at", self.archived_at)

        if self.deleted_at is not None:
            self._ensure_aware_datetime("deleted_at", self.deleted_at)

        if self.updated_at < self.created_at:
            raise InvalidKnowledgeDocumentError(reason="updated_at cannot be earlier than created_at.")

    def _validate_lifecycle_consistency(self) -> None:
        if self.status is KnowledgeDocumentStatus.ACTIVE and self.archived_at is not None:
            raise InvalidKnowledgeDocumentError(reason="An active knowledge document cannot have archived_at.")

        if self.status is KnowledgeDocumentStatus.ARCHIVED and self.archived_at is None:
            raise InvalidKnowledgeDocumentError(reason="An archived knowledge document must have archived_at.")

        if self.status is KnowledgeDocumentStatus.DELETED and self.deleted_at is None:
            raise InvalidKnowledgeDocumentError(reason="A deleted knowledge document must have deleted_at.")

        if self.status is not KnowledgeDocumentStatus.DELETED and self.deleted_at is not None:
            raise InvalidKnowledgeDocumentError(reason="A non-deleted knowledge document cannot have deleted_at.")

    # Normalization helpers
    @staticmethod
    def _normalize_title(title: str) -> str:
        if not isinstance(title, str):
            raise KnowledgeDocumentTitleError(reason="Title must be a string.")

        normalized = title.strip()
        if not normalized:
            raise KnowledgeDocumentTitleError(reason="Title cannot be empty.")

        if len(normalized) > MAX_DOCUMENT_TITLE_LENGTH:
            raise KnowledgeDocumentTitleError(reason=f"Title cannot exceed {MAX_DOCUMENT_TITLE_LENGTH} characters.")

        return normalized

    @staticmethod
    def _normalize_description(description: str | None) -> str | None:
        if description is None:
            return None

        if not isinstance(description, str):
            raise TypeError("description must be a string or None.")

        normalized = description.strip()
        if not normalized:
            return None

        if len(normalized) > MAX_DOCUMENT_DESCRIPTION_LENGTH:
            raise InvalidKnowledgeDocumentError(reason=f"Description cannot exceed {MAX_DOCUMENT_DESCRIPTION_LENGTH} characters.")

        return normalized

    @staticmethod
    def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        if len(metadata) > MAX_DOCUMENT_METADATA_KEYS:
            raise InvalidKnowledgeDocumentError(reason=f"Metadata cannot contain more than {MAX_DOCUMENT_METADATA_KEYS} keys.")

        normalized: dict[str, Any] = {}

        for key, value in metadata.items():
            if not isinstance(key, str):
                raise TypeError("metadata keys must be strings.")

            normalized_key = key.strip()
            if not normalized_key:
                raise InvalidKnowledgeDocumentError(reason="Metadata keys cannot be empty.")

            if len(normalized_key) > MAX_METADATA_KEY_LENGTH:
                raise InvalidKnowledgeDocumentError(reason=f"Metadata keys cannot exceed {MAX_METADATA_KEY_LENGTH} characters.")

            if normalized_key in normalized:
                raise InvalidKnowledgeDocumentError(reason="Metadata contains duplicate keys after normalization.")

            normalized[normalized_key] = value

        return normalized

    # Time helpers
    def _resolve_mutation_time(self, occurred_at: datetime | None) -> datetime:
        value = occurred_at or datetime.now(timezone.utc)
        self._ensure_aware_datetime("occurred_at", value)
        if value < self.created_at:
            raise InvalidKnowledgeDocumentError(reason="Mutation time cannot be earlier than created_at.")

        if value < self.updated_at:
            raise InvalidKnowledgeDocumentError(reason="Mutation time cannot be earlier than updated_at.")

        return value

    @staticmethod
    def _ensure_aware_datetime(field_name: str, value: datetime) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime.")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware.")