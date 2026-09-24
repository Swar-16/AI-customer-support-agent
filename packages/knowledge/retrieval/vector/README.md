# Vector Retrieval

## Overview

The `packages/knowledge/retrieval/vector/` package provides the **semantic/vector retrieval path** of the knowledge-retrieval subsystem.

It separates two responsibilities:

* `repository.py` defines the persistence-facing contract for searching stored knowledge embeddings.
* `service.py` handles query embedding, validates embedding compatibility, invokes the repository, and converts raw vector-search evidence into canonical `RetrievalCandidate` objects.

```text
Customer / AI Retrieval Query
            │
            ▼
   VectorRetrievalService
            │
            ├── embed query
            │
            ├── validate dimensions
            │
            ▼
     VectorSearchRequest
            │
            ▼
 VectorRetrievalRepository
            │
            ▼
   VectorSearchMatch[]
            │
            ▼
   canonical candidates
            │
            ▼
      RetrievalCandidate[]
```

The package deliberately keeps **embedding-provider concerns in the service** and **database/persistence concerns in the repository**.

---

# Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── knowledge/
        └── retrieval/
            └── vector/
                ├── repository.py
                ├── service.py
                └── README.md
```

| File            | Responsibility                                                                                                        |
| --------------- | --------------------------------------------------------------------------------------------------------------------- |
| `repository.py` | Defines vector-search request/result models and the `VectorRetrievalRepository` persistence contract                  |
| `service.py`    | Generates query embeddings, validates them, executes vector retrieval, and maps raw results into canonical candidates |

---

# Architectural Position

Vector retrieval is one of the retrieval branches used by the higher-level knowledge retrieval pipeline.

```text
PreparedRetrievalQuery
        │
        ├─────────────────────┐
        │                     │
        ▼                     ▼
 semantic_query          lexical_query
        │                     │
        ▼                     ▼
 Vector Retrieval       Lexical Retrieval
        │                     │
        └──────────┬──────────┘
                   ▼
                 Fusion
                   │
                   ▼
               Reranking
                   │
                   ▼
           Grounding Context
```

The orchestration layer supplies the semantic query to `VectorRetrievalService`, while the vector repository remains an infrastructure abstraction underneath it.

---

# Core Design Principle

The key separation is:

```text
                  VectorRetrievalService
                           │
             ┌─────────────┴─────────────┐
             │                           │
       Query embedding              Search request
             │                           │
             ▼                           ▼
    EmbeddingProvider       VectorRetrievalRepository
```

The repository **does not generate embeddings**.

The service generates the query embedding first and passes the resulting vector to the repository. This intentionally keeps the persistence layer embedding-provider agnostic.

---

# `repository.py`

`repository.py` defines the persistence-side models and protocol used for vector search.

It contains:

```text
VectorSearchRequest
VectorSearchMatch
VectorRetrievalRepository
```

These form the contract between the application/domain retrieval service and the actual vector-storage implementation.

---

# `VectorSearchRequest`

`VectorSearchRequest` is the immutable persistence-facing request.

```text
VectorSearchRequest
├── query_vector
├── provider
├── input_descriptor
├── filters
└── limit
```

It deliberately contains only the information required to execute a vector search.

The repository does not receive the original natural-language query.

Instead, it receives the already-generated embedding.

---

# Query Vector

The `query_vector` must be an `EmbeddingVector`.

The repository therefore operates on a concrete vector representation rather than knowing how the vector was generated.

```text
RetrievalQuery
      │
      ▼
EmbeddingProvider
      │
      ▼
EmbeddingVector
      │
      ▼
VectorSearchRequest
```

This keeps embedding generation outside persistence.

---

# Provider Descriptor

The request includes an `EmbeddingProviderDescriptor`.

This allows the persistence layer to verify that the query vector corresponds to the expected embedding configuration.

The descriptor captures the identity/configuration of the embedding provider, including the expected dimensionality.

---

# Input Descriptor

`EmbeddingInputDescriptor` accompanies the provider descriptor.

Together they identify the embedding representation expected by the persisted vector index.

Conceptually:

```text
EmbeddingProviderDescriptor
        +
EmbeddingInputDescriptor
        +
EmbeddingVector
        │
        ▼
