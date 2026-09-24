# Embedding Provider

## Overview

The `packages/knowledge/embeddings/provider/` package contains infrastructure responsible for interacting with embedding providers and managing provider-related concerns.

One important concern in this layer is **query-embedding reuse**. Retrieval systems frequently embed the same or nearly identical customer queries within a short period of time. Recomputing those embeddings unnecessarily increases provider latency, API usage, and potentially cost.

The `query_cache.py` module provides a process-local, bounded, TTL-based cache specifically for **retrieval-query embeddings**.

```text
packages/
└── knowledge/
    └── embeddings/
        └── provider/
            └── query_cache.py
```

Its primary abstraction is:

```text
QueryEmbeddingCache
```

which provides:

```text
query text
    +
embedding provider descriptor
    │
    ▼
cache key
    │
    ├── HIT ──────────────► cached EmbeddingVector
    │
    └── MISS
          │
          ▼
       loader()
          │
          ▼
    EmbeddingVector
          │
          ▼
        cache
```

The cache is designed specifically around the semantics and safety requirements of **retrieval query embeddings**, not document embeddings.

---

# Responsibilities

`query_cache.py` is responsible for:

* caching retrieval-query embedding vectors;
* preventing raw query text from being retained as cache keys;
* distinguishing embeddings produced by different provider configurations;
* enforcing TTL expiration;
* enforcing a maximum cache size;
* applying LRU eviction;
* collapsing simultaneous identical cache misses;
* preventing failed embedding computations from being cached;
* exposing lightweight cache statistics;
* providing thread-safe access to the cache.

It does **not**:

* call an embedding API itself;
* know how an embedding provider works internally;
* cache document embeddings;
* persist cache entries to a database;
* persist customer queries;
* normalize query text;
* change embedding-provider semantics.

---

# Core Design

The cache sits immediately around the query-embedding operation:

```text
                    Retrieval Query
                          │
                          ▼
                QueryEmbeddingCache
                          │
                ┌─────────┴─────────┐
                │                   │
             CACHE HIT           CACHE MISS
                │                   │
                ▼                   ▼
        EmbeddingVector          loader()
                                    │
                                    ▼
                             Embedding Provider
                                    │
                                    ▼
                             EmbeddingVector
                                    │
                                    ▼
                                  Cache
```

The caller supplies the actual computation through a `loader` callback.

This keeps the cache independent of any particular embedding provider.

---

# `QueryEmbeddingCacheResult`

The module exposes an immutable result object:

```python
@dataclass(frozen=True, slots=True)
class QueryEmbeddingCacheResult:
    vector: EmbeddingVector
    cache_hit: bool
    waited_for_inflight: bool
```

It provides three pieces of information:

| Field                 | Meaning                                                              |
| --------------------- | -------------------------------------------------------------------- |
| `vector`              | The resulting query embedding                                        |
| `cache_hit`           | Whether the vector came directly from an existing cache entry        |
| `waited_for_inflight` | Whether this caller waited for another caller computing the same key |

This makes cache behavior observable to the calling retrieval/application layer without exposing internal cache structures.

---

# Cache Entries

Internal cache entries are represented by:

```python
@dataclass(frozen=True, slots=True)
class _CacheEntry:
    vector: EmbeddingVector
    expires_at: float
```

Each entry therefore contains only:

```text
EmbeddingVector
+
absolute expiration time
```

The raw query text is not stored in the entry.

---

# Query Cache Characteristics

The implementation explicitly guarantees the following properties:

```text
Bounded
    ↓
TTL expiration
    ↓
LRU eviction
    ↓
Thread-safe
    ↓
Provider-aware
    ↓
Query-text-safe
    ↓
In-flight request coalescing
```

The module's documented correctness/security properties include:

* raw query text is never retained as a cache key;
* the complete provider descriptor identity participates in the key;
* document embeddings are not supported;
* failed computations are never cached;
* simultaneous identical misses are collapsed into one computation;
* storage is bounded using LRU eviction.

---

# Configuration

The constructor is:

```python
QueryEmbeddingCache(
    max_entries=512,
    ttl_seconds=3600.0,
)
```

