# Retrieval Application Layer

## Overview

The `packages/knowledge/retrieval/application/` package contains the application-level orchestration for the knowledge retrieval pipeline.

It provides the boundary between:

* prepared retrieval queries;
* vector and lexical retrieval;
* ranking fusion;
* optional reranking;
* retrieval telemetry;
* grounding-context construction;
* context budgeting;
* and the final structured context consumed by downstream AI workflows.

The package contains two application services:

```text
packages/knowledge/retrieval/application/
│
├── retrieve_knowledge.py
└── build_grounding_context.py
```

Their responsibilities are deliberately separated:

```text
PreparedRetrievalQuery
        │
        ▼
┌────────────────────────┐
│    RetrieveKnowledge   │
│                        │
│ Vector Retrieval       │
│ Lexical Retrieval      │
│ Fusion                 │
│ Reranking              │
│ Final Candidate Limit  │
└────────────┬───────────┘
             │
             ▼
       RetrievalResult
             │
             ▼
┌────────────────────────────┐
│   BuildGroundingContext    │
│                            │
│ Context Selection          │
│ Context Budgeting          │
│ Query Integrity            │
│ Retrieval Telemetry        │
└────────────┬───────────────┘
             │
             ▼
       GroundingContext
```

The package therefore represents the **application orchestration layer of retrieval**, rather than the implementation of individual retrieval technologies.

---

# Responsibilities

| File                         | Responsibility                                                                                                        |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `retrieve_knowledge.py`      | Orchestrates configured vector/lexical retrieval, ranking fusion, optional reranking, limits, and retrieval telemetry |
| `build_grounding_context.py` | Runs retrieval and converts the resulting candidates into bounded, trusted grounding context                          |

The two services form a sequential application workflow:

```text
PreparedRetrievalQuery
        │
        ▼
RetrieveKnowledge
        │
        ▼
RetrievalResult
        │
        ▼
GroundingContextBuilder
        │
        ▼
GroundingContext
```

---

# Architectural Position

The package sits above the concrete retrieval implementations.

```text
                         AI / Application
                               │
                               ▼
                    PreparedRetrievalQuery
                               │
                               ▼
              ┌─────────────────────────────┐
              │ Retrieval Application Layer │
              │                             │
              │ RetrieveKnowledge           │
              │ BuildGroundingContext       │
              └─────────────┬───────────────┘
                            │
            ┌───────────────┼────────────────┐
            │               │                │
            ▼               ▼                ▼
        Vector          Lexical           Reranking
       Retrieval       Retrieval           Service
            │               │                │
            └───────────────┼────────────────┘
                            ▼
                         Fusion
                            │
                            ▼
                    RetrievalResult
                            │
                            ▼
                  Grounding Context
```

The application layer decides **how the retrieval components are composed**.

The lower-level retrieval services remain responsible for their own infrastructure-specific behavior.

---

# `retrieve_knowledge.py`

## Purpose

`RetrieveKnowledge` is the main retrieval orchestration service.

Its job is to execute the retrieval stages enabled by a `RetrievalProfile` and return a canonical `RetrievalResult`.

The service coordinates:

* vector retrieval;
* lexical retrieval;
* ranking fusion;
* optional reranking;
* candidate limits;
* retrieval telemetry.

It does not implement vector search, lexical search, fusion algorithms, or reranking itself.

Instead, those capabilities are injected as dependencies.

---

# Retrieval Pipeline

The overall retrieval flow is:

```text
PreparedRetrievalQuery
          │
          ├──────────────────────────────┐
          │                              │
          ▼                              ▼
    Semantic Query                  Lexical Query
          │                              │
          ▼                              ▼
   Vector Retrieval              Lexical Retrieval
          │                              │
          └──────────────┬───────────────┘
                         ▼
                  Candidate Rankings
                         │
                         ▼
                  Fusion Strategy
                         │
                         ▼
                 Fused Candidates
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
```

The service supports both single-source and hybrid retrieval.

---

# Retrieval Profile

The `RetrievalProfile` determines which stages are active.

The profile controls whether:

```text
Vector retrieval
Lexical retrieval
Reranking
```

are enabled and provides candidate limits for each stage.

Relevant limits include:

```text
vector_candidate_limit
lexical_candidate_limit
fused_candidate_limit
final_candidate_limit
```

This keeps retrieval policy outside the orchestration implementation.

The application service simply follows the supplied profile.

---

# Vector Retrieval

When vector retrieval is enabled, `RetrieveKnowledge` requires a configured `VectorRetrievalService`.

The prepared query's semantic representation is converted into a `RetrievalQuery`:

```text
PreparedRetrievalQuery
        │
        ▼
semantic_query
        │
        ▼
RetrievalQuery
        │
        ▼
VectorRetrievalService.search()
```

