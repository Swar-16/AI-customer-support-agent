# Knowledge Database Models

## Overview

The `packages/database/models/knowledge/` package contains the SQLAlchemy persistence models for the application's **knowledge-management and retrieval data layer**.

These models represent the lifecycle of knowledge from its stable document identity through immutable versions, retrieval-ready chunks, and independently managed vector embeddings.

The package consists of four database entities plus the package export module:

```text
packages/database/models/knowledge/
├── __init__.py
├── document.py
├── document_version.py
├── chunk.py
└── chunk_embedding.py
```

The overall hierarchy is:

```text
Knowledge Document
│
├── Version 1
│   ├── Chunk 0
│   │   ├── Embedding A
│   │   └── Embedding B
│   ├── Chunk 1
│   │   └── Embedding A
│   └── ...
│
├── Version 2
│   ├── Chunk 0
│   │   └── Embedding A
│   └── ...
│
└── Version N
    └── ...
```

The central design principle is that each layer has a distinct responsibility:

```text
Document
    = stable knowledge identity

Document Version
    = immutable source revision

Chunk
    = version-specific retrieval unit

Chunk Embedding
    = model/provider-specific vector artifact
```

---

# Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── database/
        └── models/
            └── knowledge/
                ├── __init__.py
                ├── document.py
                ├── document_version.py
                ├── chunk.py
                └── chunk_embedding.py
```

All four ORM entities use the PostgreSQL `knowledge` schema.

The package's `__init__.py` exposes the four model classes as the public model-level API.

---

# Model Relationship

The complete persistence relationship is:

```text
┌──────────────────────────────┐
│     KnowledgeDocument        │
│                              │
│ Stable logical identity      │
└──────────────┬───────────────┘
               │ 1:N
               ▼
┌──────────────────────────────┐
│   KnowledgeDocumentVersion   │
│                              │
│ Immutable source revision    │
└──────────────┬───────────────┘
               │ 1:N
               ▼
┌──────────────────────────────┐
│       KnowledgeChunk         │
│                              │
│ Retrieval unit               │
└──────────────┬───────────────┘
               │ 1:N
               ▼
┌──────────────────────────────┐
│   KnowledgeChunkEmbedding    │
│                              │
│ Vector artifact              │
└──────────────────────────────┘
```

This separation is particularly important for RAG because **document identity, source revision, chunking, and embedding generation do not have the same lifecycle**.

---

# 1. `document.py`

## `KnowledgeDocumentModel`

`KnowledgeDocumentModel` represents the **stable identity of a logical knowledge document**.

A document might represent:

```text
Refund Policy
Privacy Policy
Shipping Policy
Account Recovery Guide
Billing Dispute Procedure
```

The document itself does not represent a particular revision of its content.

Instead:

```text
Refund Policy
├── Version 1
├── Version 2
└── Version 3
```

The model explicitly keeps document identity separate from its revisions. It does not contain a `current_version_id`; publication state belongs to versions and is coordinated by the application layer.

---

## Core Fields

The document contains:

```text
id
title
description
content_type
visibility
status
metadata
created_at
updated_at
archived_at
deleted_at
```

The title must not be blank, and content type, visibility, and status are constrained to their domain-defined values.

---

## Document Lifecycle

The document supports lifecycle states such as:

```text
active
archived
deleted
```

The database enforces consistency between the status and lifecycle timestamps:

```text
active
  ├── archived_at = NULL
  └── deleted_at  = NULL

archived
  ├── archived_at != NULL
  └── deleted_at  = NULL

deleted
  └── deleted_at != NULL
```

This prevents contradictory states from being persisted.

---

## Metadata

The PostgreSQL column is named:

```text
metadata
```

while the Python attribute is:

```text
metadata_
```

because `metadata` is reserved by SQLAlchemy's declarative API.

The field uses PostgreSQL `JSONB`.

---

## Versions Relationship

A document owns an ordered collection of versions:

```text
KnowledgeDocument
       │
       ├── Version 1
       ├── Version 2
       ├── Version 3
       └── ...
```

The relationship is configured with cascading deletion and ordered by `version_number`.

---

# 2. `document_version.py`

## `KnowledgeDocumentVersionModel`

`KnowledgeDocumentVersionModel` represents an **immutable revision of a knowledge document**.

The key rule is:

> When source content changes, create a new version rather than overwriting the existing source revision.

This gives the system reproducible historical knowledge states.

---

# Version Identity

Each version belongs to exactly one document:

```text
Document
   │
   ├── version 1
   ├── version 2
   └── version 3
