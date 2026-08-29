from __future__ import annotations
from uuid import UUID
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from packages.database.models.knowledge.chunk import KnowledgeChunkModel
from packages.database.repositories.knowledge.mappers import chunk_to_domain, chunk_to_model
from packages.knowledge.domain.chunk import KnowledgeChunk


class SQLAlchemyKnowledgeChunkRepository:
    """
    SQLAlchemy/PostgreSQL implementation of knowledge-chunk persistence.

    Chunks are derived artifacts belonging to a specific document version.
    Transaction ownership remains with the surrounding Unit of Work.
    """
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, chunk: KnowledgeChunk) -> None:
        """
        Stage one new chunk for persistence.

        Does not flush or commit.
        """
        self._session.add(chunk_to_model(chunk))

    def add_many(self, chunks: list[KnowledgeChunk]) -> None:
        """
        Stage multiple chunks efficiently in the current transaction.

        Empty input is treated as a no-op.
        """
        if not chunks:
            return

        models = [chunk_to_model(chunk) for chunk in chunks]
        self._session.add_all(models)

    def get_by_id(self, chunk_id: UUID) -> KnowledgeChunk | None:
        model = self._session.get(KnowledgeChunkModel, chunk_id)
        if model is None:
            return None

        return chunk_to_domain(model)

    def list_for_version(self, version_id: UUID) -> list[KnowledgeChunk]:
        statement = (select(KnowledgeChunkModel)
                     .where(KnowledgeChunkModel.version_id == version_id)
                     .order_by(KnowledgeChunkModel.chunk_index.asc())
        )
        
        models = self._session.scalars(statement).all()

        return [chunk_to_domain(model) for model in models]

    def delete_for_version(self, version_id: UUID) -> None:
        """
        Delete all derived chunks for a version.

        Intended for reprocessing unpublished versions. No commit is
        performed here.
        """
        statement = delete(KnowledgeChunkModel).where(KnowledgeChunkModel.version_id == version_id)
        self._session.execute(statement)