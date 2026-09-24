# Knowledge Retrieval

## Overview

The `packages/knowledge/retrieval/` package is the **core retrieval and grounding subsystem** of the knowledge layer.

It transforms a canonical customer-support retrieval request into a bounded, provenance-preserving grounding context suitable for downstream AI answer generation.

The subsystem separates:

* query preparation;
* semantic/vector retrieval;
* lexical retrieval;
* ranking fusion;
* optional reranking;
* retrieval result modeling;
* grounding-context construction;
* retrieval configuration;
* domain-specific error handling;
* and application-level orchestration.

The overall architecture is intentionally modular so that individual retrieval technologies can be replaced without changing the rest of the pipeline.

---

# Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── knowledge/
        └── retrieval/
            ├── README.md
            ├── errors.py
            ├── models.py
            ├── profiles.py
            │
            ├── query/
            │   ├── README.md
            │   └── ...
            │
            ├── vector/
            │   ├── README.md
            │   └── ...
            │
            ├── lexical/
            │   ├── README.md
            │   └── ...
            │
            ├── fusion/
            │   ├── README.md
            │   └── ...
            │
            ├── reranking/
            │   ├── README.md
            │   └── ...
            │
            ├── context/
            │   ├── README.md
            │   └── ...
            │
            ├── application/
            │   ├── README.md
            │   └── ...
            │
            └── ...
```

The exact implementation may contain additional modules/subpackages, but the architecture is organized around these major responsibilities.

---

# Architectural Role

The retrieval package sits between the knowledge/application layer and the downstream grounded-generation workflow.

```text
AI / Application Layer
          │
          ▼
RetrievalQueryContext
          │
          ▼
┌──────────────────────────────┐
│       Query Preparation      │
│                              │
│ semantic query               │
│ lexical queries              │
└──────────────┬───────────────┘
               │
        PreparedRetrievalQuery
               │
       ┌───────┴────────┐
       │                │
       ▼                ▼
 Vector Retrieval   Lexical Retrieval
       │                │
       └───────┬────────┘
               ▼
             Fusion
               │
               ▼
          Reranking
          (optional)
               │
               ▼
      Final Candidate Limit
               │
               ▼
       RetrievalResult
               │
               ▼
   Grounding Context Builder
               │
               ▼
      GroundingContext
               │
               ▼
    Downstream AI Generation
```

The application layer is responsible for orchestrating this pipeline, while the individual retrieval packages implement their respective technical concerns.

---

# Core Responsibility

The subsystem answers a fundamental question:

> **Given a customer-support query and trusted retrieval scope, which knowledge chunks should be supplied as evidence to the AI system?**

It does **not** directly generate the final customer-facing answer.

Instead, it produces progressively refined representations:

```text
Customer request
      │
      ▼
RetrievalQueryContext
      │
      ▼
PreparedRetrievalQuery
      │
      ▼
retrieval candidates
      │
      ▼
fused / optionally reranked candidates
      │
      ▼
RetrievalResult
      │
      ▼
GroundingContext
```

This separation keeps retrieval and answer generation independently replaceable.

---

# Main Subsystems

## Query Preparation

`query/` is responsible for transforming the canonical retrieval context into representations appropriate for different retrieval mechanisms.

```text
RetrievalQueryContext
        │
        ▼
RetrievalQueryPreparationService
        │
        ▼
PreparedRetrievalQuery
        ├── semantic_query
        └── lexical_queries
```

Semantic and lexical retrieval deliberately receive different representations.

The query layer does not execute retrieval itself. It performs deterministic, bounded query transformation and maintains the distinction between semantic hints and trusted retrieval scope.

---

## Vector Retrieval

`vector/` implements semantic retrieval.

Its primary separation is:

```text
VectorRetrievalService
        │
        ├── EmbeddingProvider
        │
        └── VectorRetrievalRepository
```

The service generates the query embedding and validates its dimensional compatibility.

The repository performs the actual persisted vector search.

```text
semantic_query
      │
      ▼
EmbeddingProvider
      │
      ▼
EmbeddingVector
      │
      ▼
VectorSearchRequest
      │
      ▼
VectorRetrievalRepository
      │
      ▼
VectorSearchMatch[]
      │
      ▼
