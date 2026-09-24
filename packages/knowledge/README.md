# Knowledge

## Overview

The `packages/knowledge/` package is the **complete knowledge-base subsystem** of the AI customer-support agent.

It is responsible for the full lifecycle of trusted support knowledge:

```text
Create / Upload
      │
      ▼
Knowledge Document
      │
      ▼
Knowledge Version
      │
      ▼
    Ingestion
(parse → normalize → chunk)
      │
      ▼
Knowledge Chunks
      │
      ▼
  Embeddings
      │
      ▼
Ready for Retrieval
      │
      ▼
  Retrieval
      │
      ▼
Grounding Context
      │
      ▼
AI Answer Generation
```

The package deliberately separates **business knowledge, document processing, embeddings, persistence, lifecycle orchestration, and retrieval** into independent layers.

---

# Package Structure

At a high level:

```text
packages/
└── knowledge/
    │
    ├── domain/
    │
    ├── application/
    │
    ├── ingestion/
    │
    ├── embeddings/
    │
    ├── retrieval/
    │
    ├── repositories/
    │
    ├── uow.py
    │
    └── ...
```

The exact directory may contain additional supporting modules, but these are the major architectural areas.

| Area            | Responsibility                                                  |
| --------------- | --------------------------------------------------------------- |
| `domain/`       | Core knowledge entities, states, invariants, and domain errors  |
| `application/`  | Knowledge lifecycle use cases and workflow orchestration        |
| `ingestion/`    | Source parsing, normalization, and chunking                     |
| `embeddings/`   | Provider-independent embedding contracts and providers          |
| `retrieval/`    | Query preparation, retrieval, ranking, reranking, and grounding |
| `repositories/` | Persistence contracts for knowledge artifacts                   |
| `uow.py`        | Transaction/unit-of-work boundary for knowledge persistence     |

---

# Architectural Role

The knowledge package sits between the application's business workflows and the AI answer-generation layer.

```text
                 Application / AI Layer
                         │
                         ▼
              ┌──────────────────────┐
              │   packages/knowledge │
              └──────────────────────┘
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
        ▼                ▼                 ▼
     Domain          Ingestion         Embeddings
        │                │                 │
        │                ▼                 │
        │          Knowledge Chunks        │
        │                │                 │
        └────────────────┼─────────────────┘
                         │
                         ▼
                    Persistence
                         │
                         ▼
                     Retrieval
                         │
                         ▼
                 Grounding Context
                         │
                         ▼
                    AI Generation
```

The package therefore provides both sides of the RAG knowledge boundary:

* **building trustworthy knowledge artifacts**, and
* **retrieving trustworthy evidence from those artifacts**.

---

# 1. Knowledge Domain

`domain/` is the business-rule core.

It defines the authoritative knowledge model:

```text
KnowledgeDocument
       │
       └── KnowledgeDocumentVersion
                │
                └── KnowledgeChunk
                         │
                         └── KnowledgeChunkEmbedding
```

A useful distinction is:

```text
Authoritative
─────────────
Document
Version
Source Content

Derived
───────
Chunks
Embeddings
```

A document represents the stable identity of a knowledge asset, while versions contain immutable source revisions. Chunks and embeddings are derived from those versions.

The domain also owns lifecycle states such as:

```text
Document:
ACTIVE → ARCHIVED / DELETED

Version:
DRAFT
  ↓
PROCESSING
  ↓
READY
  ↓
PUBLISHED
  ↓
SUPERSEDED
```

with `FAILED` representing processing failure.

The domain does **not** know about PostgreSQL, HTTP, embedding APIs, retrieval providers, or application services.

Detailed domain behavior belongs in:

```text
packages/knowledge/domain/README.md
```

---

# 2. Knowledge Application

`application/` is the **workflow orchestration layer**.

It coordinates domain entities with repositories, ingestion, embeddings, and auditing while keeping those concerns behind contracts.

Its major workflows are:

```text
Upload / Create
       │
       ▼
 Create Version
       │
       ▼
 Process Version
       │
       ▼
     READY
       │
       ▼
  Embed Version
       │
       ▼
 Fully Embedded
       │
       ▼
 Publish Version
       │
       ▼
    PUBLISHED
       │
       ▼
    SUPERSEDED
       │
       ▼
    Archived
```

The application layer also handles:

* upload validation;
* mutation identity;
* authorization;
* concurrency;
* audit recording;
* transactional coordination;
* administrative reads;
* idempotency.

The detailed workflow documentation belongs in:

```text
packages/knowledge/application/README.md
```

---

# 3. Knowledge Ingestion

`ingestion/` converts authoritative source content into retrieval-ready chunks.

Its pipeline is:

```text
IngestionSource
      │
      ▼
    Parser
      │
      ▼
 ParsedDocument
      │
      ▼
  Normalizer
      │
      ▼
NormalizedDocument
      │
      ▼
    Chunker
      │
      ▼
ChunkedDocument
      │
      ▼
KnowledgeChunk
```

The ingestion package intentionally stops before embedding and retrieval.

Major responsibilities are separated into:

```text
parser/
    Understand source format and structure

normalization/
    Produce canonical normalized content

chunking/
    Produce bounded retrieval units
```

The current operational upload formats are Markdown and plain text; a new format should not be advertised until its parser, normalizer, and chunker are all available and validated.

See:

```text
packages/knowledge/ingestion/README.md
```

for the subsystem-level documentation and its child READMEs for implementation details.

---

# 4. Embeddings

`embeddings/` is the **vector-generation boundary** shared by ingestion and retrieval.

It provides:

```text
Embedding Models
       │
       ▼
EmbeddingProvider
       │
       ├── Jina
       ├── Deterministic
       └── Future Providers
```

The subsystem separates provider identity from embedding-input identity.

An embedding profile can therefore be understood as:

```text
Provider
Model
Revision
Dimensions
+
Input Strategy
Input Strategy Version
Configuration
```

This is important because changing either the model or the way content is prepared can invalidate existing embeddings.

The package supports:

* document/chunk embeddings;
* query embeddings;
* provider resolution;
* dimension validation;
* provider-specific error translation;
* deterministic local/test embeddings;
* provider instrumentation;
* query embedding caching.

### Current provider strategy

```text
Production / External
└── JinaEmbeddingProvider

Testing / Local
└── DeterministicEmbeddingProvider
```

The deterministic provider is **not a production semantic retrieval model**; it exists for repeatable testing and local development.

The embedding package itself does not perform vector search, ranking, reranking, or answer generation.

Detailed documentation:

```text
packages/knowledge/embeddings/README.md
```

---

# 5. Retrieval

`retrieval/` is the **evidence discovery and grounding subsystem**.

It answers:

> Given a support query and trusted retrieval scope, which knowledge chunks should be supplied as evidence to the AI system?

It does not generate the final answer.

The high-level pipeline is:

```text
Retrieval Query
      │
      ▼
Query Preparation
      │
      ├───────────────┐
      ▼               ▼
 Semantic          Lexical
 Query             Queries
      │               │
      ▼               ▼
 Vector            Lexical
 Retrieval         Retrieval
      │               │
      └───────┬───────┘
              ▼
            Fusion
              │
              ▼
      Optional Reranking
              │
              ▼
       RetrievalResult
              │
              ▼
      Grounding Context
              │
              ▼
       AI Generation
```

---

## Retrieval Components

The subsystem is divided into focused areas:

```text
retrieval/
├── query/
├── vector/
├── lexical/
├── fusion/
├── reranking/
├── context/
├── application/
├── models.py
├── profiles.py
└── errors.py
```

### Query

Produces representations appropriate for semantic and lexical retrieval.

```text
RetrievalQueryContext
        │
        ▼
PreparedRetrievalQuery
├── semantic_query
└── lexical_queries
```