## `max_entries`

Controls the maximum number of completed entries held by the cache.

Constraints:

```text
must be an integer
must be > 0
must be <= 100000
```

Boolean values are deliberately rejected even though Python considers `bool` a subclass of `int`.

---

## `ttl_seconds`

Controls how long a cached embedding remains valid.

Constraints:

```text
must be numeric
must be > 0
must be <= 86400 seconds
```

The default is:

```text
3600 seconds = 1 hour
```

The implementation uses `monotonic()` for expiration timing rather than wall-clock time, avoiding problems caused by system clock adjustments.

---

# Internal State

The cache maintains:

```text
_entries
_inflight
_lock
_hits
_misses
_inflight_waits
_evictions
```

The completed cache uses:

```python
OrderedDict[str, _CacheEntry]
```

so the ordering can represent LRU state.

The in-flight registry uses:

```python
dict[str, Event]
```

to coordinate concurrent callers requesting the same embedding.

A re-entrant lock protects the shared state.

---

# Cache Lookup

The primary API is:

```python
get_or_compute(
    text: str,
    descriptor: EmbeddingProviderDescriptor,
    loader: Callable[[], EmbeddingVector],
)
```

Its behavior is:

```text
                   get_or_compute()
                          │
                          ▼
                    Build cache key
                          │
                          ▼
                   Check cache entry
                    /             \
                  HIT             MISS
                   │                │
                   ▼                ▼
             return vector     Check inflight
                                  /       \
                              existing    none
                                │           │
                                ▼           ▼
                              wait       become
                                │       computation
                                │           │
                                └─────┬─────┘
                                      ▼
                                   loader()
                                      │
                                      ▼
                                  cache vector
                                      │
                                      ▼
                                    return
```

---

# Cache Hit

If an entry exists and has not expired:

1. it is moved to the end of the `OrderedDict`;
2. the hit counter is incremented;
3. the cached vector is returned immediately.

Moving the key to the end makes it the most recently used entry.

The result is:

```text
cache_hit = True
waited_for_inflight = <whether caller previously waited>
```

---

# TTL Expiration

If a cached entry exists but:

```text
expires_at <= current_monotonic_time
```

the entry is removed and treated as a cache miss.

The implementation therefore never returns an expired embedding.

---

# In-Flight Request Coalescing

One of the most important features of this cache is **in-flight computation collapsing**.

Consider five concurrent requests:

```text
Request A ──┐
Request B ──┤
Request C ──┼── same query + provider
Request D ──┤
Request E ──┘
```

Without coalescing:

```text
5 requests
    │
    ├── provider call
    ├── provider call
    ├── provider call
    ├── provider call
    └── provider call
```

With this cache:

```text
Request A
    │
    └── loader()
          │
          ▼
     Provider call
          │
          ▼
     cache result
          │
    ┌─────┼─────┐
    ▼     ▼     ▼
Request B/C/D/E
    │
    └── receive same result
```

When the first caller registers the cache key as in-flight, subsequent callers wait on the corresponding `Event`.

This prevents a burst of identical retrieval queries from multiplying provider calls.

---

# Locking During In-Flight Work

The implementation deliberately does **not** hold the cache lock while waiting for the embedding computation.

```text
Cache lock
   │
   ├── inspect state
   ├── register/wait decision
   └── release
          │
          ▼
       Event.wait()
```

The comment in the implementation explicitly establishes this invariant.

This is important because provider execution can involve network I/O and therefore may take significantly longer than ordinary cache operations.

---

# Loader Execution

The actual embedding computation is delegated to:

```python
loader()
```

The cache expects the loader to return:

```text
EmbeddingVector
```

If the returned object is not an `EmbeddingVector`, a `TypeError` is raised.

This keeps the cache contract strongly typed even though the actual provider implementation is external to the cache.

---

# Failed Computations Are Not Cached

If `loader()` raises an exception:

```text
loader()
   │
   ├── exception
   │
   ▼
release in-flight state
   │
   ▼
re-raise exception
```

The computation is not inserted into the cache.

