# Embedding Providers

## Overview

The `packages/knowledge/embeddings/provider/` package defines the **provider boundary for the knowledge embedding subsystem**.

It isolates the rest of the application from concrete embedding vendors and provides the infrastructure required to:

* generate document/chunk embeddings;
* generate retrieval-query embeddings;
* expose stable provider/model/dimension identity;
* integrate real external embedding services;
* provide deterministic embeddings for tests and local development;
* record provider-call telemetry;
* cache repeated query embeddings;
* normalize provider-specific failures into the application's embedding error hierarchy.

```text
packages/
└── knowledge/
    └── embeddings/
        └── provider/
            ├── base.py
            ├── jina.py
            ├── deterministic.py
            ├── instrumented.py
            └── query_cache.py
```

The package is intentionally divided into **contract, implementation, infrastructure, and cross-cutting concerns** rather than allowing application code to depend directly on an embedding SDK.

---

# Architecture

The five files work together as follows:

```text
                         EmbeddingProvider
                              base.py
                                 │
                    ┌────────────┴──────────────────┐
                    │                               │
                    ▼                               ▼
          DeterministicEmbeddingProvider   JinaEmbeddingProvider
                 deterministic.py                jina.py
                    │                               │
                    └────────────┬──────────────────┘
                                 │
                                 ▼
                     InstrumentedEmbeddingProvider
                              instrumented.py
                                 │
                      ┌──────────┴──────────┐
                      │                     │
                      ▼                     ▼
              Telemetry Recorder      QueryEmbeddingCache
                                           query_cache.py
```

The important distinction is:

```text
base.py
    = What an embedding provider must do

jina.py
    = How the real Jina provider does it

deterministic.py
    = How a local/test provider can satisfy the same contract

instrumented.py
    = How provider calls are observed without changing provider behavior

query_cache.py
    = How repeated retrieval-query embeddings are reused
```

---

# Files

| File               | Responsibility                                     |
| ------------------ | -------------------------------------------------- |
| `base.py`          | Provider-neutral embedding contract                |
| `jina.py`          | Production-facing Jina AI embedding implementation |
| `deterministic.py` | Deterministic, dependency-free test/local provider |
| `instrumented.py`  | Telemetry wrapper around any `EmbeddingProvider`   |
| `query_cache.py`   | Process-local TTL/LRU query-embedding cache        |

---

# 1. `base.py` — Provider Contract

## `EmbeddingProvider`

`base.py` defines the abstract `EmbeddingProvider` contract.

Higher application layers are expected to depend on this abstraction rather than directly on a provider SDK. The contract intentionally supports hosted APIs, local models, deterministic providers, and other embedding backends.

The interface consists of three main operations:

```python
descriptor
embed_documents(...)
embed_query(...)
```

plus an optional health check:

```python
health_check()
```

---

## Provider Descriptor

Every provider exposes:

```python
@property
def descriptor() -> EmbeddingProviderDescriptor
```

The descriptor identifies the actual embedding configuration, including provider, model, revision, and vector dimensionality.

This metadata is important for:

* embedding provenance;
* compatibility checks;
* persisted embedding artifacts;
* determining whether existing embeddings can be reused;
* deciding when re-embedding is required.

Conceptually:

```text
EmbeddingProvider
       │
       ▼
EmbeddingProviderDescriptor
       │
       ├── provider
       ├── model
       ├── revision
       └── dimensions
```

---

# Document Embeddings

The contract defines:

```python
embed_documents(texts)
```

for embedding indexed knowledge content.

The input ordering is significant.

For every input:

```text
input[0] → DocumentEmbedding(input_index=0)
input[1] → DocumentEmbedding(input_index=1)
...
```

Implementations must preserve the mapping between input positions and returned embeddings even if an external API internally reorders or batches requests.

All returned vectors must match:

```text
descriptor.dimensions
```

Provider-specific exceptions must also be translated into the application's embedding exception hierarchy.

---

# Query Embeddings

The contract separately defines:

```python
embed_query(text)
```

Query embeddings are intentionally separate from document embeddings because some embedding models use different prompting, prefixes, pooling, or task configuration for indexed content versus retrieval queries.

This distinction becomes particularly important for the Jina implementation.

---

# Health Check

The base implementation provides:

```python
health_check() -> bool
```

