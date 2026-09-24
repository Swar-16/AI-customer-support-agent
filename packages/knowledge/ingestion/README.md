# Knowledge Ingestion

## Overview

The `packages/knowledge/ingestion/` package is the **document-processing pipeline** of the knowledge subsystem.

It takes the source content associated with a knowledge-document version and transforms it into persistent, retrieval-ready knowledge chunks through three explicit stages:

```text
     IngestionSource
           │
           ▼
        Parsing
           │
           ▼
      ParsedDocument
           │
           ▼
      Normalization
           │
           ▼
    NormalizedDocument
           │
           ▼
        Chunking
           │
           ▼
     ChunkedDocument
           │
           ▼
 Persistent KnowledgeChunk
```

The package also contains the orchestration and contracts required to execute this pipeline safely, preserve provenance, validate cross-stage invariants, and transition a knowledge version through its processing lifecycle.

---

# Package Structure

```text
packages/
└── knowledge/
    └── ingestion/
        ├── models.py
        ├── errors.py
        ├── process_version.py
        │
        ├── parser/
        │   ├── base.py
        │   ├── markdown.py
        │   ├── plain_text.py
        │   ├── resolver.py
        │   └── README.md
        │
        ├── normalization/
        │   ├── base.py
        │   ├── errors.py
        │   ├── models.py
        │   ├── markdown.py
        │   ├── plain_text.py
        │   ├── resolver.py
        │   └── README.md
        │
        └── chunking/
            ├── base.py
            ├── errors.py
            ├── models.py
            ├── resolver.py
            ├── semantic_text.py
            ├── ...
            └── README.md
```

The detailed behavior of each stage belongs in its respective subpackage README. This README provides the **system-level view**.

---

# Architectural Role

The ingestion package sits between knowledge-version management and downstream embedding/retrieval.

```text
Knowledge Application
        │
        │ ProcessKnowledgeVersion
        ▼
┌─────────────────────────────┐
│      Knowledge Ingestion    │
│                             │
│  Parser                     │
│     ↓                       │
│  Normalizer                 │
│     ↓                       │
│  Chunker                    │
│                             │
└──────────────┬──────────────┘
               │
               ▼
       Persistent Chunks
               │
               ▼
        Embedding Pipeline
               │
               ▼
        Retrieval System
```

The ingestion package itself does **not** perform embedding or retrieval.

Its output is the stable chunk representation consumed by those later stages.

---

# Core Pipeline

## 1. Source

Processing begins by constructing an `IngestionSource` from the knowledge version.

It carries information such as:

* knowledge-version identity;
* source type;
* source content;
* source name/URI;
* ingestion metadata.

The source type determines which parser, normalizer, and chunker will be selected.

---

## 2. Parsing

The parser converts source-format content into a structured `ParsedDocument`.

```text
IngestionSource
      │
      ▼
DocumentParserResolver
      │
      ▼
DocumentParser
      │
      ▼
ParsedDocument
```

The parser layer is responsible for understanding **source syntax and structure**, not retrieval semantics.

Current production parsers include:

```text
MARKDOWN
    → MarkdownStructuralParser

PLAIN_TEXT
    → PlainTextStructuralParser
```

Parser implementations preserve source ordering and source provenance, including exact offsets where applicable.

See:

```text
packages/knowledge/ingestion/parser/README.md
```

for parser-specific details.

---

# 3. Normalization

Normalization converts the parser-specific structural representation into a **canonical ingestion representation**.

```text
ParsedDocument
      │
      ▼
DocumentNormalizerResolver
      │
      ▼
DocumentNormalizer
      │
      ▼
NormalizedDocument
```

The purpose is to remove source-format-specific presentation concerns while retaining meaningful semantic structure and provenance.

Current strategies include:

```text
MARKDOWN
    → MarkdownNormalizer

PLAIN_TEXT
    → PlainTextNormalizer
```

The normalized representation is intentionally **not yet a retrieval chunk**.

See:

```text
packages/knowledge/ingestion/normalization/README.md
```

for the detailed normalization contract.

---

# 4. Chunking

Chunking converts the normalized document into bounded retrieval-oriented chunks.

```text
 NormalizedDocument
        │
        ▼
DocumentChunkerResolver
        │
        ▼
  DocumentChunker
        │
        ▼
  ChunkedDocument
```

A chunk contains the text and the provenance required by later embedding and retrieval stages.

The current production ingestion composition uses:

```text
StructuralTextChunker
```

for the currently supported text source types.

Chunking is where retrieval-unit boundaries are established. It is deliberately separated from parsing and normalization.

See:

```text
packages/knowledge/ingestion/chunking/README.md
```

for the detailed chunking behavior and invariants.

---

# Strategy Resolution

