# Configuration

## Overview

The `packages/config` package provides the **centralized, typed configuration system** for the AI customer-support application.

It is responsible for:

* loading configuration from environment-specific `.env` files;
* defining application-wide settings;
* validating configuration at startup;
* constructing derived configuration values;
* configuring authentication;
* configuring PostgreSQL;
* configuring LLM providers;
* configuring embedding providers;
* configuring retrieval and RAG limits;
* configuring provider concurrency and retry behavior;
* configuring conversation-title generation;
* configuring browser/security settings;
* providing a cached application settings object.

The configuration layer is intentionally centralized so that other packages can consume validated configuration rather than reading environment variables directly.

---

# Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── config/
        ├── settings.py
        └── README.md
```

The primary implementation is:

```text
settings.py
```

which defines the `Settings` model and the `get_settings()` factory.

---

# Architectural Role

The configuration package sits underneath the application's major components.

```text
                    Application
                        │
                        ▼
                ┌───────────────┐
                │ packages/     │
                │ config        │
                └───────┬───────┘
                        │
        ┌───────────────┼────────────────┐
        │               │                │
        ▼               ▼                ▼
   Application        AI Package     Infrastructure
        │               │                │
        ├── Auth        ├── LLM           ├── Database
        ├── API         ├── Retrieval     ├── Cache
        ├── Dashboard   ├── Embeddings    └── ...
        └── ...         └── Telemetry
```

Consumers should depend on the validated `Settings` object rather than independently parsing environment variables.

---

# Configuration Loading Model

Configuration is environment-aware.

The supported environments are:

```text
development
test
production
```

Each environment maps to a dedicated environment file:

```text
development → .env
test        → .env.test
production  → .env.production
```

The mapping is explicitly defined by `ENV_FILES`.

Conceptually:

```text
                  environment
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    development       test      production
          │            │            │
          ▼            ▼            ▼
        .env       .env.test   .env.production
          │            │            │
          └────────────┼────────────┘
                       ▼
                    Settings
```

---

# `Settings`

The central configuration object is:

```python
class Settings(BaseSettings):
    ...
```

It inherits from Pydantic Settings:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
```

This provides typed environment-backed configuration with Pydantic validation.

---

# Base Application Configuration

The application-level settings include:

```text
app_env
app_name
```

Current defaults are:

```text
app_env  = "development"
app_name = "support-ai"
```

`app_env` determines which environment configuration is loaded.

---

# Authentication Configuration

Authentication-related configuration includes:

```text
auth_jwt_secret
auth_jwt_issuer
auth_jwt_audience
auth_access_token_ttl_minutes
auth_refresh_token_ttl_days
auth_clock_skew_seconds
auth_login_max_failed_attempts
auth_login_lockout_minutes
browser_allowed_origins
auth_refresh_cookie_secure
```

Current defaults include:

```text
issuer                    = "support-ai"
audience                  = "support-ai-api"
access token TTL          = 15 minutes
refresh token TTL         = 30 days
clock skew                = 30 seconds
maximum failed attempts   = 5
login lockout             = 15 minutes
refresh cookie secure     = true
```

The JWT secret itself is required rather than given a default.

---

# Authentication Validation

The configuration layer validates security-sensitive authentication settings.

For example:

```text
auth_jwt_secret
```

must contain at least 32 UTF-8 encoded bytes.

The issuer and audience must also be non-empty.

Authentication TTL values must be positive. Login lockout configuration must also be valid and positive.

This ensures invalid security configuration fails during settings validation instead of surfacing later during request processing.

---

# Browser Security Configuration

The configuration package also validates:

```text
browser_allowed_origins
auth_refresh_cookie_secure
```

Browser origins must be explicit HTTP(S) origins.

The validation rejects origins containing:

```text
whitespace
*
\
?
#
```

and rejects credentials, paths, query strings, or fragments in browser origins.

---

# Development/Test HTTP Restriction

Plain HTTP browser origins are permitted only for local development/test loopback hosts:

```text
localhost
127.0.0.1
::1
```

Outside development/test, HTTP origins are rejected.

This creates an explicit distinction between:

```text
Local development
      │
      └── HTTP loopback allowed

Production
      │
      └── HTTPS required
```

---

# Database Configuration

Database settings include:

```text
database_host
database_port
database_name
database_user
database_password
database_echo
```

Current defaults include:

```text
host       = localhost
port       = 5432
user       = support_ai_admin
echo       = false
```

The database name and password are required configuration values.

---

# Database URL Construction

The settings object exposes a derived:

```python
database_url
```

property.

It constructs a SQLAlchemy `URL` using:

```text
drivername = postgresql+psycopg
```

and the configured:

```text
username
password
host
port
database
```

Conceptually:

```text
database configuration
        │
        ▼
┌─────────────────────────┐
│ Settings.database_url   │
└────────────┬────────────┘
             │
             ▼
postgresql+psycopg://...
```

This keeps connection-string construction centralized.

---

# Dashboard Analytics Configuration

Dashboard analytics settings include:

```text
dashboard_analytics_statement_timeout_ms
dashboard_analytics_cache_ttl_seconds
dashboard_analytics_cache_max_entries
```

Current defaults are:

```text
statement timeout = 5 seconds
cache TTL         = 15 seconds
cache entries     = 256
```

The settings are additionally bounded during validation.

For example, the analytics statement timeout must be positive and cannot exceed 120 seconds. The cache TTL cannot exceed 300 seconds, and cache capacity must remain within the configured upper bound.

---

# LLM Provider Configuration

The active LLM provider is selected through:

```text
llm_provider
```

The current default is:

```text
groq
```

Provider-specific configuration is kept alongside the provider selection.

---

# Groq / LLM Settings

The current Groq configuration includes:

```text
groq_api_key
groq_model
groq_timeout_seconds
groq_max_completion_tokens
groq_temperature
```

Current defaults include:

```text
model                 = openai/gpt-oss-20b
timeout               = 30 seconds
max completion tokens = 1024
temperature           = 0.0
```

The API key is optional at the settings-schema level because provider availability can be handled by the consuming provider layer.

---

# Provider Capacity Protection

The configuration also controls process-local provider capacity:

```text
ai_provider_max_concurrency
ai_provider_queue_timeout_seconds
ai_provider_minimum_start_interval_seconds
```

Current defaults are:

```text
maximum concurrency       = 2
queue timeout             = 8 seconds
minimum start interval   = 0.75 seconds
```

These values allow the application to place explicit limits around outbound AI provider usage.

---

# Provider Retry Configuration

Retry behavior is separately configurable:

```text
ai_provider_max_retries
ai_provider_retry_base_delay_seconds
ai_provider_retry_maximum_delay_seconds
ai_provider_retry_jitter_ratio
```

Current defaults are:

```text
max retries       = 1
base delay        = 0.75 seconds
maximum delay     = 8 seconds
jitter ratio      = 0.20
```

The important architectural distinction is that provider configuration can describe retry limits without forcing retry behavior into the provider adapter itself.

---

# Provider Concurrency Validation

The settings validator requires:

```text
1 <= ai_provider_max_concurrency <= 32
```

and requires a positive provider queue timeout.

The minimum start interval cannot be negative and the queue timeout cannot exceed 60 seconds.

This prevents obviously unsafe or nonsensical provider-capacity configurations.

---

# Conversation Title Configuration

Conversation-title generation has its own settings:

```text
conversation_title_enabled
conversation_title_max_input_characters
conversation_title_timeout_seconds
conversation_title_max_completion_tokens
```

Current defaults are:

```text
enabled              = true
maximum input        = 2,000 characters
timeout              = 4 seconds
maximum completion   = 32 tokens
```

These values are consumed by the conversation-title subsystem rather than being hard-coded into the generator.

---

# Embedding Configuration

Embedding configuration includes:

```text
embedding_provider
embedding_dimensions
embedding_batch_size
```

Current defaults are:

```text
provider     = jina
dimensions   = 1024
batch size   = 16
```

This allows the application to select an embedding provider and maintain a single source of truth for expected vector dimensions.

---

# Knowledge Upload Configuration

Knowledge uploads are bounded by:

```text
knowledge_upload_max_bytes
```

The current default is:

```text
1,048,576 bytes
```

which is:

```text
1 MiB
```

The validator requires this value to be greater than zero and prevents it from exceeding 10 MiB.

This establishes a configuration-level safety boundary for knowledge ingestion.

---

# Jina Embedding Configuration

Jina-specific configuration includes:

```text
jina_api_key
jina_embedding_model
jina_embedding_timeout_seconds
```

Current defaults include:

```text
model   = jina-embeddings-v4
timeout = 30 seconds
```

The API key is optional at the settings model level.

---

# Query Embedding Cache

The configuration also contains a process-local retrieval-query embedding cache setting:

```text
query_embedding_cache_ttl_seconds
```

The current default is:

```text
3,600 seconds
```

or:

```text
1 hour
```

This setting belongs to retrieval performance configuration rather than persistent database caching.

---

# RAG Context Limits

The settings model also defines limits around the amount of knowledge context supplied to the AI system.

Important settings include:

```text
rag_context_max_tokens
rag_context_max_blocks
rag_context_max_blocks_per_document
```

The validator requires all relevant limits to be positive and enforces:

```text
rag_context_max_blocks_per_document
    <=
rag_context_max_blocks
```

These limits prevent a single document or retrieval result from dominating the entire grounding context.

---

# Conversation Context Limits

Conversation history is also bounded through:

```text
conversation_context_max_messages
conversation_context_max_characters
conversation_context_max_characters_per_message
```

The validator requires these values to be positive and enforces:

```text
per-message character limit
    <=
total conversation character limit
```

It also caps:

```text
conversation_context_max_messages <= 100
conversation_context_max_characters <= 30,000
```

This provides a configuration-level protection against unbounded context growth.

---

# Configuration Normalization

Before validation completes, important provider/security strings are normalized.

The validator strips and lowercases provider names:

```text
llm_provider
embedding_provider
```

and strips security-sensitive values such as:

```text
auth_jwt_secret
auth_jwt_issuer
auth_jwt_audience
```

This ensures configuration values are normalized before consumers use them.

---

# Pydantic Settings Configuration

The settings model uses:

```python
SettingsConfigDict(
    env_file_encoding="utf-8",
    case_sensitive=False,
    extra="ignore",
)
```

Therefore:

* environment files are interpreted as UTF-8;
* environment variable names are not case-sensitive;
* unspecified extra settings do not cause validation failures.

---

# Environment Selection

The public configuration factory is:

```python
get_settings(environment: str = "development")
```

The function first resolves the environment through `ENV_FILES`.

Unsupported environments raise a `ValueError`.

Supported values are:

```text
development
test
production
```

This prevents accidental use of arbitrary environment filenames.

---

# Cached Settings

`get_settings()` is decorated with:

```python
@lru_cache
```

This means repeated calls for the same environment reuse the same `Settings` instance instead of reconstructing configuration every time.

Conceptually:

```text
get_settings("development")
        │
        ▼
    first call
        │
        ▼
  Settings created
        │
        ▼
      cache
```

Subsequent calls:

```text
get_settings("development")
        │
        ▼
 cached Settings
```

This is particularly useful because configuration is generally application-scoped and should not be reparsed during every request.

---

# Derived Time Configuration

Several configuration values are stored as simple numeric settings but exposed as richer Python objects.

For example:

```python
auth_access_token_ttl
```

returns:

```python
timedelta(minutes=...)
```

while:

```python
auth_refresh_token_ttl
```

returns:

```python
timedelta(days=...)
```

Likewise:

```python
auth_login_lockout_duration
```

returns a `timedelta`.

This provides a clean separation between:

```text
Environment representation
        │
        ▼
integer configuration
        │
        ▼
Application representation
        │
        ▼
timedelta
```

---

# Validation Strategy

Configuration validation is performed at the settings boundary rather than being distributed throughout the application.

The validator checks several categories.

## Type correctness

Values must have the expected Python types.

For example, concurrency limits reject booleans even though `bool` is technically a subclass of `int` in Python.

---

## Range correctness

Numeric settings are checked against sensible lower and upper bounds.

Examples include:

```text
JWT secret length
token TTLs
provider concurrency
provider queue timeout
dashboard timeout
cache capacity
RAG context limits
conversation context limits
knowledge upload size
```

---

## Cross-field correctness

Some settings are valid only relative to another setting.

Examples:

```text
rag_context_max_blocks_per_document
    <= rag_context_max_blocks
```

and:

```text
conversation_context_max_characters_per_message
    <= conversation_context_max_characters
```

---

## Environment-aware security validation

Security behavior depends on the selected environment.

For example, insecure refresh cookies are rejected outside:

```text
development
test
```

---

# Configuration Flow

The overall configuration lifecycle is:

```text
Process Environment
       │
       ▼
Environment Name
       │
       ▼
ENV_FILES
       │
       ├── .env
       ├── .env.test
       └── .env.production
       │
       ▼
Pydantic Settings
       │
       ▼
Type Validation
       │
       ▼
Cross-field Validation
       │
       ▼
Security Validation
       │
       ▼
Normalized Settings
       │
       ▼
Cached Settings Instance
       │
       ├────────► Database
       ├────────► Authentication
       ├────────► AI Providers
       ├────────► Retrieval
       ├────────► Embeddings
       ├────────► Knowledge
       └────────► Application Services
```

---

# Configuration Consumers

The configuration package is intended to be consumed by multiple layers.

Examples include:

```text
Database
   └── database_url

Authentication
   ├── JWT configuration
   ├── token TTLs
   └── cookie/security settings

LLM
   ├── provider
   ├── API key
   ├── model
   ├── timeout
   └── generation limits

Embeddings
   ├── provider
   ├── dimensions
   ├── batch size
   └── API key/model

Retrieval
   ├── RAG limits
   ├── embedding cache
   └── context limits

Knowledge
   └── upload size limits

Dashboard
   ├── statement timeout
   └── cache configuration

Conversation Title
   ├── enabled
   ├── input limit
   ├── timeout
   └── output limit
```

---

# Relationship With the AI Package

The configuration package is outside `packages/ai`, but it directly supports it.

```text
packages/
├── config/
│   └── settings.py
│
└── ai/
    ├── orchestration/
    ├── intent/
    ├── decision/
    ├── retrieval/
    ├── generation/
    └── telemetry/
```

The dependency direction is:

```text
packages.ai
     │
     │ consumes
     ▼
packages.config
```

For example, AI provider construction can use:

```text
llm_provider
groq_api_key
groq_model
groq_timeout_seconds
groq_max_completion_tokens
groq_temperature
```

while embedding/retrieval components can use:

```text
embedding_provider
embedding_dimensions
embedding_batch_size
jina_api_key
jina_embedding_model
jina_embedding_timeout_seconds
rag_context_*
query_embedding_cache_*
```

---

# Configuration vs Component Configuration

Not every configuration value belongs in `packages/config`.

There is an important distinction between:

### Application configuration

Global environment/application configuration belongs here:

```text
database credentials
provider API keys
environment
global limits
security settings
provider defaults
```

### Component configuration

A highly local, immutable behavior configuration can remain within its component.

For example, the AI orchestrator has its own:

```python
AIOrchestratorConfig
```

with:

```text
pipeline_version = "v1"
```

The orchestrator configuration describes the AI pipeline itself, while `packages/config` describes environment/application configuration.

This distinction prevents `Settings` from becoming a container for every possible class-level option.

---

# Secrets

The following types of values should be treated as secrets:

```text
auth_jwt_secret
database_password
groq_api_key
jina_api_key
```

They should be supplied through environment-specific secret management rather than committed to source control.

The settings model defines the fields but does not itself provide secret storage.

---

# Example Environment Layout

A typical project-level arrangement is:

```text
AI-customer-support-agent/
├── .env
├── .env.test
├── .env.production
└── packages/
    └── config/
        ├── settings.py
        └── README.md
```

The configuration package determines which file to load based on the requested environment.

---

# Example Configuration Usage

Consumers should obtain configuration through the centralized factory:

```python
from packages.config.settings import get_settings

settings = get_settings("development")
```

Then use the validated object:

```python
settings.database_url
settings.llm_provider
settings.groq_model
settings.embedding_provider
settings.embedding_dimensions
```

rather than repeatedly accessing environment variables directly.

---

# Database Consumer Example

A database layer can consume:

```python
settings.database_url
```

instead of reconstructing:

```text
postgresql+psycopg://...
```

itself.

This centralizes database configuration and avoids duplicating environment parsing logic.

---

# AI Provider Consumer Example

An LLM provider can consume:

```text
settings.groq_api_key
settings.groq_model
settings.groq_timeout_seconds
settings.groq_max_completion_tokens
settings.groq_temperature
```

The provider then converts those validated settings into its provider-specific configuration object.

The provider itself should not own global application configuration.

For example, the Groq adapter is responsible for invoking Groq and normalizing provider responses, but explicitly does not own persistence, telemetry timing, retry policy, pricing, or intent logic.

---

# Configuration and Retry Responsibility

The settings package defines retry parameters:

```text
ai_provider_max_retries
ai_provider_retry_base_delay_seconds
ai_provider_retry_maximum_delay_seconds
ai_provider_retry_jitter_ratio
```

but configuration does not execute retries.

The actual resilience layer should consume these values.

This maintains the distinction:

```text
Configuration
     │
     └── describes retry policy

Resilience Layer
     │
     └── executes retry policy
```

---

# Configuration and Telemetry

Telemetry can consume configuration indirectly to identify:

```text
provider
model
pipeline version
retrieval profile
```

However, telemetry should not persist secrets.

For example:

```text
provider = groq
model = openai/gpt-oss-20b
```

may be useful operational metadata.

But:

```text
groq_api_key
database_password
auth_jwt_secret
```

must never be emitted as telemetry.

---

# Configuration and Privacy

Some configuration values themselves define privacy boundaries.

Examples include:

```text
knowledge_upload_max_bytes
rag_context_max_tokens
rag_context_max_blocks
conversation_context_max_messages
conversation_context_max_characters
conversation_context_max_characters_per_message
```