### Vector Retrieval

Uses an embedding provider to create a query vector and a repository to search persisted vectors.

### Lexical Retrieval

Performs traditional/full-text retrieval and converts its output into the same candidate model used by vector retrieval.

### Fusion

Combines independent rankings into one deterministic ranking. The current strategy is Reciprocal Rank Fusion.

### Reranking

Provides a second-stage ranking boundary.

**Important current state:** a real learned/provider-based reranker is **not currently active**. The current implementation is a passthrough reranker, while the architecture is prepared for a future implementation such as Jina.

### Context

Transforms retrieval candidates into bounded, deduplicated, provenance-preserving grounding context.

It applies controls such as:

* duplicate removal;
* redundancy suppression;
* per-document limits;
* block limits;
* token budgets.

Detailed retrieval behavior belongs in:

```text
packages/knowledge/retrieval/README.md
```

---

# 6. Repositories

`repositories/` provides persistence contracts between the knowledge subsystem and the database infrastructure.

Typical repository responsibilities include:

```text
KnowledgeDocumentRepository
KnowledgeVersionRepository
KnowledgeChunkRepository
KnowledgeEmbeddingRepository
```

The repositories handle persistence concerns without exposing SQLAlchemy/PostgreSQL implementation details to the domain/application layers.

The embedding repository, for example, can query embedding coverage for a version under an **exact embedding provider + input-strategy profile**.

This distinction is important:

```text
Same chunk
   │
   ├── Jina / Model A / Input Strategy X
   └── Other Model / Input Strategy Y
```

These embeddings are not automatically interchangeable.

Repositories participate in the surrounding transaction rather than owning commits themselves.

---

# 7. Unit of Work

`uow.py` defines the transaction boundary used by knowledge workflows.

Conceptually:

```text
KnowledgeUnitOfWork
│
├── documents
├── versions
├── chunks
├── embeddings
├── embedding_calls
└── audit_events
```

The application layer controls:

```text
begin
  ↓
load / validate
  ↓
mutate
  ↓
audit
  ↓
commit / rollback
```

Long-running operations such as document parsing or external embedding calls are intentionally performed outside database transactions.

---

# End-to-End Knowledge Lifecycle

The complete knowledge subsystem can be understood as one pipeline:

```text
                 ┌──────────────────────┐
                 │ Create / Upload      │
                 └──────────┬───────────┘
                            │
                            ▼
                   KnowledgeDocument
                            │
                            ▼
                KnowledgeDocumentVersion
                            │
                            ▼
                      ┌──────────┐
                      │ Ingestion│
                      └────┬─────┘
                           │
                 parse → normalize → chunk
                           │
                           ▼
                    KnowledgeChunk
                           │
                           ▼
                    ┌────────────┐
                    │ Embeddings │
                    └─────┬──────┘
                          │
                          ▼
                 KnowledgeChunkEmbedding
                          │
                          ▼
                      PUBLISHED
                          │
                          │
                 Customer Query
                          │
                          ▼
                   Query Preparation
                          │
                ┌─────────┴─────────┐
                ▼                   ▼
          Vector Retrieval    Lexical Retrieval
                │                   │
                └─────────┬─────────┘
                          ▼
                       Fusion
                          │
                          ▼
                  Optional Reranking
                          │
                          ▼
                   RetrievalResult
                          │
                          ▼
                 Grounding Context
                          │
                          ▼
                   AI Answer Layer
```

This separation allows each stage to evolve independently.

---

# Source of Truth vs Derived Artifacts

A central architectural principle is the distinction between authoritative content and derived data.

```text
                AUTHORITATIVE
                ─────────────
                Document
                   │
                   ▼
                Version
                   │
              source_content
                   │
                   ▼
                ─────────
                  DERIVED
                ─────────
                   │
                   ▼
                 Chunks
                   │
                   ▼
               Embeddings
```

If the source changes:

```text
Create a new Version
```

