# Embeddings

## Overview

The `packages/knowledge/embeddings/` package is the **embedding subsystem of the knowledge layer**.

It provides the common models, provider abstraction, provider resolution, validation, and supporting infrastructure required to convert knowledge content and retrieval queries into vector representations.

```text
packages/
└── knowledge/
    └── embeddings/
        ├── models.py
        ├── resolver.py
        ├── errors.py
        ├── provider/
        └── ...
```

The package deliberately separates **embedding contracts and domain models** from concrete provider implementations and from the higher-level ingestion/retrieval workflows.

---

## Responsibilities

The embeddings package is responsible for:

* defining provider-independent embedding models;
* describing embedding-provider identity and configuration;
* representing prepared embedding inputs;
* representing individual vectors and batches;
* defining the common `EmbeddingProvider` contract;
* resolving configured providers by stable provider ID;
* integrating concrete embedding providers;
* validating embedding dimensions and response structure;
* translating provider-specific failures into domain exceptions;
* supporting deterministic providers for testing/local development;
* providing query-embedding caching and provider instrumentation.

It is **not responsible for**:

* chunking or canonical knowledge preparation;
* vector-database search;
* retrieval ranking or reranking;
* grounding;
* LLM generation;
* answer generation;
* application-level orchestration.

Those concerns consume the embedding abstractions rather than belonging to this package.

---

# Architecture

At a high level:

```text
                    Knowledge Content / User Query
                               │
                               ▼
                       Embedding Subsystem
                               │
             ┌─────────────────┼─────────────────┐
             │                 │                 │
             ▼                 ▼                 ▼
          Models            Provider          Resolver
             │                 │                 │
             │          ┌──────┴──────┐          │
             │          ▼             ▼          │
             │        Jina      Deterministic    │
             │          │             │          │
             │          └──────┬──────┘          │
             │                 │                 │
             └─────────────────┼─────────────────┘
                               ▼
                         Embedding Output
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
              Persistence             Retrieval
```

The provider layer additionally supports instrumentation and query-embedding caching.

---

# Core Building Blocks

## `models.py`

`models.py` contains the provider-independent data contracts used throughout the subsystem.

Important models include:

| Model                         | Purpose                                                |
| ----------------------------- | ------------------------------------------------------ |
| `EmbeddingProviderDescriptor` | Stable identity of the embedding provider/model        |
| `EmbeddingInputDescriptor`    | Identity of the strategy used to construct model input |
| `PreparedEmbeddingInput`      | Exact text prepared for one knowledge chunk            |
| `EmbeddingVector`             | Immutable numerical vector                             |
| `DocumentEmbedding`           | Vector associated with a particular input index        |
| `EmbeddingBatch`              | Provider-normalized batch of document embeddings       |

The provider descriptor captures:

```text
provider
model
revision
dimensions
```

and exposes a stable identity used for provenance and compatibility decisions.

The input descriptor separately identifies the preparation strategy and its version/configuration. This is important because changing how knowledge text is prepared can require re-embedding even when the underlying model remains unchanged.

`EmbeddingVector` is immutable and validates that vectors contain finite numerical values.

`EmbeddingBatch` preserves the relationship between provider responses and input positions while enforcing provider dimensionality.

---

# Provider Abstraction

## `provider/base.py`

The `EmbeddingProvider` abstraction defines the common interface that all embedding implementations must satisfy.

Its primary operations are:

```text
descriptor
embed_documents(...)
embed_query(...)
health_check()
```

The distinction between document and query embeddings is intentional because embedding models may use different task configurations or representations for indexed content and retrieval queries.

Document embedding must preserve input-to-output correspondence and provider dimensionality, while provider-specific failures must be translated into the embedding error hierarchy.

Higher layers should depend on this abstraction rather than directly on a provider SDK.

---

# Provider Implementations

The current provider layer supports two important implementations.

```text
EmbeddingProvider
      │
      ├── JinaEmbeddingProvider
      │
      └── DeterministicEmbeddingProvider
```

### Jina

The Jina implementation provides the external embedding-provider integration used for actual embedding generation.

It is responsible for provider-specific concerns such as:

* request construction;
* document/query task selection;
* external API communication;
* response validation;
* provider error translation.

The rest of the knowledge system interacts with the provider contract rather than directly with Jina.

### Deterministic

The deterministic provider is intended for:

* tests;
* local development;
* contract verification;
* deterministic fixtures.

It produces repeatable vectors without external API calls and deliberately does **not** attempt to represent real semantic similarity. It must not be treated as a production retrieval model.

---

# Provider Resolution

