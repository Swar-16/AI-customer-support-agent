# Knowledge Document Parsers

## Overview

The `packages/knowledge/ingestion/parser/` package is the **source-parsing boundary of the knowledge ingestion pipeline**.

Its responsibility is to transform an `IngestionSource` containing raw source content into a structured `ParsedDocument` while preserving:

* source ordering;
* source character offsets;
* structural information;
* source-type identity;
* parser provenance.

```text
Raw Knowledge Source
        │
        ▼
   Parser Resolver
        │
        ▼
Source-Specific Parser
        │
        ▼
   ParsedDocument
        │
        ▼
  Normalization Layer
        │
        ▼
   Chunking Layer
```

The parser layer deliberately stops at **structural parsing**. It does not perform semantic normalization, retrieval chunking, embeddings, classification, or vector search. The plain-text parser explicitly defines these as non-responsibilities.

---

# Package Structure

```text
packages/
└── knowledge/
    └── ingestion/
        └── parser/
            ├── base.py
            ├── markdown.py
            ├── plain_text.py
            ├── resolver.py
            └── README.md
```

| File            | Responsibility                                |
| --------------- | --------------------------------------------- |
| `base.py`       | Parser contracts and parser strategy identity |
| `markdown.py`   | Structure-preserving Markdown parser          |
| `plain_text.py` | Structure-preserving plain-text parser        |
| `resolver.py`   | Source-type → parser resolution               |

Together they establish a provider-independent parser architecture.

---

# Architecture

```text
                         DocumentParser
                              │
                 ┌────────────┴────────────┐
                 │                         │
                 ▼                         ▼
      MarkdownStructuralParser    PlainTextStructuralParser
             markdown.py                 plain_text.py
                 │                         │
                 └────────────┬────────────┘
                              ▼
                       ParsedDocument
                              │
                              ▼
                    Normalization Layer


                 DefaultDocumentParserResolver
                              │
                  resolves by KnowledgeSourceType
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
            MARKDOWN                   PLAIN_TEXT
                │                           │
                ▼                           ▼
        Markdown Parser             Plain Text Parser
```

Parser registration happens during application composition, while actual resolution happens later when a knowledge version is processed. The resolver is intentionally immutable after construction so that runtime parser mutation cannot make ingestion behavior unpredictable.

---

# 1. `base.py` — Parser Contract

`base.py` defines the abstraction that all document parsers must satisfy.

The contract separates **what a parser does** from **how a particular source format is parsed**.

Conceptually:

```text
DocumentParser
├── descriptor
├── supported_source_types
├── supports(source_type)
└── parse(source)
```

Concrete implementations therefore expose a common interface to the ingestion pipeline.

---

## Parser Descriptor

Each parser has a stable descriptor containing its strategy identity and version.

Conceptually:

```text
ParserDescriptor
├── strategy_id
├── version
└── config_fingerprint
```

This allows a parsed artifact to record which parser behavior produced it.

For example, the current implementations identify themselves as:

```text
markdown-structural@1.1.0
plain-text-structural@1.0.0
```

The Markdown parser explicitly attaches its descriptor information to the resulting `ParsedDocument`.

---

# Parser Responsibilities

A concrete parser is responsible for:

1. validating the supplied `IngestionSource`;
2. verifying that the parser supports its source type;
3. parsing the source format;
4. identifying source-backed structural segments;
5. preserving source ordering;
6. preserving exact source offsets;
7. attaching parser provenance;
8. returning a valid `ParsedDocument`.

It should **not** decide how those segments will eventually be chunked for retrieval.

---

# Parsed Artifact Boundary

The parser produces:

```text
IngestionSource
      │
      ▼
DocumentParser
      │
      ▼
ParsedDocument
├── version_id
├── source_type
├── segments
├── parser_strategy_id
├── parser_version
├── parser_config_fingerprint
└── metadata
```

The downstream normalizer consumes this artifact.

This creates a clean boundary:

```text
Parser
  │
  │ source-format understanding
  ▼
ParsedDocument
  │
  │ semantic canonicalization
  ▼
Normalizer
```

---

# 2. `markdown.py` — Markdown Structural Parser

`MarkdownStructuralParser` is the source-specific parser for:

```text
KnowledgeSourceType.MARKDOWN
```

Its current descriptor is:

```text
strategy_id = "markdown-structural"
version     = "1.1.0"
```

