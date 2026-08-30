from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from packages.knowledge.domain.enums import KnowledgeDocumentStatus, KnowledgeVersionStatus
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory


# Application errors
class PublishKnowledgeVersionError(RuntimeError):
    """
    Base application-layer error for publication coordination.

    Domain lifecycle errors are deliberately not duplicated here.
    KnowledgeDocumentVersion.publish()/supersede() remain responsible
    for validating version-level state transitions.
    """

class KnowledgeVersionDoesNotExistError(PublishKnowledgeVersionError):
    def __init__(self, version_id: UUID) -> None:
        self.version_id = version_id
        super().__init__(f"Knowledge document version does not exist: {version_id}")

class KnowledgeDocumentDoesNotExistError(PublishKnowledgeVersionError):
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        super().__init__(f"Knowledge document does not exist: {document_id}")

class KnowledgeDocumentNotPublishableError(PublishKnowledgeVersionError):
    def __init__(self, *, document_id: UUID, status: KnowledgeDocumentStatus) -> None:
        self.document_id = document_id
        self.status = status
        super().__init__(f"Knowledge document does not permit publication while in status {status.value!r}: {document_id}")

class KnowledgePublicationConflictError(PublishKnowledgeVersionError):
    """
    Indicates persisted state that violates the application's cross-version publication assumptions.
    """


# Contracts
@dataclass(frozen=True, slots=True)
class PublishKnowledgeVersionCommand:
    version_id: UUID

    def __post_init__(self) -> None:
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


# Application service
class PublishKnowledgeVersion:
    """
    Atomically publish one READY knowledge-document version.

    Publication is a document-wide invariant rather than merely a
    single-version mutation.

    Transaction:

        load target -> lock parent document -> reload + lock target -> find current published version
                                                                                    ↓
                                                                            current.publish? 
                                                                                    ↓ NO
            commit once   <---   flush   <---  target.publish()   <---    current.supersede()
      

    Locking the parent document serializes publication attempts for
    different versions belonging to the same logical document.
    """

    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        self._uow_factory = uow_factory

    def execute(self, command: PublishKnowledgeVersionCommand) -> PublishKnowledgeVersionResult:
        if not isinstance(command, PublishKnowledgeVersionCommand):
            raise TypeError("command must be a PublishKnowledgeVersionCommand.")

        with self._uow_factory() as uow:
            # Preliminary target read.
            # Only used to discover document_id. Publication decisions are made after acquiring the document-level serialization lock.
            target = uow.versions.get_by_id(command.version_id)
            if target is None:
                raise KnowledgeVersionDoesNotExistError(command.version_id)
            
            document_id = target.document_id

            # Serialize publication for the logical document.
            document = uow.documents.get_by_id_for_update(document_id)
            if document is None:
                raise KnowledgeDocumentDoesNotExistError(document_id)

            if document.status is not KnowledgeDocumentStatus.ACTIVE:
                raise KnowledgeDocumentNotPublishableError(document_id=document.id, status=document.status)

            # Reload target AFTER aggregate lock.
            # The original object may now be stale.
            target = uow.versions.get_by_id_for_update(command.version_id)
            if target is None:
                raise KnowledgeVersionDoesNotExistError(command.version_id)

            if target.document_id != document.id:
                raise KnowledgePublicationConflictError("Target knowledge version no longer belongs to the locked document.")

            # Resolve existing published version while lock is held.
            current_published = uow.versions.get_published_for_document(document.id)
            if current_published is not None and current_published.id == target.id:
                raise KnowledgePublicationConflictError("Target version is already the published version for this document.")
            
            occurred_at = datetime.now(timezone.utc)
            superseded_version_id: UUID | None = None

            # Supersede previous version through DOMAIN behavior.
            if current_published is not None:
                self._validate_current_published(current=current_published, document_id=document.id)
                superseded = current_published.supersede(occurred_at=occurred_at)
                uow.versions.save(superseded)
                # Important:
                # Materialize PUBLISHED -> SUPERSEDED in PostgreSQL before attempting READY -> PUBLISHED on the replacement version.
                # The partial unique index allows only one PUBLISHED version per document, and 
                # unique indexes are checked during statement execution rather than at transaction commit.
                uow.flush()
                superseded_version_id = current_published.id

            # Publish target through DOMAIN behavior.
            # publish() itself validates READY + completed ingestion.
            published = target.publish(occurred_at=occurred_at)
            uow.versions.save(published)
            
            # Cause mapper/constraint problems to surface before commit.
            uow.flush()
            # One atomic commit.
            uow.commit()

        if published.published_at is None:
            # This is a programming/domain-contract violation.
            raise KnowledgePublicationConflictError("Published version did not contain published_at.")

        return PublishKnowledgeVersionResult(
            version_id=published.id,
            document_id=published.document_id,
            version_number=published.version_number,
            status=published.status,
            published_at=published.published_at,
            superseded_version_id=superseded_version_id,
        )

    @staticmethod
    def _validate_current_published(*, current: KnowledgeDocumentVersion, document_id: UUID) -> None:
        """
        Defensive validation of repository output.

        Most of these conditions are already protected by the domain
        constructor, but verifying the cross-document association here
        protects the publication coordinator itself.
        """
        if current.document_id != document_id:
            raise KnowledgePublicationConflictError("Published knowledge version does not belong to the target document.")

        if not current.is_published:
            raise KnowledgePublicationConflictError("Published-version repository returned a non-published version.")

        if current.published_at is None:
            raise KnowledgePublicationConflictError("Published knowledge version is missing published_at.")