and returns `True` without external I/O.

Remote providers may override this when an inexpensive provider-health check is useful. Application startup should not automatically invoke it; readiness behavior belongs to higher application/composition layers.

---

# 2. `jina.py` — Jina AI Provider

## `JinaEmbeddingProvider`

`jina.py` is the concrete external-provider implementation backed by **Jina AI's Embeddings API**.

It is deliberately limited to the provider boundary:

```text
JinaEmbeddingProvider
├── request construction
├── task selection
├── HTTP transport
├── provider error translation
├── response validation
└── provider-neutral model conversion
```

It does **not** know about:

* knowledge documents;
* knowledge chunks;
* repositories;
* pgvector;
* application lifecycle;
* embedding persistence.

Those responsibilities belong to higher layers.

---

# Jina Defaults

The provider defines:

```text
provider       = jina
model          = jina-embeddings-v4
dimensions     = 1024
endpoint       = https://api.jina.ai/v1/embeddings
timeout        = 30 seconds
```

and distinguishes:

```text
document task = retrieval.passage
query task    = retrieval.query
```

This means document and query representations are explicitly separated at the external-provider boundary.

---

# Configuration

The provider accepts:

```python
JinaEmbeddingProvider(
    api_key=...,
    model=...,
    dimensions=...,
    endpoint=...,
    timeout_seconds=...,
    normalized=...,
    client=...,
)
```

The API key, model, endpoint, dimensionality, and timeout are validated during construction.

The provider exposes its descriptor through:

```python
provider.descriptor
```

and additional configuration such as:

```python
provider.endpoint
provider.normalized
```

is available without exposing the HTTP client abstraction to higher layers.

---

# Document Embedding Flow

For documents:

```text
Sequence[str]
     │
     ▼
validate inputs
     │
     ▼
Jina API
     │
     ▼
parse response
     │
     ▼
DocumentEmbedding
     │
     ▼
EmbeddingBatch
```

An empty document batch is allowed by the provider contract and returns an empty `EmbeddingBatch`.

---

# Query Embedding Flow

For a query:

```text
query text
    │
    ▼
validate
    │
    ▼
task = retrieval.query
    │
    ▼
Jina API
    │
    ▼
EmbeddingVector
```

The resulting vector must match the configured descriptor dimensionality.

---

# Jina Response Validation

The implementation does not blindly trust the provider response.

It validates:

* response structure;
* data presence;
* response cardinality;
* returned indexes;
* duplicate indexes;
* missing indexes;
* vector type;
* vector dimensionality;
* individual vector values.

For batch responses, the provider reconstructs output according to the returned input indexes and ensures that every requested input is represented exactly once.

This protects the rest of the system from malformed or inconsistent provider responses.

---

# Provider Error Translation

The Jina implementation translates external failures into domain-specific embedding exceptions, including categories such as:

```text
Authentication
Authorization
Connection
Execution
Rate Limit
Request
Timeout
Unavailable
Response Cardinality
Response Ordering
Dimension Mismatch
Invalid Vector
Input Validation
```

This prevents Jina/httpx-specific exceptions from leaking into higher application layers.

The application therefore interacts with:

```text
EmbeddingProvider
       │
       ▼
Embedding error hierarchy
```

rather than:

```text
EmbeddingProvider
       │
       ▼
Jina SDK/httpx implementation details
```

---

# 3. `deterministic.py` — Deterministic Provider

## Purpose

`DeterministicEmbeddingProvider` implements the same `EmbeddingProvider` contract without making any external API calls.

It exists for:

* unit tests;
* integration tests;
* local development;
* deterministic fixtures;
* provider-contract testing.

It deliberately does **not** attempt to model real semantic similarity and must not be used as the production retrieval model.

---

# Deterministic Configuration

Defaults:

```text
provider     = deterministic
model        = sha256-projection
revision     = 1
dimensions   = 64
normalize    = True
```

The dimensionality is configurable as long as it is positive.

---

# Deterministic Embedding Algorithm

The provider derives every vector dimension from SHA-256.

Conceptually:

```text
provider
model
revision
task
dimension index
normalized text
        │
        ▼
     SHA-256
        │
        ▼
64-bit integer
        │
        ▼
value in approximately [-1, 1]
```

The task is deliberately included in the hash input.