The configured vector candidate limit is applied during the search.

The resulting candidates become one of the rankings supplied to the fusion stage.

If vector retrieval is enabled but no vector service is configured, the application fails fast with `RetrievalPipelineError`.

This is treated as a composition/configuration problem rather than something to silently recover from.

---

# Lexical Retrieval

When lexical retrieval is enabled, the service uses the prepared lexical query.

The current implementation uses the first lexical query:

```text
PreparedRetrievalQuery
        │
        ▼
lexical_queries[0]
        │
        ▼
RetrievalQuery
        │
        ▼
LexicalRetrievalService.search()
```

The configured lexical candidate limit is applied.

As with vector retrieval, an enabled lexical stage without its required service is considered invalid application composition.

---

# Hybrid Retrieval

When both vector and lexical retrieval are enabled, the service collects both rankings:

```text
                 Prepared Query
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
       Vector                  Lexical
       Ranking                Ranking
          │                       │
          └───────────┬───────────┘
                      ▼
                  Fusion
```

The application layer does not assume that one branch is authoritative.

Instead, both rankings are passed to the configured `RetrievalFusionStrategy`.

---

# Fusion

All retrieved rankings are passed through the configured fusion strategy.

This includes the case where only one retrieval branch is active.

```text
rankings
   │
   ▼
FusionInput
   │
   ▼
RetrievalFusionStrategy
   │
   ▼
Fused Candidates
```

Passing even a single ranking through fusion ensures consistent:

* scoring;
* provenance;
* result semantics;
* candidate handling.

The service also verifies that the fusion strategy returns a result associated with the same canonical query.

A query mismatch results in `RetrievalPipelineError`.

---

# Reranking

Reranking is optional and controlled by the retrieval profile.

When enabled:

```text
Fused Candidates
       │
       ▼
RerankingService
       │
       ▼
Reranked Candidates
```

The reranker receives:

* the canonical query;
* the fused candidates;
* the configured final candidate limit.

If reranking is enabled but the corresponding service is missing, the application fails fast.

---

# Final Candidate Limit

After optional reranking, candidates are truncated to:

```text
profile.final_candidate_limit
```

The returned `RetrievalResult` therefore contains only the final application-approved candidate set.

```text
Vector / Lexical
       │
       ▼
Fusion
       │
       ▼
Reranking
       │
       ▼
Final Candidate Limit
       │
       ▼
RetrievalResult
```

---

# Empty Retrieval

If no enabled retrieval branch returns candidates, the service returns an empty `RetrievalResult`.

Conceptually:

```text
No vector candidates
        +
No lexical candidates
        │
        ▼
Empty rankings
        │
        ▼
RetrievalResult(candidates=())
```

The telemetry recorder is informed of the final empty candidate set when configured.

The service does not treat zero results as an exception.

---

# Failure Semantics

An important design principle is that retrieval failures are **not silently converted into partial retrieval**.

For example, if both vector and lexical retrieval are enabled and the vector branch fails, the service does not automatically pretend that the system was configured for lexical-only retrieval.

Known typed failures from lower layers are allowed to propagate.

This preserves failure visibility and prevents silently degraded retrieval quality.

```text
Hybrid Retrieval
      │
      ├── Vector fails
      │
      └── Lexical succeeds
               │
               ▼
        Do NOT silently
        return lexical-only
```

This is particularly important because downstream AI generation could otherwise treat incomplete retrieval as authoritative.

---

# Dependency Validation

`RetrieveKnowledge` validates its dependencies during construction.

The following relationships are enforced:

```text
vector_enabled  → vector_service required
lexical_enabled → lexical_service required
reranking_enabled → reranking_service required
```

This means configuration errors are detected during composition rather than much later during a customer request.

```text
Application Startup / Composition
            │
            ▼
       Validate Profile
            │
      ┌─────┼─────┐
      ▼     ▼     ▼
   Vector Lexical Rerank
      │     │     │
      └─────┼─────┘
            ▼
       Valid Graph
```

---

# Retrieval Telemetry

`RetrieveKnowledge` optionally integrates with `RetrievalTelemetryRecorder`.

Telemetry can capture:

* vector retrieval;
* lexical retrieval;
* fusion;
* reranking;
* final candidate selection;
* latency;
* embedding call correlation.

The service measures stage latency using `perf_counter()`.

Conceptually:

```text
Retrieval
   │
   ├── vector latency
   ├── lexical latency
   ├── fusion latency
   ├── reranking latency
   └── total pipeline latency
```

The vector retrieval path also attempts to associate the retrieval operation with the embedding provider's latest call ID.

This allows retrieval telemetry to be correlated with embedding-provider telemetry.

---

# `build_grounding_context.py`

## Purpose

`BuildGroundingContext` is the higher-level application service that turns retrieval results into a bounded and trusted grounding context.

