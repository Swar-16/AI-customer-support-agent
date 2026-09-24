# Knowledge Normalization

## Overview

The `packages/knowledge/ingestion/normalization/` package is the **canonical normalization stage of the knowledge-ingestion pipeline**.

It converts parser-specific `ParsedDocument` artifacts into a **format-independent `NormalizedDocument`** that is suitable for downstream chunking.

```text
Raw Knowledge Source
        │
        ▼
     Parser
        │
        ▼
 ParsedDocument
        │
        ▼
 ┌──────────────────────┐
 │     Normalization    │
 │                      │
 │  source-specific     │
 │  normalizer          │
 │        │             │
 │        ▼             │
 │  NormalizedDocument  │
 └──────────────────────┘
        │
        ▼
     Chunking
        │
        ▼
    Embeddings
```

The normalization layer deliberately sits **between parsing and chunking**. A normalized segment is still **not a retrieval chunk**; combining, splitting, overlap, and final retrieval-unit construction belong to the chunking stage.

---

# Responsibilities

The normalization subsystem is responsible for:

* defining the normalizer contract;
* defining normalizer strategy identity and versioning;
* converting parsed source structures into retrieval-oriented normalized segments;
* preserving source provenance;
* preserving meaningful structural information such as section paths;
* removing source-format-specific presentation artifacts where appropriate;
* canonicalizing text representation;
* validating normalized output;
* selecting normalizers by `KnowledgeSourceType`;
* exposing structured normalization errors.

It does **not**:

* parse raw files;
* create final retrieval chunks;
* generate embeddings;
* perform vector or lexical retrieval;
* interact with the database;
* perform LLM processing.

---

# Files

```text
packages/
└── knowledge/
    └── ingestion/
        └── normalization/
            ├── base.py
            ├── errors.py
            ├── markdown.py
            ├── models.py
            ├── plain_text.py
            └── resolver.py
```

| File            | Responsibility                             |
| --------------- | ------------------------------------------ |
| `base.py`       | Normalizer contracts and strategy identity |
| `models.py`     | Immutable normalized-document artifacts    |
| `errors.py`     | Normalization-specific error hierarchy     |
| `markdown.py`   | Markdown normalization strategy            |
| `plain_text.py` | Plain-text normalization strategy          |
| `resolver.py`   | Source-type → normalizer resolution        |

---

# Architecture

The six files form a simple strategy-based normalization layer:

```text
                    DocumentNormalizer
                           │
                ┌──────────┴──────────┐
                │                     │
                ▼                     ▼
      MarkdownNormalizer      PlainTextNormalizer
          markdown.py             plain_text.py
                │                     │
                └──────────┬──────────┘
                           ▼
                  NormalizedDocument
                       models.py
                           │
                           ▼
                     Chunking Layer

              DefaultDocumentNormalizerResolver
                         resolver.py
                              │
                    selects appropriate
                         normalizer
```

Errors from the entire layer are represented through the normalization exception hierarchy in `errors.py`.

---

# 1. `base.py` — Normalizer Contract

`base.py` defines the provider-independent contract for document normalization.

The core abstraction is:

```text
DocumentNormalizer
```

A normalizer transforms:

```text
ParsedDocument
       │
       ▼
NormalizedDocument
```

The abstraction allows different source formats to have different normalization strategies without making downstream ingestion stages format-dependent.

---

## `NormalizerDescriptor`

Each normalizer exposes immutable identity information:

```text
NormalizerDescriptor
├── strategy_id
├── version
└── config_fingerprint
```

The identity allows the resulting normalized artifact to record **which normalization strategy produced it**.

Conceptually:

```text
strategy_id@version
```

A configuration fingerprint can additionally identify output-affecting configuration.

This is important for reproducibility and for determining when downstream artifacts may need to be regenerated.

---

## `DocumentNormalizer`

The contract provides the essential operations:

```text
descriptor
supported_source_types
supports(source_type)
normalize(document)
```

Concrete normalizers therefore remain interchangeable from the perspective of the ingestion pipeline.

---

## `BaseDocumentNormalizer`

The base class supplies common source-type capability handling while leaving the actual transformation to concrete strategies.

A concrete implementation primarily needs to provide:

```text
descriptor
supported_source_types
normalize(...)
```

This keeps source-specific normalization logic isolated.

---

# 2. `models.py` — Normalized Artifacts

`models.py` contains the core immutable artifacts produced by normalization.

The two primary models are:

```text
NormalizedSegment
        │
        ▼
NormalizedDocument
```

---

## `NormalizedSegment`

A normalized segment is a **retrieval-oriented representation derived from exactly one parsed segment**.

