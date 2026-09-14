# AI-customer-support-agent\packages\knowledge\application\list_documents.py
from __future__ import annotations
from dataclasses import dataclass

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.knowledge.application.exceptions import KnowledgeReadAccessDeniedError
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import KnowledgeContentType, KnowledgeDocumentStatus, KnowledgeVisibility
from packages.knowledge.repositories.document_repository import KnowledgeDocumentListFilter
from packages.knowledge.uow import KnowledgeUnitOfWorkFactory

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

@dataclass(frozen=True, slots=True)
class ListKnowledgeDocumentsQuery:
    principal: AuthenticatedPrincipal
    status: KnowledgeDocumentStatus | None = None
    content_type: KnowledgeContentType | None = None
    visibility: KnowledgeVisibility | None = None
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal.")

        if self.principal.role is not AuthRole.ADMIN:
            raise KnowledgeReadAccessDeniedError("Only administrators may list knowledge documents.")

        if self.status is not None and not isinstance(self.status, KnowledgeDocumentStatus):
            raise TypeError("status must be a KnowledgeDocumentStatus or None.")

        if self.content_type is not None and not isinstance(self.content_type, KnowledgeContentType):
            raise TypeError("content_type must be a KnowledgeContentType or None.")

        if self.visibility is not None and not isinstance(self.visibility, KnowledgeVisibility):
            raise TypeError("visibility must be a KnowledgeVisibility or None.")

        if not isinstance(self.limit, int) or isinstance(self.limit, bool):
            raise TypeError("limit must be an integer.")

        if not 1 <= self.limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}.")

        if not isinstance(self.offset, int) or isinstance(self.offset, bool):
            raise TypeError("offset must be an integer.")

        if self.offset < 0:
            raise ValueError("offset must be non-negative.")

@dataclass(frozen=True, slots=True)
class ListKnowledgeDocumentsResult:
    documents: tuple[KnowledgeDocument, ...]
    total: int
    limit: int
    offset: int

    def __post_init__(self) -> None:
        if not isinstance(self.documents, tuple):
            raise TypeError("documents must be a tuple.")

        if not all(isinstance(document, KnowledgeDocument) for document in self.documents):
            raise TypeError("documents must contain KnowledgeDocument instances.")

        if not isinstance(self.total, int) or isinstance(self.total, bool):
            raise TypeError("total must be an integer.")

        if self.total < 0:
            raise ValueError("total must be non-negative.")

        if self.total < len(self.documents):
            raise ValueError("total cannot be smaller than the returned count.")

    @property
    def count(self) -> int:
        return len(self.documents)

    @property
    def has_more(self) -> bool:
        return self.offset + self.count < self.total

    @property
    def next_offset(self) -> int | None:
        if not self.has_more:
            return None

        return self.offset + self.count

class ListKnowledgeDocuments:
    """
    Return a filtered and paginated administrative document listing.

    Filtering and pagination are executed by PostgreSQL rather than by loading the entire knowledge catalog into application memory.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable.")

        self._uow_factory = uow_factory

    def execute(self, query: ListKnowledgeDocumentsQuery) -> ListKnowledgeDocumentsResult:
        if not isinstance(query, ListKnowledgeDocumentsQuery):
            raise TypeError("query must be a ListKnowledgeDocumentsQuery.")

        if query.principal.role is not AuthRole.ADMIN:
            raise KnowledgeReadAccessDeniedError("Only administrators may list knowledge documents.")

        filter_ = KnowledgeDocumentListFilter(status=query.status, content_type=query.content_type, visibility=query.visibility)

        with self._uow_factory() as uow:
            documents = tuple(uow.documents.list(filter_=filter_, limit=query.limit, offset=query.offset))
            total = uow.documents.count(filter_=filter_)

        return ListKnowledgeDocumentsResult(
            documents=documents,
            total=total,
            limit=query.limit,
            offset=query.offset,
        )