Therefore:

```text
same text + document task
```

and:

```text
same text + query task
```

belong to different deterministic namespaces.

---

# Why Task Separation Matters

The deterministic provider intentionally mirrors an important real-provider property:

```text
Document embedding
      ≠
Query embedding
```

even when the textual input is identical.

This allows tests to catch accidental mixing of document/query embedding pathways.

---

# Normalization

When enabled, the generated vector is L2-normalized.

```text
raw vector
    │
    ▼
L2 normalization
    │
    ▼
EmbeddingVector
```

The normalization implementation explicitly handles the theoretical zero-norm case as well.

---

# Input Validation

The deterministic provider validates:

* input types;
* blank text;
* document batch shape;
* query text;
* vector dimensionality;
* response cardinality.

A string is explicitly rejected as the document `Sequence[str]` input because otherwise:

```python
embed_documents("hello")
```

could accidentally become:

```text
"h", "e", "l", "l", "o"
```

rather than one document.

---

# Batch Contract Validation

After generating document embeddings, the implementation verifies:

```text
returned_count == requested_count
```

and:

```text
every vector.dimension == descriptor.dimensions
```

Violations produce structured embedding exceptions rather than silently returning malformed batches.

---

# 4. `instrumented.py` — Provider Telemetry Wrapper

## Purpose

`InstrumentedEmbeddingProvider` is a **decorator/wrapper** around any `EmbeddingProvider`.

It adds observability without changing the provider contract.

```text
             EmbeddingProvider
                    │
                    ▼
       InstrumentedEmbeddingProvider
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
   Telemetry                 Provider
   Recorder                      │
        │                        ▼
        └──────────────► Result/Error
```

The wrapper preserves provider results and exceptions. Telemetry failures are not supposed to replace the actual provider result or failure.

---

# `EmbeddingCallContext`

Provider calls can be associated with immutable context:

```text
purpose
ai_run_id
trace_id
knowledge_version_id
metadata
```

The context validates UUID fields and normalizes the purpose to lowercase. Metadata is converted to an immutable mapping.

This allows provider telemetry to be correlated with higher-level AI execution without storing the actual embedding input.

---

# Telemetry Recorder Contract

The instrumentation layer expects a recorder supporting:

```text
start_call()
complete_call()
fail_call()
timeout_call()
```

The wrapper validates that these operations are available during construction.

The intended lifecycle is:

```text
provider invocation
       │
       ▼
start_call
       │
       ▼
actual provider operation
       │
   ┌───┴────┐
   │        │
success   failure/timeout
   │        │
   ▼        ▼
complete  fail/timeout
```

---

# Privacy Boundary

Instrumentation deliberately does not persist:

```text
raw input text
embedding vectors
```

Instead, telemetry can correlate calls through IDs, fingerprints, provider/model identity, latency, status, and bounded metadata.

This follows the broader telemetry data-minimization approach used by the knowledge subsystem.

---

# `last_call_id`

The wrapper exposes:

```python
last_call_id
```

which represents the telemetry identifier of the most recent provider invocation.

This can be used by retrieval/application layers to associate a retrieval operation with the exact embedding call that generated its query vector.

---

# Query Cache Integration

`InstrumentedEmbeddingProvider` can optionally receive:

```python
query_cache: QueryEmbeddingCache | None
```

This allows query embedding to be instrumented and cached within the same provider boundary.

The resulting architecture can therefore be:

```text
Retrieval Service
      │
      ▼
InstrumentedEmbeddingProvider
      │
      ├── QueryEmbeddingCache
      │
      ├── Telemetry Recorder
      │
      └── Actual Provider
             │
             └── Jina / Deterministic / other
```

---

# 5. `query_cache.py` — Query Embedding Cache

## Purpose

`QueryEmbeddingCache` is a process-local cache specifically for **retrieval-query embeddings**.

It is:

* bounded;
* TTL-based;
* LRU-evicted;
* thread-safe;
* provider-aware;
* privacy-conscious;
* capable of collapsing concurrent identical misses.

It is **not** a cache for persisted document embeddings.

---

# Cache Configuration

Defaults:

```text
max_entries = 512
ttl_seconds = 3600
```

Maximums:

```text
max_entries <= 100000
ttl_seconds <= 86400
```