and it uses `markdown-it` with CommonMark behavior plus selected GitHub-style extensions.

---

## Purpose

The Markdown parser is **structure-preserving**.

It understands Markdown syntax and converts source-backed Markdown blocks into `ParsedSegment` objects while retaining the original Markdown source.

Its responsibilities include:

* recognizing heading hierarchy;
* preserving section paths;
* preserving source order;
* preserving exact source spans;
* exposing block-level metadata;
* preserving Markdown rather than rendering the entire document to plain text;
* attaching parser provenance.

---

# Markdown Parsing Engine

The parser uses `MarkdownIt` configured with:

```text
commonmark
html = enabled
breaks = disabled
typographer = disabled
```

and explicitly enables:

```text
table
strikethrough
```

This provides predictable CommonMark parsing while supporting common knowledge-base Markdown constructs.

---

# Structural Blocks

Internally, Markdown source is first represented as structural blocks:

```text
_StructuralBlock
├── start_line
├── end_line
├── section_path
└── block_type
```

These are parser-internal structures rather than final retrieval chunks.

The distinction is important:

```text
Markdown structural block
        ≠
Retrieval chunk
```

The block only describes what the parser found in the source.

---

# Heading Hierarchy

Markdown headings update the current section hierarchy.

For example:

```text
# Account
## Security
### Password Reset
```

produces a section path conceptually equivalent to:

```text
("Account", "Security", "Password Reset")
```

The parser does not require authors to use perfectly sequential heading levels.

For example:

```text
# Account
### Password Reset
```

is accepted, with the hierarchy representing the structure that actually exists rather than inventing a missing H2 section.

---

# Heading Representation

Headings update `section_path` rather than being blindly emitted as independent lexical segments.

This prevents the heading itself from becoming an isolated retrieval unit and allows downstream normalization/chunking to use the heading as structural context.

---

# Source Spans

`markdown-it` reports token locations as line ranges:

```text
[start_line, end_line)
```

The parser maintains a `_LineIndex` to convert those line ranges into exact character offsets in the original source.

```text
Markdown line range
        │
        ▼
_LineIndex
        │
        ▼
(start_offset, end_offset)
```

This allows the resulting `ParsedSegment` to satisfy the important invariant:

```text
source[start_offset:end_offset] == segment.text
```

The line index explicitly exists to bridge Markdown parser line numbers and the character-offset representation used by ingestion artifacts.

---

# Non-Overlapping Segments

Markdown parsers naturally expose nested/container tokens.

The implementation therefore:

1. extracts source-backed blocks;
2. converts line ranges into character spans;
3. trims surrounding whitespace;
4. removes duplicate/overlapping structural ranges;
5. produces non-overlapping `ParsedSegment` objects.

The implementation uses deterministic block priorities for cases where identical source spans are represented by multiple token types.

This ensures that a source region is not accidentally represented multiple times downstream.

---

# Block Metadata

Each Markdown `ParsedSegment` retains useful parser-level metadata such as:

```text
markdown_block_type
start_line
end_line
```

while also preserving:

```text
section_path
start_offset
end_offset
```

This provides both structural information and precise source provenance.

---

# Markdown Validation

Before parsing, the source is validated to ensure:

* it is an `IngestionSource`;
* its source type is supported;
* its content is not blank.

Unsupported types and invalid source content are translated into the ingestion error hierarchy.

If the underlying Markdown library fails, the failure is translated into `KnowledgeParserExecutionError` while preserving the original exception as the cause.

---

# 3. `plain_text.py` — Plain Text Structural Parser

`PlainTextStructuralParser` handles:

```text
KnowledgeSourceType.PLAIN_TEXT
```

Its descriptor is:

```text
strategy_id = "plain-text-structural"
version     = "1.0.0"
```

Unlike Markdown, plain text has no presentation syntax that needs to be interpreted.

The parser therefore focuses on identifying **paragraph-like structural blocks**.

---

# Plain Text Segmentation

Blank lines delimit structural segments.

```text
Paragraph one.

Paragraph two.

Paragraph three.
```

becomes conceptually:

```text
ParsedSegment 0
ParsedSegment 1
ParsedSegment 2
```

The parser walks the original content using `splitlines(keepends=True)` and maintains exact character offsets while detecting blank-line boundaries.

---

# Offset Preservation

For each segment:

```text
content[start_offset:end_offset] == segment.text
```

