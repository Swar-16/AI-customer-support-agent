# Knowledge Chunking

## Overview

The `packages/knowledge/ingestion/chunking/` package converts a fully normalized knowledge document into **deterministic, retrieval-oriented chunks** while preserving provenance, structural context, strategy identity, and reproducibility metadata.

```text
packages/
└── knowledge/
    └── ingestion/
        └── chunking/
            ├── base.py
            ├── errors.py
            ├── models.py
            ├── resolver.py
            └── semantic_text.py
```

The package sits between **normalization** and downstream stages such as embedding and persistence:

```text
        Raw Source
            │
            ▼
        Parsing
            │
            ▼
        Normalization
            │
            ▼
┌──────────────────────────────┐
│          Chunking            │
│                              │
│  NormalizedDocument          │
│          │                   │
│          ▼                   │
│  DocumentChunker             │
│          │                   │
│          ▼                   │
│  ChunkedDocument             │
└──────────────────────────────┘
            │
            ├── Embedding
            ├── Persistence
            └── Retrieval
```

The chunking layer **does not perform embeddings or retrieval**. It produces the canonical chunk artifacts consumed by those later stages.

---

# Responsibilities

This package is responsible for:

* defining the document-chunker contract;
* identifying chunking strategies and versions;
* routing source types to appropriate chunkers;
* representing chunk provenance;
* preserving section hierarchy;
* enforcing chunk-size constraints;
* generating controlled overlap;
* validating chunking output;
* generating deterministic chunk fingerprints;
* exposing structured chunking errors;
* preserving parser/normalizer/chunker provenance.

It intentionally keeps **embedding-specific context separate from canonical chunk content**.

---

# File Structure

| File               | Responsibility                             |
| ------------------ | ------------------------------------------ |
| `base.py`          | Chunker contracts and strategy descriptors |
| `models.py`        | Chunking domain models and provenance      |
| `semantic_text.py` | Structural text chunking implementation    |
| `resolver.py`      | Composition-time chunker selection         |
| `errors.py`        | Chunking-specific exception hierarchy      |

Together they form:

```text
                  DocumentChunker
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
        Contract             Resolver
          base.py           resolver.py
             │                   │
             └─────────┬─────────┘
                       ▼
             StructuralTextChunker
                 semantic_text.py
                       │
                       ▼
                 ChunkedDocument
                    models.py
                       │
                       ▼
                  Errors/Validation
                    errors.py
```

---

# 1. Chunker Contract — `base.py`

`base.py` defines the abstraction that every document chunking strategy must satisfy.

## `ChunkerDescriptor`

Each strategy exposes immutable identity metadata:

```text
strategy_id
version
config_fingerprint
```

The descriptor provides a stable logical identity:

```text
strategy_id@version
```

and allows output-affecting configuration to be tracked separately.

This is important for reproducibility: changing chunking behavior should produce a distinguishable strategy configuration rather than silently producing incompatible artifacts.

---

## `DocumentChunker`

The runtime-checkable protocol defines the common interface:

```python
descriptor
supported_source_types
supports(source_type)
chunk(document)
```

A chunker transforms a `NormalizedDocument` into a `ChunkedDocument`.

Implementations are expected to be deterministic for the same:

* normalized input;
* strategy version;
* output-affecting configuration.

---

## `BaseDocumentChunker`

The abstract base class provides common `supports()` behavior while requiring concrete implementations to define:

* `descriptor`;
* `supported_source_types`;
* `chunk()`.

---

## `DocumentChunkerResolver`

The contract also defines the resolver boundary used to select the appropriate chunker for a `KnowledgeSourceType`.

Strategy selection belongs to composition rather than request-time mutation.

---

# 2. Chunking Models — `models.py`

`models.py` contains the immutable domain artifacts produced and consumed by the chunking stage.

The primary objects are:

```text
ChunkSourceSpan
      │
      ▼
ChunkCandidate
      │
      ▼
ChunkedDocument
```

---

## `ChunkSourceSpan`

A `ChunkSourceSpan` identifies exactly which portion of a normalized segment contributed to a chunk.

Offsets are:

```text
[start_offset:end_offset]
```

relative to `NormalizedSegment.text`.

They are **not offsets into the original source document**. This is important because parsing and normalization may have changed the original representation.

---

# `ChunkCandidate`

A `ChunkCandidate` represents canonical semantic content produced by a chunker.

It contains:

```text
index
text
source_spans
section_path
metadata
```

The canonical `text` represents the chunk's semantic content and should not contain synthetic retrieval context solely introduced for a particular embedding model. Structural information such as headings is represented separately through `section_path`.