compatible vector search
```

This prevents vectors generated under an incompatible embedding configuration from silently entering the vector-search path.

---

# Trusted Filters

The request also contains:

```text
RetrievalFilters
```

These are the trusted retrieval constraints established by the application/retrieval context.

The repository is responsible for applying supported retrieval filters.

The vector repository must not reinterpret arbitrary AI-derived entities as authorization or database filters.

---

# Limit Validation

`VectorSearchRequest` requires a positive integer `limit`.

Invalid values are rejected:

```text
limit <= 0
       │
       ▼
ValueError
```

Booleans are also rejected as integer-like values.

This ensures the persistence boundary always receives a meaningful result-count constraint.

---

# Dimension Validation

One of the most important invariants is:

```text
query_vector.dimensions
        ==
provider.dimensions
```

If they differ, the request is rejected.

```text
Configured provider: 1024
Query vector:        768
                     │
                     ▼
                  reject
```

This prevents incompatible vectors from reaching the vector database.

---

# `VectorSearchMatch`

`VectorSearchMatch` represents raw semantic-search evidence returned by persistence.

```text
VectorSearchMatch
├── candidate
└── distance
```

The candidate is already a `RetrievalCandidate`.

The additional `distance` field represents the raw vector-search metric returned by the persistence implementation.

---

# Why Distance Is Kept Separate

The repository returns raw vector evidence rather than modifying the canonical retrieval score itself.

This creates a clean boundary:

```text
Database / vector backend
          │
          ▼
raw distance
          │
          ▼
VectorSearchMatch
          │
          ▼
VectorRetrievalService
          │
          ▼
vector_distance
vector_similarity
```

The service owns the conversion into canonical retrieval scoring.

---

# Distance Validation

`VectorSearchMatch` validates the distance.

It must:

* be numeric;
* not be negative;
* be finite.

Invalid distance values are rejected before they become retrieval evidence.

This prevents invalid numeric values such as:

```text
NaN
Infinity
-Infinity
negative distance
```

from contaminating downstream ranking.

---

# `VectorRetrievalRepository`

`VectorRetrievalRepository` is a `Protocol`.

It defines the persistence contract:

```python
search(request: VectorSearchRequest)
    -> tuple[VectorSearchMatch, ...]
```

The repository is responsible for:

* searching persisted chunk embeddings;
* matching the appropriate embedding provider/model/profile;
* enforcing knowledge lifecycle visibility;
* applying supported retrieval filters;
* ranking by vector distance;
* returning no more than `request.limit` results.

---

# What the Repository Must Not Do

The repository explicitly must **not**:

* call embedding providers;
* perform query rewriting;
* perform rank fusion;
* rerank results;
* build LLM grounding context;
* commit transactions.

This is an important architectural boundary.

```text
Repository
   │
   ├── persistence/search ✓
   │
   ├── embeddings        ✗
   ├── query rewriting   ✗
   ├── fusion            ✗
   ├── reranking         ✗
   ├── grounding         ✗
   └── transaction commit ✗
```

---

# `service.py`

`service.py` defines:

```text
VectorRetrievalService
```

It is the application/domain service responsible for semantic retrieval.

Its responsibilities are explicitly:

1. convert the retrieval query into an embedding;
2. validate embedding dimensions;
3. invoke the vector repository;
4. convert raw vector-distance evidence into canonical retrieval candidates and scores.

---

# Dependencies

The service requires three dependencies:

```text
EmbeddingProvider
VectorRetrievalRepository
EmbeddingInputDescriptor
```

Conceptually:

```text
VectorRetrievalService
├── EmbeddingProvider
├── VectorRetrievalRepository
└── EmbeddingInputDescriptor
```

These are injected into the constructor rather than created internally.

This keeps the service independently testable and provider agnostic.

---

# `EmbeddingProvider`

The embedding provider is responsible for generating the query vector.

The service calls:

```text
provider.embed_query(query.text)
```

The repository never performs this operation.

This allows the same vector-retrieval service to work with different embedding providers as long as they satisfy the embedding contract.

---

# Search Flow

The main method is:

```python
search(
    query: RetrievalQuery,
    limit: int
) -> tuple[RetrievalCandidate, ...]
```

The execution sequence is:

```text
RetrievalQuery
      │
      ▼
validate query + limit
      │
      ▼
embed query text
      │
      ▼
validate embedding dimensions
      │
      ▼
build VectorSearchRequest
      │
      ▼
