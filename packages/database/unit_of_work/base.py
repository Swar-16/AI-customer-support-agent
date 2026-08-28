## Application code should eventually depend on the UoW abstraction, not directly on SQLAlchemy.
from __future__ import annotations
from typing import Protocol

class UnitOfWork(Protocol):
    """
    Transaction boundary used by application services.

    Application code should depend on this contract rather than directly
    depending on SQLAlchemy session management.
    """
    def __enter__(self) -> "UnitOfWork":
        ...

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...

    def flush(self) -> None:
        ...