Each pipeline stage is selected through a resolver.

```text
KnowledgeSourceType
        │
        ├───────────────┐
        │               │
        ▼               ▼
     Parser          Normalizer
     Resolver         Resolver
        │               │
        └───────┬───────┘
                │
                ▼
             Chunker
             Resolver
```

This prevents the processing service from knowing concrete parser, normalizer, or chunker implementations.

The application therefore depends on contracts such as:

```text
DocumentParserResolver
DocumentNormalizerResolver
DocumentChunkerResolver
```

rather than hard-coding format-specific behavior.

---

# Current Supported Sources

The production ingestion composition currently advertises:

```text
┌─────────────────────────────┐
│ Supported Upload Types      │
├─────────────────────────────┤
│ Markdown                    │
│ UTF-8 Plain Text            │
└─────────────────────────────┘
```

For both formats, the complete pipeline is registered:

```text
Source Type
    │
    ├── Parser
    ├── Normalizer
    └── Chunker
```

PDF, DOCX, and HTML source types may exist in the domain model, but they are **not advertised as operational ingestion formats** until their complete parser/normalizer pipeline is available. The composition factory explicitly enforces this rule.

---

# Pipeline Composition

The complete ingestion graph is assembled by the application composition layer.

Conceptually:

```text
create_knowledge_ingestion_components()
        │
        ├── DefaultDocumentParserResolver
        │       ├── MarkdownStructuralParser
        │       └── PlainTextStructuralParser
        │
        ├── DefaultDocumentNormalizerResolver
        │       ├── MarkdownNormalizer
        │       └── PlainTextNormalizer
        │
        └── DefaultDocumentChunkerResolver
                └── StructuralTextChunker
```

The resulting immutable object is:

```text
KnowledgeIngestionComponents
```

It contains:

```text
parser_resolver
normalizer_resolver
chunker_resolver
supported_source_types
```

The composition factory validates that every advertised source type has a complete parser → normalizer → chunker path.

---

# Fail-Fast Composition

Ingestion configuration is deliberately validated during application startup rather than waiting for the first document upload.

The factory:

1. validates each resolver;
2. verifies supported source types;
3. checks required source types;
4. checks `supports()` and `resolve()`;
5. resolves every registered strategy;
6. verifies that the resolved strategy supports the requested source type.

```text
Invalid ingestion configuration
             │
             ▼
KnowledgeIngestionConfigurationError
             │
             ▼
Application startup fails
```

This prevents a partially configured ingestion pipeline from reaching production runtime.

---

# `ProcessKnowledgeVersion`

The primary application-level orchestration for ingestion is `ProcessKnowledgeVersion`.

Its responsibility is broader than simply calling the three strategies.

It coordinates:

* version claiming;
* lifecycle state transitions;
* parser/normalizer/chunker execution;
* cross-stage validation;
* persistent chunk replacement;
* success/failure state recording;
* audit events;
* processing concurrency protection.

The core processing path is:

```text
Knowledge Version
       │
       ▼
  Claim version
       │
       ▼
PROCESSING / RUNNING
       │
       ▼
Create IngestionSource
       │
       ▼
     Parse
       │
       ▼
    Normalize
       │
       ▼
     Chunk
       │
       ▼
Validate artifacts
       │
       ▼
 Persist chunks
       │
       ▼
READY / COMPLETED
```

The expensive parse → normalize → chunk phase deliberately runs **without an open database transaction or long-lived row lock**.

---

# Processing Lifecycle

Processing is divided into explicit phases.

```text
             Transaction A
                  │
                  ▼
            DRAFT / PENDING
                  │
                  ▼
        PROCESSING / RUNNING
                  │
                  │
       ┌──────────┴──────────┐
       │                     │
       ▼                     ▼
    Success                Failure
       │                     │
       ▼                     ▼
  Transaction B          Transaction C
       │                     │
       ▼                     ▼
READY / COMPLETED      FAILED / FAILED
```

### Phase A — Claim

A short transaction:

* verifies the version;
* verifies the parent document;
* locks required records;
* validates that processing is allowed;
* transitions the version to processing;
* records the processing-started audit event.

### Phase B — Process

No database transaction is held while:

```text
parse → normalize → chunk
```

takes place.

### Phase C — Complete

A second transaction:

* verifies that processing ownership is still valid;
* replaces derived chunks;
* marks the version ready;
* records completion metadata;
* commits the result.

### Failure

If processing fails, the original processing exception remains the primary exception while failure state is persisted separately on a best-effort basis.

---

# Cross-Stage Contract Validation

One of the most important responsibilities at this level is ensuring that individual strategies cannot silently produce incompatible artifacts.

The pipeline validates that:

```text
source.version_id
parsed.version_id
normalized.version_id
chunked.version_id
```