Invalid values are rejected during construction.

---

# Cache Key

Raw query text is never used directly as a stored cache key.

Instead:

```text
cache key input
    │
    ├── cache-key version
    ├── provider descriptor identity
    ├── query byte length
    └── exact UTF-8 query text
          │
          ▼
       SHA-256
          │
          ▼
      cache key
```

The exact query text is hashed rather than normalized, ensuring cache behavior does not silently change provider-input semantics.

---

# Provider-Aware Cache Identity

The provider descriptor participates in the cache key.

Therefore:

```text
same query
+
Jina v4 / 1024 dimensions
```

cannot collide with:

```text
same query
+
different provider/model/dimensions
```

This is necessary because embeddings produced by different provider configurations are not interchangeable.

---

# TTL

Each cached vector has an expiration timestamp:

```text
expires_at = monotonic() + ttl_seconds
```

Expired entries are removed rather than returned.

The implementation uses monotonic time for expiration rather than wall-clock time, making TTL behavior independent of system clock changes.

---

# LRU Eviction

The cache uses an `OrderedDict`.

When:

```text
len(entries) > max_entries
```

the oldest entry is removed.

```text
Least Recently Used
        │
        ▼
     evicted
```

This guarantees that cache memory/cardinality remains bounded.

---

# In-Flight Request Coalescing

The cache does more than ordinary memoization.

If multiple concurrent callers request the same embedding:

```text
Request A ─┐
Request B ─┤
Request C ─┼── same query/provider
Request D ─┘
```

only one caller executes:

```text
loader()
```

The others wait for that computation to finish.

```text
                same cache key
                     │
             ┌───────┴────────┐
             ▼                ▼
        first caller     other callers
             │                │
             ▼                ▼
          loader()          wait()
             │                │
             ▼                │
        cache vector ─────────┘
```

The cache explicitly releases its lock before waiting, preventing a slow provider call from blocking unrelated cache operations.

---

# Failed Computations

If the loader raises an exception:

```text
loader()
   │
   ▼
failure
   │
   ├── no cache entry
   ├── release in-flight state
   └── propagate exception
```

Failed computations are therefore never cached.

Waiting callers are released so a later request can retry normally.

---

# Cache Result

`get_or_compute()` returns:

```text
QueryEmbeddingCacheResult
├── vector
├── cache_hit
└── waited_for_inflight
```

This allows higher layers to distinguish:

```text
direct cache hit
```

from:

```text
new computation
```

and:

```text
caller waited for another in-flight computation
```

---

# Cache Statistics

The cache exposes:

```text
size
hits
misses
inflight_waits
evictions
```

These metrics are useful for operational monitoring and cache tuning.

For example:

```text
high hits
    → good query reuse

high misses
    → low query repetition / short TTL / small cache

high inflight_waits
    → concurrent duplicate requests

high evictions
    → working set exceeds cache capacity
```

---

# Thread Safety

The cache uses an `RLock` around shared cache state.

The protected state includes:

```text
entries
in-flight computations
statistics
evictions
```

Provider execution is intentionally performed outside the cache lock.

---

# End-to-End Provider Architecture

When all five files are used together, the provider subsystem can be understood as:

```text
                           Retrieval / Ingestion
                                   │
                                   ▼
                         EmbeddingProvider contract
                                  base.py
                                   │
                 ┌─────────────────┴─────────────────┐
                 │                                   │
                 ▼                                   ▼
       Instrumented Provider                    Direct Provider
         instrumented.py                            │
                 │                                  │
        ┌────────┴─────────┐                ┌───────┴────────┐
        │                  │                │                │
        ▼                  ▼                ▼                ▼
 QueryEmbeddingCache   Telemetry       Jina Provider   Deterministic
   query_cache.py      Recorder          jina.py        deterministic.py
                                            │
                                            ▼
                                      External API
```

The instrumentation wrapper can therefore act as the stable operational boundary around a concrete provider.

---

# Document Embedding Flow

The document-ingestion path is conceptually:

```text
Canonical Knowledge Chunks
          │
          ▼
Embedding Input Builder
          │
          ▼
Prepared Embedding Inputs
          │
          ▼
InstrumentedEmbeddingProvider
          │
          ▼
JinaEmbeddingProvider
          │
          ▼
Jina Embeddings API
          │
          ▼
EmbeddingBatch
          │
          ▼
Embedding Persistence
```

