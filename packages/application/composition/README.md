# Application Composition

## Overview

The `packages/application/composition/` package is the **composition root of the application layer**.

Its responsibility is to transform configuration and infrastructure dependencies into fully wired application services.

The package does **not** primarily implement business behavior. Instead, it answers questions such as:

* Which LLM provider should the application use?
* Which embedding provider should be active?
* Which document parsers, normalizers, and chunkers should be registered?
* Which retrieval branches should be enabled?
* How should vector and lexical repositories be constructed?
* How should retrieval, reranking, and grounding be assembled?
* How should knowledge-management use cases be wired?
* How should the grounded answer service connect AI understanding to knowledge retrieval?
* How should request-scoped AI instrumentation be constructed?
* How should the complete application service container be assembled?

The package therefore sits between **configuration/infrastructure** and the **application/domain services**.

```text
                         Configuration
                              │
                              ▼
              ┌───────────────────────────────┐
              │ application/composition       │
              │                               │
              │ Composition Factories         │
              └───────────────┬───────────────┘
                              │
          ┌───────────────────┼────────────────────┐
          │                   │                    │
          ▼                   ▼                    ▼
     AI / LLM            Knowledge              App
     Runtime             Subsystem             Services
          │                   │                    │
          └───────────────────┼────────────────────┘
                              ▼
                    Application Runtime
```

---

# Package Contents

```text
packages/application/composition/
│
├── provider_factory.py
│
├── knowledge_embedding_factory.py
│
├── knowledge_ingestion_factory.py
│
├── knowledge_retrieval_factory.py
│
├── knowledge_application_factory.py
│
├── answer_service_factory.py
│
├── ai_pipeline_factory.py
│
└── application_factory.py
```

Each factory operates at a different composition level.

| File                               | Composition responsibility                                                            |
| ---------------------------------- | ------------------------------------------------------------------------------------- |
| `provider_factory.py`              | Creates the base LLM provider                                                         |
| `knowledge_embedding_factory.py`   | Creates the configured embedding provider and resolver                                |
| `knowledge_ingestion_factory.py`   | Creates parser, normalizer, and chunker strategy graph                                |
| `knowledge_retrieval_factory.py`   | Creates query preparation, vector/lexical retrieval, fusion, reranking, and grounding |
| `knowledge_application_factory.py` | Creates the complete knowledge-management application boundary                        |
| `answer_service_factory.py`        | Connects AI answer generation with knowledge application/retrieval                    |
| `ai_pipeline_factory.py`           | Creates the request-scoped AI orchestration pipeline                                  |
| `application_factory.py`           | Top-level composition root for the long-lived application                             |

---

# 1. Composition Hierarchy

The files form a deliberate hierarchy rather than eight unrelated factories.

```text
application_factory.py
        │
        ├── provider_factory.py
        │
        ├── knowledge_embedding_factory.py
        │
        ├── knowledge_application_factory.py
        │       │
        │       └── knowledge_ingestion_factory.py
        │
        ├── ai_pipeline_factory.py
        │
        └── application services
                │
                └── ProcessCustomerMessage
                        │
                        ├── AI pipeline
                        ├── knowledge application
                        ├── embeddings
                        └── retrieval configuration
```

At request/application-operation scope:

```text
AI Pipeline
    │
    ├── IntentClassifier
    ├── DecisionEngine
    ├── GroundedResponseGenerator
    ├── GuardrailEvaluator
    └── AIOrchestrator
            │
            ▼
      AnswerService
            │
            ├── KnowledgeRetrievalContextService
            ├── RetrievalQueryPreparationService
            ├── BuildGroundingContext
            ├── KnowledgeEvidenceMapper
            └── GroundedResponseGenerator
```

The retrieval implementation itself is composed separately by `knowledge_retrieval_factory.py`.

---

# 2. Composition Philosophy

The package follows several consistent architectural principles.

## 2.1 Configuration belongs at the composition boundary

Concrete implementations should not generally know about:

```text
Settings
environment variables
application configuration
```

Instead:

```text
Settings
   │
   ▼
Factory
   │
   ▼
Concrete implementation
```

For example, `knowledge_embedding_factory.py` explicitly exists as the layer that maps application configuration to concrete embedding-provider implementations.

---

## 2.2 Infrastructure is injected

Factories accept dependencies such as:

```text
Session
UnitOfWork factory
LLMProvider
EmbeddingProvider
Reranker
Telemetry recorder
Token estimator
```

rather than constructing all infrastructure internally.

This allows the same application services to work with:

* production infrastructure;
* test infrastructure;
* mock providers;
* alternate persistence implementations;
* custom observability implementations.

---

## 2.3 Long-lived and request-scoped objects are separated

The application root creates reusable dependencies once.

Request-specific objects are constructed later.

For example, `ApplicationServices` deliberately does not contain:

* active SQLAlchemy sessions;
* UnitOfWork instances;
* request-specific AI runs;
* request-specific telemetry recorders;
* request-specific instrumented LLM providers.

Similarly, `AIPipelineFactory` creates request-scoped instrumented providers for each AI run.

---

# 3. `provider_factory.py`

## Responsibility

`provider_factory.py` creates the application's **base LLM provider**.

Its public entry point is:

```python
create_llm_provider(settings: Settings) -> LLMProvider
```

The returned provider is deliberately **not request-instrumented**. Request-specific `InstrumentedLLMProvider` instances are created later by `AIPipelineFactory`.

---

## Supported Providers

The factory currently supports:

```text
groq
mock
```

Provider names are normalized using:

```python
settings.llm_provider.strip().lower()
```

Unsupported values raise:

```text
ProviderConfigurationError
```

---

## Groq Composition

For Groq, the factory creates:

```text
GroqProvider
       │
       ▼
CapacityLimitedLLMProvider
       │
       ▼
ResilientLLMProvider
```

The capacity wrapper receives:

```text
max_concurrency
queue_timeout_seconds
minimum_start_interval_seconds
```

and the resilience wrapper receives:

```text
max_retries
base_delay_seconds
maximum_delay_seconds
jitter_ratio
```

---

## Groq Configuration

The underlying `GroqProvider` receives:

```text
API key
model
timeout
maximum completion tokens
temperature
```

The temperature is converted through `Decimal`.

A missing or blank API key results in:

```text
ProviderConfigurationError
```

rather than allowing an invalid provider to enter the runtime.

---

## Mock Provider

The mock branch returns:

```python
MockLLMProvider()
```

directly.

This provides a clean dependency-injection path for testing and local development.

---

# 4. `knowledge_embedding_factory.py`

## Responsibility

`knowledge_embedding_factory.py` is the composition boundary for the application's embedding subsystem.

It creates:

```text
EmbeddingProvider
EmbeddingProviderResolver
```

and packages them as:

```python
KnowledgeEmbeddingServices
```

---

## Supported Embedding Providers

The current supported providers are:

```text
jina
deterministic
```

The provider ID is normalized before resolution.

---

## Jina Provider

When:

```text
embedding_provider = jina
```

the factory validates:

```text
Jina API key
embedding model
embedding dimensions
timeout
```

before constructing:

```text
JinaEmbeddingProvider
```

Invalid configuration raises `EmbeddingConfigurationError`.

---

## Deterministic Provider

When:

```text
embedding_provider = deterministic
```

the factory validates the configured embedding dimensions and creates:

```text
DeterministicEmbeddingProvider
```

This provides a deterministic implementation useful for testing and environments where an external embedding provider is unnecessary.

---

## Resolver Construction

The provider is placed into:

```text
EmbeddingProviderResolver
```

The current architecture intentionally creates one active provider/profile.

---

## Provider Instance Reuse

`create_knowledge_embedding_services()` creates the provider once and puts that **same instance** into the resolver.

```text
                 ┌───────────────────┐
                 │ EmbeddingProvider │
                 └────────┬──────────┘
                          │
                 ┌────────┴─────────┐
                 ▼                  ▼
           direct access       resolver
```

This matters for providers that may eventually own:

* HTTP clients;
* connection pools;
* metrics state;
* rate-limit state.

---

# 5. `knowledge_ingestion_factory.py`

## Responsibility

This factory creates the complete document-ingestion strategy graph:

```text
Parser
   ↓
Normalizer
   ↓
Chunker
```

The resulting immutable object is:

```python
KnowledgeIngestionComponents
```

---

## Supported Upload Types

Currently:

```text
Markdown
UTF-8 Plain Text
```

are supported.

PDF, DOCX, and HTML are intentionally not registered as operational strategies. Their enum values may exist for future expansion, but the factory refuses to advertise them until complete parser and normalizer implementations exist.

---

## Parser Graph

```text
Markdown
    → MarkdownStructuralParser

Plain Text
    → PlainTextStructuralParser
```

The strategies are registered through:

```text
DefaultDocumentParserResolver
```

---

## Normalizer Graph

```text
Markdown
    → MarkdownNormalizer

Plain Text
    → PlainTextNormalizer
```

through:

```text
DefaultDocumentNormalizerResolver
```

---

## Chunking

Both supported source types ultimately use:

```text
StructuralTextChunker
```

with an optional:

```text
StructuralTextChunkerConfig
```

---

## Fail-Fast Validation

The factory eagerly resolves every supported strategy during composition:

```python
_resolve_every_strategy(components)
```

This intentionally moves configuration errors from:

```text
first administrator upload
```

to:

```text
application startup
```

---

## Pipeline Validation

For every ingestion stage, the factory verifies:

* resolver type;
* `supported_source_types`;
* valid enum values;
* required source types;
* `supports()`;
* `resolve()`.

Then it resolves each source type and independently verifies the resolved strategy's `supports()` method.

This prevents partially configured pipelines.

---

# 6. `knowledge_retrieval_factory.py`

## Responsibility

This factory composes the complete knowledge retrieval and grounding pipeline.

```text
Retrieval Query
      │
      ▼
Query Preparation
      │
      ▼
Prepared Query
      │
      ├───────────────┐
      ▼               ▼
Vector Retrieval   Lexical Retrieval
      │               │
      └───────┬───────┘
              ▼
             RRF
              │
              ▼
          Reranking
              │
              ▼
      Grounding Context
```

---

## `KnowledgeRetrievalComponents`

The composition result exposes:

```text
query_preparation_service
retrieve_knowledge
build_grounding_context
vector_service
lexical_service
reranking_service
context_builder
```

The individual components remain exposed intentionally for:

* health checks;
* integration tests;
* diagnostics;
* observability;
* controlled application-level customization.

---

## Query Preparation

The factory uses:

```text
DeterministicRetrievalQueryBuilder
```

inside:

```text
RetrievalQueryPreparationService
```

---

## Vector Retrieval

Vector retrieval is created only when:

```text
profile.vector_enabled == True
```

When enabled, both are required:

```text
EmbeddingProvider
EmbeddingInputDescriptor
```

---

## Vector Repository Selection

Two persistence modes are supported.

### Scoped UoW

```text
RetrievalReadUnitOfWorkFactory
          │
          ▼
ScopedSQLAlchemyVectorRetrievalRepository
```

### Direct Session

```text
SQLAlchemy Session
       │
       ▼
SQLAlchemyVectorRetrievalRepository
```

The resulting repository is supplied to:

```text
VectorRetrievalService
```

---

## Lexical Retrieval

Lexical retrieval is enabled through:

```text
profile.lexical_enabled
```

It follows the same repository-selection pattern:

```text
UoW Factory
    → ScopedSQLAlchemyLexicalRetrievalRepository
```

or:

```text
Session
    → SQLAlchemyLexicalRetrievalRepository
```

---

## Persistence Invariant

Exactly one of:

```text
session
retrieval_uow_factory
```

must be supplied.

Both supplied or neither supplied causes:

```text
ValueError
```

---

## Fusion

The factory always creates:

```text
ReciprocalRankFusion(k=profile.rrf_k)
```

and injects it into:

```text
RetrieveKnowledge
```

---

## Reranking

Reranking is conditional:

```text
profile.reranking_enabled
```

If enabled and no custom reranker is supplied:

```text
PassthroughReranker
```

is used.

When a reranker telemetry recorder exists:

```text
Reranker
   ↓
InstrumentedReranker
   ↓
RerankingService
```

---

## Grounding Context

The factory uses:

```text
TokenEstimator
```

and defaults to:

```text
CharacterTokenEstimator
```

when no custom estimator is supplied.

It then creates:

```text
GroundingContextBuilder
```

and:

```text
BuildGroundingContext
```

---

# 7. `knowledge_application_factory.py`

## Responsibility

This factory assembles the **complete knowledge application boundary**.

It combines:

```text
Knowledge UoW
Embedding Provider
Embedding Input Builder
Ingestion
Knowledge CRUD
Version lifecycle
Embedding
Publication
Archival
Retrieval-context translation
```

---

## `KnowledgeApplicationComponents`

The bundle exposes:

### Retrieval bridge

```text
retrieval_context_service
```

### Query services

```text
list_documents
get_document
list_versions
get_version
```

### Mutation services

```text
create_document
create_version
process_version
embed_version
publish_version
archive_document
```

### Upload services

```text
upload_document
upload_version
```

### Ingestion

```text
ingestion
```

---

## Knowledge Lifecycle

The resulting application-level knowledge lifecycle is:

```text
Upload
  │
  ▼
Create Document
  │
  ▼
Create Version
  │
  ▼
Process Version
  │
  ├── parser
  ├── normalizer
  └── chunker
  │
  ▼
Embed Version
  │
  ▼
Publish Version
  │
  ▼
Retrievable Knowledge
```

Archival is handled as a separate lifecycle operation.

---

## Upload Policy

The factory creates:

```text
KnowledgeUploadPolicy
```

from:

```text
knowledge_upload_max_bytes
```

and applies it to both:

```text
UploadKnowledgeDocument
UploadKnowledgeVersion
```

---

## Retrieval Context Bridge

The factory constructs:

```text
AIKnowledgeRetrievalRequestFactory
KnowledgeRetrievalContextFactory
KnowledgeRetrievalContextService
```

The bridge transforms AI-understood customer requests into retrieval-specific context without mutating knowledge.

Conceptually:

```text
AI Intent / Request
       │
       ▼
AIKnowledgeRetrievalRequestFactory
       │
       ▼
KnowledgeRetrievalContextFactory
       │
       ▼
KnowledgeRetrievalContextService
       │
       ▼
RetrievalQueryContext
```

---

## Embedding Integration

`EmbedKnowledgeVersion` receives:

```text
EmbeddingProvider
EmbeddingInputBuilder
embedding_batch_size
```

while version queries receive embedding descriptors.

This makes the embedding factory's provider directly usable by the knowledge application layer.

---

# 8. `answer_service_factory.py`

## Responsibility

This factory connects:

```text
AI-understood request
        ↓
Knowledge retrieval
        ↓
Evidence mapping
        ↓
Grounded response generation
        ↓
AnswerService
```

The composition result is:

```python
AnswerServiceComponents
```

which contains:

```text
answer_service
knowledge_application
knowledge_retrieval
evidence_mapper
```

---

## Main Dependency Graph

```text
SQLAlchemy Session / Retrieval UoW
             │
             ▼
Knowledge Retrieval Infrastructure
             │
             ├── Query Preparation
             ├── Vector Retrieval
             ├── Lexical Retrieval
             ├── Fusion
             ├── Reranking
             └── Grounding Context
                         │
                         ▼
                KnowledgeEvidenceMapper
                         │
                         ▼
              GroundedResponseGenerator
                         │
                         ▼
                    AnswerService
```

This is explicitly represented in the factory's design documentation.

---

## AI → Knowledge Translation

A separate path bridges AI interpretation into knowledge retrieval:

```text
        IntentResult
             │
             ▼
KnowledgeApplicationComponents
             │
             ▼
KnowledgeRetrievalContextService
             │
             ▼
    RetrievalQueryContext
```

This keeps knowledge retrieval independent from the details of AI intent classification.

---

## Dependency Reuse

The factory accepts an optional precomposed:

```text
KnowledgeRetrievalComponents
```

If supplied, the factory uses it directly rather than rebuilding retrieval infrastructure.

Likewise, `KnowledgeEvidenceMapper` can be injected or defaults to a new instance.

---

## Final Answer Service

The actual service is constructed with:

```text
retrieval_context_service
query_preparation_service
build_grounding_context
evidence_mapper
response_generator
```

This makes `AnswerService` the application-level boundary between retrieval/grounding and response generation.

---

# 9. `ai_pipeline_factory.py`

## Responsibility

`ai_pipeline_factory.py` constructs the **request-scoped AI execution graph for one logical AI run**.

Its output is:

```python
AIPipeline
```

The pipeline contains:

```text
AIOrchestrator
IntentClassifier
DecisionEngine
GroundedResponseGenerator
GuardrailEvaluator
Intent InstrumentedLLMProvider
Generation InstrumentedLLMProvider
```

---

# Long-Lived vs Request-Scoped Dependencies

The factory separates dependencies into two categories.

## Long-lived

```text
Base LLM Provider
IntentClassifierConfig
DecisionEngineConfig
AIOrchestratorConfig
GroundedGenerationPromptBuilder
DirectResponseResolver
GuardrailEvaluator
Optional OrchestrationObserver
AIPipelineFactoryConfig
```

## Request-scoped

```text
ai_run_id
LLMCallRecorder
InstrumentedLLMProvider instances
IntentClassifier
GroundedResponseGenerator
DecisionEngine
AIOrchestrator
```

---

# Purpose-Specific LLM Instrumentation

A critical design decision is that one AI run gets multiple instrumented wrappers around the same base provider.

```text
                    Base LLM Provider
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
      Intent Provider            Generation Provider
              │                         │
              │ purpose=                │ purpose=
              │ intent_classification   │ answer_generation
              │                         │
              └──────────┬──────────────┘
                         │
                    Same ai_run_id
```

The wrappers share:

```text
base provider
ai_run_id
LLMCallRecorder
```

but have separate immutable `LLMCallContext` values.

This prevents intent-classification telemetry from being confused with answer-generation telemetry.

---

# Why Instrumented Providers Are Request Scoped

`InstrumentedLLMProvider` carries an immutable context containing:

```text
ai_run_id
purpose
prompt_version_id
temperature
```

Sharing such a wrapper between simultaneous requests could attribute an LLM call to the wrong AI run. Therefore wrappers are created inside:

```python
AIPipelineFactory.create(...)
```

rather than kept globally.

---

# `AIPipelineFactoryConfig`

The configuration distinguishes:

```text
intent_purpose
intent_temperature
intent_prompt_version_id

generation_purpose
generation_temperature
generation_prompt_version_id
```

Purposes must be:

* non-empty;
* distinct.

Temperature must be:

```text
0 <= temperature <= 2
```

when supplied. Prompt-version identifiers must be UUIDs.

