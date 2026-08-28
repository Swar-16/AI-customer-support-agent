from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from packages.config.settings import get_settings

def create_session_factory(*, database_url: str | URL, echo: bool = False) -> sessionmaker[Session]:
    """
    Create a SQLAlchemy session factory for the supplied database.

    This function does not open a database connection or Session eagerly.
    Connections are acquired when a Session actually performs database work.
    """
    engine = create_engine(database_url, echo=echo, pool_pre_ping=True)

    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )


# Default application database
settings = get_settings()

SessionLocal = create_session_factory(
    database_url=settings.database_url,
    echo=settings.database_echo,
)