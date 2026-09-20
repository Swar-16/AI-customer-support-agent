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
from packages.knowledge.embeddings.models import EmbeddingInputDescriptor, EmbeddingProviderDescriptor
from packages.knowledge.repositories.embedding_repository import KnowledgeVersionEmbeddingCoverage

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
    embedding_coverage: KnowledgeVersionEmbeddingCoverage

    @property
    def is_current_published_version(self) -> bool:
        return self.current_published_version_id == self.version.id
    
    @property
    def total_chunk_count(self) -> int:
        return self.embedding_coverage.total_chunk_count


    @property
    def embedded_chunk_count(self) -> int:
        return self.embedding_coverage.embedded_chunk_count


    @property
    def is_fully_embedded(self) -> bool:
        return self.embedding_coverage.is_fully_embedded

class GetKnowledgeVersion:
    """
    Return one knowledge version together with its parent document.

    This administrative query requires an authenticated administrator.
    Transport schemas remain responsible for selecting safe response fields.
    """
    def __init__(self, *, uow_factory: KnowledgeUnitOfWorkFactory, embedding_provider: EmbeddingProviderDescriptor, embedding_input_descriptor: EmbeddingInputDescriptor) -> None:
        if not isinstance(embedding_provider, EmbeddingProviderDescriptor):
            raise TypeError("embedding_provider must be an EmbeddingProviderDescriptor")

        if not isinstance(embedding_input_descriptor, EmbeddingInputDescriptor):
            raise TypeError("embedding_input_descriptor must be an EmbeddingInputDescriptor")

        self._uow_factory = uow_factory
        self._embedding_provider = embedding_provider
        self._embedding_input_descriptor = embedding_input_descriptor

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
            embedding_coverage = uow.embeddings.get_coverage_for_version(
                version.id, provider=self._embedding_provider, input_descriptor=self._embedding_input_descriptor
            )

        return GetKnowledgeVersionResult(
            document=document,
            version=version,
            current_published_version_id=published.id if published is not None else None,
            embedding_coverage=embedding_coverage,
        )