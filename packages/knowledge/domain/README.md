# Knowledge Domain

## Overview

The `packages/knowledge/domain/` package contains the **core business model for the knowledge base**.

It defines the domain entities, lifecycle states, value semantics, and domain-specific errors used by the knowledge subsystem. The domain layer is intentionally independent of persistence, HTTP, retrieval infrastructure, embedding providers, and other external concerns.

```text
packages/knowledge/domain/
├── document.py
├── version.py
├── chunk.py
├── embedding.py
├── enums.py
└── errors.py
```

The six files work together to represent the lifecycle:

```text
KnowledgeDocument
      │
      ├── Version 1
      ├── Version 2
      └── Version N
             │
             ├── Chunk 0
             ├── Chunk 1
             └── Chunk N
                    │
                    └── Embeddings
```

---

# Files

| File           | Responsibility                                                   |
| -------------- | ---------------------------------------------------------------- |
| `document.py`  | Logical knowledge-document identity and lifecycle                |
| `version.py`   | Immutable content revisions and processing/publication lifecycle |
| `chunk.py`     | Derived retrieval units belonging to a specific version          |
| `embedding.py` | Model-dependent embedding artifacts for chunks                   |
| `enums.py`     | Shared domain state/type vocabularies                            |
| `errors.py`    | Domain-specific invariant and lifecycle errors                   |

---

# `document.py`

Defines `KnowledgeDocument`, representing the **stable identity of a knowledge asset** such as a refund policy, FAQ, or internal guide. The actual knowledge content is intentionally stored on versions rather than directly on the document.

A document contains information such as:

* identity;
* title;
* content type;
* visibility;
* description;
* administrative metadata;
* lifecycle timestamps.

The document lifecycle is:

```text
ACTIVE
  │
  ├── ARCHIVED
  │
  └── DELETED
```

Deletion is terminal at the domain level, while archival represents a retained but inactive document.

The entity is immutable and mutations return a new domain instance rather than modifying the existing object.

---

# `version.py`

Defines `KnowledgeDocumentVersion`, representing one **immutable revision of a document's authoritative source content**.

A document can therefore maintain historical revisions:

```text
Refund Policy
├── v1
├── v2
└── v3
```

Each version retains its original source content so it can remain auditable and be reprocessed later. Chunks and embeddings are derived artifacts and are intentionally kept outside the version entity itself.

The version lifecycle is:

```text
DRAFT
  │
  ▼
PROCESSING
  │
  ├──► READY ──► PUBLISHED ──► SUPERSEDED
  │
  └──► FAILED ──► PROCESSING
                        

Any non-processing historical version
  │
  └──► ARCHIVED
```

Processing and publication are separate concepts:

```text
PROCESSING
    │
    ▼
READY
    │
    ▼
PUBLISHED
```

A version cannot be published until ingestion has completed successfully.

Cross-version coordination, such as ensuring only one published version exists, belongs outside the entity and is coordinated by the application layer.

---

# `chunk.py`

Defines `KnowledgeChunk`, the **derived retrieval unit** produced from a knowledge-document version.

A chunk belongs to exactly one version and represents a bounded portion of normalized source content.

Important properties include:

* `id`;
* `version_id`;
* `chunk_index`;
* content;
* optional section title;
* source offsets;
* token count;
* metadata;
* timestamps.

Chunk content is intentionally immutable. If the source content or chunking strategy changes, chunks should be regenerated rather than silently modifying existing content.

The model validates fundamental invariants such as:

```text
valid UUIDs
non-negative chunk index
non-empty content
maximum content size
valid offsets
valid token count
valid timestamps
```

Source offsets allow retrieved chunks to remain traceable to their position within the normalized source content.

---

# `embedding.py`

Defines `KnowledgeChunkEmbedding`, representing an **immutable, model-dependent embedding artifact** for a knowledge chunk.

```text
KnowledgeChunk
      │
      ▼
Embedding Provider
      │
      ▼
KnowledgeChunkEmbedding
```

An embedding records:

* chunk identity;
* embedding provider/model descriptor;
* embedding input descriptor;
* input fingerprint;
* vector;
* creation timestamp.

The provenance information is important because an embedding is only valid for the exact provider/model and input-building configuration that produced it.

The model also validates that:

```text
vector.dimensions == provider.dimensions
```

and that the input fingerprint is a valid 64-character SHA-256 hexadecimal digest.

This allows multiple embedding configurations to coexist for the same chunk without treating them as interchangeable.

---

# `enums.py`

Contains the controlled vocabularies used throughout the domain.

## Document status

```text
ACTIVE
ARCHIVED
DELETED
```

## Version status

```text
DRAFT
PROCESSING
READY
PUBLISHED
SUPERSEDED
FAILED
ARCHIVED
```