The parser trims surrounding whitespace from the segment while adjusting the offsets accordingly.

This means trimming does **not** destroy source provenance.

---

# Plain Text Responsibilities

The parser handles:

* source-type validation;
* blank-source rejection;
* paragraph-like structural segmentation;
* ordering;
* exact source offsets;
* parser provenance.

It intentionally does not handle:

* semantic normalization;
* retrieval chunking;
* token-budget splitting;
* embeddings;
* document classification.

---

# Plain Text Output

The resulting `ParsedDocument` retains:

```text
version_id
source_type
segments
parser_strategy_id
parser_version
parser_config_fingerprint
metadata
```

The parser rejects an input that produces no segments rather than returning an empty parsed artifact.

---

# 4. `resolver.py` — Parser Resolution

`DefaultDocumentParserResolver` is the composition-time registry for parsers.

Its job is simple:

```text
KnowledgeSourceType
        │
        ▼
DefaultDocumentParserResolver
        │
        ▼
DocumentParser
```

The resolver maps each supported source type to exactly one parser.

---

# Registration

Parsers are supplied when the resolver is constructed:

```text
DefaultDocumentParserResolver(parsers)
```

The registry is then built once.

Runtime mutation is intentionally unsupported because changing parser registration during ingestion could make behavior difficult to reproduce.

---

# Resolution

The resolver exposes:

```text
supported_source_types
supports(source_type)
resolve(source_type)
```

If a source type is not registered:

```text
UnsupportedKnowledgeSourceTypeError
```

is raised rather than silently selecting a fallback parser.

---

# Duplicate Registration

Each source type may have only one active parser.

For example:

```text
Parser A ──► MARKDOWN
Parser B ──► MARKDOWN
```

is rejected during registry construction.

This prevents ambiguous source-type routing.

---

# Parser Contract Validation

The resolver validates each parser before registering it.

It checks that:

* the parser satisfies the `DocumentParser` contract;
* its descriptor is a `ParserDescriptor`;
* `supported_source_types` is a `frozenset`;
* at least one source type is supported;
* each declared source type is a valid `KnowledgeSourceType`;
* `supports()` agrees with the declared capabilities.

This makes invalid parser configuration a **startup/composition-time failure** instead of a request-time surprise.

---

# Current Parser Mapping

The current parser implementations establish:

```text
MARKDOWN
    │
    ▼
MarkdownStructuralParser

PLAIN_TEXT
    │
    ▼
PlainTextStructuralParser
```

The resolver provides the abstraction that allows additional parsers to be introduced without changing the processing service.

---

# End-to-End Flow

The parser layer participates in the overall knowledge-processing pipeline as follows:

```text
Knowledge Version
       │
       ▼
   IngestionSource
       │
       ▼
Parser Resolver
       │
       ├───────────────┐
       │               │
       ▼               ▼
   Markdown        Plain Text
    Parser           Parser
       │               │
       └───────┬───────┘
               ▼
         ParsedDocument
               │
               ▼
       Normalization
               │
               ▼
          Chunking
               │
               ▼
          Embeddings
```

The processing service explicitly performs the stages in this order:

```text
parser → normalizer → chunker
```

and validates the resulting artifacts afterward.

---

# Provenance

Parser provenance is a first-class part of the parsed artifact.

```text
ParsedDocument
├── parser_strategy_id
├── parser_version
└── parser_config_fingerprint
```

This identity is later carried into normalized artifacts and ultimately used when recording processing metadata. The processing layer verifies that normalization preserves the parser provenance exactly.

This gives the ingestion pipeline a traceable transformation chain:

```text
Source
  │
  ▼
Parser
  │
  ├── strategy
  ├── version
  └── configuration
  │
  ▼
ParsedDocument
  │
  ▼
Normalizer
  │
  ▼
Chunker
```

---

# Error Handling

The parser implementations translate source/parser failures into the application's ingestion error hierarchy.

Typical categories include:

```text
InvalidKnowledgeSourceError
        │
        └── invalid/blank source

UnsupportedKnowledgeSourceTypeError
        │
        └── parser cannot handle requested source type

KnowledgeParserExecutionError
        │
        └── underlying parser/library failure

KnowledgeParserOutputError
        │
        └── parser completed but produced invalid/empty output

KnowledgeParserConfigurationError
        │
        └── invalid parser registration/configuration
```