The in-flight event is released so that waiting callers can retry rather than being permanently blocked.

This is a critical correctness property:

```text
failure ≠ cacheable result
```

---

# Successful Computation

After successful provider execution:

```text
EmbeddingVector
      │
      ▼
expires_at = monotonic() + ttl
      │
      ▼
insert into OrderedDict
      │
      ▼
LRU eviction if necessary
      │
      ▼
release waiting callers
```

Waiting callers can then observe the newly cached result.

---

# LRU Eviction

The cache is bounded by `max_entries`.

When the number of entries exceeds that limit:

```python
popitem(last=False)
```

removes the least recently used entry.

Conceptually:

```text
Oldest ─────────────────── Newest
  │                           │
  ▼                           ▼
evict                       retain
```

Every eviction increments:

```text
evictions
```

---

# TTL and LRU Work Together

The cache has two independent retention controls:

### TTL

Removes entries because they have become stale.

### LRU

Removes entries because the cache has reached its configured capacity.

Therefore:

```text
TTL = freshness bound
LRU = memory/cardinality bound
```

Both are needed.

A frequently used query can remain in the cache while its TTL is valid, but it still cannot force the cache beyond `max_entries`.

---

# Cache Key Construction

The cache never uses raw query text directly as a dictionary key.

Instead, `_build_key()` computes a SHA-256 digest.

The key includes:

```text
CACHE_KEY_VERSION
+
EmbeddingProviderDescriptor.identity
+
exact query bytes
```

with explicit separators and the query byte length.

Conceptually:

```text
cache-key-input =
    cache-version
    +
    provider-identity
    +
    query-byte-length
    +
    exact-query-bytes
```

Then:

```text
SHA-256(...)
      │
      ▼
hexadecimal cache key
```

---

# Why Provider Identity Is Part of the Key

The same query can produce different vectors depending on:

* provider;
* model;
* dimensions;
* revision;
* other descriptor-defined identity information.

Therefore:

```text
"Where is my order?"
+
Provider A
```

must not collide with:

```text
"Where is my order?"
+
Provider B
```

The cache uses the complete `EmbeddingProviderDescriptor.identity` to prevent this class of collision.

---

# Exact Query Semantics

The key is generated from the **exact input text**.

It does not normalize the query before hashing.

For example:

```text
"Where is my order?"
```

and:

```text
"where is my order?"
```

produce different cache keys.

Likewise:

```text
"Where is my order?"
```

and:

```text
"Where is my order? "
```

remain different.

This is intentional.

The cache must never change the semantics of the input that reaches the embedding provider. The implementation explicitly hashes the exact text rather than normalizing it.

---

# Query Privacy

The raw query text is not retained as the cache key.

Instead:

```text
Customer Query
      │
      ▼
    SHA-256
      │
      ▼
Opaque Cache Key
```

This avoids retaining customer query text directly in the cache's indexing structure.

The cache key is therefore a one-way digest rather than a readable query.

---

# Cache Key Versioning

The cache defines:

```python
CACHE_KEY_VERSION = "query-embedding-cache-v1"
```

This value participates in the hash input.

The purpose is to make future cache-key changes explicit.

For example, if the key construction algorithm changes:

```text
query-embedding-cache-v1
        │
        ▼
query-embedding-cache-v2
```

the new key space will naturally avoid accidental compatibility with the previous scheme.

This is particularly useful if the cache design evolves.

---

# Thread Safety

`QueryEmbeddingCache` is designed for concurrent access within a process.

A shared `RLock` protects:

* cache entries;
* in-flight state;
* statistics;
* eviction;
* cache clearing.

The cache therefore supports concurrent retrieval requests without requiring the caller to implement its own synchronization around cache operations.

---

# Cache Statistics

The cache exposes several operational counters.

## `size`

Returns the number of currently stored completed entries.

Expired entries are removed before the size is returned.

## `hits`

Number of successful direct cache hits.

## `misses`

Number of callers that became responsible for a new cache computation.

## `inflight_waits`

Number of callers that encountered an already-running computation and waited for it.

## `evictions`

Number of entries removed because the cache exceeded its capacity.

