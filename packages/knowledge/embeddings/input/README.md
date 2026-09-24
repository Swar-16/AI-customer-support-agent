# Embedding Input Construction

## Overview

The `packages/knowledge/embeddings/input/` package defines how canonical knowledge chunks are transformed into the **exact text representation sent to an embedding model**.

This layer intentionally sits between the canonical knowledge representation and the embedding provider:

```text
Canonical Knowledge Chunk
          │
          ▼
EmbeddingSourceChunk
          │
          ▼
EmbeddingInputBuilder
          │
          ▼
PreparedEmbeddingInput
          │
          ▼
Embedding Provider
```

The package currently contains two files:

```text
packages/knowledge/embeddings/input/
├── base.py
└── contextual.py
```

* `base.py` defines the provider-independent source representation and the abstract builder contract.
* `contextual.py` provides the concrete deterministic contextual-input strategy.

The key architectural principle is that **canonical knowledge content is never modified**. Context is added only to the derived representation used for embedding.

---

# Responsibilities

| File            | Responsibility                                                       |
| --------------- | -------------------------------------------------------------------- |
| `base.py`       | Defines the input-building abstraction and canonical source contract |
| `contextual.py` | Implements deterministic contextual enrichment of chunk text         |

Together they answer one specific question:

> **What exact text should be embedded for this knowledge chunk?**

They do **not** perform the actual embedding operation.

---

# Architecture

The package deliberately separates **input construction** from **embedding generation**.

```text
                         Knowledge Domain
                               │
                               ▼
                       Canonical Chunk
                               │
                               ▼
                    EmbeddingSourceChunk
                               │
                               ▼
                  EmbeddingInputBuilder
                               │
                  ┌────────────┴────────────┐
                  │                         │
                  ▼                         ▼
        Contextual Strategy          Future Strategies
                  │
                  ▼
        PreparedEmbeddingInput
                  │
                  ▼
          Embedding Provider
```

The builder therefore owns the **model-facing text representation**, while the provider owns the conversion of that representation into a vector.

---

# `base.py`

## Purpose

`base.py` establishes the foundational contracts for embedding-input construction.

It defines two important abstractions:

1. `EmbeddingSourceChunk`
2. `EmbeddingInputBuilder`

The module is intentionally independent from ORM and persistence models so that input-building strategies do not need to know about SQLAlchemy or database structures.

---

# `EmbeddingSourceChunk`

`EmbeddingSourceChunk` is a provider-independent representation of a canonical knowledge chunk plus the structural metadata that an input-building strategy may use.

```text
EmbeddingSourceChunk
├── chunk_id
├── document_id
├── version_id
├── document_title
├── chunk_text
├── section_title
├── section_path
├── document_metadata
└── chunk_metadata
```

This gives an input strategy enough information to construct richer embedding text without accessing repositories or persistence.

---

## Identity

The source contains three identifiers:

```text
chunk_id
document_id
version_id
```

These allow the prepared embedding input to remain associated with the exact canonical chunk and its document/version hierarchy.

The builder contract requires the returned `chunk_id` to match the source chunk ID.

---

## Canonical Content

The most important fields are:

```text
document_title
chunk_text
```

`chunk_text` represents the actual canonical knowledge content.

The source model strips surrounding whitespace and rejects blank document titles and blank chunk content.

This means builders receive normalized basic textual values before constructing model-facing input.

---

## Structural Context

The source can also contain:

```text
section_title
section_path
```

For example:

```text
section_path:
    ("Billing", "4.4 Refund Calculation")

section_title:
    "4.4 Refund Calculation"
```

A contextual strategy can use these fields to improve the semantic representation of a chunk without changing the canonical chunk itself.

---

## Metadata

Two optional metadata mappings are available:

```text
document_metadata
chunk_metadata
```

These are exposed to input-building strategies but are not automatically rendered into the embedding text.

This allows future strategies to selectively use retrieval-relevant metadata without coupling the base abstraction to any specific metadata schema.