all refer to the same knowledge version.

It also verifies that all stages preserve the same:

```text
KnowledgeSourceType
```

and that provenance is carried forward.

For example:

```text
ParsedDocument
    │
    ├── parser identity
    ▼
NormalizedDocument
    │
    ├── parser identity preserved
    ├── normalizer identity
    ▼
ChunkedDocument
    │
    ├── parser identity preserved
    ├── normalizer identity preserved
    └── chunker identity
```

The processing service explicitly validates these relationships before persistence.

---

# Provenance

Ingestion treats transformation provenance as a first-class concern.

Each strategy exposes an identity consisting conceptually of:

```text
strategy_id
version
configuration fingerprint
```

The artifact chain therefore remains traceable:

```text
Source
  │
  ▼
Parser
  │
  └── parser identity
  │
  ▼
ParsedDocument
  │
  ▼
Normalizer
  │
  └── normalizer identity
  │
  ▼
NormalizedDocument
  │
  ▼
Chunker
  │
  └── chunker identity
  │
  ▼
ChunkedDocument
```

When processing succeeds, these identities are also included in completion/audit information.

This makes ingestion behavior reproducible and diagnosable when strategies evolve.

---

# Persistence Boundary

The ingestion strategies themselves operate on in-memory artifacts.

Persistence happens at the application orchestration boundary.

```text
Parser
   │
   ▼
ParsedDocument

Normalizer
   │
   ▼
NormalizedDocument

Chunker
   │
   ▼
ChunkedDocument
   │
   ▼
ProcessKnowledgeVersion
   │
   ▼
KnowledgeChunk
   │
   ▼
Repository / Unit of Work
```

The processing service maps chunk candidates into domain `KnowledgeChunk` objects and persists them transactionally.

For an unpublished version, existing derived chunks are replaced before the new set is stored.

---

# Error Boundaries

The ingestion subsystem uses stage-specific error hierarchies.

Conceptually:

```text
Knowledge Ingestion
│
├── Parser Errors
│   ├── configuration
│   ├── unsupported source
│   ├── execution
│   └── invalid output
│
├── Normalization Errors
│   ├── configuration
│   ├── unsupported source
│   ├── execution
│   └── invalid output
│
├── Chunking Errors
│   ├── configuration
│   ├── unsupported source
│   ├── invalid input
│   ├── execution
│   └── invalid output
│
└── Processing Errors
    ├── version/document state
    ├── processing conflict
    ├── cross-stage contract violation
    └── persistence failure
```

The stage-specific errors remain independent of HTTP/transport concerns.

At the orchestration boundary, `ProcessKnowledgeVersionError` represents use-case-level failures such as an unprocessable version, processing conflict, cross-stage contract violation, or persistence failure.

---

# Concurrency and Consistency

Processing is designed to avoid holding database locks while expensive document processing occurs.

The lifecycle is effectively:

```text
Short DB transaction
       │
       ▼
Claim ownership
       │
       ▼
Release transaction
       │
       ▼
Parse / Normalize / Chunk
       │
       ▼
Short DB transaction
       │
       ▼
Verify ownership
       │
       ▼
Persist derived artifacts
       │
       ▼
READY
```

Before completion, the service verifies that the version is still in the expected processing state. This prevents an outdated processing attempt from overwriting newer lifecycle state.

---

# Relationship With Embeddings

Ingestion ends at **chunk persistence**.

Embedding is a separate downstream operation:

```text
Knowledge Ingestion
        │
        ▼
KnowledgeChunk
        │
        ▼
Embedding Pipeline
        │
        ▼
Persisted Embedding
        │
        ▼
Publication / Retrieval
```

This separation allows the system to:

* reprocess document structure independently;
* change embedding providers without reparsing documents;
* regenerate embeddings without repeating parsing;
* validate ingestion independently from external embedding services.

The knowledge application composition wires `ProcessKnowledgeVersion` with the ingestion resolvers and separately wires `EmbedKnowledgeVersion` with the embedding provider.

---

# Relationship With Retrieval

The ingestion subsystem does not know how chunks will later be retrieved.

Its output is consumed by the retrieval/embedding side of the knowledge system.

```text
Ingestion
   │
   ▼
Knowledge Chunks
   │
   ├── Embeddings
   │
   ├── Lexical retrieval
   │
   └── Metadata/provenance
```

This keeps ingestion independent from:

* vector databases;
* lexical search engines;
* rerankers;
* retrieval profiles;
* LLM providers.

---

# Current End-to-End Knowledge Flow

At the knowledge application level, ingestion fits into the broader document lifecycle:

