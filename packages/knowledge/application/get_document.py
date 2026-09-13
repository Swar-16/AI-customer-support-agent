# AI-customer-support-agent\packages\knowledge\application\get_document.py
from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.knowledge.application.exceptions import QueriedKnowledgeDocumentDoesNotExistError, KnowledgeDocumentReadAccessDeniedError
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.repositories.version_repository import KnowledgeVersionListFilter
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory

@dataclass(frozen=True, slots=True)
class GetKnowledgeDocumentQuery:
    principal: AuthenticatedPrincipal
    document_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if self.principal.role is not AuthRole.ADMIN:
            raise KnowledgeDocumentReadAccessDeniedError("Only administrators may inspect knowledge documents.")

        if not isinstance(self.document_id, UUID):
            raise TypeError("document_id must be a UUID.")

@dataclass(frozen=True, slots=True)
class GetKnowledgeDocumentResult:
    document: KnowledgeDocument
    published_version_id: UUID | None
    version_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.document, KnowledgeDocument):
            raise TypeError("document must be a KnowledgeDocument.")

        if self.published_version_id is not None and not isinstance(self.published_version_id, UUID):
            raise TypeError("published_version_id must be a UUID or None.")

        if not isinstance(self.version_count, int) or isinstance(self.version_count, bool):
            raise TypeError("version_count must be an integer.")

        if self.version_count < 0:
            raise ValueError("version_count must be non-negative.")

class GetKnowledgeDocument:
    """
    Return one logical knowledge document for administrative inspection.

    Version history is exposed through the separately paginated ListKnowledgeVersions service,
    avoiding unbounded loading of version source content.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        self._uow_factory = uow_factory

    def execute(self, query: GetKnowledgeDocumentQuery) -> GetKnowledgeDocumentResult:
        if not isinstance(query, GetKnowledgeDocumentQuery):
            raise TypeError("query must be a GetKnowledgeDocumentQuery.")

        if query.principal.role is not AuthRole.ADMIN:
            raise KnowledgeDocumentReadAccessDeniedError("Only administrators may inspect knowledge documents.")

        with self._uow_factory() as uow:
            document = uow.documents.get_by_id(query.document_id)
            if document is None:
                raise QueriedKnowledgeDocumentDoesNotExistError(query.document_id)

            published = uow.versions.get_published_for_document(document.id)
            version_count = uow.versions.count_for_document(document.id, filter_=KnowledgeVersionListFilter())

        return GetKnowledgeDocumentResult(
            document=document,
            published_version_id=published.id if published is not None else None,
            version_count=version_count,
        )