This creates an important separation:

```text
Canonical chunk
├── semantic text
├── structural context
└── provenance

Embedding-specific representation
└── constructed later
```

---

## Provenance

Each chunk retains source spans back to normalized segments.

This allows downstream systems to answer:

```text
Which normalized content produced this chunk?
```

without embedding provenance into the actual semantic text.

Multiple chunks may legitimately reference the same normalized segment because splitting and overlap are supported.

---

## Section Context

`ChunkCandidate` exposes derived structural information:

```text
section_title
section_context
```

The complete section hierarchy can therefore be represented as:

```text
Account
  >
Security
  >
Password Reset
```

without modifying the canonical chunk text.

---

## Content Fingerprint

Each chunk exposes a deterministic `content_fingerprint`.

The fingerprint is based on:

```text
chunk text
+
section path
```

and intentionally excludes source offsets.

Therefore, moving unchanged semantic content within a source document does not inherently change its semantic identity.

---

# `ChunkedDocument`

`ChunkedDocument` represents the complete output of a chunking operation.

It preserves the transformation chain:

```text
Parser
   │
   ▼
Normalizer
   │
   ▼
Chunker
   │
   ▼
ChunkedDocument
```

It contains:

* knowledge version ID;
* source type;
* ordered chunks;
* parser provenance;
* normalizer provenance;
* chunker provenance;
* metadata.

Embedding provenance deliberately does not belong here because embeddings are model-dependent artifacts created later.

---

## Chunk Ordering

Chunks must be:

```text
0, 1, 2, 3, ...
```

with no gaps or reordering.

The model explicitly validates contiguous zero-based indexes.

---

# 3. Chunking Errors — `errors.py`

`errors.py` defines the domain-specific error boundary for chunking.

The hierarchy begins with:

```text
KnowledgeChunkingError
├── KnowledgeChunkerConfigurationError
├── UnsupportedKnowledgeChunkingSourceTypeError
├── InvalidChunkingInputError
├── KnowledgeChunkingExecutionError
└── KnowledgeChunkerOutputError
```

The base exception provides:

```text
code
message
context
```

where `code` is intended to be machine-readable and `context` contains structured diagnostics.

---

## Configuration Errors

`KnowledgeChunkerConfigurationError` represents composition/deployment problems such as:

* duplicate source-type registrations;
* malformed chunker contracts;
* empty source-type declarations;
* inconsistent `supports()` behavior;
* invalid chunker configuration.

These are generally **application configuration problems**, not bad customer knowledge content.

---

## Unsupported Source Types

`UnsupportedKnowledgeChunkingSourceTypeError` indicates that no configured chunker can process the requested `KnowledgeSourceType`.

---

## Invalid Input

`InvalidChunkingInputError` represents semantically invalid ingestion artifacts, such as:

* unsupported normalized source type;
* structurally inconsistent normalized data;
* missing provenance required by the strategy.

---

## Execution Errors

`KnowledgeChunkingExecutionError` provides the translation boundary for unexpected failures occurring while a valid chunking operation is being executed.

The original exception should remain available through exception chaining.

---

## Output Errors

`KnowledgeChunkerOutputError` represents a chunker that completed its algorithm but violated its output contract.

Examples include:

* no chunks;
* blank chunks;
* invalid provenance spans;
* non-contiguous indexes;
* unexpected size violations;
* lost source content.

This distinction is useful because it separates:

```text
Bad input
   ≠
Chunker execution failure
   ≠
Invalid chunker output
```

---

# 4. Chunker Resolution — `resolver.py`

`DefaultDocumentChunkerResolver` provides deterministic, immutable strategy selection.

At application composition time:

```text
Configured Chunkers
       │
       ▼
DefaultDocumentChunkerResolver
       │
       ▼
KnowledgeSourceType
       │
       ▼
DocumentChunker
```

Exactly one active chunker may be registered for each supported source type.

---

## Eager Validation

The resolver validates configured chunkers when it is constructed rather than during document processing.

It checks:

* the object implements `DocumentChunker`;
* the descriptor is valid;
* `supported_source_types` is a `frozenset`;
* at least one source type is supported;
* all entries are valid `KnowledgeSourceType` values;
* declared capabilities agree with `supports()`.

This moves configuration failures toward application startup/composition instead of allowing them to appear unpredictably during ingestion.

---

## Duplicate Registrations

If two chunkers claim the same source type:

```text
Chunker A ──► MARKDOWN
Chunker B ──► MARKDOWN
```

construction fails with a configuration error rather than silently choosing one.

---

## Immutable Routing

