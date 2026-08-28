from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "support-ai"

    ## Database
    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str
    database_user: str = "support_ai_admin"
    database_password: str
    database_echo: bool = False
    
    llm_provider: str = "groq"
    
    ## Groq / LLM
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-20b"
    groq_timeout_seconds: float = 30.0
    groq_max_completion_tokens: int = 1024
    groq_temperature: float = 0.0
    
    model_config = SettingsConfigDict(
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

ENV_FILES = {
    "development": ".env",
    "test": ".env.test",
    "production": ".env.production",
}        
        
@lru_cache
def get_settings(environment: str = "development") -> Settings:
    try:
        env_file = ENV_FILES[environment]
    except KeyError as exc:
        raise ValueError(f"Unsupported environment: {environment!r}. Expected one of {tuple(ENV_FILES)}.") from exc
    
    return Settings(
        _env_file=Path(env_file),
        _env_file_encoding="utf-8",
        app_env=environment,
    )