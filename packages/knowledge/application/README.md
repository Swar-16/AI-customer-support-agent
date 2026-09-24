# Knowledge Application Layer

## Overview

The `packages/knowledge/application/` package contains the **application services and use-case orchestration layer** for the knowledge subsystem.

It sits between the external/API layer and the lower-level knowledge domain, repositories, ingestion pipeline, embedding infrastructure, and audit system.

Its responsibility is to coordinate business workflows while keeping:

* domain rules inside the knowledge domain;
* persistence behind repositories / Unit of Work;
* ingestion behind parser/normalizer/chunker contracts;
* embeddings behind provider/input-builder contracts;
* authentication and mutation identity explicit;
* audit recording atomic with mutations.

```text
External / API Layer
        │
        ▼
packages.knowledge.application
        │
        ├── Domain
        ├── Repositories / UoW
        ├── Ingestion
        ├── Embeddings
        └── Audit
```

---

# Files

```text
packages/
└── knowledge/
    └── application/
        ├── archive_document.py
        ├── create_document.py
        ├── create_version.py
        ├── embed_version.py
        ├── exceptions.py
        ├── get_document.py
        ├── get_version.py
        ├── knowledge_upload_policy.py
        ├── list_documents.py
        ├── list_versions.py
        ├── mutation_context.py
        ├── process_version.py
        ├── publish_version.py
        ├── upload_document.py
        └── upload_version.py
```

| File                         | Primary responsibility                                   |
| ---------------------------- | -------------------------------------------------------- |
| `mutation_context.py`        | Trusted identity and authorization context for mutations |
| `exceptions.py`              | Application-level error taxonomy                         |
| `knowledge_upload_policy.py` | Validate and sanitize uploaded knowledge files           |
| `create_document.py`         | Create a logical knowledge document                      |
| `create_version.py`          | Create an immutable source revision                      |
| `upload_document.py`         | Create a document and its initial version from an upload |
| `upload_version.py`          | Add a new uploaded version to an existing document       |
| `process_version.py`         | Parse, normalize, chunk, and persist derived chunks      |
| `embed_version.py`           | Generate and persist embedding artifacts                 |
| `publish_version.py`         | Validate and publish a fully prepared version            |
| `archive_document.py`        | Archive a document and supersede its published version   |
| `get_document.py`            | Retrieve one document for administrative inspection      |
| `get_version.py`             | Retrieve one version and its embedding coverage          |
| `list_documents.py`          | Filtered/paginated document listing                      |
| `list_versions.py`           | Filtered/paginated version history                       |

---

# Overall Knowledge Lifecycle

The application layer coordinates the knowledge lifecycle:

```text
                    ┌──────────────────┐
                    │ Upload / Create  │
                    └────────┬─────────┘
                             │
                             ▼
                    Knowledge Document
                             │
                             ▼
                    Knowledge Version
                             │
                             ▼
                       Processing
                 parse → normalize → chunk
                             │
                             ▼
                           READY
                             │
                             ▼
                         Embedding
                             │
                             ▼
                       Fully Embedded
                             │
                             ▼
                         Published
                             │
                             ▼
                       Superseded
                             │
                             ▼
                         Archived
```

The important distinction is that **creation, processing, embedding, publication, and archival are separate use cases**.

---

# 1. Mutation Context

## `mutation_context.py`

`KnowledgeMutationContext` represents the trusted execution identity for knowledge mutations.

It contains:

```text
actor
trace_id
initiating_admin_id
```

The actor may represent:

* an authenticated administrator;
* a trusted system process.

An administrator context requires the actor ID and requires `initiating_admin_id` to match that actor. A system context cannot claim an administrator identity.

Convenience constructors are provided:

```text
KnowledgeMutationContext.from_admin(...)
KnowledgeMutationContext.for_system(...)
```

This gives every mutating use case an explicit identity and trace boundary.

---

# 2. Upload Validation

## `knowledge_upload_policy.py`

`KnowledgeUploadPolicy` is the security boundary for untrusted uploaded knowledge bytes.

It validates:

* filename safety;
* supported extension;
* declared media type;
* file size;
* empty content;
* binary signatures;
* UTF-8 encoding;
* unsafe control characters;
* bidirectional control characters.

The default supported formats are currently:

```text
.md  → Markdown
.txt → Plain text
```

with the associated allowed media types defined by the format registry.

The policy deliberately does **not**:

* persist files;
* open filesystem paths;
* execute content;
* invoke a shell;
* interpret Markdown as executable instructions.

It returns normalized, inert text plus hashes and upload metadata.