```

A unique constraint prevents the same document from having duplicate version numbers.

`version_number` must be positive.

---

# Source Information

A version stores the source material from which downstream knowledge artifacts are generated:

```text
source_type
source_content
content_hash
source_name
source_uri
metadata
```

The source content and content hash cannot be blank.

The `content_hash` provides a stable way to identify the exact source content associated with a version.

---

# Version Lifecycle

A version has two related lifecycle dimensions:

```text
status
ingestion_status
```

The model uses domain-defined values for:

* source type;
* version status;
* ingestion status.

These are database-constrained.

This distinction is useful because:

```text
Version status
    =
publication / lifecycle state

Ingestion status
    =
processing state
```

For example, a version can exist as a draft while its ingestion pipeline is still pending or processing.

---

# Processing Timestamps

The model tracks processing milestones:

```text
processing_started_at
processing_completed_at
ready_at
published_at
superseded_at
archived_at
```

It can also retain:

```text
failure_code
failure_message
```

for ingestion failures.

This provides a durable representation of the knowledge ingestion lifecycle.

---

# Published Version Constraint

A document can have at most one published version.

This is implemented with a PostgreSQL partial unique index:

```text
document_id
WHERE status = 'published'
```

Conceptually:

```text
Document
├── Version 1 → superseded
├── Version 2 → superseded
└── Version 3 → published  ← only one
```

This is an important invariant for retrieval systems because there must be an unambiguous published revision of a document.

---

# Version → Chunk Relationship

A document version owns its chunks:

```text
Document Version
      │
      ├── Chunk 0
      ├── Chunk 1
      ├── Chunk 2
      └── ...
```

The relationship is ordered by `chunk_index` and uses cascading deletion.

---

# 3. `chunk.py`

## `KnowledgeChunkModel`

`KnowledgeChunkModel` represents a **persisted retrieval unit derived from a specific document version**.

This is the entity that the RAG retrieval layer ultimately works with.

The important distinction is:

```text
Document
    ↓
Version
    ↓
Chunk
```

A chunk is therefore always associated with the exact source version from which it was generated.

---

# Chunk Identity and Ordering

Each chunk belongs to a version through:

```text
version_id
```

and has:

```text
chunk_index
```

A database uniqueness constraint ensures that one version cannot contain two chunks at the same position.

For example:

```text
Version 7
│
├── chunk_index = 0
├── chunk_index = 1
├── chunk_index = 2
└── chunk_index = 3
```

`chunk_index` must be non-negative.

---

# Chunk Content

The primary retrieval content is:

```text
content
```

The database ensures the content is not blank.

A chunk may additionally retain:

```text
section_title
```

for structural provenance.

---

# Source Offsets

Chunks can preserve their location inside the source content using:

```text
start_offset
end_offset
```

The model treats the range as half-open:

```text
[start_offset, end_offset)
```

equivalent to:

```python
source[start_offset:end_offset]
```

Offsets may be absent when the parser cannot provide reliable positions. When present, the database ensures they form a valid range.

---

# Token Count

A chunk may store:

```text
token_count
```

When present, it must be positive.

This can support downstream context-budget calculations without requiring the content to be tokenized again.

---

# Chunk Metadata

Chunks have extensible JSONB metadata:

```text
metadata
```

represented in Python as:

```text
metadata_
```

This can hold derived chunk-level attributes without requiring schema changes for every new metadata field.

---

# Why Embeddings Are Separate

A critical architectural decision is that `KnowledgeChunkModel` does **not** contain its vector.

The chunk represents canonical textual content.

Its embeddings are separate because different embedding providers/models/configurations can generate multiple valid vector representations of the same chunk.

Therefore:

```text
Chunk
├── Embedding using Model A
├── Embedding using Model B
└── Embedding using Model C
```

can exist without duplicating the chunk itself.

---

# 4. `chunk_embedding.py`

## `KnowledgeChunkEmbeddingModel`

`KnowledgeChunkEmbeddingModel` represents an **immutable embedding artifact generated from a canonical knowledge chunk**.

The embedding is deliberately separated from the chunk because it depends on:

* embedding provider;
* embedding model/revision;
* vector dimensionality;
* embedding-input strategy;
* input configuration.

---

# Vector Storage

The actual embedding is stored using pgvector:

```text
embedding
```

with SQLAlchemy's:

```text
Vector
```

type.

The vector dimensionality is stored separately as:

```text
dimensions
```

and must be greater than zero.

---

# Embedding Provenance

Every embedding records:

```text
provider
model
model_revision
dimensions
```

This means the system can determine exactly which embedding implementation produced a vector.

For example:

```text
Chunk
  │
  └── Embedding
       ├── provider = jina
       ├── model = jina-embeddings-v4
       ├── revision = ...
       └── dimensions = 1024