RetrievalCandidate[]
```

The repository does not generate embeddings, perform fusion, rerank results, or construct grounding context.

---

## Lexical Retrieval

The lexical branch consumes the prepared lexical representation and performs traditional/full-text retrieval.

Its results enter the same common `RetrievalCandidate` model used by vector retrieval.

Conceptually:

```text
lexical_queries
      │
      ▼
Lexical Retrieval
      │
      ▼
Lexical candidates
      │
      ▼
    Fusion
```

The application orchestration keeps the semantic and lexical branches independent until ranking fusion. The vector branch receives `semantic_query`, while lexical retrieval receives the prepared lexical query representation.

---

# Retrieval Models

`models.py` contains the canonical domain models shared across retrieval stages.

Important concepts include:

```text
RetrievalMethod
RetrievalFilters
RetrievalQuery
RetrievalScores
RetrievalCandidate
RetrievalResult
```

These models establish a common language between otherwise different retrieval mechanisms.

---

## `RetrievalMethod`

The retrieval subsystem recognizes:

```text
VECTOR
LEXICAL
HYBRID
```

`VECTOR` and `LEXICAL` represent individual retrieval mechanisms.

`HYBRID` is reserved for results produced by combining multiple retrieval mechanisms rather than by a persistence backend directly.

---

## `RetrievalQuery`

`RetrievalQuery` is the canonical query entering the retrieval subsystem.

```text
RetrievalQuery
├── text
└── filters
```

The query text is normalized and cannot be blank.

The associated `RetrievalFilters` represent trusted business-level retrieval constraints.

---

## `RetrievalFilters`

Filters can constrain retrieval using values such as:

```text
content_types
visibilities
document_ids
metadata
```

They are normalized and immutable.

Importantly, lifecycle invariants such as active documents and published versions are **system-enforced retrieval invariants**, rather than arbitrary caller-controlled filters.

---

# Candidate Model

All retrieval mechanisms ultimately converge on:

```text
RetrievalCandidate
```

This gives vector, lexical, fusion, and reranking stages a common representation.

A candidate contains enough information for:

* ranking;
* provenance;
* grounding;
* observability;
* debugging;
* source attribution.

The candidate therefore carries knowledge identity and content rather than requiring downstream layers to perform another database lookup.

---

# Retrieval Scores

`RetrievalScores` deliberately keeps different ranking signals separate:

```text
RetrievalScores
├── vector_distance
├── vector_similarity
├── lexical_score
├── fusion_score
└── reranker_score
```

These values are **not assumed to share the same scale or semantics**.

For example:

```text
vector_distance   → lower is better
vector_similarity → higher is better
lexical_score     → higher is better
fusion_score      → higher is better
reranker_score    → higher is better
```

This separation allows each retrieval stage to contribute evidence without incorrectly treating unrelated scores as directly comparable.

---

# Retrieval Profile

`profiles.py` defines the configuration governing one retrieval execution.

The `RetrievalProfile` controls:

```text
vector_enabled
lexical_enabled
reranking_enabled
```

as well as:

```text
vector_candidate_limit
lexical_candidate_limit
fused_candidate_limit
final_candidate_limit
rrf_k
```

The profile therefore describes **retrieval behavior**, while provider and persistence configuration remain outside the profile.

---

# Default Retrieval Configuration

The default customer-support profile is:

```text
vector retrieval      = enabled
lexical retrieval     = enabled
reranking             = disabled
vector candidates     = 20
lexical candidates    = 20
fused candidates      = 20
final candidates      = 8
RRF k                  = 60
```

The default profile therefore represents a **hybrid vector + lexical retrieval pipeline**, with reranking infrastructure available but not enabled by default.

---

# Profile Validation

The profile enforces several configuration invariants.

At least one retrieval mechanism must be enabled.

```text
vector_enabled == False
AND
lexical_enabled == False
        │
        ▼
     invalid
```

Candidate limits must be positive integers.

The fused candidate limit cannot exceed the maximum number of candidates available from the enabled retrieval branches.

The final candidate limit cannot exceed the fused candidate limit.

---

# Profile Identity and Reproducibility

A retrieval profile exposes a stable:

```text
config_fingerprint
```

generated from its behavior-affecting configuration.

It also exposes:

```text
identity
```

combining the profile ID and fingerprint.

This provides a stable representation useful for:

* telemetry;
* debugging;
* reproducibility;
* comparing retrieval configurations.

---

# Retrieval Fusion

The `fusion/` package combines independently ranked retrieval results into one unified ranking.

```text
Vector candidates ─────┐
                       │