The normal successful version lifecycle is:

```text
DRAFT → PROCESSING → READY → PUBLISHED → SUPERSEDED
```

with processing failures represented by `FAILED`.

## Other domain vocabularies

### Source type

```text
MARKDOWN
PLAIN_TEXT
PDF
DOCX
HTML
RICH_TEXT
```

### Content type

```text
POLICY
FAQ
PROCEDURE
GUIDE
REFERENCE
OTHER
```

### Ingestion status

```text
PENDING
RUNNING
COMPLETED
FAILED
```

### Visibility

```text
CUSTOMER
INTERNAL
BOTH
```

These enums keep domain state explicit and prevent arbitrary strings from becoming lifecycle state.

---

# `errors.py`

Defines the domain's **business-rule error hierarchy**.

All domain-specific failures derive from:

```text
KnowledgeDomainError
```

The base error intentionally contains domain semantics rather than HTTP status codes, database exceptions, provider failures, or transport-specific details. Higher layers can translate these errors into their own representations.

The hierarchy is broadly divided into:

```text
KnowledgeDomainError
│
├── KnowledgeDocumentError
│
├── KnowledgeVersionError
│
├── KnowledgeChunkError
│
└── KnowledgePublicationError
```

Examples include:

* invalid document state;
* deleted document mutation;
* invalid version number;
* invalid version content;
* illegal lifecycle transitions;
* publishing an unready version;
* published-version conflicts;
* invalid chunk data;
* duplicate chunk indexes;
* attempting to publish a version without usable chunks.

Errors carry stable machine-readable codes and structured context so application and operational layers can handle them without parsing human-readable messages.

---

# Domain Relationships

The six files form a hierarchy of knowledge artifacts:

```text
KnowledgeDocument
       │
       │ 1:N
       ▼
KnowledgeDocumentVersion
       │
       │ 1:N
       ▼
KnowledgeChunk
       │
       │ 1:N
       ▼
KnowledgeChunkEmbedding
```

The supporting files provide the vocabulary and failure semantics used throughout:

```text
                 ┌──────────────┐
                 │    enums.py  │
                 └──────┬───────┘
                        │
                        ▼
Document ───────► Version ───────► Chunk ───────► Embedding
   │                │                │               │
   └────────────────┴────────────────┴───────────────┘
                            │
                            ▼
                       errors.py
```

---

# Immutability

The domain strongly favors immutable entities.

Document, version, chunk, and embedding models use frozen dataclasses.

Instead of mutating an existing object:

```text
existing entity
      │
      ▼
domain operation
      │
      ▼
new entity
```

This makes lifecycle transitions explicit and prevents accidental state mutation across application, ingestion, retrieval, and persistence boundaries.

---

# Source vs Derived Data

A major architectural distinction is:

```text
AUTHORITATIVE
─────────────
KnowledgeDocument
KnowledgeDocumentVersion
source_content
```

versus:

```text
DERIVED
───────
KnowledgeChunk
KnowledgeChunkEmbedding
```

If source content changes, a new version should be created.

If chunking changes, chunks should be regenerated.

If the embedding model/input configuration changes, new embedding artifacts can be generated.

This preserves historical reproducibility.

---

# Domain Boundary

The domain layer intentionally does **not** know about:

* PostgreSQL;
* SQLAlchemy;
* HTTP;
* REST APIs;
* vector databases;
* embedding API calls;
* LLM providers;
* retrieval repositories;
* application services.

Instead:

```text
Application / Infrastructure
          │
          ▼
   Knowledge Domain
          │
          ├── entities
          ├── state
          └── business rules
```

The surrounding layers are responsible for persistence, orchestration, provider interaction, and transport concerns.

---

# Key Invariants

The domain protects several important business rules:

* document identity is separate from versioned content;
* source content of a version is immutable;
* version numbers are positive;
* version lifecycle transitions are validated;
* publication requires successful ingestion;
* a published version must have completed ingestion;
* supersession applies to previously published versions;
* processing failures retain sanitized failure information;
* chunk content is non-empty and bounded;
* chunk indexes are non-negative;
* embedding dimensions must match the provider descriptor;
* embedding provenance is tied to its exact input configuration;
* deleted documents reject normal mutations.

---

# Summary

`packages/knowledge/domain/` is the **business-rule core of the knowledge base**.

Its model can be summarized as:

```text
Document
   │
   └── Versioned authoritative content
           │
           └── Derived chunks
                   │
                   └── Model-specific embeddings
```

`enums.py` defines the legal states and classifications, while `errors.py` provides the stable semantic failure boundary.

Together, these six files ensure that knowledge lifecycle rules remain enforced **inside the domain model**, rather than being scattered across repositories, ingestion services, retrieval code, or API handlers.