If chunking changes:

```text
Regenerate Chunks
```

If the embedding configuration changes:

```text
Generate new Embeddings
```

This preserves historical reproducibility and avoids silently changing previously derived artifacts.

---

# Provenance

The knowledge subsystem is designed around explicit provenance.

Important identities include:

```text
Source / Upload hash
Parser identity
Normalizer identity
Chunker identity
Embedding provider identity
Embedding input strategy identity
Retrieval profile identity
Trace ID
Mutation actor
```

This allows the system to answer not only:

> "What knowledge was retrieved?"

but also:

> "Which version, transformation pipeline, embedding configuration, and retrieval configuration produced this result?"

The application layer explicitly treats provenance as an operational requirement for reproducibility and auditing.

---

# Trust Boundaries

The package contains several deliberate trust boundaries.

### Uploaded Files

```text
Untrusted Bytes
      │
      ▼
KnowledgeUploadPolicy
      │
      ▼
Validated Knowledge Source
```

Uploads are validated for filename, format, size, encoding, signatures, and unsafe control characters before entering the knowledge domain.

### Retrieval Scope

AI/customer-derived information may provide semantic hints, but trusted `RetrievalFilters` define hard retrieval scope.

### Reranking

A reranker may reorder trusted candidates but cannot introduce new knowledge content.

### External Providers

Provider-specific failures are translated into application-level embedding/retrieval errors rather than leaking SDK-specific exceptions.

---

# Concurrency and Transactions

Knowledge lifecycle operations use explicit transaction boundaries and row locking where required.

For example:

```text
 Document Lock
      │
      ▼
Version Operation
      │
      ▼
    Audit
      │
      ▼
    Commit
```

This protects operations such as:

* version creation;
* processing claims;
* publication;
* archival;
* version uploads.

Expensive processing is intentionally separated:

```text
Claim Transaction
       ↓
Parse / Normalize / Chunk
       ↓
Completion Transaction
```

and:

```text
Snapshot Transaction
       ↓
External Embedding Calls
       ↓
Persistence Transaction
```

This avoids holding database connections or locks while CPU-heavy or external work is running.

---

# No Silent Degradation

A major principle across the knowledge subsystem is:

> **Configured capabilities must actually work; failures must remain visible.**

Examples:

```text
Vector retrieval enabled
        +
Vector service unavailable
        ↓
       FAIL
```

rather than silently falling back to lexical retrieval.

Similarly:

```text
Incomplete embeddings
        ↓
Cannot publish
```

and:

```text
Parser / normalizer / chunker failure
        ↓
Version becomes FAILED
```

The application layer explicitly tests and enforces these failure boundaries.

---

# Provider Independence

The knowledge subsystem intentionally avoids coupling its core business logic to particular vendors.

Examples:

```text
EmbeddingProvider
RetrievalFusionStrategy
Reranker
VectorRetrievalRepository
```

are contracts rather than vendor-specific dependencies.

Therefore:

```text
Jina
  │
  └── EmbeddingProvider

Future Provider
  │
  └── EmbeddingProvider
```

can be swapped without changing the surrounding ingestion, application, or retrieval contracts.

The same principle applies to retrieval infrastructure and ranking components.

---

# Relationship to the AI Layer

The knowledge package does **not** generate the final customer-support answer.

Its responsibility ends at:

```text
Trusted Knowledge
       │
       ▼
Retrieved Candidates
       │
       ▼
Bounded GroundingContext
```

The downstream AI layer consumes this context:

```text
Knowledge
   │
   ▼
Retrieval
   │
   ▼
GroundingContext
   │
   ▼
AI / LLM
   │
   ▼
Customer Answer
```

This separation ensures that the model generation layer does not become responsible for searching the knowledge base or deciding the underlying source-of-truth content.

---

# Architectural Principles

The major principles across `packages/knowledge/` are:

### Domain-first

Business rules and lifecycle invariants live in the domain rather than repositories or APIs.