Lexical candidates ────┼──► Fusion ──► Unified ranking
                       │
Other rankings ────────┘
```

Fusion exists because vector and lexical retrieval produce ranking signals with different semantics and potentially different scales.

The fusion layer therefore operates on **rankings**, rather than assuming that raw retrieval scores are directly comparable.

---

# Fusion Abstraction

The package defines a provider-neutral:

```text
RetrievalFusionStrategy
```

with a stable contract.

The current implementation includes:

```text
ReciprocalRankFusion
```

while leaving room for future fusion strategies.

```text
RetrievalFusionStrategy
        │
        ├── ReciprocalRankFusion
        │
        └── future strategies
```

Fusion itself does not perform retrieval, embeddings, reranking, or context construction.

---

# Reranking

The `reranking/` package provides the second-stage ranking boundary.

Its position is:

```text
Vector Retrieval
      +
Lexical Retrieval
      │
      ▼
    Fusion
      │
      ▼
  Reranking
      │
      ▼
Grounding Context
```

The architecture supports external APIs, local cross-encoders, learned ranking models, or deterministic implementations.

### Current state

**A real learned/provider-based reranker is not currently active.**

The current implementation is:

```text
PassthroughReranker
```

which preserves the fused ordering and applies the requested limit without model inference or an external API call.

The architecture is prepared for a future implementation such as Jina or another reranking provider.

---

# Reranking Trust Boundary

A particularly important design rule is:

> **Reranking can change relevance ordering, but it does not become the source of truth for knowledge content.**

A reranker returns ranking information such as:

```text
chunk_id
score
```

The retrieval service then maps those results back onto the original trusted candidates.

```text
Trusted candidates
       │
       ▼
    Reranker
       │
       ▼
 chunk IDs + scores
       │
       ▼
Validate against trusted candidates
       │
       ▼
Updated ordering
```

This prevents an external ranking provider from injecting arbitrary knowledge into the grounding pipeline.

---

# Retrieval Application Layer

The `application/` package is the orchestration layer above the individual retrieval mechanisms.

It contains two major application services:

```text
retrieve_knowledge.py
build_grounding_context.py
```

Their responsibilities are deliberately separated.

---

## `RetrieveKnowledge`

`RetrieveKnowledge` coordinates:

```text
Vector Retrieval
       +
Lexical Retrieval
       ↓
Fusion
       ↓
Optional Reranking
       ↓
Final Candidate Limit
       ↓
RetrievalResult
```

It does not implement the retrieval algorithms itself.

Instead, it coordinates the configured components through their contracts.

---

## `BuildGroundingContext`

`BuildGroundingContext` takes the retrieval result and converts it into bounded grounding context.

```text
RetrievalResult
       │
       ▼
GroundingContextBuilder
       │
       ├── selection
       ├── deduplication
       ├── redundancy suppression
       ├── document limits
       ├── block limits
       └── token budget
       │
       ▼
GroundingContext
```

This separates **finding knowledge** from **deciding what knowledge can safely fit into the model context**.

---

# Retrieval Context

The `context/` package is the trusted grounding-context layer.

Its purpose is to transform ranked candidates into a:

* bounded;
* deduplicated;
* redundancy-controlled;
* provenance-preserving

`GroundingContext`.

---

# Context Construction

The context builder treats candidate ordering as authoritative relevance ordering.

It:

1. preserves retrieval order;
2. removes duplicate chunk IDs;
3. suppresses redundant overlapping chunks;
4. enforces per-document limits;
5. enforces total block limits;
6. enforces token budgets;
7. preserves canonical chunk content and provenance.

Candidate text is included as a whole or excluded as a whole, maintaining a direct relationship between grounding content and the persisted knowledge chunk.

---

# Grounding Context Budget

The grounding layer operates under an explicit `GroundingContextBudget`.

This prevents retrieval from producing an unbounded prompt payload.

The budget controls the final amount of evidence that can reach grounded generation.

The result explicitly records whether candidates were excluded because of budget constraints.

---

# End-to-End Retrieval Pipeline

The complete subsystem can be understood as:

```text
                         RetrievalQueryContext
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ Query Preparation│
                         └────────┬────────┘
                                  │
                         PreparedRetrievalQuery
                                  │
                   ┌──────────────┴──────────────┐
                   │                             │
                   ▼                             ▼
             semantic_query                lexical_queries
                   │                             │
                   ▼                             ▼
          VectorRetrievalService        LexicalRetrievalService
                   │                             │
                   └──────────────┬──────────────┘
                                  │
                                  ▼
                         Retrieval Rankings
                                  │
                                  ▼
                         Fusion Strategy
                                  │
                                  ▼
                           Fused Candidates
                                  │
                                  ▼
                         Optional Reranking
                                  │
                                  ▼
                       Final Candidate Limit
                                  │
                                  ▼
                         RetrievalResult
                                  │
                                  ▼
                    GroundingContextBuilder
                                  │
                                  ▼
                         GroundingContext
                                  │
                                  ▼
                       Grounded AI Generation