The provider itself does not know about the persistence layer.

---

# Query Embedding Flow

The retrieval path is:

```text
User Query
    │
    ▼
Retrieval Service
    │
    ▼
InstrumentedEmbeddingProvider
    │
    ▼
QueryEmbeddingCache
    │
 ┌──┴─────────┐
 │            │
HIT          MISS
 │            │
 ▼            ▼
Vector     Actual Provider
              │
              ▼
         JinaEmbeddingProvider
              │
              ▼
         EmbeddingVector
              │
              ▼
            Cache
              │
              ▼
       Vector Retrieval
```

The retrieval service then passes the query vector to the vector repository. The repository remains responsible for searching persisted embeddings and does not generate query embeddings itself.

---

# Provider Identity and Persistence

Provider identity is not merely diagnostic metadata.

Persisted embeddings are associated with their exact embedding profile.

Conceptually:

```text
Embedding Artifact
├── provider
├── model
├── revision
├── dimensions
└── input descriptor
```

Therefore, changing:

```text
provider
model
revision
dimensions
input strategy
input strategy version/configuration
```

can require a new embedding generation process rather than treating existing vectors as interchangeable.

This aligns the provider descriptor with the repository's exact-profile embedding coverage model.

---

# Separation of Responsibilities

A major design goal of this package is to keep concerns separated.

## `base.py`

Owns:

```text
provider contract
```

## `jina.py`

Owns:

```text
external provider boundary
```

## `deterministic.py`

Owns:

```text
test/local deterministic implementation
```

## `instrumented.py`

Owns:

```text
provider-call observability
```

## `query_cache.py`

Owns:

```text
query embedding reuse
```

None of these should own:

```text
knowledge persistence
retrieval ranking
reranking
grounding context
LLM generation
application orchestration
```

---

# Error Boundary

The provider subsystem establishes an important error boundary:

```text
External Provider / HTTP
          │
          ▼
Jina Provider
          │
          ▼
Embedding Exception Hierarchy
          │
          ▼
Application / Retrieval Layer
```

This means callers do not need to know whether a failure originated from:

```text
httpx
Jina API
network
authentication
malformed response
dimension mismatch
rate limiting
timeout
```

They receive the application's structured embedding error types instead.

---

# Validation Philosophy

The provider implementations validate aggressively at the boundary.

Typical rules include:

```text
text
  → must be string
  → must not be blank

dimensions
  → must be positive

batch
  → input/output cardinality must match

vectors
  → correct dimensionality
  → valid numeric values

provider descriptor
  → must identify the actual configuration
```

This keeps malformed provider behavior from propagating into retrieval or persistence.

---

# Privacy Model

The provider layer follows a data-minimization approach.

It may retain or expose:

```text
provider identity
model
revision
dimensions
call IDs
trace IDs
latencies
status
error metadata
query fingerprints
cache statistics
```

It should not persist:

```text
raw customer query
raw knowledge chunk
embedding vectors in telemetry
provider API secrets
```

In particular, `query_cache.py` uses a SHA-256 cache key rather than retaining raw query text as the cache key.

---

# Testing Strategy

The five modules support a layered testing strategy.

## Provider contract tests

Run against every `EmbeddingProvider` implementation:

```text
descriptor
embed_documents
embed_query
dimension validation
error translation
```

## Jina tests

Mock the HTTP boundary and test:

```text
request construction
document/query task selection
authentication failures
timeouts
rate limits
malformed responses
cardinality mismatches
ordering mismatches
dimension mismatches
invalid vectors
```

## Deterministic provider tests

Verify:

```text
same input → same vector
same configuration → same descriptor
document/query namespaces differ
dimensions remain stable
normalization works
invalid inputs fail correctly
batch ordering is preserved
```

## Cache tests

Verify:

```text
cache hit
cache miss
TTL expiration
LRU eviction
provider-aware keys
exact-text semantics
in-flight coalescing
failure handling
thread safety
statistics
```

## Instrumentation tests

Verify:

```text
start_call
complete_call
fail_call
timeout_call
call ID propagation
telemetry failure isolation
query-cache integration
raw-content privacy
```

---

# Important Invariants

## 1. Application code depends on the provider contract