These properties are useful for diagnostics and operational metrics without exposing internal structures.

---

# Interpreting Statistics

The counters provide useful signals.

### High hit rate

```text
hits ↑
misses ↓
```

suggests query reuse is effective.

### High misses

May indicate:

* low query repetition;
* short TTL;
* rapidly changing provider descriptors;
* insufficient cache size.

### High in-flight waits

Indicates bursts of concurrent identical queries.

This is not necessarily a problem; it can demonstrate that request coalescing is actively preventing duplicate provider work.

### High evictions

Indicates that the working set exceeds the configured `max_entries`.

---

# Clearing the Cache

The cache provides:

```python
clear()
```

which removes completed entries.

It deliberately does **not** cancel in-flight computations.

Therefore:

```text
clear()
   │
   ├── completed entries → removed
   │
   └── in-flight calls → continue
```

This avoids disrupting provider operations already in progress.

---

# Invalid Input Behavior

`get_or_compute()` validates its primary arguments.

### `text`

If `text` is not a string, the cache deliberately bypasses its own key construction and calls the loader directly:

```text
invalid text
    │
    ▼
loader()
```

This preserves the wrapped provider's own validation and exception type rather than replacing it with cache-specific validation.

### `descriptor`

Must be an:

```text
EmbeddingProviderDescriptor
```

otherwise a `TypeError` is raised.

### `loader`

Must be callable.

Otherwise:

```text
TypeError
```

is raised.

---

# Intended Scope

This cache is explicitly a:

```text
process-local
```

cache.

That means:

```text
Application Process A
└── QueryEmbeddingCache

Application Process B
└── QueryEmbeddingCache
```

do not share entries.

It is therefore not a replacement for a distributed cache such as Redis.

This design is appropriate when query embeddings have short-lived reuse opportunities and a local cache can eliminate duplicate provider calls within the same process.

---

# Why Document Embeddings Are Not Cached Here

The class is intentionally scoped to retrieval-query embeddings.

Document embeddings have different characteristics:

```text
Document embeddings
    │
    ├── persistent
    ├── tied to chunks
    ├── require provenance
    └── belong in embedding artifacts/storage
```

Query embeddings are:

```text
Query embeddings
    │
    ├── transient
    ├── frequently repeated
    ├── short-lived
    └── suitable for TTL caching
```

The cache explicitly documents that document embeddings are unsupported.

---

# Relationship to Retrieval

The intended retrieval flow is approximately:

```text
Customer Query
      │
      ▼
Query Embedding Cache
      │
      ├── hit ────────────────┐
      │                       │
      └── miss → Provider     │
                   │          │
                   ▼          │
              Embedding       │
                   │          │
                   └────┬─────┘
                        ▼
                  Vector Search
                        │
                        ▼
                 Candidate Chunks
                        │
                        ▼
                    Retrieval
```

The cache therefore optimizes the **query embedding stage**, not vector search itself.

---

# Example Usage

Conceptually, a retrieval service can use:

```python
result = query_embedding_cache.get_or_compute(
    text=query,
    descriptor=provider.descriptor,
    loader=lambda: provider.embed_query(query),
)

vector = result.vector
```

The application can then inspect:

```python
result.cache_hit
result.waited_for_inflight
```

for observability.

The cache itself remains unaware of how `provider.embed_query()` is implemented.

---

# Concurrency Example

Suppose three requests arrive simultaneously:

```text
R1 ──┐
R2 ──┼── "How do I return an item?"
R3 ──┘
```

Assuming the same provider descriptor:

### R1

```text
cache miss
→ register in-flight
→ loader()
```

### R2

```text
cache miss
→ detect in-flight
→ wait
```

### R3

```text
cache miss
→ detect in-flight
→ wait
```

Provider:

```text
1 actual embedding call
```

After completion:

```text
R1 → result
R2 → result
R3 → result
```

Only one vector computation is performed.

---

# Failure Example

If the provider fails:

```text
R1
 │
 ▼
loader()
 │
 └── provider error
        │
        ▼
remove in-flight marker
        │
        ▼
re-raise
```