```text
Upload/Create Version
        │
        ▼
   Knowledge Version
        │
        ▼
ProcessKnowledgeVersion
        │
        ▼
Parser
        │
        ▼
Normalizer
        │
        ▼
Chunker
        │
        ▼
Persistent Knowledge Chunks
        │
        ▼
EmbedKnowledgeVersion
        │
        ▼
Persisted Embeddings
        │
        ▼
PublishKnowledgeVersion
        │
        ▼
Available for Retrieval
```

The application factory exposes these operations together as part of the knowledge application boundary.

---

# Design Principles

## 1. Explicit Pipeline Stages

```text
Parse
  ↓
Normalize
  ↓
Chunk
```

Each stage has one clear responsibility.

## 2. Contract-Based Composition

The processing layer depends on parser, normalizer, and chunker contracts rather than concrete implementations.

## 3. Source-Type Driven Strategy Selection

`KnowledgeSourceType` determines the strategy chain.

## 4. Fail Fast

Incomplete strategy graphs are rejected during application composition.

## 5. Provenance Preservation

Every transformation retains enough information to identify the strategy that produced the artifact.

## 6. Immutable Intermediate Artifacts

The pipeline passes well-defined artifact objects rather than loosely structured dictionaries.

## 7. No Long Database Transactions Around CPU Work

Expensive parsing, normalization, and chunking execute outside the database transaction.

## 8. Explicit Error Boundaries

Parser, normalization, chunking, and processing failures remain distinguishable.

## 9. Retrieval Independence

The ingestion subsystem creates retrieval-ready chunks but does not implement retrieval itself.

## 10. Safe Extension

A new source format should become operational only after its complete:

```text
Parser
  +
Normalizer
  +
Chunker
```

pipeline exists and is registered successfully.

---

# Adding a New Document Format

Adding a new source type should follow the complete pipeline rather than exposing the enum value prematurely.

For example:

```text
PDF
 │
 ├── PDF Parser
 │
 ├── PDF Normalizer
 │
 └── PDF Chunker
```

Only after all three stages are implemented and validated should the format be added to the operational supported-source set.

The composition factory explicitly follows this principle for currently unsupported PDF/DOCX/HTML formats.

---

# Testing Strategy

Testing should exist at multiple levels.

### Stage Tests

Each parser, normalizer, and chunker should test its own contract and transformation behavior.

### Resolver Tests

Resolvers should verify:

* supported source types;
* duplicate registrations;
* invalid implementations;
* deterministic resolution;
* capability consistency.

### Pipeline Tests

The complete ingestion graph should verify:

```text
source
  → parser
  → normalizer
  → chunker
```

for every advertised source type.

### Processing Tests

`ProcessKnowledgeVersion` should cover:

* successful processing;
* retry from failed state;
* invalid lifecycle state;
* concurrent processing conflicts;
* stage failures;
* contract violations;
* zero-chunk output;
* persistence failures;
* failure-state recording;
* successful audit recording.

---

# Key Invariants

The ingestion subsystem guarantees, at the application boundary, that:

* every advertised source type has a parser, normalizer, and chunker;
* artifacts belong to the same knowledge version;
* artifacts retain the original source type;
* parser provenance survives normalization and chunking;
* normalizer provenance survives chunking;
* successful processing produces at least one persistent chunk;
* strategy resolution is deterministic;
* processing does not hold database transactions during expensive parsing/chunking;
* failed processing does not silently become successful;
* derived chunks are replaced deterministically for unpublished processing attempts.

---

# Summary

`packages/knowledge/ingestion/` is the **canonical transformation pipeline from knowledge-source content to retrieval-ready knowledge chunks**.

Its architecture can be summarized as:

```text
                 Knowledge Version
                       │
                       ▼
                IngestionSource
                       │
                       ▼
              ┌─────────────────┐
              │     Parser      │
              └────────┬────────┘
                       │
                       ▼
                ParsedDocument
                       │
                       ▼
              ┌─────────────────┐
              │   Normalizer    │
              └────────┬────────┘
                       │
                       ▼
              NormalizedDocument
                       │
                       ▼
              ┌─────────────────┐
              │     Chunker     │
              └────────┬────────┘
                       │
                       ▼
                 ChunkedDocument
                       │
                       ▼
               KnowledgeChunk
                       │
                       ▼
              Embedding Pipeline
                       │
                       ▼
                  Retrieval
```

The package is intentionally divided into specialized layers:

```text
parser/
    Source-format interpretation

normalization/
    Canonical semantic representation

chunking/
    Retrieval-unit construction

process_version.py
    Lifecycle + pipeline orchestration

errors.py
    Ingestion-level failure contracts

models.py
    Shared ingestion artifacts
```

The detailed implementation decisions belong in the individual subpackage READMEs; this level should primarily be used to understand **how those components fit together into one reliable ingestion pipeline**.