repository.search()
      │
      ▼
VectorSearchMatch[]
      │
      ▼
convert each match
      │
      ▼
RetrievalCandidate[]
```

---

# Request Validation

Before performing any embedding or database operation, the service validates:

```text
query
limit
```

The query must be a `RetrievalQuery`.

The limit must:

* be an integer;
* not be a boolean;
* be greater than zero.

Invalid inputs fail early.

---

# Query Embedding

The service generates the embedding through the configured provider.

```text
query.text
    │
    ▼
EmbeddingProvider.embed_query()
    │
    ▼
EmbeddingVector
```

The repository is intentionally unaware of this operation.

This ensures the persistence layer remains independent of embedding-provider implementation details.

---

# Embedding Error Translation

Provider-level embedding failures represented by `KnowledgeEmbeddingError` are translated into:

```text
QueryEmbeddingError
```

This gives the retrieval layer a domain-specific error contract without exposing lower-level embedding implementation details.

If the provider returns something that is not an `EmbeddingVector`, the service also raises `QueryEmbeddingError`.

---

# Query Embedding Dimension Validation

After embedding, the service validates:

```text
actual dimensions
        ==
provider descriptor dimensions
```

If the dimensions differ:

```text
QueryEmbeddingDimensionError
```

is raised.

This provides an additional validation layer before the repository receives the vector.

The system therefore has two complementary checks:

```text
Service
  │
  └── validate generated vector

Repository request model
  │
  └── validate request/vector compatibility
```

---

# Building the Persistence Request

After successful embedding validation, the service constructs:

```text
VectorSearchRequest
```

with:

```text
query_vector
provider descriptor
input descriptor
trusted filters
limit
```

The request therefore contains everything the persistence layer needs and nothing related to higher-level query interpretation.

---

# Repository Invocation

The service calls:

```text
repository.search(request)
```

Repository-specific failures represented by:

```text
VectorRetrievalRepositoryError
```

are translated into:

```text
VectorSearchError
```

This keeps repository implementation errors from leaking directly into higher application layers.

---

# Converting Raw Vector Evidence

The repository returns:

```text
VectorSearchMatch[]
```

The service converts each match into a canonical:

```text
RetrievalCandidate
```

The conversion is handled by `_to_candidate()`.

---

# Cosine Distance → Similarity

The implementation explicitly follows pgvector cosine-distance semantics:

```text
smaller distance = better match
```

For cosine distance:

```text
cosine_similarity = 1 - cosine_distance
```

The service intentionally retains **both** representations.

For example:

```text
distance   = 0.15
similarity = 0.85
```

This means later stages do not need to reverse-engineer the original vector metric.

---

# Preserving Both Scores

The resulting candidate receives:

```text
vector_distance
vector_similarity
```

inside its `RetrievalScores`.

Conceptually:

```text
RetrievalCandidate
       │
       └── scores
             ├── vector_distance
             └── vector_similarity
```

This is important because later fusion/reranking stages may need either representation.

---

# Finite Distance Validation

The service additionally validates that the repository's returned distance is finite.

```text
NaN
Infinity
-Infinity
```

are rejected.

Negative distances are also rejected.

Invalid values result in `VectorSearchError`.

This gives the service a defensive boundary even though `VectorSearchMatch` already validates distance values.

---

# Candidate Validation

The repository is expected to return a `RetrievalCandidate`.

If it returns another object type, the service raises:

```text
VectorSearchError
```

This prevents malformed repository output from propagating into fusion or downstream retrieval stages.

---

# Retrieval Method Tracking

The converted candidate is marked with:

```text
RetrievalMethod.VECTOR
```

The service preserves any existing methods while adding the vector method.

Conceptually:

```text
existing methods
      +
VECTOR
      │
      ▼
updated methods
```

This becomes useful when candidates are later combined with lexical retrieval.

---

# Candidate Provenance Preservation

The service uses `dataclasses.replace()` to update the existing candidate rather than constructing an unrelated candidate from scratch.

This preserves the existing candidate's:

* identity;
* document information;
* chunk information;
* metadata;
* provenance;
* existing retrieval scores;
* retrieval methods.

Only vector-specific evidence is added or updated.

---

# Interaction With Lexical Retrieval

Vector retrieval is deliberately parallel to lexical retrieval.

```text
                 Prepared Query
                      │
              ┌───────┴────────┐
              │                │
              ▼                ▼
       Vector Service    Lexical Service
              │                │
              ▼                ▼
      vector candidates  lexical candidates
              │                │
              └───────┬────────┘
                      ▼
                    Fusion
