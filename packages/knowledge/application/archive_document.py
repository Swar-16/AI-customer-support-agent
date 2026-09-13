# AI-customer-support-agent\packages\knowledge\application\archive_document.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.knowledge.application.exceptions import ArchiveKnowledgeDocumentDoesNotExistError
from packages.knowledge.application.exceptions import KnowledgeArchiveAccessDeniedError, KnowledgeArchiveConflictError
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import KnowledgeDocumentStatus
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory

@dataclass(frozen=True, slots=True)
class ArchiveKnowledgeDocumentCommand:
    principal: AuthenticatedPrincipal
    trace_id: UUID
    document_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if self.principal.role is not AuthRole.ADMIN:
            raise KnowledgeArchiveAccessDeniedError("Only administrators may archive knowledge documents.")

        if not isinstance(self.trace_id, UUID):
            raise TypeError("trace_id must be a UUID.")

        if not isinstance(self.document_id, UUID):
            raise TypeError("document_id must be a UUID.")

@dataclass(frozen=True, slots=True)
class ArchiveKnowledgeDocumentResult:
    document_id: UUID
    status: KnowledgeDocumentStatus
    archived_at: datetime
    superseded_version_id: UUID | None

class ArchiveKnowledgeDocument:
    """
    Archive a logical knowledge document atomically.

    A currently published version is superseded in the same transaction. The document mutation, 
    version supersession and immutable audit event either all commit or all roll back.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        self._uow_factory = uow_factory

    def execute(self, command: ArchiveKnowledgeDocumentCommand) -> ArchiveKnowledgeDocumentResult:
        if not isinstance(command, ArchiveKnowledgeDocumentCommand):
            raise TypeError("command must be an ArchiveKnowledgeDocumentCommand.")

        if command.principal.role is not AuthRole.ADMIN:
            raise KnowledgeArchiveAccessDeniedError("Only administrators may archive knowledge documents.")

        with self._uow_factory() as uow:
            # Publication and version creation lock the same parent row, serializing all aggregate lifecycle mutations.
            document = uow.documents.get_by_id_for_update(command.document_id)
            if document is None:
                raise ArchiveKnowledgeDocumentDoesNotExistError(command.document_id)

            occurred_at = datetime.now(timezone.utc)
            published = uow.versions.get_published_for_document(document.id)
            published_version_id = published.id if published is not None else None
            superseded_version_id: UUID | None = None
            before_state = {
                "status": document.status.value,
                "archived_at": document.archived_at.isoformat() if document.archived_at is not None else None,
                "published_version_id": str(published_version_id) if published_version_id is not None else None,
            }

            if published is not None:
                self._validate_published_version(document=document, version=published)
                superseded = published.supersede(occurred_at=occurred_at)
                uow.versions.save(superseded)
                uow.flush()

                superseded_version_id = superseded.id

            # Domain rules reject deleted or already archived documents.
            archived = document.archive(occurred_at=occurred_at)
            uow.documents.save(archived)
            uow.flush()

            archived_at = archived.archived_at
            if archived_at is None:
                raise KnowledgeArchiveConflictError("Archived document did not contain archived_at.")

            AuditRecorder(repository=uow.audit_events).record(
                RecordAuditEventCommand(
                    event_type="knowledge_document.archived",
                    entity_type="knowledge_document",
                    entity_id=archived.id,
                    action="archived",
                    actor=AuditActor(actor_type=AuditActorType.ADMIN, actor_id=command.principal.user_id),
                    trace_id=command.trace_id,
                    before_state=before_state,
                    after_state={
                        "status": archived.status.value,
                        "archived_at": archived_at.isoformat(),
                        "published_version_id": None,
                    },
                    metadata={"superseded_version_id": str(superseded_version_id) if superseded_version_id is not None else None,},
                    occurred_at=occurred_at,
                )
            )

            result = ArchiveKnowledgeDocumentResult(
                document_id=archived.id,
                status=archived.status,
                archived_at=archived_at,
                superseded_version_id=superseded_version_id,
            )

            uow.commit()

        return result

    @staticmethod
    def _validate_published_version(*, document: KnowledgeDocument, version: KnowledgeDocumentVersion) -> None:
        if version.document_id != document.id:
            raise KnowledgeArchiveConflictError("Published knowledge version does not belong to the document being archived.")

        if not version.is_published:
            raise KnowledgeArchiveConflictError("Published-version repository returned a non-published version.")

        if version.published_at is None:
            raise KnowledgeArchiveConflictError("Published knowledge version is missing published_at.")