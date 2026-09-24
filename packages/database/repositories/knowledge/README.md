# Knowledge Database Repositories

## Overview

The `packages/database/repositories/knowledge/` package contains the **SQLAlchemy/PostgreSQL implementations of the knowledge persistence and retrieval contracts**.

These repositories form the infrastructure boundary between the domain/application-level knowledge system and PostgreSQL:

```text
Knowledge Domain / Application
             │
             │ repository contracts
             ▼
packages/database/repositories/knowledge/
             │
             │ SQLAlchemy
             ▼
     PostgreSQL / pgvector
```

The package covers the complete persisted knowledge lifecycle:

```text
Document
   │
   ▼
Version
   │
   ▼
Chunks
   │
   ▼
Embeddings
   │
   ├──────────────► Vector Retrieval
   │
   └──────────────► Lexical Retrieval
                         │
                         ▼
                  Retrieval Results
```

It also contains the scoped retrieval adapters that ensure each retrieval operation gets a short-lived database session.

---

## Files

```text
packages/
└── database/
    └── repositories/
        └── knowledge/
            ├── version_repository.py
            ├── document_repository.py
            ├── chunk_repository.py
            ├── embedding_repository.py
            ├── mappers.py
            ├── vector_retrieval_repository.py
            ├── lexical_retrieval_repository.py
            └── scoped_retrieval_repositories.py
```

| File | Main responsibility |
|---|---|
| `document_repository.py` | Persist and query knowledge documents |
| `version_repository.py` | Manage document versions and lifecycle |
| `chunk_repository.py` | Persist and retrieve derived chunks |
| `embedding_repository.py` | Persist and query embedding artifacts |
| `mappers.py` | Convert domain objects ↔ SQLAlchemy models |
| `vector_retrieval_repository.py` | PostgreSQL/pgvector semantic retrieval |
| `lexical_retrieval_repository.py` | PostgreSQL full-text lexical retrieval |
| `scoped_retrieval_repositories.py` | Execute retrieval inside short-lived read transactions |

---

# Repository Architecture

There are effectively **two groups** of repositories in this package.

### Knowledge persistence

```text
document_repository
        │
        ▼
version_repository
        │
        ▼
chunk_repository
        │
        ▼
embedding_repository
```

These repositories manage the stored knowledge artifacts.

### Knowledge retrieval

```text
                  Retrieval Contract
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
        Vector Retrieval      Lexical Retrieval
              │                     │
              └──────────┬──────────┘
                         ▼
                  Retrieval Matches
```

`scoped_retrieval_repositories.py` provides the transaction/session boundary around the two retrieval implementations.

---

# 1. `document_repository.py`

## `SQLAlchemyKnowledgeDocumentRepository`

This repository is the persistence implementation for the **knowledge document aggregate**.

It works with:

```text
KnowledgeDocument
        ↕
KnowledgeDocumentModel
```

The repository supports:

- `add()`
- `get_by_id()`
- `get_by_id_for_update()`
- `save()`
- `exists()`
- `list()`
- `count()`



### Filtering

Document listing supports:

```text
status
content_type
visibility
```

These are translated into SQLAlchemy predicates by `_apply_filter()`.

### Row Locking

`get_by_id_for_update()` acquires a PostgreSQL row-level lock using `FOR UPDATE`.

This is intended for lifecycle operations where concurrent workers must not modify the same document simultaneously.

### Safe Updates

`save()` explicitly loads the existing row before updating it.

If the document no longer exists, it raises `LookupError` instead of silently allowing the operation to behave like an insert.

---

# 2. `version_repository.py`

## `SQLAlchemyKnowledgeVersionRepository`

This repository manages **document versions** and their lifecycle.

It works with:

```text
KnowledgeDocumentVersion
        ↕
KnowledgeDocumentVersionModel
```

The corresponding domain contract supports version creation, retrieval, lifecycle updates, duplicate-content detection, publication lookup, history, version-number allocation, embedding candidates, pagination, and counting.

### Main Responsibilities

The concrete repository provides operations for:

```text
add()
get_by_id()
get_by_id_for_update()
get_by_document_and_content_hash()
save()
get_published_for_document()
list_for_document()
next_version_number()
list_embedding_candidates()
list_page_for_document()
count_for_document()
```

### Lifecycle Locking

`get_by_id_for_update()` is particularly important.

It obtains a row-level PostgreSQL lock for lifecycle transitions such as:

```text
  DRAFT
    ↓
PROCESSING
    ↓
  READY
    ↓
PUBLISHED
```

or:

```text
PROCESSING
    ↓
  FAILED
```

The lock prevents concurrent workers from successfully claiming or completing the same version simultaneously.

### Content Deduplication

`get_by_document_and_content_hash()` validates and normalizes the supplied SHA-256 content hash before querying.

This allows ingestion logic to identify an existing version containing identical source content.

### Version Allocation

`next_version_number()` is intended to provide concurrency-safe version numbering within the surrounding transaction.

This is important when multiple workers can create versions for the same document.

---

# 3. `chunk_repository.py`

## `SQLAlchemyKnowledgeChunkRepository`

This repository persists **derived knowledge chunks**.

A chunk belongs to a particular document version:

```text
Document
   │
   └── Version
         │
         ├── Chunk 0
         ├── Chunk 1
         ├── Chunk 2
         └── ...
```

The repository works with:

```text
KnowledgeChunk
        ↕
KnowledgeChunkModel
```

and provides:

- `add()`
- `add_many()`
- `get_by_id()`
- `list_for_version()`
- `delete_for_version()`



### Ordering

`list_for_version()` returns chunks ordered by:

```text
chunk_index ASC
```

so the original document sequence can be reconstructed.

### Reprocessing

`delete_for_version()` removes all derived chunks belonging to a version.

This is intended for reprocessing an unpublished version rather than ordinary document deletion.

---

# 4. `embedding_repository.py`

## `SQLAlchemyKnowledgeEmbeddingRepository`

This repository manages **immutable, model-dependent embedding artifacts** associated with knowledge chunks.

It works with:

```text
KnowledgeChunkEmbedding
        ↕
KnowledgeChunkEmbeddingModel
```

Embeddings are associated not only with a chunk but also with an exact embedding profile.

That profile includes:

```text
provider
model
model revision
dimensions
input strategy
strategy version
configuration fingerprint
```



### Main Operations

```text
add()
add_many()
add_many_if_absent()
get_by_id()
list_for_chunk()
list_for_chunks()
get_coverage_for_version()
```



### Idempotent Bulk Insertion

`add_many_if_absent()` uses PostgreSQL:

```text
ON CONFLICT DO NOTHING
```

against the embedding artifact uniqueness constraint.

This makes concurrent embedding workers safe to run without creating duplicate logical artifacts.

### Profile-Aware Lookup

An embedding generated using a different:

```text
provider
model
revision
dimension
input strategy
configuration
```

is treated as a different artifact.

Therefore retrieval and coverage queries only consider embeddings matching the requested profile.

### Coverage

`get_coverage_for_version()` performs one aggregate query to determine:

```text
total_chunk_count
embedded_chunk_count
```

It uses distinct chunk IDs so historical embedding artifacts do not inflate the coverage calculation.

---

# 5. `mappers.py`

## Domain ↔ Persistence Translation

`mappers.py` is the translation boundary between:

```text
Knowledge Domain Objects
          ↕
SQLAlchemy Models
```

It prevents the domain layer from needing to understand SQLAlchemy model structure.

### Document Mapping

```text
document_to_domain()
document_to_model()
update_document_model()
```

The update mapper intentionally changes only mutable persisted state and leaves identity untouched.

### Version Mapping

```text
version_to_domain()
version_to_model()
update_version_model()
```

The version update mapper changes lifecycle/mutable state without changing version identity or immutable source information.

### Chunk Mapping

```text
chunk_to_domain()
chunk_to_model()
```

Chunk metadata is converted between the domain representation and the database's `metadata_` representation.

### Embedding Mapping

```text
chunk_embedding_to_domain()
chunk_embedding_to_model()
```

The embedding mapper reconstructs:

```text
EmbeddingProviderDescriptor
EmbeddingInputDescriptor
EmbeddingVector
```

from the persisted representation and performs the reverse conversion when storing an embedding.

### Why This File Matters

Repositories can therefore follow a consistent pattern:

```text
Domain object
     │
     ▼
mapper
     │
     ▼
SQLAlchemy model
     │
     ▼
PostgreSQL
```

and on reads:

```text
PostgreSQL
     │
     ▼
SQLAlchemy model
     │
     ▼
mapper
     │
     ▼
Domain object
```

---

# 6. `vector_retrieval_repository.py`