```

The lexical service similarly preserves candidates and attaches lexical scores, but the lexical score remains an opaque ranking signal and is not assumed to be directly comparable with vector similarity.

---

# Role in Fusion

The vector service does **not** perform fusion.

Its output is consumed by the higher-level retrieval orchestration:

```text
VectorRetrievalService
        │
        ▼
vector candidates
        │
        ├───────────────┐
        │               │
        ▼               ▼
   Fusion input    telemetry
        │
        ▼
Reciprocal Rank Fusion
```

The higher-level `RetrieveKnowledge` component owns the orchestration of vector retrieval, lexical retrieval, fusion, and optional reranking.

---

# Role in Reranking

The vector service itself does not rerank.

The architecture is:

```text
Vector Retrieval
      │
      ▼
Lexical Retrieval
      │
      ▼
Fusion
      │
      ▼
Reranking
```

This means vector similarity should not be interpreted as the final relevance score.

It is one retrieval signal among potentially several.

---

# Current Retrieval Pipeline

At the broader composition level, vector retrieval is created only when the configured `RetrievalProfile` enables vector retrieval.

The factory requires:

```text
embedding_provider
embedding_input_descriptor
```

when vector retrieval is enabled.

For lexical-only profiles, the vector infrastructure does not need to be constructed.

---

# Persistence Implementations

The repository protocol allows multiple concrete implementations.

The composition root can use either:

```text
ScopedSQLAlchemyVectorRetrievalRepository
```

or:

```text
SQLAlchemyVectorRetrievalRepository
```

depending on whether a retrieval Unit of Work factory or direct session is supplied.

This means the domain service does not depend on a specific SQLAlchemy repository implementation.

---

# Transaction Boundary

The repository contract explicitly states that vector repositories must not commit transactions.

```text
Vector Repository
       │
       └── search only
```

Transaction lifecycle remains owned by the surrounding persistence/application infrastructure.

This prevents retrieval operations from unexpectedly committing application transactions.

---

# Lifecycle Visibility

The repository is responsible for enforcing knowledge lifecycle visibility invariants.

This means vector search should not blindly return every persisted embedding.

The repository must respect the knowledge visibility rules applicable to the retrieval request.

The service itself remains focused on semantic retrieval mechanics.

---

# Trust Boundary

The retrieval filters reaching the repository must originate from trusted retrieval context.

```text
Customer / AI
     │
     └── semantic hints
              │
              ▼
       Query preparation
              │
              ▼
      trusted RetrievalFilters
              │
              ▼
     VectorSearchRequest
              │
              ▼
        Repository
```

The repository applies those filters but does not reinterpret arbitrary entity hints as authorization constraints.

---

# Error Boundary

The package creates several meaningful failure boundaries.

```text
Embedding Provider
       │
       └── KnowledgeEmbeddingError
                  │
                  ▼
          QueryEmbeddingError

Embedding mismatch
       │
       ▼
QueryEmbeddingDimensionError

Repository
       │
       └── VectorRetrievalRepositoryError
                  │
                  ▼
          VectorSearchError

Invalid raw vector evidence
       │
       ▼
VectorSearchError
```

This gives higher layers meaningful retrieval-domain errors rather than infrastructure-specific exceptions.

---

# End-to-End Example

Conceptually, a customer asks:

```text
"How can I get a refund for my order?"
```

The prepared semantic query reaches the vector service:

```text
RetrievalQuery
    │
    ▼
VectorRetrievalService
    │
    ▼
EmbeddingProvider
    │
    ▼
EmbeddingVector
    │
    ▼
VectorSearchRequest
    │
    ▼
VectorRetrievalRepository
    │
    ▼