No failed result is cached.

A later request can attempt the provider again.

This avoids poisoning the cache with an unsuccessful computation.

---

# Lifecycle of a Cache Entry

```text
               get_or_compute()
                      │
                      ▼
                    MISS
                      │
                      ▼
                 loader()
                  /     \
             failure   success
                │         │
                ▼         ▼
          no cache     store vector
                          │
                          ▼
                       TTL starts
                          │
                 ┌────────┴────────┐
                 │                 │
             accessed           expires
                 │                 │
                 ▼                 ▼
           LRU refresh         remove
                 │
                 ▼
            may remain
          until TTL/eviction
```

An entry therefore disappears either because:

1. its TTL expires, or
2. it becomes the least recently used entry while the cache is full.

---

# Performance Characteristics

The cache is designed to make the common retrieval path inexpensive.

### Cache hit

Approximately:

```text
lock
→ dictionary lookup
→ LRU update
→ return
```

No provider call occurs.

### Cache miss

```text
lookup
→ provider computation
→ cache insertion
```

### Concurrent identical miss

```text
one provider computation
+
N waiting callers
```

This is particularly valuable when embedding generation is network-bound.

---

# Testing Considerations

Tests for this module should cover at least:

## Basic caching

* first request is a miss;
* second identical request is a hit;
* loader executes only once.

## Provider isolation

* same text + different descriptor produces different cache entries.

## Exact input semantics

* case differences create different keys;
* whitespace differences create different keys.

## TTL

* entries are returned before expiration;
* expired entries trigger recomputation.

## LRU

* least recently used entries are evicted;
* accessing an entry updates its recency.

## In-flight coalescing

* concurrent identical misses invoke loader once;
* waiting callers receive the same result;
* `inflight_waits` increments.

## Failure

* provider failure is not cached;
* in-flight state is released;
* subsequent callers can retry.

## Validation

* invalid descriptor;
* non-callable loader;
* invalid loader result.

## Clear

* completed entries are removed;
* in-flight operations continue.

## Thread safety

* concurrent access does not corrupt cache state;
* statistics remain consistent.

---

# Operational Considerations

The cache is intentionally bounded:

```text
max_entries <= 100000
```

and:

```text
ttl <= 86400 seconds
```

This prevents accidental configuration from creating an effectively unbounded long-lived in-process cache.

For production tuning, the main parameters are:

```text
max_entries
ttl_seconds
```

Increasing `max_entries` favors reuse at the cost of memory.

Increasing `ttl_seconds` favors reuse at the cost of retaining vectors longer.

The appropriate values depend on query repetition, provider cost/latency, process memory, and retrieval workload.

---

# Architectural Boundaries

The provider cache should remain below the application/retrieval orchestration layer:

```text
Application / Retrieval
        │
        ▼
Query Embedding Cache
        │
        ▼
Embedding Provider
        │
        ▼
External Embedding Service
```

The cache should not acquire knowledge of:

* customer sessions;
* tickets;
* conversations;
* retrieval ranking;
* vector database schemas;
* HTTP requests;
* API authentication;
* document persistence.

Its concern is strictly:

> **Reuse an already-computed query embedding safely and efficiently.**

---

# Summary

`query_cache.py` provides a small but important optimization boundary around retrieval-query embeddings.

Its design combines:

```text
                 QueryEmbeddingCache
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
      SHA-256           TTL             LRU
        │                │                │
        └────────────────┼────────────────┘
                         │
                         ▼
                 In-flight coalescing
                         │
                         ▼
                 Thread-safe storage
```

The most important guarantees are:

* **raw query text is not retained as the cache key;**
* **provider identity participates in cache identity;**
* **exact query text is hashed without normalization;**
* **only successful embedding computations are cached;**
* **simultaneous identical misses share one computation;**
* **entries expire through TTL;**
* **storage remains bounded through LRU eviction;**
* **document embeddings are intentionally outside this cache;**
* **the cache is process-local and provider-agnostic.**

This makes the module a focused infrastructure component for reducing redundant embedding-provider calls during retrieval while preserving the exact semantics of the embedding input.
