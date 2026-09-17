# AI-customer-support-agent\packages\config\settings.py
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from datetime import timedelta
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL
from urllib.parse import urlsplit

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
    browser_allowed_origins: tuple[str, ...] = ()
    auth_refresh_cookie_secure: bool = True

    ## Database
    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str
    database_user: str = "support_ai_admin"
    database_password: str
    database_echo: bool = False
    
    # Dashboard analytics
    dashboard_analytics_statement_timeout_ms: int = 5_000
    dashboard_analytics_cache_ttl_seconds: int = 15
    dashboard_analytics_cache_max_entries: int = 256
    
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
    
    ## Knowledge uploads
    knowledge_upload_max_bytes: int = 1_048_576  # 1 MiB
    
    ## Jina / Embeddings
    jina_api_key: str | None = None
    jina_embedding_model: str = "jina-embeddings-v4"
    jina_embedding_timeout_seconds: float = 30.0
    
    ## RAG / Grounding
    rag_context_max_tokens: int = 6000
    rag_context_max_blocks: int = 8
    
    ## Conversation context
    conversation_context_max_messages: int = 12
    conversation_context_max_characters: int = 8_000
    conversation_context_max_characters_per_message: int = 2_000
    
    # Idempotent conversation start
    conversation_start_idempotency_ttl_seconds: int = Field(
        default=86_400,
        ge=300,
        le=604_800,
        description="How long a customer-scoped conversation-start idempotency record remains replayable.",
    )
    conversation_start_processing_lease_seconds: int = Field(
        default=120,
        ge=15,
        le=600,
        description="Duration for which one request owns conversation-start AI processing before an abandoned attempt may be reclaimed.",
    )
    
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
        
        if self.dashboard_analytics_statement_timeout_ms <= 0:
            raise ValueError("dashboard_analytics_statement_timeout_ms must be greater than zero.")

        if self.dashboard_analytics_statement_timeout_ms > 120_000:
            raise ValueError("dashboard_analytics_statement_timeout_ms cannot exceed 120000 milliseconds.")
        
        if self.dashboard_analytics_cache_ttl_seconds < 0:
            raise ValueError("dashboard_analytics_cache_ttl_seconds cannot be negative.")

        if self.dashboard_analytics_cache_ttl_seconds > 300:
            raise ValueError("dashboard_analytics_cache_ttl_seconds cannot exceed 300 seconds.")

        if self.dashboard_analytics_cache_max_entries <= 0:
            raise ValueError("dashboard_analytics_cache_max_entries must be greater than zero.")

        if self.dashboard_analytics_cache_max_entries > 4_096:
            raise ValueError("dashboard_analytics_cache_max_entries cannot exceed 4096.")

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
        
        if self.knowledge_upload_max_bytes <= 0:
            raise ValueError("knowledge_upload_max_bytes must be greater than zero.")

        if self.knowledge_upload_max_bytes > 10 * 1_024 * 1_024:
            raise ValueError("knowledge_upload_max_bytes cannot exceed 10 MiB.")
        
        if self.rag_context_max_tokens <= 0:
            raise ValueError("rag_context_max_tokens must be greater than zero.")

        if self.rag_context_max_blocks <= 0:
            raise ValueError("rag_context_max_blocks must be greater than zero.")
        
        if self.conversation_context_max_messages <= 0:
            raise ValueError("conversation_context_max_messages must be greater than zero.")

        if self.conversation_context_max_characters <= 0:
            raise ValueError("conversation_context_max_characters must be greater than zero.")

        if self.conversation_context_max_characters_per_message <= 0:
            raise ValueError("conversation_context_max_characters_per_message must be greater than zero.")

        if self.conversation_context_max_characters_per_message > self.conversation_context_max_characters:
            raise ValueError("conversation_context_max_characters_per_message cannot exceed conversation_context_max_characters.")

        if self.conversation_context_max_messages > 100:
            raise ValueError("conversation_context_max_messages cannot exceed 100.")

        if self.conversation_context_max_characters > 30_000:
            raise ValueError("conversation_context_max_characters cannot exceed 30000.")
        
        return self
    
    @model_validator(mode="after")
    def validate_browser_configuration(self) -> "Settings":
        environment = self.app_env.strip().lower()
        local_environment = environment in {"development", "test"}
        if not self.auth_refresh_cookie_secure and not local_environment:
            raise ValueError("Refresh cookies must be secure outside development and test.")

        normalized_origins: list[str] = []

        for origin in self.browser_allowed_origins:
            if not origin or origin != origin.strip() or any(character.isspace() for character in origin) or any(character in origin for character in ("*", "\\", "?", "#")):
                raise ValueError("Browser origins must be explicit HTTP(S) origins.")

            try:
                parsed = urlsplit(origin)
                port = parsed.port
                
            except ValueError as exc:
                raise ValueError("Browser origin is malformed.") from exc

            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment):
                raise ValueError("Browser origins must contain only scheme, host, and optional port.")

            hostname = parsed.hostname.lower()
            if parsed.scheme == "http" and (not local_environment or hostname not in {"localhost", "127.0.0.1", "::1"}):
                raise ValueError("HTTP browser origins are allowed only for loopback development and test.")

            if parsed.netloc.endswith(":") or (port is not None and port < 1):
                raise ValueError("Browser origin port is invalid.")

            host = f"[{hostname}]" if ":" in hostname else hostname
            default_port = 80 if parsed.scheme == "http" else 443
            port_suffix = f":{port}" if port is not None and port != default_port else ""
            normalized = f"{parsed.scheme}://{host}{port_suffix}"
            if normalized not in normalized_origins:
                normalized_origins.append(normalized)

        self.browser_allowed_origins = tuple(normalized_origins)
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