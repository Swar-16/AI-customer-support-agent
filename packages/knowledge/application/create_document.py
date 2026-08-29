from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID
from uuid6 import uuid7

from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import KnowledgeContentType, KnowledgeVisibility
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class CreateKnowledgeDocumentCommand:
    title: str
    content_type: KnowledgeContentType
    visibility: KnowledgeVisibility
    description: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class CreateKnowledgeDocumentResult:
    document_id: UUID
    created_at: datetime

class CreateKnowledgeDocument:
    """
    Application use case for creating a logical knowledge document.

    This creates document identity and metadata only. Source content belongs
    to KnowledgeDocumentVersion and is created through a separate use case.
    """
    def __init__(self, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def execute(self, command: CreateKnowledgeDocumentCommand) -> CreateKnowledgeDocumentResult:
        now = datetime.now(timezone.utc)

        document = KnowledgeDocument(
            id=uuid7(),
            title=command.title,
            description=command.description,
            content_type=command.content_type,
            visibility=command.visibility,
            metadata=dict(command.metadata),
            created_at=now,
            updated_at=now,
        )

        with self._uow_factory() as uow:
            uow.documents.add(document)
            uow.commit()

        return CreateKnowledgeDocumentResult(
            document_id=document.id,
            created_at=document.created_at,
        )