Importantly, temperature currently acts as telemetry/context metadata rather than overriding the provider's actual sampling configuration.

---

# AI Pipeline Construction

`create()` performs the following:

```text
Validate AI run
      │
      ▼
Create intent instrumented provider
      │
      ▼
Create generation instrumented provider
      │
      ▼
Create IntentClassifier
      │
      ▼
Create DecisionEngine
      │
      ▼
Create GroundedResponseGenerator
      │
      ▼
Create AnswerService if builder supplied
      │
      ▼
Create orchestration observer
      │
      ▼
Create AIOrchestrator
      │
      ▼
Return AIPipeline
```

The method explicitly does **not** perform provider calls or database commits.

---

# Orchestration Observability

The factory always creates a telemetry observer backed by:

```text
LoggingTelemetrySink
```

and optionally an additional:

```text
stage_event_sink
```

These are combined through:

```text
CompositeTelemetrySink
```

and:

```text
TelemetryOrchestrationObserver
```

If the caller also supplies an observer, the factory wraps both using:

```text
CompositeOrchestrationObserver
```

Therefore:

```text
                    Orchestration
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
      Telemetry Observer      Custom Observer
              │                     │
              └──────────┬──────────┘
                         ▼
             Composite Observer
```

---

# 10. `application_factory.py`

## Responsibility

`application_factory.py` is the **top-level composition root**.

It creates the long-lived:

```python
ApplicationServices
```

container.

This is the file that brings the other composition factories together with the rest of the application.

---

# ApplicationServices

The service container includes major application domains:

### Conversations

```text
AcceptConversationStart
StartConversation
AssignConversationTitle
CreateConversation
ListConversations
GetConversation
GetConversationMessages
ProcessCustomerMessage
CloseConversation
```

### Authentication

```text
RegisterUser
LoginUser
RefreshSession
LogoutUser
AuthenticateAccessToken
GetCurrentUser
UpdateUserAccess
```

### Observability

```text
RecordAPIRequest
```

### Dashboard

```text
GetDashboardOverview
QueryDashboardTraces
GetTraceDetail
QueryDashboardLLMCalls
QueryDashboardRetrievalRuns
QueryDashboardAPIRequests
QueryDashboardAuditEvents
```

### Analytics

```text
GetConversationAnalytics
GetAIAnalytics
GetSupportAnalytics
GetKnowledgeHealth
```

### Audit

```text
GetAuditEvent
ListAuditEvents
GetEntityAuditHistory
GetTraceAuditEvents
```

### Escalations

```text
GetEscalation
ListEscalations
ListConversationEscalations
GetCustomerEscalationStatus
UpdateEscalation
```

### Tickets

```text
CreateTicket
CreateTicketFromEscalation
AddTicketComment
GetTicket
ListTickets
UpdateTicket
```

### Feedback

```text
SubmitFeedback
GetFeedback
ListFeedback
ReviewFeedback
```

### Knowledge

```text
ListKnowledgeDocuments
GetKnowledgeDocument
ListKnowledgeVersions
GetKnowledgeVersion
CreateKnowledgeDocument
CreateKnowledgeVersion
ProcessKnowledgeVersion
EmbedKnowledgeVersion
PublishKnowledgeVersion
ArchiveKnowledgeDocument
UploadKnowledgeDocument
UploadKnowledgeVersion
```

### AI Composition

```text
AIPipelineFactory
LLMProvider
OrchestrationObserver
```

---

# Top-Level Application Construction

The primary function is:

```python
create_application(...)
```

It accepts:

```text
Settings
SessionFactory
optional base LLM provider
optional orchestration observer
```

The composition process begins by resolving:

```text
LLM provider
title provider
orchestration observer
AI pipeline factory
embedding services
```

---

# Database Transaction Factories

The application root creates factory functions rather than long-lived sessions.

## General application UoW

```text
uow_factory()
    ↓
SqlAlchemyUnitOfWork
```

## Knowledge UoW

```text
knowledge_uow_factory()
    ↓
SQLAlchemyKnowledgeUnitOfWork
```

The knowledge UoW exposes transactional access to:

```text
documents
versions
chunks
embeddings
embedding_calls
audit_events
```

This ensures transaction boundaries are created per application operation.

---

# Dashboard Analytics Composition

The application root creates:

```text
SQLAlchemyDashboardAnalyticsRepository
        │
        ▼
CachingDashboardAnalyticsRepository
        │
        ▼
DashboardAnalyticsRepository factory
```

The cache is configured through:

```text
dashboard_analytics_cache_ttl_seconds
dashboard_analytics_cache_max_entries
```

The analytics application services then reuse that repository factory.

---

# Authentication Composition

The root creates:

```text
Argon2PasswordHasher
TokenService
```

The token service is configured from:

```text
JWT secret
issuer
audience
access-token TTL
clock skew
```

The resulting services include:

```text
RegisterUser
LoginUser
RefreshSession
LogoutUser
AuthenticateAccessToken
GetCurrentUser
UpdateUserAccess
```

---

# Ticket and Escalation Composition

Escalation operations share:

```text
ConversationNotificationWriter
```

Ticket creation from escalation reuses:

```text
CreateTicket
```

rather than duplicating ticket-creation logic.

```text
CreateTicket
     ▲
     │
CreateTicketFromEscalation
```

This is an example of composition being used to enforce application-level reuse.

---

# Knowledge Composition at the Application Root

The root calls:

```python
create_knowledge_embedding_services(settings)
```

and then:

```python
create_knowledge_application_components(...)
```

with:

```text
knowledge UoW factory
embedding provider
embedding input builder
embedding batch size
maximum upload bytes
```

This connects:

```text
Embedding Factory
        │
        ▼
Knowledge Application Factory
        │
        ├── ingestion
        ├── document lifecycle
        ├── version lifecycle
        ├── embedding
        ├── publication
        └── retrieval context
```

---

# Customer Message Pipeline

The most important application flow is constructed as:

```text
ProcessCustomerMessage
```

with:

```text
UoW factory
AI pipeline factory
Embedding provider
Embedding input descriptor
Retrieval profile
Grounding context budget
Knowledge application
Conversation context builder
Query embedding cache
```

Conceptually:

```text
Customer Message
       │
       ▼
ProcessCustomerMessage
       │
       ├───────────────┐
       │               │
       ▼               ▼
AI Pipeline       Knowledge Application
       │               │
       │               ▼
       │        Retrieval Context
       │               │
       └───────┬───────┘
               ▼
          AI Orchestrator
               │
               ▼
        Grounded Answer
```

---

# Conversation Start Composition

`StartConversation` combines:

```text
AcceptConversationStart
ProcessCustomerMessage
AssignConversationTitle
```

and receives a configurable processing lease duration.

This allows the application to coordinate conversation-start idempotency, AI processing, and title generation as one application-level workflow.

---

# Conversation Title Provider

Conversation-title generation has its own provider-resolution logic.

When an explicit provider is injected, it is reused.

When production configuration is used and title generation is enabled, the application creates a separate provider configuration with:

```text
shorter timeout
smaller completion-token budget
temperature = 0
```

This prevents title generation from changing the provider limits used by classification and grounded answer generation.

---

# Observer Resolution

The application root allows an observer to be injected.

If none is supplied:

```text
TelemetryOrchestrationObserver
```

is used.

This gives production a default observability implementation while preserving testability and alternate observability implementations.

---

# 11. Complete Dependency Graph

The eight composition files can be understood as one layered graph.

```text
                         Settings
                            │
             ┌──────────────┼───────────────────┐
             │              │                   │
             ▼              ▼                   ▼
      Provider Factory   Embedding       Retrieval Profile
             │           Factory                │
             ▼              │                   │
        Base LLM            ▼                   │
        Provider       Embedding Provider       │
             │              │                   │
             │              │                   │
             ▼              ▼                   ▼
       AI Pipeline    Knowledge App      Retrieval Factory
         Factory          Factory               │
             │              │                   │
             │              ├── Ingestion       │
             │              │   Factory         │
             │              │                   │
             │              └── Retrieval       │
             │                  Context         │
             │                  Bridge          │
             │                                  │
             └──────────────┬───────────────────┘
                            │
                            ▼
                    Answer Service
                       Factory
                            │
                            ▼
                  Application Factory
                            │
                            ▼
                   ApplicationServices
```

---

# 12. End-to-End AI Customer Support Flow

The composition architecture ultimately produces this runtime flow:

```text
                         Customer
                            │
                            ▼
                  ProcessCustomerMessage
                            │
                            ▼
                  ┌──────────────────┐
                  │   AI Pipeline    │
                  └────────┬─────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
          Intent       Decision      Guardrails
        Classifier      Engine       / Policy
              │            │
              └──────┬─────┘
                     ▼
              Knowledge Context
                     │
                     ▼
            Knowledge Application
                     │
                     ▼
         Knowledge Retrieval Context
                     │
                     ▼
           Retrieval Preparation
                     │
           ┌─────────┴─────────┐
           ▼                   ▼
       Vector               Lexical
      Retrieval            Retrieval
           │                   │
           └─────────┬─────────┘
                     ▼
                Rank Fusion
                     │
                     ▼
                 Reranking
                     │
                     ▼
             Grounding Context
                     │
                     ▼
             Evidence Mapping
                     │
                     ▼
            Grounded Response
                Generation
                     │
                     ▼
                   Answer
```

---

# 13. Lifecycle Boundaries

The package intentionally separates three important lifetimes.

## Process Lifetime

Created by:

```text
application_factory.py
```

Examples:

```text
LLM provider
Embedding provider
AIPipelineFactory
ApplicationServices
Analytics repository/cache
```

---

## Application Operation Lifetime

Created by UoW factories:

```text
SqlAlchemyUnitOfWork
SQLAlchemyKnowledgeUnitOfWork
```

These are not retained in `ApplicationServices`.

---

## AI Run Lifetime

Created by:

```text
AIPipelineFactory.create(...)
```

Examples:

```text
ai_run_id
LLMCallRecorder
InstrumentedLLMProvider
IntentClassifier
DecisionEngine
GroundedResponseGenerator
AIOrchestrator
```

---

# 14. Validation Strategy

The factories consistently validate dependencies at composition time.

Examples include:

```text
Settings
LLMProvider
EmbeddingProvider
EmbeddingInputBuilder
RetrievalProfile
GroundingContextBudget
Reranker
TokenEstimator
TelemetryRecorder
UnitOfWork factories
```

Invalid inputs generally result in:

```text
TypeError
ValueError
RuntimeError
Configuration-specific exceptions
```

rather than producing partially valid application objects.

---

# 15. Fail-Fast Design

A recurring architectural principle is:

> **Invalid composition should fail before a real customer request depends on it.**

Examples:

### LLM

```text
Unknown provider
       ↓
ProviderConfigurationError
```

### Embeddings

```text
Missing Jina key
       ↓
EmbeddingConfigurationError
```

### Ingestion

```text
Resolver missing strategy
       ↓
KnowledgeIngestionConfigurationError
```

### Retrieval

```text
Vector retrieval enabled
       +
Missing embedding provider
       ↓
RuntimeError
```

### Persistence

```text
No Session + No UoW
       OR
Session + UoW
       ↓
ValueError
```

---

# 16. Testing and Dependency Injection

The composition layer is designed to be testable.

## LLM

Inject:

```python
base_provider=MockLLMProvider(...)
```

into the application factory.

---

## AI Pipeline

Inject:

```text
LLMProvider
IntentClassifierConfig
DecisionEngineConfig
AIOrchestratorConfig
PromptBuilder
DirectResponseResolver
GuardrailEvaluator
Observer
```

into `AIPipelineFactory`.

---

## Knowledge

Inject:

```text
KnowledgeIngestionComponents
AIKnowledgeRetrievalRequestFactory
KnowledgeRetrievalContextFactory
```

into `KnowledgeApplicationFactory`.

---

## Retrieval

Inject:

```text
EmbeddingProvider
EmbeddingInputDescriptor
Reranker
TokenEstimator
TelemetryRecorder
Retrieval UoW
```

into `KnowledgeRetrievalFactory`.

---

## Answer Service

Inject precomposed:

```text
KnowledgeApplicationComponents
KnowledgeRetrievalComponents
KnowledgeEvidenceMapper
```

when specialized testing or alternate composition is required.

---

# 17. Important Design Invariants

## Provider Factory

* `Settings` is required.
* Provider IDs are normalized.
* Unsupported providers fail explicitly.
* Groq requires a non-empty API key.
* Groq receives capacity limiting.
* Groq receives retry/resilience handling.
* Base providers are not request-instrumented.

---

## Embedding Factory

* Provider IDs must be non-empty strings.
* Only configured providers are constructed.
* Supported providers are `jina` and `deterministic`.
* Jina requires a valid API key.
* Embedding dimensions must be positive.
* Timeout must be positive.
* Provider and resolver share the same provider instance.

---

## Ingestion Factory

* Supported source types are explicitly declared.
* Every supported source requires parser/normalizer/chunker coverage.
* Resolver capability is validated.
* Resolved strategy capability is validated.
* Unsupported formats are not advertised.
* Strategy resolution occurs eagerly.

---

## Retrieval Factory

* Exactly one persistence access mechanism is required.
* Vector retrieval requires embeddings.
* Lexical retrieval can operate without embeddings.
* Reranking is profile-controlled.
* Passthrough reranking is available as a default.
* Telemetry is independently injectable.
* Grounding always has a context budget.
* Token estimation has a default implementation.

---

## Knowledge Application Factory

* Knowledge operations use the knowledge UoW factory.
* Upload size is enforced through `KnowledgeUploadPolicy`.
* Ingestion can be replaced through dependency injection.
* Retrieval context construction is separate from knowledge mutation.
* Embedding provider and input builder are shared with lifecycle services.

---

## Answer Service Factory

* Exactly one retrieval persistence mode is required.
* Knowledge application is required.
* Retrieval can be precomposed.
* Evidence mapping can be injected.
* Grounded generation is supplied explicitly.
* The factory owns composition, not database transaction lifecycle.

---

## AI Pipeline Factory