The resolver does not support runtime strategy mutation.

Changing the configured chunking strategy should happen by rebuilding application composition with different configuration.

---

# 5. Structural Text Chunker — `semantic_text.py`

`semantic_text.py` contains the current concrete implementation:

```text
StructuralTextChunker
```

It is a deterministic, structure-aware chunking strategy.

Its responsibilities include:

* combining small normalized segments;
* splitting oversized segments;
* preferring natural textual boundaries;
* preserving section boundaries;
* generating bounded overlap;
* retaining exact source provenance;
* enforcing a hard chunk-size limit.

---

# Configuration

`StructuralTextChunkerConfig` controls output-affecting behavior.

Default values include:

```text
target_chars                 = 1200
max_chars                    = 1800
min_chunk_chars              = 250
overlap_chars                = 160
preserve_section_boundaries  = True
merge_small_sections         = True
max_section_depth_distance   = 1
separator                    = "\n\n"
```

These settings are validated and represented by a deterministic configuration fingerprint.

The fingerprint is included in the chunker's `ChunkerDescriptor`.

---

# Supported Source Types

The structural chunker currently supports:

```text
MARKDOWN
PLAIN_TEXT
PDF
DOCX
HTML
RICH_TEXT
```

The chunker operates on the normalized representation, so it does not need to understand every original source format independently.

---

# Chunking Pipeline

The internal flow is approximately:

```text
NormalizedDocument
       │
       ▼
Create source pieces
       │
       ▼
Split oversized segments
       │
       ▼
Assemble semantic chunks
       │
       ├── section boundaries
       ├── target size
       ├── hard size limit
       └── overlap
       │
       ▼
Validate output
       │
       ▼
ChunkedDocument
```

The public `chunk()` method validates the input, creates source pieces, assembles chunks, validates the resulting output, and preserves parser/normalizer provenance.

---

# Natural Boundary Splitting

When an ordinary text segment exceeds the hard limit, the chunker searches for the best available boundary.

Priority:

```text
1. paragraph/newline
2. sentence-ending punctuation
3. whitespace
4. hard character boundary
```

The implementation intentionally avoids heavyweight NLP dependencies.

Sentence boundaries support common punctuation including:

```text
.
!
?
。
！
？
।
```

---

# Code and Table Handling

Fenced-code and indented-code blocks receive different treatment.

They are considered structurally atomic and prefer line boundaries rather than ordinary sentence punctuation when splitting is unavoidable.

This reduces the risk of treating programming syntax as ordinary prose.

---

# Section-Aware Assembly

When section preservation is enabled, the chunker considers section hierarchy before merging pieces.

A sufficiently large existing chunk causes a new section to begin a new chunk.

Small adjacent sections may be merged when their hierarchy remains structurally related.

Conceptually:

```text
Document
├── Account
│   ├── Login
│   └── Password Reset
│
└── Billing
    ├── Invoices
    └── Refunds
```

The chunker attempts to preserve meaningful structural boundaries rather than blindly packing characters.

---

# Overlap

The chunker can carry a bounded suffix from one chunk into the next.

```text
Chunk A
[.......................]
             │
             └── overlap ──►
                              Chunk B
                              [overlap.................]
```

Overlap is:

* source-backed;
* bounded by configuration;
* based on natural boundaries where possible;
* never invented without provenance.

The overlap search prefers:

1. paragraph boundaries;
2. sentence boundaries;
3. whitespace.

It avoids intentionally beginning an overlap in the middle of a word.

---

# Output Validation

After chunk construction, the chunker validates its own postconditions.

Important guarantees include:

```text
chunks != empty
indexes are contiguous and zero-based
chunk text is non-blank
chunk length <= max_chars
section-only chunks are rejected
source spans reference real normalized segments
source spans remain within segment boundaries
```

This makes the chunker an explicit validation boundary rather than assuming its internal algorithm always produced valid artifacts.

---

# Provenance Flow

The chunking subsystem preserves the complete ingestion transformation chain:

```text
Source
  │
  ▼
Parser
  │
  ├── strategy
  ├── version
  └── configuration fingerprint
  │
  ▼
Normalizer
  │
  ├── strategy
  ├── version
  └── configuration fingerprint
  │
  ▼
Chunker
  │
  ├── strategy
  ├── version
  └── configuration fingerprint
  │
  ▼
ChunkedDocument
  │
  └── ChunkCandidate
        │
        └── ChunkSourceSpan
```

This allows downstream systems to determine how a chunk was produced without embedding implementation details into the chunk's semantic content.

---

# Relationship With Embeddings

Chunking intentionally stops before model-specific representation.

