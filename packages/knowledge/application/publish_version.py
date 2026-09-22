# AI-customer-support-agent\packages\knowledge\application\publish_version.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from packages.application.audit.models import RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.knowledge.application.exceptions import KnowledgeDocumentNotPublishableError, KnowledgePublicationConflictError
from packages.knowledge.application.exceptions import PublishKnowledgeDocumentDoesNotExistError, PublishKnowledgeVersionDoesNotExistError
from packages.knowledge.application.exceptions import KnowledgeVersionEmbeddingsIncompleteError
from packages.knowledge.application.mutation_context import KnowledgeMutationContext
from packages.knowledge.domain.enums import KnowledgeDocumentStatus, KnowledgeVersionStatus
from packages.knowledge.domain.errors import KnowledgeVersionHasNoChunksError, KnowledgeVersionNotReadyError
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory
from packages.knowledge.embeddings.models import EmbeddingInputDescriptor, EmbeddingProviderDescriptor

@dataclass(frozen=True, slots=True)
class PublishKnowledgeVersionCommand:
    context: KnowledgeMutationContext
    version_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.context, KnowledgeMutationContext):
            raise TypeError("context must be a KnowledgeMutationContext.")

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

    The parent document lock serializes publication, archival, and version creation for the same logical document.

    Any currently published version is superseded before the target version is published.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory, embedding_provider: EmbeddingProviderDescriptor, embedding_input_descriptor: EmbeddingInputDescriptor) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        if not isinstance(embedding_provider, EmbeddingProviderDescriptor):
            raise TypeError("embedding_provider must be an EmbeddingProviderDescriptor.")

        if not isinstance(embedding_input_descriptor, EmbeddingInputDescriptor):
            raise TypeError("embedding_input_descriptor must be an EmbeddingInputDescriptor.")

        self._uow_factory = uow_factory
        self._embedding_provider = embedding_provider
        self._embedding_input_descriptor = embedding_input_descriptor

    def execute(self, command: PublishKnowledgeVersionCommand) -> PublishKnowledgeVersionResult:
        if not isinstance(command, PublishKnowledgeVersionCommand):
            raise TypeError("command must be a PublishKnowledgeVersionCommand.")

        with self._uow_factory() as uow:
            # This preliminary read discovers the parent document ID. The target is reloaded under a lock after the parent is locked.
            preliminary_target = uow.versions.get_by_id(command.version_id)
            if preliminary_target is None:
                raise PublishKnowledgeVersionDoesNotExistError(command.version_id)

            document = uow.documents.get_by_id_for_update(preliminary_target.document_id)
            if document is None:
                raise PublishKnowledgeDocumentDoesNotExistError(preliminary_target.document_id)

            if document.status is not KnowledgeDocumentStatus.ACTIVE:
                raise KnowledgeDocumentNotPublishableError(document_id=document.id, status=document.status)

            # Lock and reload the target after locking its parent aggregate.
            target = uow.versions.get_by_id_for_update(command.version_id)
            if target is None:
                raise PublishKnowledgeVersionDoesNotExistError(command.version_id)

            if target.document_id != document.id:
                raise KnowledgePublicationConflictError("Target knowledge version no longer belongs to the locked document.")
            
            current_published = uow.versions.get_published_for_document(document.id)
            # An identical retry of an already completed publication is successful and must not create another audit event or mutate state.
            if current_published is not None and current_published.id == target.id:
                self._validate_current_published(current=current_published, document_id=document.id)
                published_at = current_published.published_at
                if published_at is None:
                    raise KnowledgePublicationConflictError("Published knowledge version is missing published_at.")

                return PublishKnowledgeVersionResult(
                    version_id=current_published.id,
                    document_id=current_published.document_id,
                    version_number=current_published.version_number,
                    status=current_published.status,
                    published_at=published_at,
                    superseded_version_id=None,
                )

            if target.status is not KnowledgeVersionStatus.READY:
                raise KnowledgeVersionNotReadyError(target.id, current_status=target.status.value)

            if current_published is not None:
                self._validate_current_published(current=current_published, document_id=document.id)

            embedding_coverage = uow.embeddings.get_coverage_for_version(target.id, provider=self._embedding_provider, input_descriptor=self._embedding_input_descriptor)
            if embedding_coverage.total_chunk_count == 0:
                raise KnowledgeVersionHasNoChunksError(target.id)

            if not embedding_coverage.is_fully_embedded:
                raise KnowledgeVersionEmbeddingsIncompleteError(
                    version_id=target.id,
                    total_chunk_count=embedding_coverage.total_chunk_count,
                    embedded_chunk_count=embedding_coverage.embedded_chunk_count,
                    provider_identity=self._embedding_provider.identity,
                    input_strategy_identity=self._embedding_input_descriptor.identity,
                )

            before_state = {
                "status": target.status.value,
                "ingestion_status": target.ingestion_status.value,
                "published_at": target.published_at.isoformat() if target.published_at is not None else None,
                "current_published_version_id": str(current_published.id) if current_published is not None else None,
            }

            occurred_at = datetime.now(timezone.utc)
            superseded_version_id: UUID | None = None
            if current_published is not None:
                superseded = current_published.supersede(occurred_at=occurred_at)
                uow.versions.save(superseded)

                # Materialize supersession before publishing the target.
                # PostgreSQL checks the partial unique index during statement execution.
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
                    actor=command.context.actor,
                    trace_id=command.context.trace_id,
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
                        "total_chunk_count": embedding_coverage.total_chunk_count,
                        "embedded_chunk_count": embedding_coverage.embedded_chunk_count,
                        "embedding_provider": self._embedding_provider.identity,
                        "embedding_input_strategy": self._embedding_input_descriptor.identity,
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