Higher layers should use:

```text
EmbeddingProvider
```

rather than Jina/httpx directly.

---

## 2. Document and query embedding remain separate

```text
embed_documents()
        ≠
embed_query()
```

This distinction is intentional and must be preserved across provider implementations.

---

## 3. Provider identity must remain stable

The descriptor must accurately describe the provider instance used to generate the vector.

---

## 4. Vector dimensionality must match the descriptor

```text
vector.dimensions
        ==
descriptor.dimensions
```

---

## 5. Provider-specific errors do not leak upward

External provider failures are translated into the project's embedding exception hierarchy.

---

## 6. Deterministic provider is not a production semantic model

It is a testing/local-development implementation only.

---

## 7. Telemetry must not alter provider semantics

The instrumentation layer observes provider calls but should not replace successful results or underlying provider exceptions.

---

## 8. Query caching must not change query semantics

The cache hashes the exact query text rather than normalizing it before key generation.

---

## 9. Failed embedding computations must not be cached

Only successful `EmbeddingVector` results enter the query cache.

---

## 10. The cache is process-local

`QueryEmbeddingCache` is not a distributed cache and does not provide cross-process synchronization.

---

# Current Provider Strategy

The package currently provides two provider implementations:

```text
Production / External
└── JinaEmbeddingProvider

Testing / Local
└── DeterministicEmbeddingProvider
```

Both satisfy:

```text
EmbeddingProvider
```

This means application and retrieval code can switch implementations without changing their provider-facing contract.

---

# Adding Another Provider

A future provider should:

1. inherit from `EmbeddingProvider`;
2. expose an accurate `EmbeddingProviderDescriptor`;
3. implement `embed_documents()`;
4. implement `embed_query()`;
5. validate returned dimensions;
6. preserve document input ordering;
7. translate provider-specific failures into the embedding error hierarchy;
8. avoid leaking SDK-specific exceptions;
9. avoid embedding persistence concerns;
10. remain independent of retrieval/application orchestration.

For example:

```text
EmbeddingProvider
       │
       ├── JinaEmbeddingProvider
       ├── DeterministicEmbeddingProvider
       └── FutureEmbeddingProvider
```

No retrieval service should need to know which concrete implementation is active.

---

# Summary

`packages/knowledge/embeddings/provider/` is the **provider boundary and runtime infrastructure for embeddings**.

The five files have complementary responsibilities:

```text
┌──────────────────────────────────────────────────────────┐
│                  Embedding Provider Layer                │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  base.py                                                 │
│  └── Provider contract                                   │
│                                                          │
│  jina.py                                                 │
│  └── Real Jina AI integration                            │
│                                                          │
│  deterministic.py                                        │
│  └── Deterministic testing/local implementation          │
│                                                          │
│  instrumented.py                                         │
│  └── Telemetry + provider-call correlation               │
│                                                          │
│  query_cache.py                                          │
│  └── Query embedding caching + coalescing                │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

The resulting design gives the rest of the system a clean boundary:

```text
                    Application / Retrieval
                              │
                              ▼
                    EmbeddingProvider
                              │
             ┌────────────────┼────────────────┐
             │                │                │
             ▼                ▼                ▼
          Jina          Deterministic     Instrumentation
             │                │                │
             └────────────────┴────────────────┘
                              │
                              ▼
                     EmbeddingVector
                              │
                              ▼
                    Retrieval / Storage
```

The key architectural properties are:

* **provider neutrality** through `EmbeddingProvider`;
* **real external integration** through `JinaEmbeddingProvider`;
* **deterministic testing** through `DeterministicEmbeddingProvider`;
* **observability without behavioral coupling** through `InstrumentedEmbeddingProvider`;
* **efficient query reuse** through `QueryEmbeddingCache`;
* **stable provider identity and dimensionality** through `EmbeddingProviderDescriptor`;
* **strict response validation** at the external-provider boundary;
* **structured provider errors** rather than SDK-specific exceptions;
* **privacy-aware query caching and telemetry**;
* **clear separation from persistence, retrieval, reranking, and application orchestration**.

Together, these files form the runtime boundary through which the knowledge system converts text into provider-neutral embeddings while keeping external-provider concerns, testing concerns, observability, and query-performance optimization isolated from the rest of the application.