```

---

# Input Strategy Provenance

The model additionally records how the text was prepared before embedding:

```text
input_strategy_id
input_strategy_version
input_config_fingerprint
input_fingerprint
```

This is important because the same source chunk can produce different embeddings even with the same embedding model if the input construction changes.

For reproducibility:

```text
   Embedding
      ↓
   Provider
      ↓
    Model
      ↓
  Model Revision
      ↓
 Input Strategy
      ↓
Input Configuration
      ↓
 Input Fingerprint
```

---

# Embedding Uniqueness

The database prevents duplicate embedding artifacts for the same combination of:

```text
chunk
provider
model
model_revision
dimensions
input_strategy_id
input_strategy_version
input_config_fingerprint
input_fingerprint
```

This makes embedding generation effectively idempotent at the persistence level.

---

# Multiple Embeddings Per Chunk

A chunk can therefore have multiple embedding artifacts:

```text
Chunk
│
├── Provider A / Model A / 768 dimensions
├── Provider B / Model B / 1024 dimensions
└── Provider B / Model C / 1536 dimensions
```

This supports:

* embedding model migration;
* experimentation;
* re-indexing;
* multiple retrieval configurations;
* evaluation;
* provider changes.

The canonical chunk does not need to be rewritten for any of these operations.

---

# Complete Knowledge Data Flow

The four main models represent the complete persistence pipeline:

```text
Source
  │
  ▼
KnowledgeDocument
  │
  │ logical identity
  ▼
KnowledgeDocumentVersion
  │
  │ immutable source revision
  ▼
KnowledgeChunk
  │
  │ retrieval units
  ▼
KnowledgeChunkEmbedding
  │
  │ vector representation
  ▼
Vector Retrieval
```

This separation allows every retrieval result to be traced back to:

```text
Vector
 ↓
Embedding configuration
 ↓
Chunk
 ↓
Document version
 ↓
Logical document
```

---

# Versioning and Reprocessing

The model hierarchy is designed to support reprocessing without destroying historical artifacts.

For example:

```text
Document
│
├── Version 1
│   ├── Chunks
│   └── Embeddings
│
└── Version 2
    ├── Chunks
    └── Embeddings
```

Version 1 remains historically identifiable even after Version 2 becomes published.

Similarly, changing the embedding model does not require changing the chunk:

```text
Version 2
│
└── Chunk 17
     │
     ├── Embedding Model A
     └── Embedding Model B
```

---

# Deletion and Cascading

The hierarchy uses cascading relationships where child records are dependent artifacts.

```text
Document
   │
   └── Version
          │
          └── Chunk
                 │
                 └── Embedding
```

The model relationships configure cascading deletion for:

```text
Document → Versions
Version  → Chunks
Chunk    → Embeddings
```

For example, a chunk's embedding relationship uses `cascade="all, delete-orphan"` and database-level cascading deletion.

Similarly, versions cascade from documents and chunks cascade from versions.

This ensures derived artifacts do not remain orphaned.

---

# Data Integrity Philosophy

The models use database-level constraints extensively.

Examples include:

### Documents

```text
title cannot be blank
valid content type
valid visibility
valid status
consistent lifecycle timestamps
```

### Versions

```text
version number > 0
source content cannot be blank
content hash cannot be blank
valid source type
valid version status
valid ingestion status
one published version per document
```

### Chunks

```text
chunk index >= 0
content cannot be blank
unique position per version
valid source offsets
positive token count
```

### Embeddings

```text
dimensions > 0
unique artifact provenance
```

This prevents invalid knowledge states from entering the database even if data bypasses normal application-level validation.

---

# Timestamp Strategy

All four persistence models use timezone-aware timestamps.

Important timestamps include:

```text
Document
├── created_at
├── updated_at
├── archived_at
└── deleted_at

Version
├── created_at
├── updated_at
├── processing_started_at
├── processing_completed_at
├── ready_at
├── published_at
├── superseded_at
└── archived_at

Chunk
├── created_at
└── updated_at

Embedding
└── created_at
```

This gives the knowledge subsystem a complete lifecycle timeline.

---

# Indexing Strategy

Indexes are focused on the queries expected from knowledge management and retrieval.

## Documents

Indexed dimensions include:

```text
status
content_type
visibility
created_at
```

## Versions

Indexes support:

```text
document
created_at
processing completion
content hash
status
ingestion status
published version lookup
```

## Chunks

Chunks are indexed by:

```text
version_id
```

## Embeddings

Embeddings are indexed by:

```text
chunk_id
provider + model + dimensions
```

---

# Relationship to RAG

These models form the persistence foundation for the RAG knowledge lifecycle:

```text
                Knowledge Management
                         │
                         ▼
                      Document
                         │
                         ▼
                      Version
                         │
                         ▼
                      Chunking
                         │
                         ▼
                       Chunks
                         │
                         ▼
                     Embeddings
                         │
                         ▼
                    Vector Search
                         │
                         ▼
                  Retrieval Candidates
                         │
                         ▼
                     RAG Context
                         │
                         ▼
                     LLM Answer