---

# 3. Creating a Document

## `create_document.py`

`CreateKnowledgeDocument` creates the **logical document identity** without source content.

```text
CreateKnowledgeDocumentCommand
        │
        ▼
KnowledgeDocument
        │
        ├── title
        ├── content type
        ├── visibility
        ├── description
        └── metadata
```

Source content intentionally does not belong here; it belongs to `KnowledgeDocumentVersion`.

The operation:

1. creates a UUIDv7 document ID;
2. constructs the domain entity;
3. persists it;
4. records an audit event;
5. commits atomically;
6. returns `CreateKnowledgeDocumentResult`.

---

# 4. Creating a Version

## `create_version.py`

`CreateKnowledgeVersion` creates a new immutable source revision for an existing document.

```text
Document
   │
   ├── Version 1
   ├── Version 2
   └── Version N
```

Before creation, the parent document is locked.

This ensures that lifecycle validation and version-number allocation cannot race with archival or other aggregate mutations.

The source content receives a SHA-256 hash of the exact UTF-8 content. The content itself is deliberately not written into the audit event.

---

# 5. Uploading a New Document

## `upload_document.py`

`UploadKnowledgeDocument` is the combined upload workflow for creating:

```text
KnowledgeDocument
        +
initial KnowledgeDocumentVersion
```

It first passes the raw upload through `KnowledgeUploadPolicy`.

It then creates both entities inside one Unit-of-Work transaction and records both document and version creation audit events.

The upload metadata includes system-owned values such as:

```text
upload_extension
upload_media_type
upload_sha256
upload_size_bytes
upload_trust_boundary
```

User-supplied metadata cannot overwrite the reserved `upload_*` namespace.

This is the primary **one-step onboarding workflow** for a new knowledge resource.

---

# 6. Uploading a New Version

## `upload_version.py`

`UploadKnowledgeVersion` adds a new source revision to an **existing explicitly identified document**.

The filename is treated purely as source metadata and is never used to locate the parent document.

Flow:

```text
Upload bytes
     │
     ▼
Upload Policy
     │
     ▼
Lock document
     │
     ▼
Validate document lifecycle
     │
     ▼
Check content hash
     │
     ├── existing → return existing version
     │
     └── new
          │
          ▼
     Allocate version number
          │
          ▼
     Persist version
          │
          ▼
     Audit + commit
```

The content-hash check makes repeated identical uploads idempotent at the application level.

---

# 7. Processing a Version

## `process_version.py`

`ProcessKnowledgeVersion` is the ingestion orchestration service.

Its core pipeline is:

```text
KnowledgeDocumentVersion
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
KnowledgeChunk[]
```

The application service resolves each stage through provider-neutral resolver contracts.

---

## Processing Transactions

Processing intentionally avoids keeping a database transaction open during expensive parsing work.

### Transaction A — Claim

```text
DRAFT/PENDING
      │
      ▼
PROCESSING/RUNNING
```

A snapshot of the source is captured.

### No transaction — Process

```text
parse
  ↓
normalize
  ↓
chunk
```

### Transaction B — Complete

```text
replace chunks
      ↓
READY/COMPLETED
```

### Transaction C — Failure

```text
PROCESSING/RUNNING
        ↓
FAILED/FAILED
```

This design avoids holding database locks while parsing, normalization, or chunking executes.

---

# Processing Integrity

The service validates that processing artifacts preserve:

* version identity;
* source type;
* parser provenance;
* normalizer provenance;
* chunk provenance;
* chunk cardinality.

When chunks are persisted, transformation provenance is stored in chunk metadata, including parser, normalizer, and chunker strategy/version/config fingerprints.

---

# Processing Failure Handling

Processing failures are recorded as a `FAILED` version state using a separate short transaction.

The original processing exception remains the primary exception and is never replaced by a failure-recording error.

Persisted failure information is intentionally conservative:

* failure codes are bounded;
* messages are bounded;
* arbitrary exception representations are not persisted;
* potentially sensitive paths, credentials, or source content are avoided.

---

# 8. Embedding a Version

## `embed_version.py`

`EmbedKnowledgeVersion` generates model-dependent embeddings for the canonical chunks of a processed version.

The workflow deliberately separates database work from external embedding calls:

```text
Transaction A
─────────────
read version
validate state
read document
read chunks
snapshot
     │
     ▼
No DB transaction
─────────────────
prepare inputs
find existing embeddings
call embedding provider
     │
     ▼
Transaction B
─────────────
re-check artifacts
persist missing embeddings
audit
commit
```

This prevents long-running external provider calls from holding database transactions open.