It contains:

```text
NormalizedSegment
├── index
├── source_segment_index
├── text
├── section_path
└── metadata
```

The distinction between `index` and `source_segment_index` is important.

```text
index
    → position in normalized output

source_segment_index
    → originating parsed segment
```

This preserves deterministic provenance even when normalization removes some parsed segments.

The model explicitly allows normalization to change cardinality: some parsed structural segments may produce no lexical representation.

---

## Segment Validation

Normalized segments enforce:

* non-negative indexes;
* valid source-segment indexes;
* non-blank text;
* valid section paths;
* mapping-compatible metadata.

Metadata is frozen into an immutable mapping after construction.

---

## Section Context

A segment may carry:

```text
section_path = (
    "Account",
    "Password Reset",
)
```

The final section title can be derived from the final path component.

This structural information survives normalization and becomes available to the downstream chunking layer.

---

# `NormalizedDocument`

`NormalizedDocument` is the complete output of a normalizer.

It contains:

```text
NormalizedDocument
├── version_id
├── source_type
├── segments
├── source parser provenance
├── normalizer provenance
└── metadata
```

The artifact therefore preserves both:

```text
Parser
  │
  └── strategy/version/config
        │
        ▼
Normalizer
  │
  └── strategy/version/config
        │
        ▼
NormalizedDocument
```

This makes the ingestion transformation history reconstructable.

---

## Segment Ordering

Normalized segments must be:

```text
0, 1, 2, ..., N-1
```

with contiguous zero-based indexes.

They must also reference distinct source segments.

This creates a deterministic representation for downstream chunking.

---

## Normalizer Identity

The normalized document exposes a stable normalizer identity conceptually equivalent to:

```text
normalizer_strategy_id@normalizer_version
```

This provides a compact representation of which normalization behavior produced the artifact.

---

# 3. `errors.py` — Normalization Error Boundary

`errors.py` defines the domain-level error hierarchy for normalization.

The root exception is:

```text
KnowledgeNormalizationError
```

It provides:

```text
code
message
context
```

for machine-readable classification and structured diagnostics.

The major categories are:

```text
KnowledgeNormalizationError
├── KnowledgeNormalizerConfigurationError
├── UnsupportedKnowledgeNormalizationSourceTypeError
├── InvalidNormalizedDocumentError
├── KnowledgeNormalizationExecutionError
└── KnowledgeNormalizerOutputError
```

---

## Configuration Errors

`KnowledgeNormalizerConfigurationError` represents invalid strategy configuration or composition.

Examples include:

* malformed normalizer registration;
* duplicate source-type ownership;
* invalid normalizer contract;
* inconsistent source-type declarations.

These generally represent deployment/programming configuration problems rather than bad knowledge content.

---

## Unsupported Source Type

`UnsupportedKnowledgeNormalizationSourceTypeError` is raised when no active normalizer is configured for a requested `KnowledgeSourceType`.

---

## Invalid Input

`InvalidNormalizedDocumentError` represents semantically invalid input supplied to a normalizer.

For example:

```text
ParsedDocument
    │
    ├── wrong source type
    ├── missing segments
    └── invalid parser artifact
          │
          ▼
InvalidNormalizedDocumentError
```

---

## Execution Errors

`KnowledgeNormalizationExecutionError` provides the boundary for failures occurring while a normalization strategy is executing.

This prevents lower-level implementation failures from becoming coupled to higher layers.

---

## Output Errors

`KnowledgeNormalizerOutputError` represents a normalizer that completed execution but generated an invalid normalized artifact.

This distinction is important:

```text
Invalid input
      ≠
Execution failure
      ≠
Invalid output
```

The separate categories make failures easier to diagnose and translate.

---

# 4. `plain_text.py` — Plain Text Normalization

`PlainTextNormalizer` implements normalization for:

```text
KnowledgeSourceType.PLAIN_TEXT
```

Its strategy identity is:

```text
strategy_id = "plain-text-semantic"
version     = "1.0.0"
```

with no additional configuration fingerprint.

Because plain text contains no presentation syntax that needs to be stripped, its normalization is intentionally lightweight.

---

## Transformation

The core transformation is:

```text
ParsedSegment.text
        │
        ▼
Normalize line endings
        │
        ▼
Strip surrounding whitespace
        │
        ▼
NormalizedSegment
```

Line endings are canonicalized:

```text
\r\n → \n
\r   → \n
```

while meaningful internal spacing and paragraph structure are retained.

Blank normalized segments are discarded.

---

## Provenance

For each emitted segment, the normalizer preserves:

```text
source_segment_index
source_start_offset
source_end_offset
source_page_number
```

