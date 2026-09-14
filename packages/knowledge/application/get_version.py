# AI-customer-support-agent\packages\knowledge\application\get_version.py
from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.knowledge.application.exceptions import KnowledgeReadAccessDeniedError, QueriedKnowledgeVersionDoesNotExistError
from packages.knowledge.application.exceptions import QueriedKnowledgeDocumentDoesNotExistError
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory

@dataclass(frozen=True, slots=True)
class GetKnowledgeVersionQuery:
    principal: AuthenticatedPrincipal
    version_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if self.principal.role is not AuthRole.ADMIN:
            raise KnowledgeReadAccessDeniedError("Only administrators may inspect knowledge versions.")

        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")

@dataclass(frozen=True, slots=True)
class GetKnowledgeVersionResult:
    document: KnowledgeDocument
    version: KnowledgeDocumentVersion
    current_published_version_id: UUID | None

    @property
    def is_current_published_version(self) -> bool:
        return self.current_published_version_id == self.version.id

class GetKnowledgeVersion:
    """
    Return one knowledge version together with its parent document.

    This administrative query requires an authenticated administrator.
    Transport schemas remain responsible for selecting safe response fields.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        self._uow_factory = uow_factory

    def execute(self, query: GetKnowledgeVersionQuery) -> GetKnowledgeVersionResult:
        if not isinstance(query, GetKnowledgeVersionQuery):
            raise TypeError("query must be a GetKnowledgeVersionQuery.")
        
        if query.principal.role is not AuthRole.ADMIN:
            raise KnowledgeReadAccessDeniedError("Only administrators may inspect knowledge versions.")

        with self._uow_factory() as uow:
            version = uow.versions.get_by_id(query.version_id)
            if version is None:
                raise QueriedKnowledgeVersionDoesNotExistError(query.version_id)

            document = uow.documents.get_by_id(version.document_id)
            if document is None:
                # This should normally be prevented by the database foreign key, but handling it keeps the application contract safe.
                raise QueriedKnowledgeDocumentDoesNotExistError(version.document_id)

            published = uow.versions.get_published_for_document(version.document_id)

        return GetKnowledgeVersionResult(
            document=document,
            version=version,
            current_published_version_id=published.id if published is not None else None,
        )