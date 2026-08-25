from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "support-ai"

    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "support_ai"
    database_user: str = "support_ai_admin"
    database_password: str
    database_echo: bool = False
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    @property
    def database_url(self) -> URL:
        return URL.create(
        drivername="postgresql+psycopg",
        username=self.database_user,
        password=self.database_password,
        host=self.database_host,
        port=self.database_port,
        database=self.database_name,
    )
        
@lru_cache
def get_settings() -> Settings:
    return Settings()