---

# Source Normalization

`EmbeddingSourceChunk` performs limited normalization during initialization:

```text
document_title → strip()
chunk_text      → strip()
section_title   → strip()
section_path    → remove blank entries + strip()
```

Blank section titles become `None`.

The normalized values are written back to the frozen dataclass during initialization.

This provides a clean input boundary while preserving the actual canonical content semantics.

---

# `EmbeddingInputBuilder`

`EmbeddingInputBuilder` is the abstract strategy interface for constructing the exact model-facing text.

Its purpose is intentionally narrow:

> Construct the deterministic embedding input for one canonical knowledge chunk.

Implementations may enrich the source with stable context such as:

* document title;
* section hierarchy;
* selected retrieval-relevant metadata.

They must never mutate canonical knowledge content.

---

# Builder Descriptor

Every implementation exposes:

```python
descriptor
```

which returns an `EmbeddingInputDescriptor`.

The descriptor provides the stable identity of the input-construction strategy.

Material changes to output behavior must be reflected by changing:

```text
descriptor.version
```

or:

```text
descriptor.config_fingerprint
```

This is critical because a change in the text sent to the embedding model means that previously generated embeddings may no longer correspond to the same input semantics.

---

# `build()`

Every builder implements:

```python
build(source: EmbeddingSourceChunk) -> PreparedEmbeddingInput
```

The contract requires:

* returned `chunk_id` equals `source.chunk_id`;
* returned text is non-blank;
* identical source + identical configuration produces identical output;
* `input_fingerprint` identifies the exact returned text;
* no network I/O;
* no embedding-provider calls;
* no repository/database access;
* no mutation of source content.

This makes input construction a deterministic, local transformation.

---

# Why No Provider Calls?

The builder is deliberately separated from embedding generation.

```text
Builder
  │
  └── text construction only

Provider
  │
  └── text → vector
```

This separation provides:

* deterministic testing;
* easy provider replacement;
* reproducible fingerprints;
* clean retry behavior;
* no hidden network operations inside a formatting strategy.

---

# `contextual.py`

## Purpose

`contextual.py` provides the concrete:

```text
ContextualEmbeddingInputBuilder
```

strategy.

It enriches canonical chunk text with stable structural context such as:

* document title;
* section path;
* section title.

The resulting context is used only for embedding and is **not persisted as replacement canonical content**.

---

# `ContextualEmbeddingInputConfig`

The strategy is controlled by an immutable configuration object:

```text
ContextualEmbeddingInputConfig
├── include_document_title
├── include_section_path
├── include_section_title
├── document_label
├── section_label
├── section_separator
├── block_separator
└── max_context_chars
```

Default behavior enables:

```text
document title     = enabled
section path       = enabled
section title      = enabled
```

The default labels are:

```text
Document
Section
```

and structural sections are separated with:

```text
" > "
```

while context blocks are separated with:

```text
"\n\n"
```

---

# Configuration Validation

The configuration validates its own invariants.

If document-title context is enabled:

```text
document_label != blank
```

If section context is enabled:

```text
section_label != blank
```

Separators must not be empty.

If a context character budget is configured:

```text
max_context_chars > 0
```

This prevents invalid configurations from reaching the embedding pipeline.

---

# Configuration Fingerprinting

One of the most important features of the configuration is:

```python
fingerprint()
```

The configuration is converted to deterministic JSON using:

* `sort_keys=True`;
* stable separators;
* UTF-8 encoding.

The resulting representation is hashed using SHA-256.

Conceptually:

```text
Configuration
     │
     ▼
Canonical JSON
     │
     ▼
SHA-256
     │
     ▼
config_fingerprint
```

This fingerprint becomes part of the strategy descriptor.

Therefore:

```text
different behavior
       ↓
different configuration fingerprint
       ↓
different embedding identity
       ↓
existing embeddings can be invalidated/rebuilt
```

---

# Strategy Identity

`ContextualEmbeddingInputBuilder` declares:

```text
STRATEGY_ID      = "contextual-chunk"
STRATEGY_VERSION = "1.0.0"
```

The descriptor combines:

```text
strategy_id
version
config_fingerprint
```

This gives an embedding artifact a stable identity for the exact input-construction strategy that produced it.

A material formatting/behavior change should therefore result in an appropriate strategy version or configuration fingerprint change.

---

# Contextual Build Pipeline

`ContextualEmbeddingInputBuilder.build()` follows this sequence:

```text
EmbeddingSourceChunk
        │
        ▼
Validate source
        │
        ▼
Build context blocks
        │
        ▼
Apply optional context budget
        │
        ▼
Render final text
        │
        ▼
Validate non-blank output
        │
        ▼
Fingerprint exact text
        │
        ▼
PreparedEmbeddingInput
```

---

# Source Validation

Before building the input, the strategy verifies that required source information exists.

The canonical chunk text must not be blank.

If document-title context is enabled, the document title must also be present.

This ensures that a configured contextual strategy cannot silently produce incomplete contextual representations.

---

# Context Construction

The contextual builder creates a sequence of context blocks.

When enabled:

```text
Document: <document title>
```

is added first.

Then section information is constructed from:

```text
section_path
+
section_title
```

---

# Section Hierarchy

Section context is represented as a single normalized hierarchy.

For example:

```text
section_path:
    Billing
    4.4 Refund Calculation

section_title:
    4.4 Refund Calculation
```

produces:

```text
Billing > 4.4 Refund Calculation
```

The implementation intentionally avoids rendering the same final heading twice.

---

# Duplicate Handling

The helper:

```python
_append_unique()
```

removes only **adjacent duplicate structural labels**.

It does not globally deduplicate section names.

For example, a repeated name at different hierarchy levels may be legitimate and is therefore preserved.

This preserves hierarchy semantics while avoiding accidental repeated headings.

---

# Context Budget

The optional:

```text
max_context_chars
```

controls how much contextual enrichment can be included.

The important design rule is:

> **Context may be reduced, but canonical chunk text is never truncated by this mechanism.**

Context blocks are considered in priority order and retained only when adding another block would remain within the configured budget.

A structural block is either retained completely or skipped; it is not sliced in the middle.

---

# Rendering

The final representation is deliberately simple.

If no contextual blocks are available:

```text
<chunk text>
```

Otherwise:

```text
<context block 1>

<context block 2>

<chunk text>
```

using the configured `block_separator`.

For example:

```text
Document: Billing Dispute Policy

Section: Billing Disputes > 4.4 Refund Calculation

Partial refunds may be issued when only part of an invoice is
disputed successfully.
```

The important point is that the final representation is deterministic.

---

# Exact Input Fingerprinting

After rendering, the builder computes:

```text
SHA-256(exact model-facing text)
```

This fingerprint represents the **actual text that will be embedded**, not merely the canonical chunk content.

Therefore, any change to:

* document title;
* section hierarchy;
* labels;
* separators;
* context inclusion;
* context budget;
* formatting;

can result in a different embedding input fingerprint.

---

# Embedding Identity

The overall identity model can be viewed as:

```text
Canonical Chunk
      │
      ▼
Input Strategy
      │
      ├── strategy_id
      ├── strategy_version
      └── config_fingerprint
      │
      ▼
Exact Rendered Text
      │
      ▼
input_fingerprint
      │
      ▼
Embedding Provider
      │
      ▼
Embedding Artifact
```

This is important for reproducibility and safe re-embedding.

If the model-facing representation changes, the fingerprint changes and the old embedding can be treated as belonging to a different input representation.

---

# Immutability

Both the source representation and contextual configuration are frozen dataclasses.

This supports the broader embedding architecture:

```text
Canonical source
      │
      │ immutable
      ▼
Derived embedding input
      │
      │ immutable
      ▼
Embedding artifact
```

The builder itself does not mutate the source object.

---

# Error Handling

