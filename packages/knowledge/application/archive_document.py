from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import KnowledgeDocumentStatus
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory


# Application errors
class ArchiveKnowledgeDocumentError(RuntimeError):
    """Base application error for document archival coordination."""

class KnowledgeDocumentDoesNotExistError(ArchiveKnowledgeDocumentError):
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(f"Knowledge document does not exist: {document_id}")

class KnowledgeArchiveConflictError(ArchiveKnowledgeDocumentError):
    """
    Raised when persisted cross-entity state violates assumptions required to archive a logical knowledge document safely.
    """


# Contracts
@dataclass(frozen=True, slots=True)
class ArchiveKnowledgeDocumentCommand:
    document_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, UUID):
            raise TypeError("document_id must be a UUID.")

@dataclass(frozen=True, slots=True)
class ArchiveKnowledgeDocumentResult:
    document_id: UUID
    status: KnowledgeDocumentStatus
    archived_at: datetime
    superseded_version_id: UUID | None


# Application service
class ArchiveKnowledgeDocument:
    """
    Archive a logical knowledge document atomically.

    If the document currently has a published version, that version is superseded within the same
    transaction before the parent document becomes archived.

    The application service coordinates the aggregate while the domain entities continue to own their individual lifecycle transitions.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        self._uow_factory = uow_factory

    def execute(self, command: ArchiveKnowledgeDocumentCommand) -> ArchiveKnowledgeDocumentResult:
        if not isinstance(command, ArchiveKnowledgeDocumentCommand):
            raise TypeError("command must be an ArchiveKnowledgeDocumentCommand.")

        with self._uow_factory() as uow:
            # 1. Lock aggregate root.
            # Publication also locks this same document row, which means publication and archival are serialized against one another.
            document = uow.documents.get_by_id_for_update(command.document_id)
            if document is None:
                raise KnowledgeDocumentDoesNotExistError(command.document_id)

            occurred_at = datetime.now(timezone.utc)
            
            # 2. Resolve current active publication.
            published = (uow.versions.get_published_for_document(document.id))
            superseded_version_id: UUID | None = None

            # 3. Remove published child from active retrieval state first.
            if published is not None:
                self._validate_published_version(document=document, version=published)
                superseded = published.supersede(occurred_at=occurred_at)
                uow.versions.save(superseded)
                # Make the supersession visible to subsequent statements within the transaction before archiving the parent.
                uow.flush()
                superseded_version_id = published.id

            # 4. Delegate parent lifecycle validation to domain.
            # archive() itself handles:  deleted documents, already archived documents, transition validity
            archived = document.archive(occurred_at=occurred_at)
            uow.documents.save(archived)
            uow.flush()
            uow.commit()

        if archived.archived_at is None:
            raise KnowledgeArchiveConflictError("Archived document did not contain archived_at.")

        return ArchiveKnowledgeDocumentResult(
            document_id=archived.id,
            status=archived.status,
            archived_at=archived.archived_at,
            superseded_version_id=superseded_version_id,
        )

    @staticmethod
    def _validate_published_version(*, document: KnowledgeDocument, version: KnowledgeDocumentVersion) -> None:
        if version.document_id != document.id:
            raise KnowledgeArchiveConflictError("Published knowledge version does not belong to the document being archived.")

        if not version.is_published:
            raise KnowledgeArchiveConflictError("Published-version repository returned a non-published version.")

        if version.published_at is None:
            raise KnowledgeArchiveConflictError("Published knowledge version is missing published_at.")