VectorSearchMatch[]
```

Suppose the repository returns:

```text
chunk A → distance 0.12
chunk B → distance 0.20
chunk C → distance 0.35
```

The service converts these into:

```text
chunk A → vector_distance=0.12, vector_similarity=0.88
chunk B → vector_distance=0.20, vector_similarity=0.80
chunk C → vector_distance=0.35, vector_similarity=0.65
```

The resulting candidates then enter the broader retrieval pipeline.

---

# Testing Strategy

## `VectorSearchRequest`

Test:

* invalid vector type;
* invalid provider descriptor;
* invalid input descriptor;
* invalid filters;
* invalid limit;
* zero/negative limit;
* vector/provider dimension mismatch.

## `VectorSearchMatch`

Test:

* invalid candidate;
* invalid distance type;
* negative distance;
* `NaN`;
* positive/negative infinity;
* normalization to `float`.

## `VectorRetrievalService`

Test:

* invalid query;
* invalid limit;
* embedding-provider invocation;
* embedding error translation;
* invalid embedding return type;
* dimension mismatch;
* repository request construction;
* repository error translation;
* non-finite repository distance;
* negative repository distance;
* invalid repository candidate;
* vector score conversion;
* `RetrievalMethod.VECTOR` preservation.

## Repository Implementations

Integration tests should verify:

* correct vector index usage;
* correct embedding configuration;
* lifecycle visibility;
* filter application;
* result limits;
* distance ordering;
* transaction behavior.

---

# Important Invariants

### Query Embedding Happens Outside Persistence

The repository never calls the embedding provider.

### Vector Dimensions Must Match

The generated query vector must match the configured embedding dimensions.

### Distances Must Be Finite

Invalid numeric values cannot enter the retrieval pipeline.

### Distance Is Non-Negative

Negative vector distances are rejected.

### Both Distance and Similarity Are Preserved

The service does not discard the original vector metric.

### Vector Retrieval Does Not Fuse

Fusion belongs to the higher retrieval orchestration layer.

### Vector Retrieval Does Not Rerank

Reranking is a separate stage.

### Vector Retrieval Does Not Build Grounding Context

Grounding is constructed downstream.

### Repository Does Not Commit

Transaction ownership remains outside the repository.

### Candidate Provenance Is Preserved

The service enriches existing `RetrievalCandidate` objects rather than replacing their identity/provenance.

---

# Relationship to the Full Knowledge Retrieval System

The vector package fits into the larger architecture as follows:

```text
                   Query Preparation
                          │
                          ▼
                PreparedRetrievalQuery
                          │
             semantic_query
                          │
                          ▼
              VectorRetrievalService
                    │          │
                    │          └── EmbeddingProvider
                    │
                    ▼
           VectorSearchRequest
                    │
                    ▼
        VectorRetrievalRepository
                    │
                    ▼
           VectorSearchMatch[]
                    │
                    ▼
          RetrievalCandidate[]
                    │
                    ▼
                  Fusion
                    │
                    ▼
                Reranking
                    │
                    ▼
            Grounding Context
```

The composition root assembles this alongside lexical retrieval, fusion, reranking, and grounding-context construction.

---

# Design Principles

## Provider Agnostic

`VectorRetrievalService` depends on the `EmbeddingProvider` contract rather than a specific provider.

## Persistence Agnostic

The service depends on `VectorRetrievalRepository`, not directly on SQLAlchemy or pgvector.

## Explicit Contracts

Requests and raw matches are represented by immutable dataclasses.

## Defensive Validation

Both service and persistence-facing models validate critical invariants.

## Separation of Concerns

Embedding, persistence, candidate conversion, fusion, reranking, and grounding remain separate stages.

## Preserve Raw Evidence

Both vector distance and derived similarity are retained.

## No Hidden AI Behavior

The repository does not perform query rewriting, embedding generation, fusion, reranking, or grounding.

## Composable

The service can be supplied with different embedding providers and repository implementations without changing its public behavior.

---

# Summary

The `packages/knowledge/retrieval/vector/` package is the semantic retrieval boundary of the RAG system.

```text
repository.py
    │
    ├── VectorSearchRequest
    ├── VectorSearchMatch
    └── VectorRetrievalRepository
              │
              │ persistence contract
              ▼
service.py
    │
    ├── validate retrieval request
    ├── generate query embedding
    ├── validate embedding dimensions
    ├── invoke repository
    ├── validate raw vector evidence
    ├── calculate cosine similarity
    └── produce RetrievalCandidate[]
```

Its central architectural rule is:

> **The service owns semantic-query embedding and evidence interpretation; the repository owns persisted vector search.**

The resulting candidates then become one input to the broader retrieval pipeline, where vector and lexical results are fused and subsequently passed through the separate reranking stage.
