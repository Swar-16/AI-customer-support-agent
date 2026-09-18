# AI-customer-support-agent\packages\database\repositories\knowledge\scoped_retrieval_repositories.py
from __future__ import annotations
from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self
from sqlalchemy.orm import Session

from packages.database.repositories.knowledge.lexical_retrieval_repository import SQLAlchemyLexicalRetrievalRepository
from packages.database.repositories.knowledge.vector_retrieval_repository import SQLAlchemyVectorRetrievalRepository
from packages.knowledge.retrieval.lexical.repository import LexicalRetrievalRepository, LexicalSearchMatch, LexicalSearchRequest
from packages.knowledge.retrieval.vector.repository import VectorRetrievalRepository, VectorSearchMatch, VectorSearchRequest

class RetrievalReadUnitOfWork(Protocol):
    """
    Minimal UoW contract required for one short retrieval query.

    Exiting without commit intentionally rolls back the SQLAlchemy read transaction and closes its session.
    """
    session: Session | None

    def __enter__(self) -> Self:
        ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        ...

RetrievalReadUnitOfWorkFactory = Callable[[], RetrievalReadUnitOfWork,]

class ScopedSQLAlchemyLexicalRetrievalRepository(LexicalRetrievalRepository):
    """
    Execute one lexical search inside one short-lived read transaction.

    No Session or ORM object escapes search().
    """
    def __init__(self, *, uow_factory: RetrievalReadUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def search(self, request: LexicalSearchRequest) -> tuple[LexicalSearchMatch, ...]:
        if not isinstance(request, LexicalSearchRequest):
            raise TypeError("request must be a LexicalSearchRequest")

        with self._uow_factory() as uow:
            session = self._require_session(uow)
            repository = SQLAlchemyLexicalRetrievalRepository(session=session)
            # Conversion to immutable retrieval-domain objects occurs
            # before the session closes.
            return repository.search(request)

    @staticmethod
    def _require_session(uow: RetrievalReadUnitOfWork) -> Session:
        session = uow.session

        if session is None:
            raise RuntimeError("Retrieval read Unit of Work did not provide an active Session")

        if not isinstance(session, Session):
            raise TypeError("uow.session must be a SQLAlchemy Session")

        return session

class ScopedSQLAlchemyVectorRetrievalRepository(VectorRetrievalRepository):
    """
    Execute one vector search inside one short-lived read transaction.

    Query embedding generation happens before this repository is called, while reranking and generation happen
    after search() has returned and the read session has closed.
    """
    def __init__(self, *, uow_factory: RetrievalReadUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def search(self, request: VectorSearchRequest) -> tuple[VectorSearchMatch, ...]:
        if not isinstance(request, VectorSearchRequest):
            raise TypeError("request must be a VectorSearchRequest")

        with self._uow_factory() as uow:
            session = self._require_session(uow)
            repository = SQLAlchemyVectorRetrievalRepository(session=session)

            return repository.search(request)

    @staticmethod
    def _require_session(uow: RetrievalReadUnitOfWork) -> Session:
        session = uow.session
        if session is None:
            raise RuntimeError("Retrieval read Unit of Work did not provide an active Session")

        if not isinstance(session, Session):
            raise TypeError("uow.session must be a SQLAlchemy Session")

        return session