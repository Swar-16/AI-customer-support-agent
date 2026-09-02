from __future__ import annotations
from typing import Any
from sqlalchemy import Select, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from packages.database.models.knowledge.chunk import KnowledgeChunkModel
from packages.database.models.knowledge.chunk_embedding import KnowledgeChunkEmbeddingModel
from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.document_version import KnowledgeDocumentVersionModel
from packages.knowledge.domain.enums import KnowledgeDocumentStatus, KnowledgeIngestionStatus, KnowledgeVersionStatus
from packages.knowledge.retrieval.errors import VectorRetrievalRepositoryError
from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalMethod
from packages.knowledge.retrieval.vector.repository import VectorRetrievalRepository, VectorSearchMatch, VectorSearchRequest


class SQLAlchemyVectorRetrievalRepository(VectorRetrievalRepository):
    """
    PostgreSQL/pgvector implementation of semantic knowledge retrieval.

    Responsibilities:
      - search stored chunk embeddings using cosine distance;
      - match the exact embedding artifact profile;
      - expose only retrieval-ready knowledge;
      - apply caller-supplied business filters;
      - return deterministic, distance-ranked results.

    This repository does not:
      - generate query embeddings;
      - commit or rollback transactions;
      - perform score fusion;
      - rerank;
      - build LLM context.
    """

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session instance.")

        self._session = session

    def search(self, request: VectorSearchRequest) -> tuple[VectorSearchMatch, ...]:
        if not isinstance(request, VectorSearchRequest):
            raise TypeError("request must be a VectorSearchRequest instance.")

        try:
            statement = self._build_search_statement(request)
            rows = self._session.execute(statement).all()

            return tuple(self._row_to_match(row) for row in rows)

        except SQLAlchemyError as exc:
            raise VectorRetrievalRepositoryError("Vector retrieval query failed.") from exc

        except (TypeError, ValueError) as exc:
            # A successfully returned database row that cannot be converted
            # into our retrieval-domain representation indicates invalid or
            # inconsistent persisted retrieval data.
            raise VectorRetrievalRepositoryError("Vector retrieval returned invalid persisted data.") from exc

    def _build_search_statement(self, request: VectorSearchRequest) -> Select[Any]:
        """
        Construct one cosine-distance query over retrieval-ready knowledge.

        The returned statement is read-only and does not mutate transaction state beyond the normal SQLAlchemy read transaction.
        """
        query_vector = list(request.query_vector.values)
        distance = KnowledgeChunkEmbeddingModel.embedding.cosine_distance(query_vector).label("vector_distance")
        
        statement = (select(KnowledgeChunkModel.id.label("chunk_id"),
                            KnowledgeChunkModel.version_id.label("version_id"),
                            KnowledgeDocumentModel.id.label("document_id"),
                            KnowledgeChunkModel.chunk_index.label("chunk_index"),
                            KnowledgeChunkModel.content.label("content"),
                            KnowledgeChunkModel.section_title.label("section_title"),
                            KnowledgeChunkModel.metadata_.label("chunk_metadata"),
                            KnowledgeDocumentModel.title.label("document_title"),
                            distance)
                     .select_from(KnowledgeChunkEmbeddingModel)
                     .join(KnowledgeChunkModel,
                           KnowledgeChunkModel.id == KnowledgeChunkEmbeddingModel.chunk_id)
                     .join(KnowledgeDocumentVersionModel,
                           KnowledgeDocumentVersionModel.id == KnowledgeChunkModel.version_id)
                     .join(KnowledgeDocumentModel,
                           KnowledgeDocumentModel.id == KnowledgeDocumentVersionModel.document_id)
                     .where(KnowledgeDocumentModel.status == KnowledgeDocumentStatus.ACTIVE.value, # Retrieval-readiness invariants
                            KnowledgeDocumentVersionModel.status == KnowledgeVersionStatus.PUBLISHED.value, # Retrieval-readiness invariants
                            KnowledgeDocumentVersionModel.ingestion_status == KnowledgeIngestionStatus.COMPLETED.value, # Retrieval-readiness invariants
                            KnowledgeChunkEmbeddingModel.provider == request.provider.provider, # Exact embedding-provider provenance
                            KnowledgeChunkEmbeddingModel.model == request.provider.model, # Exact embedding-provider provenance
                            KnowledgeChunkEmbeddingModel.dimensions == request.provider.dimensions, # Exact embedding-provider provenance
                            KnowledgeChunkEmbeddingModel.input_strategy_id == request.input_descriptor.strategy_id, # Exact embedding-input construction provenance
                            KnowledgeChunkEmbeddingModel.input_strategy_version == request.input_descriptor.version, # Exact embedding-input construction provenance
                            KnowledgeChunkEmbeddingModel.input_config_fingerprint == request.input_descriptor.config_fingerprint) # Exact embedding-input construction provenance
        )

        statement = self._apply_model_revision_filter(statement=statement, request=request)
        statement = self._apply_business_filters(statement=statement, request=request)

        return statement.order_by(distance.asc(), KnowledgeChunkModel.id.asc(),).limit(request.limit)

    @staticmethod
    def _apply_model_revision_filter(*, statement: Select[Any], request: VectorSearchRequest) -> Select[Any]:
        """
        Match model revision using NULL-safe semantics.

        revision=None means "the persisted artifact must also have no explicit revision", not "ignore revision".
        """
        if request.provider.revision is None:
            return statement.where(KnowledgeChunkEmbeddingModel.model_revision.is_(None))

        return statement.where(KnowledgeChunkEmbeddingModel.model_revision == request.provider.revision)

    @staticmethod
    def _apply_business_filters(*, statement: Select[Any], request: VectorSearchRequest) -> Select[Any]:
        filters = request.filters

        if filters.document_ids:
            statement = statement.where(KnowledgeDocumentModel.id.in_(filters.document_ids))

        if filters.content_types:
            statement = statement.where(KnowledgeDocumentModel.content_type.in_(filters.content_types))

        if filters.visibilities:
            statement = statement.where(KnowledgeDocumentModel.visibility.in_(filters.visibilities))

        if filters.metadata:
            # PostgreSQL JSONB containment:
            #
            #     {"region": "india"}
            #
            # means the document metadata must contain at least those
            # key/value pairs. It does not require metadata equality.
            statement = statement.where(KnowledgeDocumentModel.metadata_.contains(dict(filters.metadata)))

        return statement

    @staticmethod
    def _row_to_match(row: Any) -> VectorSearchMatch:
        """
        Translate a SQL result row into retrieval-domain objects.

        No SQLAlchemy model instance escapes the infrastructure boundary.
        """

        distance = float(row.vector_distance)

        candidate = RetrievalCandidate(
            chunk_id=row.chunk_id,
            version_id=row.version_id,
            document_id=row.document_id,
            chunk_index=row.chunk_index,
            content=row.content,
            document_title=row.document_title,
            section_title=row.section_title,
            methods=frozenset({RetrievalMethod.VECTOR}),
            metadata=(dict(row.chunk_metadata) if row.chunk_metadata is not None else {}),
        )

        return VectorSearchMatch(candidate=candidate, distance=distance)