### Immutable Knowledge

Documents, versions, chunks, and embeddings are treated as immutable artifacts.

### Explicit Lifecycle

Processing, embedding, and publication are separate stages.

### Contract-driven Architecture

Ingestion, embedding, retrieval, ranking, and persistence communicate through stable contracts.

### Provider Independence

External providers remain replaceable implementation details.

### Provenance by Design

Transformations and derived artifacts retain enough identity to support reproducibility.

### Short Transactions

Database transactions do not remain open across expensive CPU or external-provider work.

### Strong Validation

Invalid state, malformed provider output, incompatible artifacts, and invalid configuration fail early.

### No Silent Degradation

The system does not disguise incomplete or failed knowledge operations as successful results.

### Retrieval ≠ Generation

The knowledge subsystem produces evidence and bounded grounding context; the AI layer produces the final answer.

---

# Testing Philosophy

Testing should happen at the appropriate architectural level.

```text
Domain
  │
  └── Business invariants / lifecycle

Ingestion
  │
  └── Parser / normalization / chunking contracts

Embeddings
  │
  └── Provider contract / dimensions / response validation

Retrieval
  │
  └── Query / retrieval / fusion / reranking / grounding

Application
  │
  └── Workflow / transactions / concurrency / authorization

Repositories
  │
  └── Persistence behavior
```

The application-level tests should focus primarily on workflow invariants and transaction boundaries rather than duplicating lower-level implementation tests.

---

# Adding New Capabilities

The architecture is designed so new capabilities can be added within their respective boundaries.

### New Document Format

Implement:

```text
Parser
Normalizer
Chunker
```

then register the complete pipeline.

### New Embedding Provider

Implement:

```text
EmbeddingProvider
```

and register it through the embedding resolver/composition layer.

### New Retrieval Mechanism

Implement the appropriate retrieval contract and integrate it according to the `RetrievalProfile`.

### New Reranker

Implement the reranker contract without allowing it to introduce knowledge outside the trusted candidate set.

The detailed READMEs under each subsystem should be consulted before making these extensions.

---

# Quick Mental Model

The easiest way to understand `packages/knowledge/` is:

```text
domain/
    "What is knowledge?"

application/
    "What can we do with knowledge?"

ingestion/
    "How does source content become chunks?"

embeddings/
    "How do we turn content/query text into vectors?"

repositories/
    "How is knowledge persisted?"

uow.py
    "How are knowledge transactions coordinated?"

retrieval/
    "How do we find the right knowledge and build evidence?"
```

Together:

```text
                 packages/knowledge
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
     Domain         Application       Persistence
        │                │                │
        │                ▼                │
        │            Ingestion            │
        │                │                │
        │                ▼                │
        │             Chunks              │
        │                │                │
        │                ▼                │
        │            Embeddings           │
        │                │                │
        └────────────────┼────────────────┘
                         │
                         ▼
                     Retrieval
                         │
                         ▼
                 Grounding Context
                         │
                         ▼
                   AI Generation
```

---

# Summary

`packages/knowledge/` is the **trusted knowledge foundation of the AI customer-support agent**.

It manages the journey from authoritative support content to usable AI evidence:

```text
Source
  ↓
Document / Version
  ↓
Parse
  ↓
Normalize
  ↓
Chunk
  ↓
Embed
  ↓
Persist
  ↓
Retrieve
  ↓
Fuse
  ↓
(Optional Rerank)
  ↓
Ground
  ↓
AI Answer
```

The most important architectural boundaries are:

```text
domain/
    Business truth

application/
    Workflow orchestration

ingestion/
    Source → chunks

embeddings/
    Text → vectors

repositories/
    Knowledge → persistence

retrieval/
    Query → evidence

AI layer
    Evidence → answer
```

The lower-level READMEs should be treated as the authoritative references for implementation-specific behavior. This README provides the **map of the entire knowledge subsystem and how its major components fit together**.