These limits control how much user or knowledge-base data can flow through AI processing.

Therefore configuration is not merely convenience infrastructure; it also provides important operational and safety boundaries.

---

# Configuration and Environment Safety

The same application code can run under:

```text
development
test
production
```

while changing:

```text
database
credentials
security behavior
browser origins
provider configuration
timeouts
limits
```

through environment-specific configuration.

This avoids hardcoding deployment-specific behavior into application modules.

---

# Testing Configuration

The `test` environment uses:

```text
.env.test
```

rather than the development environment file.

This gives tests an explicit configuration boundary and avoids accidentally connecting to development resources when test configuration is expected.

Unsupported environment names fail immediately through `get_settings()` rather than silently falling back to another environment.

---

# Maintenance Guidelines

## Adding a new global setting

When adding a new application-wide configuration value:

1. Add it to `Settings`.
2. Give it a sensible type.
3. Provide a default only when a safe default exists.
4. Add validation where required.
5. Add cross-field validation if necessary.
6. Document it in the relevant environment configuration.
7. Update this README if it represents a new configuration domain.

---

## Adding a secret

Do not provide a source-code default.

Use:

```python
some_api_key: str
```

or an appropriately optional field when the provider itself may be disabled.

Never commit actual credentials to:

```text
.env
.env.test
.env.production
```

or source control.

---

## Adding an environment

Update:

```python
ENV_FILES
```

and ensure the corresponding environment semantics are explicitly validated.

Do not accept arbitrary environment names without a deliberate configuration mapping.

---

## Adding validation

Prefer validation inside the `Settings` model when the rule describes:

```text
configuration correctness
```

rather than adding repeated checks across consumers.

For example:

```text
invalid timeout
invalid provider name
invalid context limit
invalid browser origin
```

belongs at configuration validation.

---

# Common Failure Modes

## Unsupported environment

```text
get_settings("staging")
```

will fail unless `staging` is explicitly added to `ENV_FILES`.

---

## Missing required secret

Required fields such as:

```text
auth_jwt_secret
database_name
database_password
```

must be supplied by the environment.

---

## Invalid browser origin

Malformed or overly broad browser origins are rejected during validation.

---

## Invalid provider capacity

Values outside the allowed concurrency/timeout ranges fail validation.

---

## Invalid context limits

Contradictory RAG or conversation-context limits fail validation before the application starts using them.

---

# Design Principles

The configuration package follows several important principles.

## 1. One configuration boundary

Environment parsing happens centrally.

---

## 2. Typed configuration

Settings are represented as typed Python fields rather than raw strings.

---

## 3. Fail fast

Invalid configuration should fail during initialization rather than producing obscure runtime failures.

---

## 4. Environment-aware security

Security rules can vary appropriately by environment while production receives stricter validation.

---

## 5. Derived values

Consumers should receive useful application-level objects such as:

```text
SQLAlchemy URL
timedelta
normalized origins
```

instead of reconstructing them independently.

---

## 6. Cached access

Application-wide settings are cached through `lru_cache`.

---

## 7. Secrets stay external

Credentials are supplied through environment/secret management rather than hardcoded.

---

## 8. Configuration does not execute policy

Configuration describes limits and behavior; individual components remain responsible for executing that behavior.

---

# Summary

`packages/config` is the application's **central typed configuration boundary**.

Its primary implementation, `settings.py`, provides:

```text
Environment Selection
        │
        ▼
Environment File Loading
        │
        ▼
Pydantic Settings
        │
        ▼
Type Validation
        │
        ▼
Cross-field Validation
        │
        ▼
Security Validation
        │
        ▼
Normalized Settings
        │
        ▼
Cached Application Configuration
```

The configuration model covers the major application domains:

```text
┌─────────────────────────────────────────────┐
│                Settings                     │
├─────────────────────────────────────────────┤
│ Application                                 │
│ Authentication                              │
│ Browser Security                            │
│ PostgreSQL                                  │
│ Dashboard Analytics                         │
│ LLM / Groq                                  │
│ Provider Capacity & Retry                   │
│ Conversation Titles                         │
│ Embeddings / Jina                           │
│ Knowledge Uploads                           │
│ RAG Context                                 │
│ Conversation Context                        │
│ Retrieval Query Cache                       │
└─────────────────────────────────────────────┘
```

The package's core responsibility is to ensure that every consuming subsystem receives **validated, normalized, environment-appropriate configuration from one authoritative source** rather than independently interpreting environment variables.

This makes configuration behavior predictable across development, testing, and production while keeping security constraints, AI limits, provider settings, database connectivity, and application-level operational parameters centralized and auditable.