```

The database models stop at the knowledge-artifact boundary.

They do not themselves perform:

* chunking;
* embedding generation;
* vector search;
* retrieval;
* reranking;
* context construction.

Those responsibilities belong to the corresponding application/domain services.

---

# Important Architectural Boundaries

## Document vs Version

Do not treat the document as the content revision.

```text
Document
    = "Which knowledge item is this?"

Version
    = "Which exact revision of that knowledge is this?"
```

---

## Version vs Chunk

A version contains the source representation.

A chunk is a derived retrieval unit:

```text
Version
    └── source_content

Chunk
    └── retrieval-ready segment of that source
```

---

## Chunk vs Embedding

A chunk is canonical textual content.

An embedding is a model-dependent representation of that content:

```text
Chunk
    ≠
Embedding
```

One chunk may legitimately have multiple embeddings.

---

# `__init__.py`

The package initializer acts as the public import surface for the knowledge ORM models.

It exposes:

```python
KnowledgeDocumentModel
KnowledgeDocumentVersionModel
KnowledgeChunkModel
KnowledgeChunkEmbeddingModel
```

through `__all__`.

This allows higher-level database code to import the model layer from the package rather than depending on individual module paths.

---

# Typical Usage Flow

A new knowledge document follows approximately:

```text
1. Create KnowledgeDocumentModel
            │
            ▼
2. Create KnowledgeDocumentVersionModel
            │
            ▼
3. Process / ingest source
            │
            ▼
4. Create KnowledgeChunkModel rows
            │
            ▼
5. Generate embeddings
            │
            ▼
6. Create KnowledgeChunkEmbeddingModel rows
            │
            ▼
7. Mark version ready/published
            │
            ▼
8. Retrieval can use published knowledge
```

The exact orchestration of these operations belongs outside the ORM models.

---

# Re-Embedding Flow

Changing the embedding configuration does not require recreating the document or chunks.

```text
Existing Document
      │
      ▼
Existing Version
      │
      ▼
Existing Chunk
      │
      ├───────────────┐
      ▼               ▼
Old Embedding     New Embedding
Model A           Model B
```

This is one of the primary reasons the embedding artifact is its own table.

---

# Re-Versioning Flow

When source content changes:

```text
Existing Document
      │
      ├── Version 1
      │
      └── Version 2  ← new revision
            │
            ├── new chunks
            └── new embeddings
```

The previous version remains identifiable rather than being overwritten.

This preserves provenance and supports reproducibility.

---

# Query Mental Model

When investigating a retrieved piece of knowledge, the hierarchy can be followed backwards:

```text
Embedding
    │
    ▼
Chunk
    │
    ▼
Document Version
    │
    ▼
Document
```

This allows the system to answer:

> Which vector produced this retrieval result?

→ embedding artifact

> Which text does that vector represent?

→ chunk

> Which source revision produced that chunk?

→ document version

> Which logical knowledge item does that version belong to?

→ document

---

# Summary

The `packages/database/models/knowledge/` package provides a clean four-layer persistence hierarchy:

```text
┌──────────────────────────┐
│ Knowledge Document       │
│ Stable identity          │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Document Version         │
│ Immutable source         │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Knowledge Chunk          │
│ Retrieval unit           │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Chunk Embedding          │
│ Vector artifact          │
└──────────────────────────┘
```

The design deliberately separates **stable identity, immutable source revisions, retrieval units, and model-specific vector artifacts**.

That separation provides:

* versioned knowledge;
* reproducible source provenance;
* deterministic chunk ordering;
* independent embedding lifecycle;
* multiple embeddings per chunk;
* embedding-model migration support;
* publication-state integrity;
* ingestion-state tracking;
* vector provenance;
* database-level validation;
* cascading cleanup of derived artifacts;
* efficient retrieval-oriented indexing.

In short:

> **`KnowledgeDocumentModel` identifies the knowledge, `KnowledgeDocumentVersionModel` identifies the exact source revision, `KnowledgeChunkModel` defines the retrieval units derived from that revision, and `KnowledgeChunkEmbeddingModel` stores the model-specific vector representations of those units.**
