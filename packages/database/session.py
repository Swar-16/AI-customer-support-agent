from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.config.settings import get_settings


settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)