---

# Embedding Idempotency

Embedding identity is based on:

```text
chunk_id
+
input_fingerprint
+
provider descriptor
+
input descriptor
```

Existing compatible artifacts are reused.

Only missing artifacts are sent to the provider.

A second worker may create an artifact while the provider call is running, so the persistence phase performs another existence check before insertion.

---

# Embedding Eligibility

Embedding requires:

```text
ingestion_status = COMPLETED
```

and allows:

```text
READY
PUBLISHED
SUPERSEDED
```

This means historical superseded versions can be re-embedded for reproducibility or audit purposes.

`DRAFT`, `PROCESSING`, `FAILED`, and `ARCHIVED` versions are not valid embedding sources.

---

# Embedding Provider Validation

Provider responses are validated for:

* provider/model identity;
* response cardinality;
* contiguous input indexes;
* correct ordering;
* vector/model compatibility.

This prevents an incorrectly ordered or incorrectly identified provider response from producing corrupted embedding artifacts.

---

# 9. Publishing a Version

## `publish_version.py`

`PublishKnowledgeVersion` is the final lifecycle gate before a version becomes the active knowledge version.

A version must satisfy:

```text
Document ACTIVE
       │
       ▼
Version READY
       │
       ▼
Has chunks
       │
       ▼
Fully embedded
       │
       ▼
PUBLISH
```

The application verifies embedding coverage using the exact configured provider and input strategy.

---

# Publication Concurrency

Publication locks the parent document before modifying versions.

This serializes:

* publication;
* archival;
* version creation

for the same logical document.

If another version is currently published:

```text
Current Published
       │
       ▼
SUPERSEDED
       │
       ▼
Target Version
       │
       ▼
PUBLISHED
```

The supersession is flushed before publishing the target to satisfy the database's uniqueness constraints.

An identical retry against an already-published target is treated as a successful idempotent operation without creating another audit event.

---

# 10. Archiving a Document

## `archive_document.py`

`ArchiveKnowledgeDocument` terminates the active lifecycle of a logical document.

If the document currently has a published version:

```text
Published Version
       │
       ▼
   Superseded
```

and then:

```text
Document ACTIVE
       │
       ▼
Document ARCHIVED
```

Both changes occur in one transaction and are accompanied by an immutable audit event.

The parent document is locked first, matching the locking strategy used by publication and version creation.

---

# 11. Administrative Reads

The package also provides read-side application services intended for administrative inspection.

## `get_document.py`

`GetKnowledgeDocument`:

* requires an authenticated administrator;
* loads one document;
* returns the current published version ID;
* returns total version count.

It deliberately does not load the complete version history. Version history is provided by the paginated list operation.

---

## `get_version.py`

`GetKnowledgeVersion` returns:

```text
document
version
current_published_version_id
embedding_coverage
```

It also exposes convenience properties:

```text
is_current_published_version
total_chunk_count
embedded_chunk_count
is_fully_embedded
```

Embedding coverage is calculated against the configured provider and input descriptor, ensuring that "fully embedded" means **fully embedded for the exact active embedding configuration**.

---

# 12. Document Listing

## `list_documents.py`

`ListKnowledgeDocuments` provides an administrator-only filtered and paginated catalog.

Supported filters:

```text
status
content_type
visibility
```

Pagination defaults to:

```text
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE     = 200
```

Filtering and pagination are delegated to the persistence layer rather than loading the entire knowledge catalog into application memory.

The result exposes:

```text
count
has_more
next_offset
```

for straightforward pagination.

---

# 13. Version Listing

## `list_versions.py`

`ListKnowledgeVersions` provides paginated version history for one document.

Supported filters:

```text
version status
ingestion status
source type
```

with the same:

```text
default = 50
maximum = 200
```

pagination bounds.

Before listing, the service verifies that the parent document exists.

The actual filtering, pagination, and counting are delegated to the version repository.

---

# Application Error Taxonomy

## `exceptions.py`

`exceptions.py` contains application-level errors rather than domain-model errors or HTTP exceptions.

Major categories include:

```text
GetKnowledgeDocumentError
ArchiveKnowledgeDocumentError

KnowledgeReadAccessDeniedError
KnowledgeMutationAccessDeniedError

KnowledgeDocumentUploadError

GetKnowledgeVersionError
PublishKnowledgeVersionError

ProcessKnowledgeVersionError
```

Examples include:

* document/version not found;
* read access denied;
* mutation access denied;
* unsupported upload;
* invalid upload filename;
* invalid media type;
* oversized upload;
* invalid encoding;
* unsafe upload content;
* publication conflict;
* incomplete embeddings;
* processing conflict;
* invalid processing contract;
* processing persistence failure.