## `SQLAlchemyVectorRetrievalRepository`

This repository implements **semantic/vector knowledge retrieval using PostgreSQL + pgvector**.

It implements the domain retrieval contract:

```text
VectorRetrievalRepository
```

and accepts:

```text
VectorSearchRequest
```

returning:

```text
VectorSearchMatch
```



### Responsibilities

The repository:

- searches stored chunk embeddings;
- uses cosine distance;
- matches the requested embedding profile;
- restricts results to retrieval-ready knowledge;
- applies caller-supplied filters;
- returns deterministic distance-ranked results.

### Explicit Boundaries

It does **not**:

- generate the query embedding;
- commit or rollback;
- perform score fusion;
- rerank;
- build LLM context.

The intended pipeline is therefore:

```text
        User Query
            │
            ▼
    Embedding Provider
            │
            ▼
    VectorSearchRequest
            │
            ▼
Vector Retrieval Repository
            │
            ▼
    Candidate Matches
            │
            ▼
Reranker / Context Builder
```

### Database Query

The query uses pgvector cosine distance against persisted embeddings and joins the relevant chunk, version, and document records.

Database errors and invalid persisted retrieval data are converted into the retrieval-specific repository error rather than leaking raw SQLAlchemy failures into the domain layer.

---

# 7. `lexical_retrieval_repository.py`

## `SQLAlchemyLexicalRetrievalRepository`

This repository implements **lexical/full-text knowledge retrieval using PostgreSQL text search**.

It converts natural-language input into a PostgreSQL `tsquery` and ranks matching chunks using PostgreSQL full-text relevance.

### Search

The repository accepts:

```text
LexicalSearchRequest
```

and returns:

```text
LexicalSearchMatch
```



### PostgreSQL Full-Text Search

The implementation uses:

```text
english
```

as the text-search configuration and uses:

```text
websearch_to_tsquery()
ts_rank_cd()
```

for query construction and ranking.

Conceptually:

```text
Natural-language query
        │
        ▼
websearch_to_tsquery()
        │
        ▼
PostgreSQL full-text search
        │
        ▼
    ts_rank_cd()
        │
        ▼
Ranked lexical matches
```

### Retrieval Lifecycle

The repository joins chunks with their versions and documents and applies knowledge lifecycle invariants so that retrieval operates over appropriate canonical knowledge.

### Error Boundary

SQLAlchemy failures are translated into `LexicalRetrievalRepositoryError`, while invalid persisted rows are also converted into the same infrastructure-specific error.

---

# 8. `scoped_retrieval_repositories.py`

## Purpose

The two concrete retrieval repositories use a SQLAlchemy `Session`, but retrieval queries should have a **short and explicit database-session lifetime**.

`scoped_retrieval_repositories.py` provides that boundary.

It defines:

```text
RetrievalReadUnitOfWork
```

and:

```text
ScopedSQLAlchemyLexicalRetrievalRepository
ScopedSQLAlchemyVectorRetrievalRepository
```



---

## Retrieval Read Unit of Work

The protocol provides:

```text
session
__enter__()
__exit__()
```

and intentionally does not commit.

Exiting the scope rolls back the read transaction and closes the session.

This keeps retrieval transactions short-lived.

---

## Scoped Lexical Retrieval

The lexical scoped repository:

1. creates a read Unit of Work;
2. obtains its SQLAlchemy session;
3. constructs `SQLAlchemyLexicalRetrievalRepository`;
4. executes the search;
5. returns domain-level immutable matches;
6. allows the session to close.



No SQLAlchemy session or ORM object escapes the `search()` call.

---

## Scoped Vector Retrieval

The vector scoped repository follows the same pattern:

```text
search()
   │
   ▼
short-lived UoW
   │
   ▼
Session
   │
   ▼
SQLAlchemyVectorRetrievalRepository
   │
   ▼
VectorSearchMatch[]
   │
   ▼
session closes
```



Importantly, query embedding generation occurs **before** this repository is invoked, while reranking and generation occur **after** the search returns and the read session has closed.

---

# Transaction Boundaries

The persistence repositories generally do **not own transaction lifecycle**.

The intended structure is:

```text
Application / Use Case
          │
          ▼
     Unit of Work
          │
    ┌─────┴─────┐
    │           │
    ▼           ▼
Repositories   Retrieval
    │           │
    └─────┬─────┘
          ▼
       commit()
```

