from __future__ import annotations
from types import TracebackType
from typing import Self
from sqlalchemy.orm import Session, sessionmaker

from packages.database.repositories.knowledge import SQLAlchemyKnowledgeChunkRepository, SQLAlchemyKnowledgeDocumentRepository
from packages.database.repositories.knowledge import SQLAlchemyKnowledgeEmbeddingRepository,SQLAlchemyKnowledgeVersionRepository


class SQLAlchemyKnowledgeUnitOfWork:
    """
    SQLAlchemy implementation of the Knowledge Unit of Work.

    A UoW represents one transactional boundary. All knowledge repositories exposed by this object share the same
    SQLAlchemy Session and therefore the same database transaction.

    Transaction policy:
        - entering creates a fresh Session
        - commit must be explicit
        - exceptions cause rollback
        - leaving without commit also rolls back any active transaction
        - the Session is always closed
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._documents: SQLAlchemyKnowledgeDocumentRepository | None = None
        self._versions: SQLAlchemyKnowledgeVersionRepository | None = None
        self._chunks: SQLAlchemyKnowledgeChunkRepository | None = None
        self._embeddings: SQLAlchemyKnowledgeEmbeddingRepository | None = None

    # Context manager
    def __enter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Knowledge Unit of Work is already active.")

        session = self._session_factory()
        self._session = session
        self._documents = SQLAlchemyKnowledgeDocumentRepository(session)
        self._versions = SQLAlchemyKnowledgeVersionRepository(session)
        self._chunks = SQLAlchemyKnowledgeChunkRepository(session)
        self._embeddings = SQLAlchemyKnowledgeEmbeddingRepository(session)

        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        session = self._session

        if session is None:
            return

        try:
            # An exception must never leave a transaction partially applied.
            if exc_type is not None:
                session.rollback()

            # Explicit-commit semantics:
            # Even on a successful code path, uncommitted work must not accidentally survive merely because the context was exited.
            elif session.in_transaction():
                session.rollback()

        finally:
            session.close()
            self._session = None
            self._documents = None
            self._versions = None
            self._chunks = None
            self._embeddings = None

    # Repositories
    @property
    def documents(self) -> SQLAlchemyKnowledgeDocumentRepository:
        if self._documents is None:
            raise RuntimeError("Knowledge Unit of Work is not active. Use it inside a 'with' block.")

        return self._documents

    @property
    def versions(self) -> SQLAlchemyKnowledgeVersionRepository:
        if self._versions is None:
            raise RuntimeError("Knowledge Unit of Work is not active. Use it inside a 'with' block.")

        return self._versions

    @property
    def chunks(self) -> SQLAlchemyKnowledgeChunkRepository:
        if self._chunks is None:
            raise RuntimeError("Knowledge Unit of Work is not active. Use it inside a 'with' block.")

        return self._chunks

    @property
    def embeddings(self) -> SQLAlchemyKnowledgeEmbeddingRepository:
        if self._embeddings is None:
            raise RuntimeError("Knowledge Unit of Work is not active. Use it inside a 'with' block.")

        return self._embeddings

    # Transaction control
    def commit(self) -> None:
        self._require_session().commit()

    def rollback(self) -> None:
        session = self._require_session()

        if session.in_transaction():
            session.rollback()

    def flush(self) -> None:
        """
        Synchronize pending ORM changes with PostgreSQL without committing.

        Useful when an application service needs database-generated effects, FK validation, or constraint checking before continuing.
        """
        self._require_session().flush()

    # Internal helpers
    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Knowledge Unit of Work is not active. Use it inside a 'with' block.")

        return self._session