```text
ChunkCandidate
    │
    ├── canonical text
    ├── section path
    └── source provenance
          │
          ▼
      Embedding Stage
          │
          ▼
Model-specific embedding input
```

A chunk does not contain an embedding.

This separation allows the same canonical chunk to be embedded using different providers or input strategies without changing the ingestion artifact itself.

---

# Determinism

Determinism is a core property of this subsystem.

Given the same:

```text
NormalizedDocument
+
chunker strategy version
+
chunker configuration
```

the chunker should produce the same logical chunking result.

The descriptor and configuration fingerprint make output-affecting strategy changes explicit.

---

# Error Boundary

The chunking layer maintains a clean boundary between different classes of failures:

```text
Configuration
     │
     ▼
KnowledgeChunkerConfigurationError

Unsupported source
     │
     ▼
UnsupportedKnowledgeChunkingSourceTypeError

Invalid normalized input
     │
     ▼
InvalidChunkingInputError

Unexpected algorithm failure
     │
     ▼
KnowledgeChunkingExecutionError

Invalid generated output
     │
     ▼
KnowledgeChunkerOutputError
```

This makes failures easier to translate, monitor, test, and diagnose.

---

# Adding Another Chunking Strategy

A new chunking strategy should implement the existing `DocumentChunker` contract.

Typical structure:

```text
BaseDocumentChunker
       │
       ├── StructuralTextChunker
       └── FutureChunker
```

A strategy should provide:

1. a stable `ChunkerDescriptor`;
2. supported source types;
3. deterministic `chunk()` behavior;
4. valid `ChunkedDocument` output;
5. complete source provenance;
6. appropriate domain-level error translation.

It should then be registered through the resolver during application composition.

---

# Important Invariants

The package relies on several important invariants.

### Canonical content remains clean

Chunk text represents semantic content, not provider-specific retrieval decoration.

### Provenance is explicit

Source relationships are represented by `ChunkSourceSpan`.

### Chunk indexes are deterministic

```text
0 ... N-1
```

with no gaps.

### Hard size limits are enforced

No generated chunk may exceed `max_chars`.

### Section context is separate

Structural context is represented through `section_path`.

### Strategy identity is explicit

Chunker version/configuration is captured in the descriptor.

### Resolver routing is deterministic

A source type maps to exactly one configured chunker.

### Configuration is immutable at runtime

Changing strategy requires changing composition/configuration rather than mutating a live resolver.

---

# Testing Strategy

Testing should cover the subsystem at multiple levels.

## Contract tests

Verify every chunker:

* exposes a valid descriptor;
* reports supported source types correctly;
* agrees between `supported_source_types` and `supports()`;
* produces valid `ChunkedDocument` output.

## Model tests

Verify:

* source-span validation;
* contiguous indexes;
* section metadata;
* content fingerprints;
* immutable metadata;
* provenance validation.

## Structural chunker tests

Cover:

* short documents;
* oversized segments;
* paragraph boundaries;
* sentence boundaries;
* whitespace fallback;
* extremely long tokens;
* section transitions;
* small-section merging;
* overlap;
* code blocks;
* hard size limits;
* provenance preservation.

## Resolver tests

Cover:

* empty configuration;
* duplicate source types;
* invalid chunkers;
* inconsistent `supports()`;
* unsupported source types;
* immutable resolution behavior.

## Error tests

Verify stable:

```text
error.code
error.message
error.context
```

and correct exception chaining for translated execution failures.

---

# Summary

`packages/knowledge/ingestion/chunking/` is the **deterministic semantic segmentation layer of knowledge ingestion**.

Its overall responsibility can be summarized as:

```text
NormalizedDocument
       │
       ▼
Chunker Resolver
       │
       ▼
DocumentChunker
       │
       ▼
Structural Chunking
       │
       ├── semantic boundaries
       ├── section awareness
       ├── bounded overlap
       ├── size constraints
       └── provenance
       │
       ▼
ChunkedDocument
       │
       ├── ChunkCandidate
       ├── ChunkSourceSpan
       └── transformation metadata
       │
       ▼
Embedding / Persistence / Retrieval
```

The five files divide the responsibility cleanly:

```text
base.py
    → contracts and strategy identity

models.py
    → immutable chunk artifacts and provenance

semantic_text.py
    → concrete structure-aware chunking algorithm

resolver.py
    → deterministic source-type → chunker routing

errors.py
    → structured chunking failure boundary
```

The key architectural principle is that **chunking produces canonical, reproducible, provenance-aware retrieval units without coupling them to any particular embedding model or retrieval implementation**.