It composes:

```text
RetrieveKnowledge
        +
GroundingContextBuilder
        +
GroundingContextBudget
        +
RetrievalTelemetryRecorder
```

Its primary responsibility is to provide the next stage of the RAG pipeline with a structured, budget-controlled context rather than exposing raw retrieval candidates directly.

---

# Grounding Context Pipeline

The service implements:

```text
PreparedRetrievalQuery
        │
        ▼
RetrieveKnowledge
        │
        ▼
RetrievalResult
        │
        ▼
GroundingContextBuilder
        │
        │ budget
        ▼
GroundingContext
```

The retrieval service answers:

> Which knowledge candidates are relevant?

The grounding builder answers:

> Which retrieved information should actually enter the model context, within the configured budget?

This distinction keeps retrieval ranking and context construction as separate responsibilities.

---

# Context Budget

`BuildGroundingContext` accepts an optional `GroundingContextBudget`.

If no budget is provided, the service uses its configured default budget.

```text
build(
    prepared_query,
    budget=None
)
        │
        ▼
Default GroundingContextBudget
```

If an explicit budget is supplied, it is validated and used instead.

This allows callers to override context-selection constraints for specific workflows without changing the service's default configuration.

---

# Query Integrity

After `GroundingContextBuilder` creates the context, `BuildGroundingContext` verifies that:

```text
context.query == retrieval_result.query
```

If the context is associated with a different query, the service raises:

```text
RetrievalPipelineError
```

This is an important integrity check.

```text
Retrieval Query
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
Verify same query
```

The grounding context must correspond to the retrieval operation that produced it.

---

# Telemetry Lifecycle

`BuildGroundingContext` owns the high-level telemetry lifecycle for the complete retrieval-to-grounding operation.

When telemetry is configured:

```text
Build
 │
 ▼
Telemetry.start()
 │
 ▼
Retrieve Knowledge
 │
 ▼
Build Context
 │
 ├── success ──► Telemetry.complete()
 │
 └── failure ──► Telemetry.fail()
```

The telemetry records:

* start time;
* completion time;
* total latency;
* context-build latency;
* error code;
* timeout status.

This complements the more granular stage telemetry produced by `RetrieveKnowledge`.

---

# Timeout Detection

`BuildGroundingContext` specifically recognizes embedding-provider timeout failures.

It does not only check the immediate exception.

Instead, it walks through:

```text
exception
   │
   ├── __cause__
   │
   └── __context__
```

until it finds an `EmbeddingProviderTimeoutError`.

This allows timeout telemetry to remain accurate even when the original timeout has been wrapped by another exception.

Conceptually:

```text
Outer Error
    │
    ▼
Cause / Context
    │
    ▼
EmbeddingProviderTimeoutError
    │
    ▼
timeout = True
```

This information is sent to the telemetry recorder when the pipeline fails.

---

# Error Handling

Neither service uses broad exception suppression.

### `RetrieveKnowledge`

Known lower-level failures are allowed to propagate.

Configuration inconsistencies are represented through `RetrievalPipelineError`.

### `BuildGroundingContext`

The service records telemetry for failures and then re-raises the original exception.

```text
Exception
   │
   ├── record failure telemetry
   │
   └── re-raise
```

This prevents telemetry instrumentation from changing the application's actual error semantics.

---

# Dependency Direction

The package intentionally follows dependency inversion.

```text
RetrieveKnowledge
       │
       ├── RetrievalProfile
       ├── RetrievalFusionStrategy
       ├── VectorRetrievalService
       ├── LexicalRetrievalService
       ├── RerankingService
       └── RetrievalTelemetryRecorder

BuildGroundingContext
       │
       ├── RetrieveKnowledge
       ├── GroundingContextBuilder
       ├── GroundingContextBudget
       └── RetrievalTelemetryRecorder
```

The application services do not instantiate these components internally.

They receive them through dependency injection.

This makes the retrieval pipeline configurable and testable.

---

# Separation of Concerns

The two files establish an important boundary:

```text
┌───────────────────────────────────────────┐
│            RetrieveKnowledge              │
│                                           │
│ Retrieval mechanics                       │
│ ├── vector                                │
│ ├── lexical                               │
│ ├── fusion                                │
│ ├── reranking                             │
│ └── candidate limits                      │
└──────────────────────┬────────────────────┘
                       │
                       ▼
              RetrievalResult
                       │
                       ▼
┌───────────────────────────────────────────┐
│         BuildGroundingContext             │
│                                           │
│ Context construction                      │
│ ├── budget selection                      │
│ ├── context building                     │
│ ├── query integrity                      │
│ └── high-level telemetry lifecycle       │
└──────────────────────┬────────────────────┘
                       │
                       ▼
                GroundingContext
```