## `resolver.py`

`EmbeddingProviderResolver` provides the composition-time registry for configured providers.

```text
configured providers
        │
        ▼
EmbeddingProviderResolver
        │
        ▼
resolve("provider-id")
        │
        ▼
EmbeddingProvider
```

Providers are identified through their descriptor's `provider` field.

The registry is immutable after construction, and provider IDs are normalized for case-insensitive lookup. Duplicate provider IDs are rejected.
This keeps provider selection out of retrieval and ingestion business logic.

---

# Embedding Identity

Embedding identity is a first-class concept in this package.

A vector is not identified merely by its dimensionality.

The effective embedding profile includes information such as:

```text
Provider
Model
Revision
Dimensions
Input Strategy
Input Strategy Version
Input Configuration
```

This allows persisted embeddings to remain auditable and prevents vectors generated under incompatible configurations from being treated as interchangeable.

```text
Embedding Profile
├── Provider Descriptor
│   ├── provider
│   ├── model
│   ├── revision
│   └── dimensions
│
└── Input Descriptor
    ├── strategy_id
    ├── version
    └── config_fingerprint
```

The lower-level provider design explicitly treats provider identity and input strategy as compatibility information rather than merely diagnostic metadata.

---

# Document Embedding Flow

The document-ingestion path conceptually follows:

```text
Canonical Knowledge Content
          │
          ▼
Embedding Input Preparation
          │
          ▼
PreparedEmbeddingInput
          │
          ▼
EmbeddingProvider
          │
          ▼
EmbeddingBatch
          │
          ▼
Embedding Persistence
```

The embeddings package supplies the contracts and provider boundary for this flow.

Higher-level ingestion components remain responsible for deciding:

* what content should be embedded;
* how chunks are prepared;
* when embedding should occur;
* where generated embeddings are persisted.

---

# Query Embedding Flow

Retrieval uses a similar but separate path:

```text
User Query
    │
    ▼
Retrieval Query Preparation
    │
    ▼
EmbeddingProvider.embed_query()
    │
    ▼
EmbeddingVector
    │
    ▼
Vector Retrieval
```

The provider layer may add:

```text
Instrumentation
      +
Query Embedding Cache
```

around this operation.

The retrieval layer then uses the resulting vector for vector search; the embeddings package itself does not perform retrieval.

---

# Instrumentation and Caching

The provider infrastructure includes cross-cutting capabilities that can be composed around providers.

```text
                 EmbeddingProvider
                       │
                       ▼
            Instrumented Provider
                       │
              ┌────────┴────────┐
              ▼                 ▼
        Query Cache         Telemetry
              │
              ▼
        Actual Provider
```

Instrumentation records provider-call lifecycle information without changing provider semantics.

The query cache provides process-local reuse of retrieval-query embeddings using bounded TTL/LRU storage and concurrent-request coalescing.

The cache is provider-aware and uses an opaque hash-based key derived from provider identity and the exact query text.

---

# Error Handling

The embeddings package establishes a domain-level error boundary around provider failures.

Conceptually:

```text
External Provider / SDK
          │
          ▼
Provider Adapter
          │
          ▼
Embedding Exceptions
          │
          ▼
Knowledge / Retrieval Layer
```

Higher layers should therefore not need to understand provider-specific HTTP, SDK, or transport exceptions.

Typical validation/error categories include:

* invalid embedding input;
* provider resolution failure;
* provider unavailable;
* timeout;
* authentication/authorization failure;
* rate limiting;
* malformed provider response;
* response cardinality mismatch;
* invalid vector;
* dimension mismatch.

This keeps failures predictable across different provider implementations.

---

# Validation and Invariants

The subsystem maintains several important invariants.

### Provider contract

All implementations expose the same provider-facing API.

### Dimension consistency

```text
EmbeddingVector.dimensions
        ==
EmbeddingProviderDescriptor.dimensions
```

### Batch correspondence

Every document input must remain associated with the correct `input_index`.

### Stable provider identity

The descriptor must accurately describe the provider/model configuration that generated the vectors.

### Input identity

Embedding preparation strategy is tracked independently from model identity.

### Query/document separation

```text
embed_documents()
        ≠
embed_query()
```

### Error translation

Provider-specific implementation errors do not leak through the provider abstraction.

These invariants allow ingestion, persistence, and retrieval components to remain provider-independent.

---

# Provider Extensibility

Adding a new embedding provider should require implementing the existing provider contract rather than modifying retrieval or ingestion logic.

```text
EmbeddingProvider
      │
      ├── Jina
      ├── Deterministic
      └── Future Provider
```