The contextual builder distinguishes expected input-validation failures from unexpected failures.

Expected validation errors are propagated directly.

Unexpected failures are wrapped in:

```text
EmbeddingInputBuildError
```

with:

* chunk ID;
* strategy ID.

This gives the application layer a stable error boundary without leaking arbitrary implementation exceptions.

---

# What This Package Does Not Do

The input layer does **not**:

* call embedding APIs;
* generate vectors;
* access repositories;
* access SQLAlchemy;
* access databases;
* persist chunks;
* persist embeddings;
* modify canonical chunk content;
* perform retrieval;
* perform reranking.

The builder only produces:

```text
PreparedEmbeddingInput
```

from:

```text
EmbeddingSourceChunk
```

This boundary is explicitly part of the `EmbeddingInputBuilder` contract.

---

# Extension Model

New input-construction strategies can implement `EmbeddingInputBuilder`.

Conceptually:

```text
EmbeddingInputBuilder
        │
        ├── ContextualEmbeddingInputBuilder
        │
        ├── FutureStrategyA
        │
        └── FutureStrategyB
```

Every strategy must provide:

```python
descriptor
build(source)
```

and must obey the deterministic/no-I/O/no-mutation contract.

A new strategy should also establish a stable strategy ID and version and ensure that configuration changes affect its descriptor fingerprint.

---

# Determinism Contract

The central invariant is:

```text
  same source
        +
  same strategy
        +
same configuration
        │
        ▼
same rendered text
        │
        ▼
same input fingerprint
```

This makes the input layer suitable for:

* reproducible embeddings;
* idempotent embedding workflows;
* cache/deduplication logic;
* embedding backfills;
* model/strategy migrations;
* debugging and auditability.

---

# Relationship to the Embedding Pipeline

The input layer is one stage in the larger embedding architecture:

```text
Knowledge Chunk
      │
      ▼
EmbeddingSourceChunk
      │
      ▼
Embedding Input Builder
      │
      ▼
PreparedEmbeddingInput
      │
      ▼
Embedding Provider
      │
      ▼
Vector
      │
      ▼
KnowledgeChunkEmbedding
```

The separation is intentional:

**Input builder**

```text
"What exact text should be embedded?"
```

**Embedding provider**

```text
"How do we turn that text into a vector?"
```

This keeps model-facing text construction independent from the embedding vendor/model implementation.

---

# Key Design Principles

### 1. Canonical content remains authoritative

Context is a derived representation. The original chunk content is never replaced.

### 2. Input construction is deterministic

The same source and configuration must produce the same output.

### 3. Strategy identity is explicit

Behavior changes must be reflected in strategy version or configuration fingerprint.

### 4. Exact text is fingerprinted

The fingerprint represents the actual model-facing text.

### 5. No hidden I/O

Builders do not call databases, repositories, networks, or embedding providers.

### 6. Context is optional

The strategy can enrich chunks with structural context without requiring every source to have every possible context field.

### 7. Context is lower priority than canonical content

When a context budget is configured, optional context may be omitted, but canonical chunk text is preserved.

---

# Summary

`packages/knowledge/embeddings/input/` is the **deterministic model-facing text construction layer** of the knowledge embedding pipeline.

Its architecture is intentionally small:

```text
base.py
  │
  ├── EmbeddingSourceChunk
  │
  └── EmbeddingInputBuilder
             │
             ▼
contextual.py
  │
  ├── ContextualEmbeddingInputConfig
  │
  └── ContextualEmbeddingInputBuilder
             │
             ▼
     PreparedEmbeddingInput
```

`base.py` establishes the contract, while `contextual.py` implements the current contextual strategy.

The resulting design ensures that embedding input construction is:

* **provider-independent**
* **database-independent**
* **deterministic**
* **immutable**
* **fingerprintable**
* **configurable**
* **reproducible**
* **safe to integrate into idempotent embedding workflows**

Most importantly, contextual enrichment remains a **derived embedding concern** and never changes the canonical knowledge stored by the system.