when those values are available.

This metadata is copied from the parsed segment rather than recreated during normalization.

---

## Output

The resulting `NormalizedDocument` preserves:

* knowledge version ID;
* source type;
* parser strategy identity;
* parser version;
* parser configuration fingerprint;
* normalizer identity;
* normalized segments;
* inherited metadata.

It additionally records useful normalization metadata such as the originating parser identity and normalized segment count.

---

# 5. `markdown.py` — Markdown Normalization

`MarkdownNormalizer` is the source-specific normalization strategy for Markdown documents.

Its role is to convert Markdown parser output into normalized semantic content while preserving meaningful document structure.

The important distinction is:

```text
Markdown syntax
      │
      ▼
   Parser
      │
      ▼
Parsed structural representation
      │
      ▼
MarkdownNormalizer
      │
      ▼
Normalized semantic representation
```

The normalizer therefore should not be responsible for parsing Markdown syntax itself.

Instead, it consumes the already-parsed Markdown structure and produces the common `NormalizedDocument` representation used by chunking.

---

## Structural Preservation

Markdown headings and structural relationships are represented through normalized section information rather than being treated as arbitrary text.

This allows downstream chunking to reason about:

```text
section_path
section_title
```

without needing to understand Markdown syntax.

---

## Separation of Concerns

The Markdown strategy follows the same boundary as the plain-text strategy:

```text
Parser
    → understands source syntax

Normalizer
    → produces canonical semantic representation

Chunker
    → creates retrieval chunks
```

This prevents Markdown-specific logic from leaking into the chunking and embedding layers.

---

# 6. `resolver.py` — Normalizer Selection

`DefaultDocumentNormalizerResolver` is the composition-time registry responsible for selecting the active normalizer for a source type.

Conceptually:

```text
KnowledgeSourceType
        │
        ▼
DefaultDocumentNormalizerResolver
        │
        ├── MARKDOWN   → MarkdownNormalizer
        │
        └── PLAIN_TEXT → PlainTextNormalizer
```

The resolver is intentionally immutable after construction.

---

## Resolution

The resolver exposes:

```text
supported_source_types
supports(source_type)
resolve(source_type)
```

If a source type has no configured normalizer, the resolver raises:

```text
UnsupportedKnowledgeNormalizationSourceTypeError
```

rather than returning a fallback implementation.

---

## Duplicate Registration Protection

Only one active normalizer may own a given source type.

For example:

```text
MarkdownNormalizer ──► MARKDOWN
AnotherNormalizer  ──► MARKDOWN
```

is rejected during resolver construction.

This prevents ambiguous normalization behavior.

---

## Contract Validation

The resolver validates each registered normalizer before adding it to the registry.

It checks:

* the normalizer satisfies the `DocumentNormalizer` contract;
* its descriptor is a `NormalizerDescriptor`;
* `supported_source_types` is a `frozenset`;
* at least one source type is supported;
* every declared source type is a valid `KnowledgeSourceType`;
* `supports()` agrees with the declared capabilities.

This provides **fail-fast configuration validation**.

---

# End-to-End Normalization Flow

The complete ingestion path is:

```text
                 Source File
                     │
                     ▼
              Document Parser
                     │
                     ▼
              ParsedDocument
                     │
                     ▼
        ┌────────────────────────┐
        │ Normalizer Resolver    │
        └───────────┬────────────┘
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
      Markdown             Plain Text
      Normalizer           Normalizer
          │                   │
          └─────────┬─────────┘
                    ▼
             NormalizedDocument
                    │
                    ▼
              Chunking Layer
                    │
                    ▼
              ChunkedDocument
                    │
                    ▼
               Embeddings
```

The normalization stage therefore establishes the **canonical handoff contract between parsing and chunking**.

---

# Provenance Model

One of the most important responsibilities of this layer is preserving transformation provenance.

```text
ParsedDocument
    │
    ├── parser_strategy_id
    ├── parser_version
    └── parser_config_fingerprint
    │
    ▼
NormalizedDocument
    │
    ├── normalizer_strategy_id
    ├── normalizer_version
    └── normalizer_config_fingerprint
    │
    ▼
ChunkedDocument
```

At the segment level:

```text
NormalizedSegment
    │
    └── source_segment_index
```

This means downstream systems can trace normalized content back to the parsed source structure.

The normalization model explicitly stores both parser and normalizer provenance for this purpose.

---

# Relationship With Chunking

Normalization and chunking are intentionally separate.

```text
NormalizedSegment
        │
        │  NOT YET A RETRIEVAL CHUNK
        ▼
Chunker
        │
        ├── combines segments
        ├── splits segments
        ├── creates overlap
        └── produces ChunkCandidate
```

