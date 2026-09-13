# AI-customer-support-agent\packages\knowledge\application\list_versions.py
from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.knowledge.application.exceptions import KnowledgeReadAccessDeniedError, QueriedKnowledgeDocumentDoesNotExistError
from packages.knowledge.domain.enums import KnowledgeIngestionStatus, KnowledgeSourceType, KnowledgeVersionStatus
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.repositories.version_repository import KnowledgeVersionListFilter
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

@dataclass(frozen=True, slots=True)
class ListKnowledgeVersionsQuery:
    principal: AuthenticatedPrincipal
    document_id: UUID
    status: KnowledgeVersionStatus | None = None
    ingestion_status: KnowledgeIngestionStatus | None = None
    source_type: KnowledgeSourceType | None = None
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if self.principal.role is not AuthRole.ADMIN:
            raise KnowledgeReadAccessDeniedError("Only administrators may list knowledge versions.")
        
        if not isinstance(self.document_id, UUID):
            raise TypeError("document_id must be a UUID.")

        if self.status is not None and not isinstance(self.status, KnowledgeVersionStatus):
            raise TypeError("status must be a KnowledgeVersionStatus or None.")

        if self.ingestion_status is not None and not isinstance(self.ingestion_status, KnowledgeIngestionStatus):
            raise TypeError("ingestion_status must be a KnowledgeIngestionStatus or None.")

        if self.source_type is not None and not isinstance(self.source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType or None.")

        if not isinstance(self.limit, int) or isinstance(self.limit, bool):
            raise TypeError("limit must be an integer.")

        if not 1 <= self.limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}.")

        if not isinstance(self.offset, int) or isinstance(self.offset, bool):
            raise TypeError("offset must be an integer.")

        if self.offset < 0:
            raise ValueError("offset must be non-negative.")

@dataclass(frozen=True, slots=True)
class ListKnowledgeVersionsResult:
    document_id: UUID
    versions: tuple[KnowledgeDocumentVersion, ...]
    total: int
    limit: int
    offset: int

    @property
    def count(self) -> int:
        return len(self.versions)

    @property
    def has_more(self) -> bool:
        return self.offset + self.count < self.total

    @property
    def next_offset(self) -> int | None:
        if not self.has_more:
            return None

        return self.offset + self.count

class ListKnowledgeVersions:
    """Return one document's version history using database pagination."""
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        self._uow_factory = uow_factory

    def execute(self, query: ListKnowledgeVersionsQuery) -> ListKnowledgeVersionsResult:
        if not isinstance(query, ListKnowledgeVersionsQuery):
            raise TypeError("query must be a ListKnowledgeVersionsQuery.")
        
        if query.principal.role is not AuthRole.ADMIN:
            raise KnowledgeReadAccessDeniedError("Only administrators may list knowledge versions.")

        filter_ = KnowledgeVersionListFilter(
            status=query.status,
            ingestion_status=query.ingestion_status,
            source_type=query.source_type,
        )

        with self._uow_factory() as uow:
            if not uow.documents.exists(query.document_id):
                raise QueriedKnowledgeDocumentDoesNotExistError(query.document_id)

            versions = tuple(uow.versions.list_page_for_document(
                query.document_id,
                filter_=filter_,
                limit=query.limit,
                offset=query.offset,
            ))
            total = uow.versions.count_for_document(query.document_id, filter_=filter_)

        return ListKnowledgeVersionsResult(
            document_id=query.document_id,
            versions=versions,
            total=total,
            limit=query.limit,
            offset=query.offset,
        )