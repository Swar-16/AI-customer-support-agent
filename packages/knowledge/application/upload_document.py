# AI-customer-support-agent\packages\knowledge\application\upload_document.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID
from uuid6 import uuid7

from packages.application.audit.models import RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.knowledge.application.knowledge_upload_policy import KnowledgeUploadPolicy
from packages.knowledge.application.mutation_context import KnowledgeMutationContext
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import KnowledgeContentType, KnowledgeDocumentStatus, KnowledgeIngestionStatus
from packages.knowledge.domain.enums import KnowledgeSourceType, KnowledgeVersionStatus, KnowledgeVisibility
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory

_RESERVED_METADATA_PREFIX = "upload_"

@dataclass(frozen=True, slots=True)
class UploadKnowledgeDocumentCommand:
    context: KnowledgeMutationContext
    filename: str
    media_type: str
    content: bytes
    title: str
    content_type: KnowledgeContentType
    visibility: KnowledgeVisibility
    description: str | None = None
    document_metadata: Mapping[str, Any] = field(default_factory=dict)
    version_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.context, KnowledgeMutationContext):
            raise TypeError("context must be a KnowledgeMutationContext.")
        if not isinstance(self.filename, str):
            raise TypeError("filename must be a string.")
        if not isinstance(self.media_type, str):
            raise TypeError("media_type must be a string.")
        if not isinstance(self.content, bytes):
            raise TypeError("content must be bytes.")
        if not isinstance(self.title, str):
            raise TypeError("title must be a string.")
        if not isinstance(self.content_type, KnowledgeContentType):
            raise TypeError("content_type must be a KnowledgeContentType.")
        if not isinstance(self.visibility, KnowledgeVisibility):
            raise TypeError("visibility must be a KnowledgeVisibility.")
        if self.description is not None and not isinstance(self.description, str):
            raise TypeError("description must be a string or None.")
        if not isinstance(self.document_metadata, Mapping):
            raise TypeError("document_metadata must be a mapping.")
        if not isinstance(self.version_metadata, Mapping):
            raise TypeError("version_metadata must be a mapping.")

        document_metadata = dict(self.document_metadata)
        version_metadata = dict(self.version_metadata)
        _reject_reserved_metadata(document_metadata)
        _reject_reserved_metadata(version_metadata)
        object.__setattr__(self, "document_metadata", document_metadata)
        object.__setattr__(self, "version_metadata", version_metadata)

@dataclass(frozen=True, slots=True)
class UploadKnowledgeDocumentResult:
    document_id: UUID
    version_id: UUID
    version_number: int
    filename: str
    source_type: KnowledgeSourceType
    content_hash: str
    uploaded_size_bytes: int
    document_status: KnowledgeDocumentStatus
    version_status: KnowledgeVersionStatus
    ingestion_status: KnowledgeIngestionStatus
    created_at: datetime

class UploadKnowledgeDocument:
    """Create a knowledge document and its initial uploaded version atomically."""

    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory, upload_policy: KnowledgeUploadPolicy) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        if not isinstance(upload_policy, KnowledgeUploadPolicy):
            raise TypeError("upload_policy must be a KnowledgeUploadPolicy.")

        self._uow_factory = uow_factory
        self._upload_policy = upload_policy

    def execute(self, command: UploadKnowledgeDocumentCommand) -> UploadKnowledgeDocumentResult:
        if not isinstance(command, UploadKnowledgeDocumentCommand):
            raise TypeError("command must be an UploadKnowledgeDocumentCommand.")

        upload = self._upload_policy.validate(
            filename=command.filename,
            media_type=command.media_type,
            content=command.content,
        )
        occurred_at = datetime.now(timezone.utc)
        document = KnowledgeDocument(
            id=uuid7(),
            title=command.title,
            description=command.description,
            content_type=command.content_type,
            visibility=command.visibility,
            metadata=dict(command.document_metadata),
            created_at=occurred_at,
            updated_at=occurred_at,
        )

        version_metadata = dict(command.version_metadata)
        version_metadata.update(
            {
                "upload_extension": upload.extension,
                "upload_media_type": upload.media_type,
                "upload_sha256": upload.upload_hash,
                "upload_size_bytes": upload.uploaded_size_bytes,
                "upload_trust_boundary": "untrusted_admin_upload",
            }
        )

        with self._uow_factory() as uow:
            uow.documents.add(document)
            uow.flush()

            version = KnowledgeDocumentVersion(
                id=uuid7(),
                document_id=document.id,
                version_number=uow.versions.next_version_number(document.id),
                source_type=upload.source_type,
                source_content=upload.source_content,
                content_hash=upload.content_hash,
                source_name=upload.filename,
                source_uri=None,
                metadata=version_metadata,
                created_at=occurred_at,
                updated_at=occurred_at,
            )
            uow.versions.add(version)
            uow.flush()

            recorder = AuditRecorder(repository=uow.audit_events)
            recorder.record(RecordAuditEventCommand(
                event_type="knowledge_document.created",
                entity_type="knowledge_document",
                entity_id=document.id,
                action="created",
                actor=command.context.actor,
                trace_id=command.context.trace_id,
                after_state={
                    "title": document.title,
                    "content_type": document.content_type.value,
                    "visibility": document.visibility.value,
                    "status": document.status.value,
                    "has_description": document.description is not None,
                },
                metadata={
                    "creation_source": "upload",
                    "metadata_keys": sorted(document.metadata.keys()),
                },
                occurred_at=occurred_at,
            ))
            recorder.record(RecordAuditEventCommand(
                event_type="knowledge_version.created",
                entity_type="knowledge_version",
                entity_id=version.id,
                action="created",
                actor=command.context.actor,
                trace_id=command.context.trace_id,
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
            ))

            result = UploadKnowledgeDocumentResult(
                document_id=document.id,
                version_id=version.id,
                version_number=version.version_number,
                filename=upload.filename,
                source_type=version.source_type,
                content_hash=version.content_hash,
                uploaded_size_bytes=upload.uploaded_size_bytes,
                document_status=document.status,
                version_status=version.status,
                ingestion_status=version.ingestion_status,
                created_at=occurred_at,
            )
            uow.commit()

        return result
    
    @property
    def max_upload_bytes(self) -> int:
        return self._upload_policy.max_upload_bytes

def _reject_reserved_metadata(metadata: Mapping[str, Any]) -> None:
    conflicting = sorted(key for key in metadata if isinstance(key, str) and key.casefold().startswith(_RESERVED_METADATA_PREFIX))
    if conflicting:
        raise ValueError("metadata must not define reserved upload_* keys: "+ ", ".join(conflicting))