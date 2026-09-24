# Knowledge Repositories

## Overview

The `packages/knowledge/repositories/` package defines the **persistence contracts** used by the knowledge domain and application layers.

These files contain `Protocol` interfaces rather than concrete database implementations. The contracts keep the knowledge layer independent of PostgreSQL, SQLAlchemy, or any other persistence technology.

```text
repositories/
├── chunk_repository.py
├── document_repository.py
├── embedding_repository.py
└── version_repository.py
```

The concrete implementations are responsible for translating these contracts into actual persistence operations.

---

## Repository Contracts

| File                      | Contract                       | Responsibility                                        |
| ------------------------- | ------------------------------ | ----------------------------------------------------- |
| `chunk_repository.py`     | `KnowledgeChunkRepository`     | Persist and retrieve derived knowledge chunks         |
| `document_repository.py`  | `KnowledgeDocumentRepository`  | Persist and manage knowledge documents                |
| `embedding_repository.py` | `KnowledgeEmbeddingRepository` | Persist and query model-dependent embedding artifacts |
| `version_repository.py`   | `KnowledgeVersionRepository`   | Persist and manage document-version lifecycle         |

---

## `chunk_repository.py`

`KnowledgeChunkRepository` defines persistence operations for **knowledge chunks**, which are derived retrieval units belonging to an exact document version.

Main operations:

* `add()` — persist one chunk.
* `add_many()` — persist multiple chunks within the surrounding transaction.
* `get_by_id()` — retrieve a chunk by identity.
* `list_for_version()` — retrieve all chunks for a version, ordered by chunk index.
* `delete_for_version()` — remove derived chunks for a version, primarily when reprocessing.

The contract leaves bulk-operation optimization to the concrete implementation.

---

## `document_repository.py`

`KnowledgeDocumentRepository` provides persistence operations for the **knowledge document aggregate**. Its implementation may use PostgreSQL, an in-memory store, or another persistence mechanism without affecting the domain/application layer.

### Filtering

`KnowledgeDocumentListFilter` supports filtering by:

* document status;
* content type;
* visibility.

### Main operations

The contract supports:

* creation with `add()`;
* retrieval with `get_by_id()`;
* existence checks with `exists()`;
* persistence of existing state with `save()`;
* filtered/paginated listing with `list()`;
* filtered counting with `count()`.

It also exposes a row-locking `get_by_id_for_update()` operation for lifecycle operations that must serialize document-level changes, such as publishing versions.

---

## `version_repository.py`

`KnowledgeVersionRepository` defines persistence operations for **knowledge document versions** without exposing SQLAlchemy or PostgreSQL details to the knowledge layer.

### Filtering

`KnowledgeVersionListFilter` supports:

* version status;
* ingestion status;
* source type.

### Main operations

The contract supports:

* creating and retrieving versions;
* updating existing versions;
* row-locking a version with `get_by_id_for_update()`;
* locating duplicate content using document/source/content hash;
* retrieving the currently published version;
* listing version history;
* allocating the next version number;
* retrieving versions eligible for embedding;
* paginated history and counting.

`next_version_number()` specifically requires concurrency-safe allocation within the surrounding transaction.

`list_embedding_candidates()` returns only successfully ingested, published versions eligible for embedding/backfill.

---

## `embedding_repository.py`

`KnowledgeEmbeddingRepository` manages **model-dependent embedding artifacts** associated with knowledge chunks.

Unlike documents, versions, and chunks, embeddings are tied to a specific embedding configuration.

That configuration is represented by:

* `EmbeddingProviderDescriptor`;
* `EmbeddingInputDescriptor`.

An embedding generated under a different provider, model, revision, dimensionality, input strategy, strategy version, or configuration fingerprint does not count toward coverage for another embedding profile.

### Main operations

The contract supports:

* `add()` — persist one embedding;
* `add_many()` — persist multiple embeddings;
* `add_many_if_absent()` — insert only missing artifacts;
* `get_by_id()` — retrieve by identity;
* `list_for_chunk()` — retrieve embeddings for one chunk;
* `list_for_chunks()` — retrieve existing embeddings for multiple chunks under an exact embedding profile;
* `get_coverage_for_version()` — calculate embedding coverage for a version.

### Embedding Coverage

`KnowledgeVersionEmbeddingCoverage` represents:

```text
total_chunk_count
embedded_chunk_count
```

It validates that counts are non-negative and that embedded chunks cannot exceed total chunks. A version with zero chunks is never considered fully embedded.

Coverage is profile-specific: embeddings produced under another embedding configuration are ignored.

---

# Transaction Boundary

These repositories are designed to participate in a **surrounding Unit of Work / transaction**.

Repository methods do not own the transaction lifecycle.

In particular, the embedding repository explicitly requires implementations not to commit independently.

The same principle applies to bulk embedding operations and aggregate retrieval/coverage operations.

Conceptually:

```text
Application / Use Case
        │
        ▼
Unit of Work / Transaction
        │
        ├── Document Repository
        ├── Version Repository
        ├── Chunk Repository
        └── Embedding Repository
        │
        ▼
      Commit
```

Repositories provide persistence operations; the surrounding transaction boundary controls commit/rollback behavior.

---

# Row-Level Locking

Document and version repositories expose explicit `*_for_update()` operations.

These are intended for lifecycle operations that require serialized state transitions.

```text
get_by_id_for_update()
        │
        ▼
row-level write lock
        │
        ▼
domain lifecycle operation
        │
        ▼
      save()
```

For documents, this is explicitly used to serialize aggregate-level lifecycle operations such as publishing document versions.

For versions, the lock is held for the lifetime of the surrounding transaction.

---

# Architectural Boundary

These contracts intentionally prevent persistence concerns from leaking into the knowledge domain.

```text
Knowledge Domain / Application
              │
              ▼
     Repository Protocols
              │
              ▼
 Concrete Persistence Adapter
              │
              ▼
 PostgreSQL / SQLAlchemy / etc.
```

The domain/application layer depends on interfaces such as `KnowledgeDocumentRepository` and `KnowledgeVersionRepository`, not on concrete database classes.

---

# Design Principles

* **Protocol-based:** contracts are defined independently of persistence technology.
* **Transaction-aware:** repositories participate in an existing transaction rather than owning commits.
* **Domain-oriented:** methods represent knowledge operations rather than generic SQL operations.
* **Bulk-aware:** operations such as `add_many()` allow efficient persistence.
* **Concurrency-aware:** lifecycle-critical operations expose row-level locking where required.
* **Embedding-profile aware:** embedding operations distinguish exact provider/input configurations.
* **Implementation-neutral:** concrete adapters can use PostgreSQL, SQLAlchemy, in-memory storage, or another mechanism.

---

# Summary

The repository package is the **persistence abstraction boundary** for the knowledge subsystem:

```text
KnowledgeDocumentRepository
        │
        └── Documents

KnowledgeVersionRepository
        │
        └── Document Versions

KnowledgeChunkRepository
        │
        └── Derived Chunks

KnowledgeEmbeddingRepository
        │
        └── Embedding Artifacts
```

These files define **what persistence operations are available**, while concrete repository implementations determine **how those operations are executed**.
