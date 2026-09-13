# AI-customer-support-agent\packages\knowledge\application\create_document.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID
from uuid6 import uuid7

from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.knowledge.application.exceptions import KnowledgeDocumentCreationAccessDeniedError
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import KnowledgeContentType, KnowledgeDocumentStatus, KnowledgeVisibility
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory

@dataclass(frozen=True, slots=True)
class CreateKnowledgeDocumentCommand:
    principal: AuthenticatedPrincipal
    trace_id: UUID
    title: str
    content_type: KnowledgeContentType
    visibility: KnowledgeVisibility
    description: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if self.principal.role is not AuthRole.ADMIN:
            raise KnowledgeDocumentCreationAccessDeniedError("Only administrators may create knowledge documents.")

        if not isinstance(self.trace_id, UUID):
            raise TypeError("trace_id must be a UUID.")

        if not isinstance(self.content_type, KnowledgeContentType):
            raise TypeError("content_type must be a KnowledgeContentType.")

        if not isinstance(self.visibility, KnowledgeVisibility):
            raise TypeError("visibility must be a KnowledgeVisibility.")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        object.__setattr__(self, "metadata", dict(self.metadata))

@dataclass(frozen=True, slots=True)
class CreateKnowledgeDocumentResult:
    document_id: UUID
    title: str
    content_type: KnowledgeContentType
    visibility: KnowledgeVisibility
    status: KnowledgeDocumentStatus
    description: str | None
    created_at: datetime
    updated_at: datetime

class CreateKnowledgeDocument:
    """
    Create and atomically audit a logical knowledge document.

    Source content is deliberately excluded. Content belongs to immutable KnowledgeDocumentVersion entities.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        self._uow_factory = uow_factory

    def execute(self, command: CreateKnowledgeDocumentCommand) -> CreateKnowledgeDocumentResult:
        if not isinstance(command, CreateKnowledgeDocumentCommand):
            raise TypeError("command must be a CreateKnowledgeDocumentCommand.")

        # Retain application-layer authorization even though the API endpoint will also use AdminPrincipalDependency.
        if command.principal.role is not AuthRole.ADMIN:
            raise KnowledgeDocumentCreationAccessDeniedError("Only administrators may create knowledge documents.")

        occurred_at = datetime.now(timezone.utc)
        document = KnowledgeDocument(
            id=uuid7(),
            title=command.title,
            description=command.description,
            content_type=command.content_type,
            visibility=command.visibility,
            metadata=dict(command.metadata),
            created_at=occurred_at,
            updated_at=occurred_at,
        )

        with self._uow_factory() as uow:
            uow.documents.add(document)
            uow.flush()

            AuditRecorder(repository=uow.audit_events).record(
                RecordAuditEventCommand(
                    event_type="knowledge_document.created",
                    entity_type="knowledge_document",
                    entity_id=document.id,
                    action="created",
                    actor=AuditActor(actor_type=AuditActorType.ADMIN, actor_id=command.principal.user_id),
                    trace_id=command.trace_id,
                    before_state=None,
                    after_state={
                        "title": document.title,
                        "content_type": document.content_type.value,
                        "visibility": document.visibility.value,
                        "status": document.status.value,
                        "has_description": document.description is not None,
                    },
                    metadata={"metadata_keys": sorted(document.metadata.keys()),},
                    occurred_at=occurred_at,
                )
            )

            result = CreateKnowledgeDocumentResult(
                document_id=document.id,
                title=document.title,
                content_type=document.content_type,
                visibility=document.visibility,
                status=document.status,
                description=document.description,
                created_at=document.created_at,
                updated_at=document.updated_at,
            )

            uow.commit()

        return result