The important architectural rule is that **provider/library-specific failures should not leak through the parser abstraction**.

For example, Markdown library failures are translated at the parser boundary while retaining the original exception as the cause.

---

# Important Invariants

## Source Type

A parser must only process source types it explicitly supports.

## Ordering

Parsed segments preserve source order.

## Provenance

Every source-backed segment retains its original location whenever the source format provides one.

## Non-Overlapping Markdown Segments

Markdown parsing removes duplicate/overlapping structural representations before creating `ParsedSegment` artifacts.

## Deterministic Resolution

A source type resolves to exactly one configured parser.

## No Runtime Registry Mutation

Parser selection is determined during application composition.

## Parser/Normalizer Separation

The parser understands source syntax; normalization creates the canonical semantic representation.

## Parser/Chunker Separation

A parsed segment is not a retrieval chunk.

---

# Adding a New Parser

A new source parser should follow the existing architecture.

For example:

```text
DocumentParser
      │
      ├── MarkdownStructuralParser
      ├── PlainTextStructuralParser
      └── FutureFormatParser
```

A new implementation should:

1. implement the parser contract;
2. expose a stable `ParserDescriptor`;
3. declare its supported `KnowledgeSourceType`;
4. validate incoming `IngestionSource`;
5. produce valid `ParsedDocument` artifacts;
6. preserve source ordering;
7. preserve provenance/offsets where available;
8. translate implementation failures into ingestion exceptions;
9. register the parser through the resolver.

The resolver will then validate the new implementation and reject conflicting source-type registrations.

---

# Testing Strategy

The parser package should be tested at three levels.

## Contract Tests

Verify:

* descriptor validity;
* supported source types;
* `supports()` consistency;
* valid `ParsedDocument` output;
* provenance propagation.

## Markdown Tests

Cover:

* headings;
* nested heading hierarchies;
* skipped heading levels;
* paragraphs;
* fenced code;
* indented code;
* tables;
* blockquotes;
* lists;
* HTML blocks;
* inline formatting;
* exact source offsets;
* overlapping/nested Markdown tokens;
* blank documents;
* malformed parser output.

## Plain Text Tests

Cover:

* single paragraph;
* multiple paragraphs;
* consecutive blank lines;
* leading/trailing whitespace;
* CRLF/CR/LF inputs;
* final paragraph without trailing newline;
* exact offsets;
* blank input;
* unsupported source types.

## Resolver Tests

Cover:

* valid registration;
* source-type resolution;
* unsupported source types;
* duplicate parser registration;
* invalid parser contracts;
* invalid source-type declarations;
* inconsistent `supports()` behavior;
* immutable registry behavior.

---

# Design Principles

### Structural First

The parser extracts source structure; it does not attempt to solve downstream retrieval problems.

### Exact Provenance

Source offsets and structural metadata are preserved whenever possible.

### Format-Specific Logic Stays Local

Markdown-specific behavior belongs in `markdown.py`; plain-text behavior belongs in `plain_text.py`.

### Stable Contracts

Downstream layers consume `ParsedDocument`, not parser-specific objects.

### Deterministic Composition

The resolver establishes a stable source-type → parser mapping.

### Fail Fast

Invalid parser registration is rejected during resolver construction.

### No Provider Coupling

The parser layer has no dependency on embedding providers, vector stores, rerankers, or LLMs.

---

# Summary

`packages/knowledge/ingestion/parser/` is the **source-format interpretation boundary** of the knowledge ingestion system.

The four files divide responsibilities cleanly:

```text
base.py
    │
    └── Parser contract + parser identity

markdown.py
    │
    └── Markdown → source-backed structural segments

plain_text.py
    │
    └── Plain text → paragraph-like structural segments

resolver.py
    │
    └── KnowledgeSourceType → configured parser
```

The resulting pipeline is:

```text
                 IngestionSource
                       │
                       ▼
              Parser Resolver
                       │
              ┌────────┴────────┐
              ▼                 ▼
          Markdown          Plain Text
           Parser              Parser
              │                 │
              └────────┬────────┘
                       ▼
                ParsedDocument
                       │
                       ▼
                 Normalization
                       │
                       ▼
                    Chunking
                       │
                       ▼
                  Embeddings
```

The central design principle is that **parsers understand source syntax and preserve structural provenance, while leaving semantic normalization, retrieval chunking, and embedding concerns to the subsequent ingestion stages**.