A new provider should provide:

1. a correct `EmbeddingProviderDescriptor`;
2. document embedding support;
3. query embedding support;
4. dimensionality validation;
5. input/output correspondence;
6. translation into the embedding error hierarchy.

The rest of the knowledge system should remain unaware of provider-specific SDK details.

---

# Relationship With Other Knowledge Components

The embeddings package sits between **knowledge preparation/persistence** and **retrieval**.

```text
                    Knowledge Layer
                          │
          ┌───────────────┴────────────────┐
          │                                │
          ▼                                ▼
   Knowledge Ingestion               Retrieval
          │                                │
          ▼                                ▼
   Prepared Content                    Query
          │                                │
          └──────────────┬─────────────────┘
                         ▼
                  Embeddings Package
                         │
                         ▼
                EmbeddingProvider
                         │
                         ▼
                  Vector Outputs
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
        Persistence              Retrieval
```

The package therefore acts as a shared technical boundary rather than owning either end-to-end workflow.

---

# Privacy and Data Minimization

The embedding infrastructure is designed so that observability and caching do not unnecessarily retain raw customer content.

Provider telemetry can use:

```text
call IDs
trace IDs
provider/model identity
latency
status
error metadata
query fingerprints
```

while avoiding persistence of raw query text and embedding vectors in telemetry.

The query cache similarly uses a hashed cache key rather than retaining the raw query as its cache key.

Provider credentials and secrets remain configuration concerns and should not become part of embedding artifacts or telemetry.

---

# Testing Strategy

The package supports testing at several levels:

```text
Provider Contract Tests
        │
        ├── Descriptor
        ├── Document Embedding
        ├── Query Embedding
        └── Error Semantics
                │
                ▼
Concrete Provider Tests
        │
        ├── Jina API behavior
        └── Deterministic behavior
                │
                ▼
Infrastructure Tests
        │
        ├── Resolver
        ├── Instrumentation
        └── Query Cache
```

The deterministic provider is particularly useful for tests that require repeatable vectors without external API dependencies.

---

# Architectural Boundaries

The embeddings package **owns**:

```text
Embedding models
Provider contracts
Provider implementations
Provider resolution
Embedding validation
Embedding-domain errors
Provider instrumentation
Query embedding cache
```

It **does not own**:

```text
Knowledge chunking
Knowledge versioning
Vector database access
Similarity search
Hybrid retrieval
Reranking
Grounding
LLM calls
Answer generation
Application orchestration
```

This separation is intentional and keeps the embedding subsystem independently replaceable.

---

# Key Design Principles

### Provider independence

Application and knowledge components depend on `EmbeddingProvider`, not vendor SDKs.

### Explicit identity

Provider/model/revision/dimensions and input-preparation identity are tracked explicitly.

### Immutable contracts

Core embedding models are immutable value objects.

### Strict validation

Malformed vectors, mismatched dimensions, invalid batches, and provider response inconsistencies are rejected early.

### Document/query separation

The system explicitly distinguishes embeddings generated for indexed content from embeddings generated for retrieval queries.

### Replaceable providers

Concrete providers can be added or replaced without changing retrieval or ingestion interfaces.

### Operational isolation

Caching and instrumentation remain provider infrastructure rather than becoming responsibilities of retrieval logic.

### Privacy-aware infrastructure

Telemetry and query caching avoid unnecessary retention of raw customer content.

---

# Summary

`packages/knowledge/embeddings/` is the **central embedding boundary of the knowledge subsystem**.

Its architecture can be summarized as:

```text
                    Embeddings
                        │
        ┌───────────────┼────────────────┐
        │               │                │
        ▼               ▼                ▼
      Models         Providers        Resolver
        │               │                │
        │        ┌──────┴──────┐         │
        │        ▼             ▼         │
        │      Jina      Deterministic   │
        │        │             │         │
        └────────┴──────┬──────┘         │
                        ▼                │
                  Vector Output ◄────────┘
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
         Persistence          Retrieval
```

The lower-level packages provide the detailed implementation mechanics, while this package as a whole establishes the stable boundary through which the knowledge system:

* represents embeddings;
* identifies embedding configurations;
* prepares provider-neutral embedding contracts;
* resolves providers;
* generates document and query vectors;
* validates provider results;
* handles embedding-specific failures;
* supports provider instrumentation;
* caches repeated query embeddings;
* remains independent of any particular embedding vendor.

This makes the embeddings subsystem a **replaceable, auditable, and provider-independent foundation** for both knowledge ingestion and vector-based retrieval.
