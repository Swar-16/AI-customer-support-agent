from __future__ import annotations
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from packages.database.models.knowledge.chunk_embedding import KnowledgeChunkEmbeddingModel
from packages.database.repositories.knowledge.mappers import chunk_embedding_to_domain, chunk_embedding_to_model
from packages.knowledge.domain.embedding import KnowledgeChunkEmbedding
from packages.knowledge.embeddings.models import EmbeddingInputDescriptor, EmbeddingProviderDescriptor


class SQLAlchemyKnowledgeEmbeddingRepository:
    """
    SQLAlchemy/PostgreSQL implementation of knowledge embedding persistence.

    Embeddings are immutable, model-dependent artifacts derived from knowledge chunks.
    Transaction ownership remains with the surrounding Unit of Work.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, embedding: KnowledgeChunkEmbedding) -> None:
        """
        Stage one embedding artifact for persistence.

        Does not flush or commit.
        """
        self._session.add(chunk_embedding_to_model(embedding))

    def add_many(self, embeddings: list[KnowledgeChunkEmbedding]) -> None:
        """
        Stage multiple embedding artifacts in the current transaction.

        Empty input is treated as a no-op.
        """
        if not embeddings:
            return

        models = [chunk_embedding_to_model(embedding) for embedding in embeddings]
        self._session.add_all(models)
        
    def add_many_if_absent(self, embeddings: list[KnowledgeChunkEmbedding]) -> int:
            """
            Insert immutable embedding artifacts idempotently.
    
            Concurrent workers may independently generate the same logical artifact. PostgreSQL's unique constraint is the final authority.
    
            Returns:
                Number of rows actually inserted.
    
            This method does not commit.
            """
            if not embeddings:
                return 0
    
            values = [
                {
                    "id": embedding.id,
                    "chunk_id": embedding.chunk_id,
                    "provider": embedding.provider.provider,
                    "model": embedding.provider.model,
                    "model_revision": embedding.provider.revision,
                    "dimensions": embedding.provider.dimensions,
                    "embedding": list(embedding.vector.values),
                    "input_strategy_id": embedding.input_descriptor.strategy_id,
                    "input_strategy_version": embedding.input_descriptor.version,
                    "input_config_fingerprint": embedding.input_descriptor.config_fingerprint,
                    "input_fingerprint": embedding.input_fingerprint,
                }
                for embedding in embeddings
            ]
    
            statement = (insert(KnowledgeChunkEmbeddingModel)
                         .values(values)
                         .on_conflict_do_nothing(constraint="uq_knowledge_chunk_embeddings_artifact")
                         .returning(KnowledgeChunkEmbeddingModel.id)
            )
    
            inserted_ids = list(self._session.scalars(statement))
    
            return len(inserted_ids)
    

    def get_by_id(self, embedding_id: UUID) -> KnowledgeChunkEmbedding | None:
        model = self._session.get(KnowledgeChunkEmbeddingModel, embedding_id)
        if model is None:
            return None

        return chunk_embedding_to_domain(model)
    
    def list_for_chunk(self, chunk_id: UUID) -> list[KnowledgeChunkEmbedding]:
        statement = (select(KnowledgeChunkEmbeddingModel)
                     .where(KnowledgeChunkEmbeddingModel.chunk_id == chunk_id)
                     .order_by(KnowledgeChunkEmbeddingModel.created_at.asc(), KnowledgeChunkEmbeddingModel.id.asc())
        )
        models = self._session.scalars(statement).all()
        
        return [chunk_embedding_to_domain(model) for model in models]

    def list_for_chunks(self, chunk_ids: list[UUID], *, provider: EmbeddingProviderDescriptor, input_descriptor: EmbeddingInputDescriptor) -> list[KnowledgeChunkEmbedding]:
        """
        Return existing embedding artifacts for the supplied chunks under one exact embedding/input profile.

        Empty chunk input is treated as a no-op and avoids generating an unnecessary SQL IN expression.
        """
        if not chunk_ids:
            return []

        statement = (select(KnowledgeChunkEmbeddingModel)
                     .where(KnowledgeChunkEmbeddingModel.chunk_id.in_(chunk_ids),
                            KnowledgeChunkEmbeddingModel.provider == provider.provider,
                            KnowledgeChunkEmbeddingModel.model == provider.model,
                            KnowledgeChunkEmbeddingModel.dimensions == provider.dimensions,
                            KnowledgeChunkEmbeddingModel.input_strategy_id == input_descriptor.strategy_id,
                            KnowledgeChunkEmbeddingModel.input_strategy_version == input_descriptor.version,
                            KnowledgeChunkEmbeddingModel.input_config_fingerprint == input_descriptor.config_fingerprint)
        )

        if provider.revision is None:
            statement = statement.where(KnowledgeChunkEmbeddingModel.model_revision.is_(None))
        else:
            statement = statement.where(KnowledgeChunkEmbeddingModel.model_revision == provider.revision)

        statement = statement.order_by(KnowledgeChunkEmbeddingModel.chunk_id.asc(), KnowledgeChunkEmbeddingModel.created_at.asc())
        models = self._session.scalars(statement).all()

        return [chunk_embedding_to_domain(model) for model in models]