* Base provider is long-lived.
* Instrumented providers are request-scoped.
* Intent and generation providers have distinct purposes.
* One AI run can use multiple LLM operations.
* LLM call telemetry shares the AI run identity.
* Pipeline construction performs no provider call.
* Pipeline construction performs no database commit.

---

## Application Factory

* Configuration is resolved once at startup.
* Providers are created once where appropriate.
* Sessions are not opened during application composition.
* UoWs are created per application transaction.
* AI instrumentation remains request-scoped.
* The resulting `ApplicationServices` object is long-lived.

---

# 18. What Should and Should Not Be Added Here

## Belongs in `composition/`

Use this package when the concern is:

```text
Which implementation?
How should dependencies be wired?
Which configuration selects it?
Which decorator/wrapper should surround it?
What is the lifetime of this object?
Which infrastructure implementation should be injected?
```

---

## Does Not Belong Here

Business behavior should remain in the relevant application/domain packages.

For example:

```text
How a ticket is created
How an intent is classified
How retrieval scoring works
How a password is hashed
How a document is normalized
How an LLM request is generated
```

should not be implemented inside these factories.

The factory should instead construct the service responsible for that behavior.

---

# 19. Extension Guidelines

## Adding a New LLM Provider

1. Implement the provider under the AI provider package.
2. Add configuration fields to `Settings`.
3. Add provider selection to `provider_factory.py`.
4. Apply required capacity/resilience wrappers.
5. Keep provider implementation independent from `Settings`.

---

## Adding a New Embedding Provider

1. Implement the provider.
2. Add configuration.
3. Add provider resolution in `knowledge_embedding_factory.py`.
4. Validate provider-specific configuration.
5. Add it to the supported-provider set.
6. Preserve the shared provider/resolver instance model.

---

## Adding a New Document Format

A source type should not be advertised until:

```text
Parser
Normalizer
Chunker
```

are all available and validated.

Then update:

```text
SUPPORTED_UPLOAD_SOURCE_TYPES
```

and register the strategies in `knowledge_ingestion_factory.py`.

---

## Adding a New Retrieval Branch

Implement the retrieval service/repository below the composition layer, then extend:

```text
knowledge_retrieval_factory.py
```

to construct the branch according to `RetrievalProfile`.

The factory should remain responsible for **wiring**, not retrieval algorithm implementation.

---

## Adding a New Application Domain Service

Instantiate the service in:

```text
application_factory.py
```

and expose it through:

```text
ApplicationServices
```

if it is intended to be a long-lived application dependency.

---

# 20. Recommended Mental Model

The easiest way to understand this directory is:

```text
provider_factory
        │
        ▼
   "What AI provider?"

knowledge_embedding_factory
        │
        ▼
   "What embedding provider?"

knowledge_ingestion_factory
        │
        ▼
   "How do documents enter the KB?"

knowledge_retrieval_factory
        │
        ▼
   "How does the system retrieve evidence?"

knowledge_application_factory
        │
        ▼
   "How is the knowledge subsystem exposed to the application?"

answer_service_factory
        │
        ▼
   "How do retrieved facts become grounded answers?"

ai_pipeline_factory
        │
        ▼
   "How does one AI run execute and get instrumented?"

application_factory
        │
        ▼
   "How does the entire application get assembled?"
```

---

# 21. Final Architecture

The complete composition architecture can be summarized as:

```text
                         ┌──────────────┐
                         │   Settings   │
                         └──────┬───────┘
                                │
              ┌─────────────────┼──────────────────┐
              │                 │                  │
              ▼                 ▼                  ▼
       Provider Factory   Embedding Factory   App Configuration
              │                 │                  │
              ▼                 ▼                  │
         Base LLM         Embedding Provider       │
              │                 │                  │
              └─────────┬───────┘                  │
                        │                          │
                        ▼                          │
                AI / Knowledge                     │
                 Composition                       │
                        │                          │
        ┌───────────────┼──────────────┐           │
        │               │              │           │
        ▼               ▼              ▼           │
   AI Pipeline      Knowledge       Retrieval      │
     Factory       Application       Factory       │
        │             Factory           │          │
        │                │              │          │
        │                ├── Ingestion  │          │
        │                │    Factory   │          │
        │                │              │          │
        │                └──────────────┤          │
        │                               │          │
        └───────────────┬───────────────┘          │
                        ▼                          │
                 Answer Service                    │
                    Factory                        │
                        │                          │
                        └────────────┬─────────────┘
                                     ▼
                            Application Factory
                                     │
                                     ▼
                           ApplicationServices
                                     │
                                     ▼
                           Application Runtime
```

The key architectural rule is:

> **`composition/` owns object-graph construction and lifecycle boundaries; the services it constructs own the actual application behavior.**

That separation is what allows the rest of the application to depend on stable abstractions while infrastructure choices, configuration, decorators, telemetry, repositories, providers, and runtime lifetimes remain centralized in one composition layer.