```

The retrieval application layer explicitly implements this orchestration model.

---

# Query Representation Flow

A key architectural detail is that each retrieval branch receives the representation appropriate for it.

```text
PreparedRetrievalQuery
       │
       ├───────────────► semantic_query ──► Vector Retrieval
       │
       └───────────────► lexical_queries ─► Lexical Retrieval
```

Meanwhile, the original canonical query remains associated with the retrieval result for:

* fusion;
* reranking;
* provenance;
* query identity.

---

# Canonical Candidate Flow

Regardless of how a candidate was found, the system converges on the common candidate model:

```text
Vector Candidate ─────┐
                      │
Lexical Candidate ────┼──► Fusion
                      │      │
Other Candidate ──────┘      │
                             │
                             ▼
                     RetrievalCandidate
                             │
                             ▼
                         Reranking
                             │
                             ▼
                      RetrievalResult
```

This is what allows the retrieval pipeline to remain independent of individual retrieval technologies.

---

# Trust Boundaries

The retrieval subsystem has several deliberate trust boundaries.

## AI Semantic Hints vs Trusted Scope

AI/customer-derived entities are semantic hints.

They are not automatically converted into authorization or hard database filters.

Only trusted `RetrievalFilters` represent hard retrieval scope.

This distinction is maintained from the application layer through query preparation and retrieval.

---

## Retrieval Provider vs Knowledge Truth

Retrieval mechanisms identify candidates.

They do not redefine knowledge content.

The candidate's canonical content and provenance remain authoritative.

---

## Reranker vs Candidate Data

A reranker can change ranking but cannot introduce arbitrary knowledge.

---

## Retrieval vs Grounding

Retrieval determines which candidates are relevant.

Context construction determines which of those candidates can actually fit within the grounding budget.

---

# Error Architecture

`errors.py` provides the retrieval subsystem's domain-specific error boundary.

Errors are kept semantically distinct rather than being collapsed into a generic exception.

Conceptually:

```text
RetrievalError
├── query preparation failures
├── vector retrieval failures
├── lexical retrieval failures
├── fusion failures
├── reranking failures
├── grounding/context failures
└── pipeline/application failures
```

Individual subpackages can therefore preserve their own detailed failure semantics while higher layers receive stable retrieval-domain errors.

The query subsystem follows the same principle: expected failures derive from a dedicated retrieval-query preparation error hierarchy, while unexpected implementation failures are translated at the service boundary.

---

# No Silent Degradation

A central retrieval invariant is:

> **An enabled retrieval stage must work when the profile says it is enabled.**

For example:

```text
vector_enabled = true
vector_service = missing
        │
        ▼
fail fast
```

The application layer does not silently convert this into lexical-only retrieval.

This prevents apparently successful but incomplete retrieval results.

---

# Fusion Is Always Applied

The application orchestration always passes the available rankings through the configured fusion strategy.

This provides consistent result semantics even when only a single retrieval ranking is available.

Therefore:

```text
Vector only
     │
     ▼
   Fusion
     │
     ▼
   Result
```

and:

```text
Vector + Lexical
       │
       ▼
     Fusion
       │
       ▼
     Result
```

follow the same high-level contract.

---

# Final Candidate Bound

The retrieval profile controls the final candidate count.

The application layer applies:

```text
final_candidate_limit
```

after fusion/reranking as appropriate.

This ensures that downstream context construction does not receive an unexpectedly large candidate set.

---

# Query Integrity

The original query remains the canonical retrieval identity throughout the pipeline.

This is important because intermediate representations may differ:

```text
Original Query
      │
      ├── semantic representation
      └── lexical representation
