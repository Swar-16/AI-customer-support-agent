from __future__ import annotations
from types import TracebackType
from typing import Protocol, Self

from packages.knowledge.repositories import KnowledgeChunkRepository, KnowledgeDocumentRepository, KnowledgeVersionRepository, KnowledgeEmbeddingRepository


class KnowledgeUnitOfWorkFactory(Protocol):
    def __call__(self) -> KnowledgeUnitOfWork:
        ...

class KnowledgeUnitOfWork(Protocol):
    @property
    def documents(self) -> KnowledgeDocumentRepository:
        ...

    @property
    def versions(self) -> KnowledgeVersionRepository:
        ...

    @property
    def chunks(self) -> KnowledgeChunkRepository:
        ...
        
    @property
    def embeddings(self) -> KnowledgeEmbeddingRepository:
        ...

    def __enter__(self) -> Self:
        ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...

    def flush(self) -> None:
        ...