The errors intentionally remain independent of HTTP status codes and persistence-provider exceptions.

---

# Complete Lifecycle

The 15 files together implement the following application workflow:

```text
                    ┌───────────────────────┐
                    │ Knowledge Upload      │
                    │ / Create              │
                    └───────────┬───────────┘
                                │
                   ┌────────────┴────────────┐
                   │                         │
                   ▼                         ▼
          upload_document             create_document
                   │                         │
                   └────────────┬────────────┘
                                ▼
                         KnowledgeDocument
                                │
                                ▼
                     KnowledgeDocumentVersion
                                │
                                ▼
                       process_version
                                │
                     parse → normalize → chunk
                                │
                                ▼
                              READY
                                │
                                ▼
                        embed_version
                                │
                                ▼
                       Fully Embedded
                                │
                                ▼
                       publish_version
                                │
                                ▼
                           PUBLISHED
                                │
                         new version arrives
                                │
                                ▼
                          SUPERSEDED
                                │
                                ▼
                       archive_document
                                │
                                ▼
                           ARCHIVED
```

---

# Read Side

The read-side operations are deliberately separate from mutations:

```text
                 Administrative Read
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
       get_document  get_version  list_documents
                                      │
                                      ▼
                               list_versions
```

All administrative reads require an authenticated administrator.

---

# Mutation Side

Mutation operations share a common execution identity:

```text
Authenticated Admin
        │
        ▼
KnowledgeMutationContext
        │
        ├── actor
        ├── trace_id
        └── initiating_admin_id
        │
        ▼
Knowledge Mutation
        │
        ▼
   Audit Event
```

System-driven workflows can use an explicitly system-attributed mutation context rather than impersonating an administrator.

---

# Auditability

Mutating workflows consistently integrate `AuditRecorder`.

Important operations emit events such as:

```text
knowledge_document.created
knowledge_version.created
knowledge_version.processing_started
knowledge_version.processing_completed
knowledge_version.processing_failed
knowledge_version.embeddings_created
knowledge_version.published
knowledge_document.archived
```

Audit events are recorded inside the same persistence transaction for the relevant mutation.

This means the intended invariant is:

```text
     Mutation
        +
   Audit Event
        +
Required Persistence
        │
        ▼
   Single Commit
```

If the transaction rolls back, the mutation and its audit event roll back together.

---

# Concurrency Model

Several operations deliberately lock the **parent document row** before performing lifecycle mutations.

The common ordering is:

```text
Document lock
      │
      ▼
Version lock / lifecycle operation
```

This ordering is used by:

* version creation;
* processing claim;
* publication;
* archival;
* version upload.

This reduces races between operations acting on the same logical knowledge document.

---

# Transaction Design

The application layer follows a key rule:

> **Database transactions should be short around database work and must not remain open across expensive external processing.**

For normal CRUD mutations:

```text
Begin
  │
  ├── validate/load
  ├── mutate
  ├── audit
  └── commit
```

For processing:

```text
Claim transaction
       ↓
External CPU work
       ↓
Completion transaction
```

For embedding:

```text
Snapshot transaction
       ↓
External embedding calls
       ↓
Persistence transaction
```

This avoids holding database connections and locks during expensive parsing or external provider calls.

---

# Security Boundaries

There are three important security boundaries.

## 1. Authentication Boundary

Administrative read operations require `AuthRole.ADMIN`.

## 2. Mutation Identity Boundary

Mutation operations require a validated `KnowledgeMutationContext`.

## 3. File Trust Boundary

Uploaded bytes are treated as untrusted until `KnowledgeUploadPolicy` validates them.

```text
Untrusted Upload
       │
       ▼
KnowledgeUploadPolicy
       │
       ▼
ValidatedKnowledgeUpload
       │
       ▼
Knowledge Domain
```

This prevents file metadata or raw bytes from bypassing application-level validation.

---

# Idempotency

Several workflows are deliberately designed to tolerate retries.

### Upload version

Same document + source type + content hash:

```text
existing version → return existing
```

rather than creating a duplicate.

### Publication

Publishing an already-current published version succeeds without another mutation/audit event.

### Embedding

Existing compatible embeddings are reused and only missing artifacts are generated.

These properties are especially important for retryable workers and administrative operations.

---

# Separation of Concerns

The application layer coordinates components but does not implement their underlying mechanisms.

