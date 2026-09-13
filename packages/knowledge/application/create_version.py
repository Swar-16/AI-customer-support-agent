# AI-customer-support-agent\packages\knowledge\application\create_version.py
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID
from uuid6 import uuid7

from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.knowledge.application.exceptions import KnowledgeVersionCreationAccessDeniedError
from packages.knowledge.domain.enums import KnowledgeDocumentStatus, KnowledgeIngestionStatus, KnowledgeSourceType, KnowledgeVersionStatus
from packages.knowledge.domain.errors import KnowledgeDocumentAlreadyArchivedError, KnowledgeDocumentDeletedError, KnowledgeDocumentNotFoundError
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory

@dataclass(frozen=True, slots=True)
class CreateKnowledgeVersionCommand:
    principal: AuthenticatedPrincipal
    trace_id: UUID
    document_id: UUID
    source_type: KnowledgeSourceType
    source_content: str
    source_name: str | None = None
    source_uri: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if self.principal.role is not AuthRole.ADMIN:
            raise KnowledgeVersionCreationAccessDeniedError("Only administrators may create knowledge versions.")

        if not isinstance(self.trace_id, UUID):
            raise TypeError("trace_id must be a UUID.")

        if not isinstance(self.document_id, UUID):
            raise TypeError("document_id must be a UUID.")

        if not isinstance(self.source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType.")

        if not isinstance(self.source_content, str):
            raise TypeError("source_content must be a string.")

        if self.source_name is not None and not isinstance(self.source_name, str):
            raise TypeError("source_name must be a string or None.")

        if self.source_uri is not None and not isinstance(self.source_uri, str):
            raise TypeError("source_uri must be a string or None.")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        object.__setattr__(self, "metadata", dict(self.metadata))

@dataclass(frozen=True, slots=True)
class CreateKnowledgeVersionResult:
    version_id: UUID
    document_id: UUID
    version_number: int
    source_type: KnowledgeSourceType
    content_hash: str
    status: KnowledgeVersionStatus
    ingestion_status: KnowledgeIngestionStatus
    created_at: datetime
    updated_at: datetime

class CreateKnowledgeVersion:
    """
    Create and atomically audit an immutable source revision.

    The parent document is locked before lifecycle validation and version number allocation.
    This prevents archival and concurrent version creation from racing with this operation.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        self._uow_factory = uow_factory

    def execute(self, command: CreateKnowledgeVersionCommand) -> CreateKnowledgeVersionResult:
        if not isinstance(command, CreateKnowledgeVersionCommand):
            raise TypeError("command must be a CreateKnowledgeVersionCommand.")

        if command.principal.role is not AuthRole.ADMIN:
            raise KnowledgeVersionCreationAccessDeniedError("Only administrators may create knowledge versions.")

        with self._uow_factory() as uow:
            # Lock before checking lifecycle state. Archive and publication operations use the same parent-row lock.
            document = uow.documents.get_by_id_for_update(command.document_id)
            if document is None:
                raise KnowledgeDocumentNotFoundError(document_id=command.document_id)

            if document.status is KnowledgeDocumentStatus.ARCHIVED:
                raise KnowledgeDocumentAlreadyArchivedError(document_id=document.id)

            if document.status is KnowledgeDocumentStatus.DELETED:
                raise KnowledgeDocumentDeletedError(document_id=document.id)

            version_number = uow.versions.next_version_number(document.id)
            occurred_at = datetime.now(timezone.utc)
            content_hash = _calculate_content_hash(command.source_content)
            version = KnowledgeDocumentVersion(
                id=uuid7(),
                document_id=document.id,
                version_number=version_number,
                source_type=command.source_type,
                source_content=command.source_content,
                content_hash=content_hash,
                source_name=command.source_name,
                source_uri=command.source_uri,
                metadata=dict(command.metadata),
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
                    actor=AuditActor(actor_type=AuditActorType.ADMIN, actor_id=command.principal.user_id),
                    trace_id=command.trace_id,
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
                        "source_content_length": len(version.source_content),
                        "has_source_name": version.source_name is not None,
                        "has_source_uri": version.source_uri is not None,
                        "metadata_keys": sorted(version.metadata.keys()),
                    },
                    occurred_at=occurred_at,
                )
            )

            result = CreateKnowledgeVersionResult(
                version_id=version.id,
                document_id=version.document_id,
                version_number=version.version_number,
                source_type=version.source_type,
                content_hash=version.content_hash,
                status=version.status,
                ingestion_status=version.ingestion_status,
                created_at=version.created_at,
                updated_at=version.updated_at,
            )

            uow.commit()

        return result


def _calculate_content_hash(source_content: str) -> str:
    """
    Return the SHA-256 fingerprint of the exact UTF-8 source content.

    Content is never included in an audit event.
    """
    if not isinstance(source_content, str):
        raise TypeError("source_content must be a string.")

    return hashlib.sha256(source_content.encode("utf-8")).hexdigest()