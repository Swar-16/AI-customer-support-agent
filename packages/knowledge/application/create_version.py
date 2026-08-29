from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID
from uuid6 import uuid7

from packages.knowledge.domain.enums import KnowledgeDocumentStatus, KnowledgeSourceType
from packages.knowledge.domain.errors import KnowledgeDocumentNotFoundError, KnowledgeDocumentAlreadyArchivedError, KnowledgeDocumentDeletedError
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class CreateKnowledgeVersionCommand:
    document_id: UUID
    source_type: KnowledgeSourceType
    source_content: str
    source_name: str | None = None
    source_uri: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class CreateKnowledgeVersionResult:
    version_id: UUID
    document_id: UUID
    version_number: int
    content_hash: str
    created_at: datetime

class CreateKnowledgeVersion:
    """
    Create a new immutable source revision for an existing knowledge document.

    The version starts in the domain's default DRAFT / PENDING state.

    Version-number allocation and insertion happen within the same transaction
    so concurrent requests for the same document cannot allocate the same
    version number.
    """
    def __init__(self, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def execute(self, command: CreateKnowledgeVersionCommand) -> CreateKnowledgeVersionResult:
        with self._uow_factory() as uow:
            document = uow.documents.get_by_id(command.document_id)
            if document is None:
                raise KnowledgeDocumentNotFoundError(document_id=command.document_id)

            # Versions should not be created for documents that have been archived or logically deleted.
            if document.status is KnowledgeDocumentStatus.ARCHIVED:
                raise KnowledgeDocumentAlreadyArchivedError(document_id=document.id)
            
            if document.status is KnowledgeDocumentStatus.DELETED:
                raise KnowledgeDocumentDeletedError(document_id=document.id)

            # This method locks the parent document row with SELECT FOR UPDATE before calculating MAX(version_number) + 1.
            version_number = uow.versions.next_version_number(command.document_id)

            now = datetime.now(timezone.utc)
            content_hash = _calculate_content_hash(command.source_content)

            version = KnowledgeDocumentVersion(
                id=uuid7(),
                document_id=command.document_id,
                version_number=version_number,
                source_type=command.source_type,
                # Deliberately preserve the exact original source. 
                # Do not strip, normalize, parse, or otherwise alter it here.
                source_content=command.source_content,
                content_hash=content_hash,
                source_name=command.source_name,
                source_uri=command.source_uri,
                metadata=dict(command.metadata),
                created_at=now,
                updated_at=now,
            )

            uow.versions.add(version)
            # One transaction:
            # document lock
            #     - allocate version number
            #     - insert version
            #     - commit
            uow.commit()

        return CreateKnowledgeVersionResult(
            version_id=version.id,
            document_id=version.document_id,
            version_number=version.version_number,
            content_hash=version.content_hash,
            created_at=version.created_at,
        )

def _calculate_content_hash(source_content: str) -> str:
    """
    SHA-256 fingerprint of the exact UTF-8 source content.

    This is intentionally calculated before any future parsing,
    normalization, or chunking step.
    """
    return hashlib.sha256(source_content.encode("utf-8")).hexdigest()