```

The transformed representations are retrieval-specific, but the canonical query is retained for:

* fusion;
* reranking;
* result identity;
* grounding;
* telemetry;
* debugging.

The grounding application service also verifies that the grounding context corresponds to the retrieval query.

---

# Observability

Retrieval is designed to be observable without allowing telemetry to control business behavior.

Relevant stages can record:

* retrieval execution;
* candidate counts;
* fusion/reranking behavior;
* grounding construction;
* failures;
* timing;
* configuration identity.

However:

> **Telemetry failures must not replace or suppress the underlying retrieval or grounding exception semantics.**

This keeps observability secondary to correctness.

---

# Provider Neutrality

The retrieval subsystem intentionally avoids hard-coding specific external providers into its core contracts.

Examples include:

```text
EmbeddingProvider
VectorRetrievalRepository
RetrievalFusionStrategy
Reranker
TokenEstimator
```

This means provider-specific implementations can be replaced without redesigning the retrieval pipeline.

For example:

```text
Embedding Provider
       │
       ├── Provider A
       ├── Provider B
       └── future provider

Reranker
       │
       ├── Passthrough
       ├── future Jina implementation
       └── future local model
```

The application layer interacts with contracts rather than implementations.

---

# Current Reranking Status

The retrieval architecture includes a complete reranking boundary, but the default profile currently has:

```text
reranking_enabled = false
```

and the available fallback implementation is:

```text
PassthroughReranker
```

Therefore the current default path is effectively:

```text
Vector Retrieval
      +
Lexical Retrieval
      │
      ▼
     RRF
      │
      ▼
Final Candidate Limit
      │
      ▼
Grounding Context
```

A real learned reranker can later be introduced behind the existing abstraction without redesigning the retrieval pipeline.

---

# Design Principles

## Separation of Concerns

Each stage has one primary responsibility:

```text
Query       → prepare representations
Vector      → semantic retrieval
Lexical     → lexical retrieval
Fusion      → combine rankings
Reranking   → second-stage ordering
Context     → bounded grounding selection
Application → orchestration
```

---

## Immutable Contracts

Core retrieval objects are immutable.

This provides:

* predictable equality;
* safer cross-layer handoff;
* reduced accidental mutation;
* easier testing;
* reproducible retrieval behavior.

---

## Deterministic Preparation

Equivalent inputs and configuration should produce equivalent prepared-query representations.

---

## Bounded Processing

Limits exist at multiple stages:

```text
vector candidate limit
        ↓
lexical candidate limit
        ↓
fused candidate limit
        ↓
final candidate limit
        ↓