This prevents the retrieval service from becoming responsible for prompt/context construction.

Likewise, the grounding service does not need to know how vector search, lexical search, or reranking work.

---

# End-to-End RAG Flow

These application services fit into the larger RAG architecture as follows:

```text
Customer Query
      │
      ▼
Query Preparation
      │
      ▼
PreparedRetrievalQuery
      │
      ▼
┌─────────────────────────┐
│    RetrieveKnowledge    │
└────────────┬────────────┘
             │
      ┌──────┼──────┐
      ▼      ▼      ▼
   Vector Lexical  ...
      │      │
      └──┬───┘
         ▼
      Fusion
         │
         ▼
     Reranking
         │
         ▼
  RetrievalResult
         │
         ▼
┌────────────────────────────┐
│   BuildGroundingContext    │
└─────────────┬──────────────┘
              │
              ▼
     GroundingContextBuilder
              │
              ▼
     GroundingContextBudget
              │
              ▼
       GroundingContext
              │
              ▼
       AI Answer Generation
```

---

# Important Invariants

## 1. Retrieval profile controls the active stages

The application service does not independently decide whether vector, lexical, or reranking stages are enabled.

---

## 2. Enabled stages must have implementations

A profile cannot enable a stage without providing the corresponding service.

---

## 3. Retrieval branches use their intended query representations

```text
Vector     → semantic_query
Lexical    → lexical_queries[0]
Canonical  → original_query
```

The original query remains the canonical query for fusion, reranking, provenance, and the returned retrieval result.

---

## 4. Fusion is always applied

Even a single ranking passes through the configured fusion strategy.

This provides consistent result semantics.

---

## 5. Final candidate count is bounded

The result is always limited using the configured final candidate limit.

---

## 6. Retrieval does not silently degrade

Failures in enabled retrieval stages are not silently converted into partial retrieval behavior.

---

## 7. Grounding context must correspond to the retrieval query

`BuildGroundingContext` explicitly verifies query identity between the retrieval result and final grounding context.

---

## 8. Context construction is budgeted

The grounding layer receives an explicit or default `GroundingContextBudget`.

---

## 9. Telemetry does not alter business behavior

Telemetry failures should not replace or suppress the underlying retrieval/context exception semantics.

---

# Testing Considerations

Both services are well suited to isolated application-level testing because their dependencies are injected.

Important tests for `RetrieveKnowledge` include:

* vector-only retrieval;
* lexical-only retrieval;
* hybrid retrieval;
* empty results;
* fusion invocation;
* reranking invocation;
* final candidate limits;
* missing enabled dependencies;
* fusion query mismatch;
* telemetry recording;
* embedding-call correlation;
* lower-layer failure propagation.

Important tests for `BuildGroundingContext` include:

* default budget usage;
* explicit budget usage;
* retrieval invocation;
* context-builder invocation;
* query mismatch detection;
* successful telemetry completion;
* failure telemetry;
* timeout detection through nested exceptions;
* invalid dependency types;
* invalid budget types.

---

# Design Principles

## Composition Over Implementation

The services coordinate specialized components instead of implementing retrieval algorithms themselves.

## Fail Fast

Invalid dependency configurations are detected during construction.

## No Silent Degradation

Retrieval failures remain visible rather than producing misleading partial results.

## Canonical Query Integrity

The original query is preserved as the canonical retrieval identity throughout the pipeline.

## Bounded Context

Retrieved information is converted into a controlled grounding context under an explicit budget.

## Provider Neutrality

The application services operate through retrieval, fusion, reranking, and context contracts rather than provider-specific implementations.

## Observable by Design

Retrieval stages and grounding construction expose structured telemetry without changing the underlying application behavior.

## Separation of Retrieval and Grounding

Candidate retrieval and model-context construction are separate stages with separate responsibilities.

---

# Summary

`packages/knowledge/retrieval/application/` contains the two services responsible for turning a prepared query into usable RAG context.

```text
retrieve_knowledge.py
        │
        │ retrieval orchestration
        ▼
RetrievalResult
        │
        ▼
build_grounding_context.py
        │
        │ context selection + budgeting
        ▼
GroundingContext
```

`RetrieveKnowledge` coordinates the retrieval pipeline:

```text
Vector Retrieval
       +
Lexical Retrieval
       ↓
    Fusion
       ↓
   Reranking
       ↓
Final Candidate Limit
       ↓
RetrievalResult
```

`BuildGroundingContext` then converts that result into bounded context:

```text
RetrievalResult
      │
      ▼
GroundingContextBuilder
      │
      ▼
Budget Enforcement
      │
      ▼
GroundingContext
```

Together, the two services form the **application-level retrieval orchestration boundary** between query preparation and downstream AI answer generation, while keeping retrieval infrastructure, ranking algorithms, context construction, and telemetry independently replaceable.