For example, documents explicitly stage changes without committing, leaving commit/rollback to the surrounding Unit of Work.

The same principle applies to chunks and embeddings.

---

# Row-Level Locking

Document and version repositories expose explicit locking operations:

```text
get_by_id_for_update()
```

These are intended for operations where concurrent workers must serialize lifecycle changes.

```text
Worker A                 Worker B
   │                        │
   ├── FOR UPDATE           │
   │                        ├── waits
   │                        │
   ├── modify state         │
   ├── save                 │
   └── commit               │
                            ├── obtains lock
                            └── continues
```

This is particularly important for publishing, processing, and other knowledge lifecycle transitions.

---

# Knowledge Retrieval Flow

The repositories support two complementary retrieval strategies:

```text
                       User Query
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
       Query Embedding            Query Text
              │                         │
              ▼                         ▼
       Vector Repository         Lexical Repository
              │                         │
              ▼                         ▼
       Semantic Matches          Keyword Matches
              │                         │
              └────────────┬────────────┘
                           ▼
                    Retrieval Layer
                           │
                           ▼
                       Reranking
                           │
                           ▼
                     Context Builder
                           │
                           ▼
                          LLM
```

The vector repository handles semantic similarity, while the lexical repository handles PostgreSQL full-text matching.

Neither repository performs reranking or LLM context construction.

---

# Persistence Flow

The ingestion/persistence side follows:

```text
Source
  │
  ▼
Knowledge Document
  │
  ▼
Document Version
  │
  ▼
Chunks
  │
  ▼
Embedding Artifacts
```

The repository implementations correspond directly to these stages:

```text
document_repository.py
        │
        ▼
version_repository.py
        │
        ▼
chunk_repository.py
        │
        ▼
embedding_repository.py
```

This structure keeps the knowledge domain model independent of the underlying PostgreSQL representation.

---

# Domain / Database Boundary

A key design principle of this folder is:

> **Domain objects do not become SQLAlchemy models directly.**

Instead:

```text
KnowledgeDocument
       │
       ▼
document_to_model()
       │
       ▼
KnowledgeDocumentModel
```

and:

```text
KnowledgeDocumentModel
       │
       ▼
document_to_domain()
       │
       ▼
KnowledgeDocument
```

The same pattern exists for versions, chunks, and embeddings.

This prevents persistence concerns from leaking into the domain layer.

---

# Important Architectural Boundaries

These repositories intentionally **do not** handle:

- document parsing;
- document ingestion orchestration;
- chunking algorithms;
- embedding generation;
- query embedding generation;
- reranking;
- LLM context construction;
- answer generation;
- transaction orchestration at the application level.

Instead:

```text
Knowledge Application
       │
       ├── ingestion
       ├── chunking
       ├── embedding generation
       ├── retrieval orchestration
       └── context construction
                 │
                 ▼
       Database Repository Layer
                 │
                 ▼
              PostgreSQL
```

For example, the vector repository explicitly stops at retrieval and does not generate embeddings, rerank, or build context.

---

# Summary

`packages/database/repositories/knowledge/` is the infrastructure implementation of the knowledge persistence and retrieval layer.

```text
┌─────────────────────────────────────────────────────┐
│        packages/database/repositories/knowledge     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Document Repository                                │
│       │                                             │
│       ▼                                             │
│  Version Repository                                 │
│       │                                             │
│       ▼                                             │
│  Chunk Repository                                   │
│       │                                             │
│       ▼                                             │
│  Embedding Repository                               │
│                                                     │
│  ─────────────────────────────────────────────────  │
│                                                     │
│  Vector Retrieval ──────┐                           │
│                         ├── Retrieval Results       │
│  Lexical Retrieval ─────┘                           │
│                                                     │
│  Scoped Retrieval Repositories                ,     │
│       └── short-lived read transactions             │
│                                                     │
│  Mappers                                            │
│       └── domain ↔ SQLAlchemy translation           │
│                                                     │
└─────────────────────────────────────────────────────┘
```

The central design is:

> **Persistence repositories manage durable knowledge state, retrieval repositories query that state, mappers isolate the domain from SQLAlchemy, and scoped retrieval adapters control short-lived read transactions.**

Together, these eight files provide the database-side implementation for the knowledge lifecycle from **document → version → chunk → embedding → retrieval**, while keeping business orchestration and AI logic outside the database layer.