grounding block/token budget
```

This prevents uncontrolled retrieval growth and protects downstream context size.

---

## No Silent Degradation

Configured retrieval failures remain visible.

The system should not quietly return partial results while making them appear complete.

---

## Provenance Preservation

Knowledge candidates and grounding blocks retain enough source information to support:

* source attribution;
* debugging;
* auditing;
* reproducibility.

---

## Provider Neutrality

Retrieval behavior depends on stable interfaces rather than specific database, embedding, search, or reranking providers.

---

## Retrieval and Generation Are Separate

The retrieval subsystem produces **evidence**.

The AI generation layer decides how to use that evidence to produce the final response.

---

# Testing Strategy

Testing should exist at several levels.

## Model Tests

Validate:

* normalization;
* immutability;
* invalid identifiers;
* invalid filters;
* score validity;
* candidate invariants;
* profile constraints.

## Query Tests

Validate:

* deterministic query preparation;
* semantic representation;
* lexical query generation;
* bounded expansion;
* deduplication;
* error translation.

## Retrieval Tests

Validate:

* vector retrieval;
* lexical retrieval;
* hybrid retrieval;
* empty results;
* candidate limits;
* provider errors;
* repository errors.

## Fusion Tests

Validate:

* single-ranking fusion;
* hybrid fusion;
* candidate deduplication;
* deterministic ordering;
* RRF scoring.

## Reranking Tests

Validate:

* passthrough behavior;
* resolver behavior;
* response validation;
* candidate membership;
* ordering;
* score propagation;
* instrumentation.

## Context Tests

Validate:

* duplicate removal;
* redundancy suppression;
* per-document limits;
* block limits;
* token limits;
* truncation reporting;
* provenance preservation.

## Application Tests

The orchestration layer should test:

* vector-only retrieval;
* lexical-only retrieval;
* hybrid retrieval;
* reranking invocation;
* final candidate limits;
* missing enabled dependencies;
* query mismatch;
* telemetry;
* lower-layer failure propagation.

These application-level scenarios are explicitly identified as important test cases for the retrieval services.

---

# Architectural Invariants

The retrieval subsystem should preserve the following invariants.

### 1. At least one retrieval mechanism is enabled

A profile cannot represent an empty retrieval pipeline.

### 2. Enabled stages have implementations

Configuration and composition must agree.

### 3. Semantic and lexical representations remain separate

Vector retrieval receives semantic representation; lexical retrieval receives lexical representation.

### 4. Original query identity is preserved

Intermediate transformations never replace the canonical query.

### 5. Retrieval candidates remain provenance-aware

A candidate contains enough information to support downstream grounding and attribution.

### 6. Ranking signals remain semantically distinct

Vector, lexical, fusion, and reranker scores are not blindly merged.

### 7. Fusion happens before optional reranking

Reranking is a second-stage operation over already unified candidates.

### 8. Rerankers cannot introduce knowledge

They may reorder trusted candidates but cannot become a source of knowledge content.

### 9. Grounding is bounded

The final context is subject to explicit block and token constraints.

### 10. Retrieval failures are not silently swallowed

Enabled-stage failures remain visible.

### 11. Telemetry does not change business semantics

Observability must not hide or replace actual retrieval/context failures.

---

# Complete Responsibility Map

```text
packages/knowledge/retrieval/
│
├── models.py
│   └── Canonical retrieval domain models
│
├── profiles.py
│   └── Retrieval behavior/configuration
│
├── errors.py
│   └── Retrieval-domain error taxonomy
│
├── query/
│   └── Query preparation
│       ├── semantic representation
│       └── lexical representation
│
├── vector/
│   └── Semantic/vector retrieval
│       ├── embedding
│       └── vector persistence search
│
├── lexical/
│   └── Lexical/full-text retrieval
│
├── fusion/
│   └── Ranking aggregation
│       └── Reciprocal Rank Fusion
│
├── reranking/
│   └── Second-stage ranking
│       └── currently passthrough
│
├── context/
│   └── Grounding-context construction
│       ├── deduplication
│       ├── redundancy suppression
│       └── budget enforcement
│
└── application/
    └── End-to-end retrieval orchestration
```

---

# End-to-End Responsibility Boundary

The most important distinction in the package is:

```text
                    RETRIEVAL
                       │
                       ▼
             "What knowledge is
                relevant?"
                       │
                       ▼
            RetrievalCandidate[]
                       │
                       ▼
                     FUSION
                       │
                       ▼
                   RERANKING
                       │
                       ▼
                   RETRIEVAL
                     RESULT
                       │
                       ▼
                    CONTEXT
                       │
                       ▼
             "What relevant knowledge
                fits safely into the
                 grounding budget?"
                       │
                       ▼
                GroundingContext
                       │
                       ▼
                   GENERATION
                       │
                       ▼
                Customer Answer
```

Retrieval and context construction therefore remain distinct concerns.

---

# Summary

`packages/knowledge/retrieval/` is the **complete retrieval-to-grounding subsystem** for the customer-support RAG architecture.

Its major pipeline is:

```text
RetrievalQueryContext
        │
        ▼
Query Preparation
        │
        ▼
PreparedRetrievalQuery
        │
   ┌────┴────┐
   ▼         ▼
 Vector    Lexical
   │         │
   └────┬────┘
        ▼
      Fusion
        │
        ▼
   Reranking
   (optional)
        │
        ▼
 Final Candidates
        │
        ▼
 RetrievalResult
        │
        ▼
Grounding Context
        │
        ▼
  AI Generation
```

The subsystem is deliberately built around **immutable contracts, explicit trust boundaries, replaceable retrieval strategies, bounded processing, provenance preservation, provider neutrality, and fail-fast behavior**.

At the current stage, the default customer-support profile uses **hybrid vector + lexical retrieval with Reciprocal Rank Fusion**, while the reranking boundary is implemented but **real learned/provider-based reranking is not yet active**.

The resulting architecture keeps every major retrieval concern independently replaceable while providing the AI layer with a single, structured, bounded, and provenance-preserving grounding representation.
