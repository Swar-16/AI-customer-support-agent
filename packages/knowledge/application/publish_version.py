# AI-customer-support-agent\packages\knowledge\application\publish_version.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.knowledge.application.exceptions import PublishKnowledgeVersionDoesNotExistError, PublishKnowledgeDocumentDoesNotExistError
from packages.knowledge.application.exceptions import KnowledgePublicationAccessDeniedError, KnowledgePublicationAccessDeniedError
from packages.knowledge.application.exceptions import KnowledgeDocumentNotPublishableError, KnowledgePublicationConflictError
from packages.knowledge.domain.enums import KnowledgeDocumentStatus, KnowledgeVersionStatus
from packages.knowledge.domain.errors import KnowledgeVersionHasNoChunksError
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory

@dataclass(frozen=True, slots=True)
class PublishKnowledgeVersionCommand:
    principal: AuthenticatedPrincipal
    trace_id: UUID
    version_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if self.principal.role is not AuthRole.ADMIN:
            raise KnowledgePublicationAccessDeniedError("Only administrators may publish knowledge versions.")

        if not isinstance(self.trace_id, UUID):
            raise TypeError("trace_id must be a UUID.")

        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")

@dataclass(frozen=True, slots=True)
class PublishKnowledgeVersionResult:
    version_id: UUID
    document_id: UUID
    version_number: int
    status: KnowledgeVersionStatus
    published_at: datetime
    superseded_version_id: UUID | None

class PublishKnowledgeVersion:
    """
    Atomically publish one ready knowledge version.

    The parent document lock serializes publication, archival and version creation for the same logical document.
    Any existing publication is superseded before the target is published.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        self._uow_factory = uow_factory

    def execute(self, command: PublishKnowledgeVersionCommand) -> PublishKnowledgeVersionResult:
        if not isinstance(command, PublishKnowledgeVersionCommand):
            raise TypeError("command must be a PublishKnowledgeVersionCommand.")

        if command.principal.role is not AuthRole.ADMIN:
            raise KnowledgePublicationAccessDeniedError("Only administrators may publish knowledge versions.")

        with self._uow_factory() as uow:
            # Preliminary read is used only to discover the parent ID.
            preliminary_target = uow.versions.get_by_id(command.version_id)
            if preliminary_target is None:
                raise PublishKnowledgeVersionDoesNotExistError(command.version_id)

            document = uow.documents.get_by_id_for_update(preliminary_target.document_id)
            if document is None:
                raise PublishKnowledgeDocumentDoesNotExistError(preliminary_target.document_id)

            if document.status is not KnowledgeDocumentStatus.ACTIVE:
                raise KnowledgeDocumentNotPublishableError(document_id=document.id, status=document.status)

            # Reload and lock the target after acquiring the aggregate lock.
            target = uow.versions.get_by_id_for_update(command.version_id)
            if target is None:
                raise PublishKnowledgeVersionDoesNotExistError(command.version_id)

            if target.document_id != document.id:
                raise KnowledgePublicationConflictError("Target knowledge version no longer belongs to the locked document.")

            current_published = uow.versions.get_published_for_document(document.id)
            if current_published is not None and current_published.id == target.id:
                raise KnowledgePublicationConflictError("Target version is already the published version for this document.")

            # A ready version without derived chunks is not usable by either lexical or vector retrieval.
            chunks = uow.chunks.list_for_version(target.id)
            if not chunks:
                raise KnowledgeVersionHasNoChunksError(target.id)

            before_state = {
                "status": target.status.value,
                "ingestion_status": target.ingestion_status.value,
                "published_at": target.published_at.isoformat() if target.published_at is not None else None,
                "current_published_version_id": str(current_published.id) if current_published is not None else None,
            }

            occurred_at = datetime.now(timezone.utc)
            superseded_version_id: UUID | None = None
            if current_published is not None:
                self._validate_current_published(current=current_published, document_id=document.id)
                superseded = current_published.supersede(occurred_at=occurred_at)
                uow.versions.save(superseded)

                # PostgreSQL checks the partial unique index during statement execution, so materialize supersession first.
                uow.flush()
                superseded_version_id = superseded.id

            published = target.publish(occurred_at=occurred_at)
            uow.versions.save(published)
            uow.flush()

            published_at = published.published_at
            if published_at is None:
                raise KnowledgePublicationConflictError("Published version did not contain published_at.")

            AuditRecorder(repository=uow.audit_events).record(
                RecordAuditEventCommand(
                    event_type="knowledge_version.published",
                    entity_type="knowledge_version",
                    entity_id=published.id,
                    action="published",
                    actor=AuditActor(actor_type=AuditActorType.ADMIN, actor_id=command.principal.user_id),
                    trace_id=command.trace_id,
                    before_state=before_state,
                    after_state={
                        "status": published.status.value,
                        "ingestion_status": published.ingestion_status.value,
                        "published_at": published_at.isoformat(),
                        "active_published_version_id": str(published.id),
                    },
                    metadata={
                        "document_id": str(published.document_id),
                        "version_number": published.version_number,
                        "chunk_count": len(chunks),
                        "superseded_version_id": str(superseded_version_id) if superseded_version_id is not None else None,
                    },
                    occurred_at=occurred_at,
                )
            )

            result = PublishKnowledgeVersionResult(
                version_id=published.id,
                document_id=published.document_id,
                version_number=published.version_number,
                status=published.status,
                published_at=published_at,
                superseded_version_id=superseded_version_id,
            )

            uow.commit()

        return result

    @staticmethod
    def _validate_current_published(*, current: KnowledgeDocumentVersion, document_id: UUID) -> None:
        if current.document_id != document_id:
            raise KnowledgePublicationConflictError("Published knowledge version does not belong to the target document.")

        if not current.is_published:
            raise KnowledgePublicationConflictError("Published-version repository returned a non-published version.")

        if current.published_at is None:
            raise KnowledgePublicationConflictError("Published knowledge version is missing published_at.")