A normalized document is therefore a **canonical intermediate representation**, not the final retrieval representation.

This separation makes it possible to change chunking strategies without changing source-format normalization.

---

# Current Operational Strategies

The current ingestion composition registers:

```text
Markdown
    → MarkdownNormalizer

Plain Text
    → PlainTextNormalizer
```

The production ingestion factory advertises Markdown and UTF-8 plain text as the currently supported upload types. PDF, DOCX, and HTML enum values exist for future expansion but are intentionally not advertised as operational until their parser/normalizer paths are complete.

---

# Important Invariants

The normalization subsystem maintains several important guarantees.

### 1. Normalized artifacts are immutable

The core models are frozen and their metadata is protected from accidental mutation.

### 2. Every normalized segment has one source segment

`source_segment_index` provides deterministic provenance back to the parser output.

### 3. Normalized indexes are contiguous

```text
0 ... N-1
```

No gaps or reordered normalized indexes are allowed.

### 4. Normalization may remove segments

A parser may produce structural segments that are intentionally discarded when they contain no retrieval-worthy lexical representation.

### 5. Parser provenance must survive normalization

The normalized artifact records the parser strategy, version, and configuration fingerprint.

### 6. Normalizer provenance is explicit

The normalizer strategy and version are part of the normalized artifact.

### 7. Resolver ownership is unambiguous

Exactly one active normalizer can own a given source type.

### 8. No silent fallback

Unsupported source types produce explicit domain errors rather than being passed through an arbitrary normalizer.

### 9. Normalization does not create retrieval chunks

Chunk construction remains a separate downstream stage.

---

# Testing Strategy

The normalization package should be tested at several levels.

## Model Tests

Verify:

* segment index validation;
* source-segment provenance;
* non-blank text;
* section-path validation;
* metadata immutability;
* normalized-document version/source validation;
* contiguous segment indexes;
* duplicate source-segment rejection;
* parser/normalizer provenance validation.

## Normalizer Tests

For each concrete normalizer verify:

* supported source types;
* invalid source rejection;
* empty parsed-document handling;
* deterministic output;
* blank-segment removal;
* provenance preservation;
* metadata propagation;
* correct strategy descriptor.

For plain text specifically:

```text
CRLF → LF
CR   → LF
surrounding whitespace → removed
meaningful internal structure → preserved
```

## Resolver Tests

Verify:

* valid registration;
* source-type resolution;
* unsupported source types;
* duplicate registrations;
* invalid descriptors;
* invalid source-type declarations;
* inconsistent `supports()` behavior;
* immutable registry behavior.

## Error Tests

Verify that expected failures remain within the normalization hierarchy:

```text
KnowledgeNormalizationError
```

and retain useful machine-readable error codes and diagnostic context.

---

# Design Principles

## Format Independence

After normalization, downstream components should not need to know whether the source originally came from Markdown or plain text.

## Provenance First

Normalization never sacrifices traceability merely to produce cleaner text.

## Deterministic Artifacts

The same parsed input and normalization strategy should produce reproducible normalized output.

## Immutable Contracts

Normalized artifacts are stable handoff objects between ingestion stages.

## Fail Fast

Invalid strategy configuration should be detected during resolver/composition construction rather than during an administrator's upload.

## Separation of Stages

```text
Parsing
    ≠
Normalization
    ≠
Chunking
    ≠
Embedding
```

Each stage owns one transformation.

## Provider Neutrality

Normalization has no dependency on embedding providers, vector databases, or LLMs.

---

# Summary

`packages/knowledge/ingestion/normalization/` is the **canonicalization boundary between document parsing and retrieval-oriented chunking**.

Its six files divide responsibilities as follows:

```text
base.py
    │
    └── Normalizer contract + strategy identity

models.py
    │
    └── NormalizedDocument / NormalizedSegment

errors.py
    │
    └── Structured normalization failures

markdown.py
    │
    └── Markdown → normalized semantic representation

plain_text.py
    │
    └── Plain text → normalized semantic representation

resolver.py
    │
    └── Source type → active normalizer
```

The resulting transformation is:

```text
ParsedDocument
      │
      ▼
Normalizer Resolver
      │
      ▼
Source-Specific Normalizer
      │
      ▼
NormalizedDocument
      │
      ├── normalized segments
      ├── section structure
      ├── source provenance
      ├── parser provenance
      └── normalizer provenance
      │
      ▼
Chunking
```

The key architectural idea is that **normalization creates a stable, format-independent, provenance-preserving intermediate representation without prematurely making decisions about retrieval chunk boundaries or embedding representation**.
