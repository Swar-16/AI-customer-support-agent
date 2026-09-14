# AI-customer-support-agent\packages\knowledge\application\upload_version.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID
from uuid6 import uuid7

from packages.application.audit.models import RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.knowledge.application.knowledge_upload_policy import KnowledgeUploadPolicy, ValidatedKnowledgeUpload
from packages.knowledge.application.mutation_context import KnowledgeMutationContext
from packages.knowledge.domain.enums import KnowledgeDocumentStatus, KnowledgeIngestionStatus, KnowledgeSourceType, KnowledgeVersionStatus
from packages.knowledge.domain.errors import KnowledgeDocumentAlreadyArchivedError, KnowledgeDocumentDeletedError, KnowledgeDocumentNotFoundError
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory

_RESERVED_METADATA_PREFIX = "upload_"

@dataclass(frozen=True, slots=True)
class UploadKnowledgeVersionCommand:
    context: KnowledgeMutationContext
    document_id: UUID
    filename: str
    media_type: str
    content: bytes
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.context, KnowledgeMutationContext):
            raise TypeError("context must be a KnowledgeMutationContext.")
        if not isinstance(self.document_id, UUID):
            raise TypeError("document_id must be a UUID.")
        if not isinstance(self.filename, str):
            raise TypeError("filename must be a string.")
        if not isinstance(self.media_type, str):
            raise TypeError("media_type must be a string.")
        if not isinstance(self.content, bytes):
            raise TypeError("content must be bytes.")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        metadata = dict(self.metadata)
        _reject_reserved_metadata(metadata)
        object.__setattr__(self, "metadata", metadata)

@dataclass(frozen=True, slots=True)
class UploadKnowledgeVersionResult:
    document_id: UUID
    version_id: UUID
    version_number: int
    source_name: str | None
    source_type: KnowledgeSourceType
    content_hash: str
    uploaded_size_bytes: int
    status: KnowledgeVersionStatus
    ingestion_status: KnowledgeIngestionStatus
    created: bool
    created_at: datetime
    updated_at: datetime

class UploadKnowledgeVersion:
    """
    Upload a new immutable version for an explicitly identified document.

    Filename is source metadata only and is never used to discover the parent document. Parent-row locking serializes
    duplicate detection and version number allocation for concurrent uploads to the same document.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory, upload_policy: KnowledgeUploadPolicy) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")
        
        if not isinstance(upload_policy, KnowledgeUploadPolicy):
            raise TypeError("upload_policy must be a KnowledgeUploadPolicy.")

        self._uow_factory = uow_factory
        self._upload_policy = upload_policy

    def execute(self, command: UploadKnowledgeVersionCommand) -> UploadKnowledgeVersionResult:
        if not isinstance(command, UploadKnowledgeVersionCommand):
            raise TypeError("command must be an UploadKnowledgeVersionCommand.")

        # Reject invalid bytes before acquiring database connections or locks.
        upload = self._upload_policy.validate(filename=command.filename, media_type=command.media_type, content=command.content)
        with self._uow_factory() as uow:
            document = uow.documents.get_by_id_for_update(command.document_id)
            if document is None:
                raise KnowledgeDocumentNotFoundError(document_id=command.document_id)
            
            if document.status is KnowledgeDocumentStatus.ARCHIVED:
                raise KnowledgeDocumentAlreadyArchivedError(document_id=document.id)
            
            if document.status is KnowledgeDocumentStatus.DELETED:
                raise KnowledgeDocumentDeletedError(document_id=document.id)

            existing = uow.versions.get_by_document_and_content_hash(document_id=document.id, source_type=upload.source_type, content_hash=upload.content_hash)
            if existing is not None:
                return _result_from_existing(version=existing, upload=upload)

            occurred_at = datetime.now(timezone.utc)
            version = KnowledgeDocumentVersion(
                id=uuid7(),
                document_id=document.id,
                version_number=uow.versions.next_version_number(document.id),
                source_type=upload.source_type,
                source_content=upload.source_content,
                content_hash=upload.content_hash,
                source_name=upload.filename,
                source_uri=None,
                metadata=_build_version_metadata(supplied=command.metadata, upload=upload),
                created_at=occurred_at,
                updated_at=occurred_at,
            )
            uow.versions.add(version)
            uow.flush()

            AuditRecorder(repository=uow.audit_events).record(
                RecordAuditEventCommand(
                    event_type="knowledge_version.created",
                    entity_type="knowledge_version",
                    entity_id=version.id,
                    action="created",
                    actor=command.context.actor,
                    trace_id=command.context.trace_id,
                    before_state=None,
                    after_state={
                        "document_id": str(version.document_id),
                        "version_number": version.version_number,
                        "source_type": version.source_type.value,
                        "status": version.status.value,
                        "ingestion_status": version.ingestion_status.value,
                        "content_hash": version.content_hash,
                    },
                    metadata={
                        "creation_source": "upload",
                        "source_content_length": len(version.source_content),
                        "uploaded_size_bytes": upload.uploaded_size_bytes,
                        "upload_sha256": upload.upload_hash,
                        "metadata_keys": sorted(version.metadata.keys()),
                    },
                    occurred_at=occurred_at,
                )
            )

            result = UploadKnowledgeVersionResult(
                document_id=version.document_id,
                version_id=version.id,
                version_number=version.version_number,
                source_name=version.source_name,
                source_type=version.source_type,
                content_hash=version.content_hash,
                uploaded_size_bytes=upload.uploaded_size_bytes,
                status=version.status,
                ingestion_status=version.ingestion_status,
                created=True,
                created_at=version.created_at,
                updated_at=version.updated_at,
            )
            uow.commit()

        return result
    
    @property
    def max_upload_bytes(self) -> int:
        return self._upload_policy.max_upload_bytes

def _result_from_existing(*, version: KnowledgeDocumentVersion, upload: ValidatedKnowledgeUpload) -> UploadKnowledgeVersionResult:
    return UploadKnowledgeVersionResult(
        document_id=version.document_id,
        version_id=version.id,
        version_number=version.version_number,
        source_name=version.source_name,
        source_type=version.source_type,
        content_hash=version.content_hash,
        uploaded_size_bytes=upload.uploaded_size_bytes,
        status=version.status,
        ingestion_status=version.ingestion_status,
        created=False,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )

def _build_version_metadata(*, supplied: Mapping[str, Any], upload: ValidatedKnowledgeUpload) -> dict[str, Any]:
    metadata = dict(supplied)
    metadata.update({
        "upload_extension": upload.extension,
        "upload_media_type": upload.media_type,
        "upload_sha256": upload.upload_hash,
        "upload_size_bytes": upload.uploaded_size_bytes,
        "upload_trust_boundary": "untrusted_admin_upload",
    })
    return metadata

def _reject_reserved_metadata(metadata: Mapping[str, Any]) -> None:
    conflicting = sorted(key for key in metadata if isinstance(key, str) and key.casefold().startswith(_RESERVED_METADATA_PREFIX))
    if conflicting:
        raise ValueError("metadata must not define reserved upload_* keys: "+ ", ".join(conflicting))