```text
Application Service
       │
       ├── Domain entities
       ├── Repository contracts
       ├── Unit of Work
       ├── Ingestion resolvers
       ├── Embedding provider
       ├── Upload policy
       └── Audit recorder
```

For example, `ProcessKnowledgeVersion` does not itself implement Markdown parsing, normalization, or chunking. It resolves the appropriate strategy and coordinates the pipeline.

Likewise, `EmbedKnowledgeVersion` does not implement an embedding model; it depends on the `EmbeddingProvider` and `EmbeddingInputBuilder` contracts.

---

# Important Invariants

The application layer maintains several critical invariants.

### Document lifecycle

Archived/deleted documents cannot receive ordinary new versions or publication operations.

### Version lifecycle

Only valid lifecycle states may enter processing, embedding, or publication.

### Processing

A processing attempt must produce at least one valid chunk.

### Chunk provenance

Chunks must preserve source transformation provenance.

### Embedding

Every embedding must correspond to the expected provider/input configuration.

### Publication

A published version must:

* belong to an active document;
* be `READY`;
* have chunks;
* have complete compatible embedding coverage.

### Upload

Untrusted upload bytes must pass the upload policy before persistence.

### Audit

Mutating operations record their corresponding audit event within the mutation transaction.

### Authorization

Administrative reads require an administrator, while mutations require an administrator or explicitly trusted system context.

---

# Design Philosophy

## Domain Rules Stay in the Domain

Application services coordinate workflows; they do not replace domain lifecycle methods.

For example:

```text
application
    │
    ▼
version.publish(...)
```

rather than manually modifying version status fields.

---

## Infrastructure Is Behind Contracts

Repositories, ingestion strategies, and embedding providers are injected.

This keeps use cases testable and replaceable.

---

## Fail Fast

Commands, queries, constructors, dependencies, and configuration are validated early.

---

## No Silent Degradation

Processing, embedding, and publication failures are surfaced rather than converted into apparently successful partial results.

---

## Explicit Provenance

The system tracks:

* source hashes;
* upload hashes;
* parser identity;
* normalizer identity;
* chunker identity;
* embedding provider identity;
* embedding input strategy identity;
* trace IDs;
* mutation actors.

This supports reproducibility and auditing.

---

# Testing Focus

The application layer should be tested primarily around **workflow invariants and transaction boundaries**, rather than re-testing lower-level implementation details.

Important scenarios include:

### Creation

* document creation;
* version creation;
* archived/deleted parent rejection;
* audit creation.

### Upload

* unsupported files;
* invalid encodings;
* unsafe filenames;
* oversized content;
* duplicate content uploads;
* reserved metadata;
* atomic document/version creation.

### Processing

* successful parser → normalizer → chunker flow;
* invalid artifact provenance;
* concurrent processing;
* processing retry;
* failure-state persistence;
* stale processing state.

### Embedding

* missing artifact generation;
* existing-artifact reuse;
* provider mismatch;
* response ordering mismatch;
* response cardinality mismatch;
* concurrent embedding workers;
* invalid version state.

### Publication

* ready version;
* missing chunks;
* incomplete embeddings;
* concurrent publication;
* supersession;
* idempotent publication.

### Archival

* active document;
* already archived document;
* published-version supersession;
* atomic audit behavior.

### Reads

* administrator authorization;
* missing documents/versions;
* pagination;
* filtering;
* embedding coverage.

---

# Summary

`packages/knowledge/application/` is the **workflow orchestration layer for the complete knowledge lifecycle**.

Its responsibilities can be summarized as:

```text
             TRUST
               │
               ▼
      mutation_context.py
               │
               ▼
            Upload
               │
               ▼
         Create / Upload
               │
               ▼
           Version
               │
               ▼
          Processing
  [parse → normalize → chunk]
               │
               ▼
             READY
               │
               ▼
           Embedding
               │
               ▼
       Fully Embedded
               │
               ▼
           Publishing
               │
               ▼
          PUBLISHED
               │
               ▼
          Superseded
               │
               ▼
           Archived
```

The 15 files collectively enforce a clean application boundary around **knowledge ingestion, lifecycle management, security, authorization, persistence coordination, embeddings, publication, auditing, and administrative inspection**.

The most important architectural properties are:

* **explicit mutation identity;**
* **validated untrusted uploads;**
* **short database transactions;**
* **safe concurrency through parent-row locking;**
* **idempotent retry behavior;**
* **provider-independent ingestion and embedding contracts;**
* **complete embedding verification before publication;**
* **atomic auditability;**
* **separation of read and mutation workflows;**
* **and preservation of domain invariants throughout the lifecycle.**
