# AI-customer-support-agent\packages\config\settings.py
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from datetime import timedelta
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "support-ai"
    
    # Authentication
    auth_jwt_secret: str
    auth_jwt_issuer: str = "support-ai"
    auth_jwt_audience: str = "support-ai-api"
    auth_access_token_ttl_minutes: int = 15
    auth_refresh_token_ttl_days: int = 30
    auth_clock_skew_seconds: int = 30
    auth_login_max_failed_attempts: int = 5
    auth_login_lockout_minutes: int = 15

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
    
    ## Embeddings
    embedding_provider: str = "jina"
    embedding_dimensions: int = 1024
    embedding_batch_size: int = 16
    
    ## Jina / Embeddings
    jina_api_key: str | None = None
    jina_embedding_model: str = "jina-embeddings-v4"
    jina_embedding_timeout_seconds: float = 30.0
    
    ## RAG / Grounding
    rag_context_max_tokens: int = 6000
    rag_context_max_blocks: int = 8
    
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    @model_validator(mode="after")
    def validate_provider_configuration(self) -> "Settings":
        self.llm_provider = self.llm_provider.strip().lower()
        self.embedding_provider = self.embedding_provider.strip().lower()
        
        self.auth_jwt_secret = self.auth_jwt_secret.strip()
        self.auth_jwt_issuer = self.auth_jwt_issuer.strip()
        self.auth_jwt_audience = self.auth_jwt_audience.strip()

        if len(self.auth_jwt_secret.encode("utf-8")) < 32:
            raise ValueError("auth_jwt_secret must contain at least 32 UTF-8 encoded bytes.")

        if not self.auth_jwt_issuer:
            raise ValueError("auth_jwt_issuer must not be blank.")

        if not self.auth_jwt_audience:
            raise ValueError("auth_jwt_audience must not be blank.")

        if self.auth_access_token_ttl_minutes <= 0:
            raise ValueError("auth_access_token_ttl_minutes must be greater than zero.")

        if self.auth_refresh_token_ttl_days <= 0:
            raise ValueError("auth_refresh_token_ttl_days must be greater than zero.")

        if self.auth_clock_skew_seconds < 0:
            raise ValueError("auth_clock_skew_seconds cannot be negative.")

        if self.auth_login_max_failed_attempts <= 0:
            raise ValueError("auth_login_max_failed_attempts must be greater than zero.")

        if self.auth_login_lockout_minutes <= 0:
            raise ValueError("auth_login_lockout_minutes must be greater than zero.")

        if not self.llm_provider:
            raise ValueError("llm_provider must not be blank.")

        if not self.embedding_provider:
            raise ValueError("embedding_provider must not be blank.")

        if self.embedding_provider == "jina" and (self.jina_api_key is None or not self.jina_api_key.strip()):
            raise ValueError("jina_api_key must be configured when embedding_provider='jina'.")

        if self.embedding_dimensions <= 0:
            raise ValueError("embedding_dimensions must be greater than zero.")

        if self.embedding_batch_size <= 0:
            raise ValueError("embedding_batch_size must be greater than zero.")

        if self.jina_embedding_timeout_seconds <= 0:
            raise ValueError("jina_embedding_timeout_seconds must be greater than zero.")

        if not self.jina_embedding_model or not self.jina_embedding_model.strip():
            raise ValueError("jina_embedding_model must not be blank.")

        self.jina_embedding_model = self.jina_embedding_model.strip()
        
        if self.rag_context_max_tokens <= 0:
            raise ValueError("rag_context_max_tokens must be greater than zero.")

        if self.rag_context_max_blocks <= 0:
            raise ValueError("rag_context_max_blocks must be greater than zero.")
        
        return self
    
    @property
    def auth_access_token_ttl(self) -> timedelta:
        return timedelta(minutes=self.auth_access_token_ttl_minutes)

    @property
    def auth_refresh_token_ttl(self) -> timedelta:
        return timedelta(days=self.auth_refresh_token_ttl_days)

    @property
    def auth_login_lockout_duration(self) -> timedelta:
        return timedelta(minutes=self.auth_login_lockout_minutes)
    
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