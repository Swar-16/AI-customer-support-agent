# Retrieval Reranking

## Overview

The `packages/knowledge/retrieval/reranking/` package defines the **reranking boundary** of the knowledge-retrieval pipeline.

Its purpose is to take an already retrieved and fused set of trusted knowledge candidates and provide a pluggable mechanism for applying a second-stage relevance ordering before the candidates are used to construct the grounding context.

```text
Vector Retrieval
       │
       ▼
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
       │
       ▼
 Answer Generation
```

The package is intentionally designed so that the retrieval pipeline does **not** need to know whether reranking is performed by:

* an external API;
* a local cross-encoder;
* another learned ranking model;
* or no model at all.

The abstraction already supports all of these possibilities.

### Current implementation status

> **No real learned/provider-based reranker is currently active.**

The currently available implementation is `PassthroughReranker`. It preserves the ordering produced by the previous retrieval/fusion stage and only applies the requested result limit. It performs **no external API call, model inference, network request, or relevance scoring**.

The architecture is nevertheless prepared for a future implementation such as a **Jina reranking model**, local cross-encoder, or another provider.

---

# Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── knowledge/
        └── retrieval/
            └── reranking/
                ├── base.py
                ├── models.py
                ├── passthrough.py
                ├── resolver.py
                ├── service.py
                ├── instrumented.py
                └── README.md
```

| File              | Responsibility                                                 |
| ----------------- | -------------------------------------------------------------- |
| `base.py`         | Defines the abstract `Reranker` contract                       |
| `models.py`       | Defines reranker descriptors, requests, results, and responses |
| `passthrough.py`  | Provides the current deterministic no-op reranker              |
| `resolver.py`     | Resolves stable reranker IDs to concrete implementations       |
| `service.py`      | Provides the trusted application-facing reranking boundary     |
| `instrumented.py` | Wraps a reranker with telemetry and execution timing           |

---

# Architectural Position

Reranking occurs **after retrieval and fusion**.

The complete knowledge-retrieval pipeline is conceptually:

```text
RetrievalQueryContext
        │
        ▼
Query Preparation
        │
        ▼
PreparedRetrievalQuery
        │
        ├───────────────┐
        ▼               ▼
Vector Retrieval   Lexical Retrieval
        │               │
        └───────┬───────┘
                ▼
              Fusion
                │
                ▼
           Reranking
                │
                ▼
        Grounding Context
                │
                ▼
        Answer Generation
```

The knowledge-retrieval composition root already constructs:

* query preparation;
* vector retrieval;
* lexical retrieval;
* reciprocal-rank fusion;
* reranking;
* grounding context.

The reranker is therefore a replaceable stage rather than something embedded into retrieval itself.

---

# Core Principle: Reranking Does Not Own Knowledge

The most important architectural rule in this package is:

> A reranker may determine **ordering and relevance**, but it is never the source of truth for knowledge content.

A reranker must not replace or modify:

* chunk content;
* document identity;
* version identity;
* metadata;
* retrieval provenance;
* vector scores;
* lexical scores;
* fusion scores.

It may return:

```text
chunk_id
score
ordering
```

The application service then reconciles that response with the original trusted candidates.

This is particularly important if a future reranker is backed by an external provider.

```text
Trusted Retrieval Candidates
          │
          ▼
       Reranker
          │
          │ untrusted result
          ▼
     chunk_id + score
          │
          ▼
RerankingService validation
          │
          ▼
Original trusted candidate
```

The external provider therefore cannot inject arbitrary knowledge into the RAG pipeline.

---

# `base.py`

`base.py` defines the abstract:

```text
Reranker
```

interface.

It is the extension point for every reranking implementation.

A concrete implementation must provide:

```text
descriptor
rerank(request)
```

and may optionally override:

```text
health_check()
```

The base contract explicitly supports:

* external reranking APIs;
* local cross-encoders;
* learned ranking models;
* deterministic passthrough implementations.

---

# `Reranker.descriptor`

Every reranker exposes a `RerankerDescriptor`.

The descriptor identifies the implementation through:

```text
reranker_id
provider
model
revision
```

This identity is useful for:

* configuration;
* observability;
* reproducibility;
* provider attribution;
* model attribution.

For example, a future implementation could conceptually expose:

```text
reranker_id = "jina-reranker"
provider    = "jina"
model       = "<configured-model>"
revision    = "<configured-revision>"
```

The current passthrough implementation instead identifies itself as:

```text
reranker_id = "passthrough"
provider    = "internal"
model       = None
revision    = None
```

---

# `Reranker.rerank()`

The abstract operation is:

```text
rerank(request: RerankingRequest) -> RerankingResponse
```

Implementations must:

1. treat the request as immutable;
2. return only chunk IDs from the request;
3. return each chunk ID at most once;
4. return results ordered by relevance;
5. return at most the requested limit;
6. correctly identify the implementation in the response descriptor;
7. return finite relevance scores when scores are produced.

Empty input is valid and should produce an empty response.

---

# `models.py`

`models.py` contains the immutable data contracts shared by reranking implementations and the service boundary.

The main models are:

```text
RerankerDescriptor
RerankingRequest
RerankedCandidate
RerankingResponse
```

All are frozen/slotted dataclasses.

---

# `RerankerDescriptor`

`RerankerDescriptor` provides stable identity for a reranker.

```text
RerankerDescriptor
├── reranker_id
├── provider
├── model
└── revision
```

Required identifiers are normalized to lowercase and whitespace is stripped.

Optional `model` and `revision` values are preserved when supplied.

The descriptor exposes a combined identity string:

```text
reranker_id:provider:model:revision
```

with optional components omitted when absent.

This creates a stable representation suitable for telemetry and diagnostics.

---

# `RerankingRequest`

`RerankingRequest` represents the exact candidate set supplied to a reranker.

```text
RerankingRequest
├── query
├── candidates
└── limit
```

The request requires:

* a valid `RetrievalQuery`;
* a tuple of `RetrievalCandidate`;
* a positive integer limit.

Candidate IDs must be unique.

Duplicate chunk IDs are rejected before the reranker executes.

---

# Candidate Ordering Is Meaningful

The ordering of candidates inside `RerankingRequest` is intentionally preserved.

That ordering represents the result of the previous retrieval/fusion stage.

A future reranker can therefore use it as:

* an input signal;
* a fallback ordering;
* a deterministic tie-breaker.

The reranker must never mutate that input tuple.

This is especially relevant while the current implementation is passthrough-based.

---

# `RerankedCandidate`

`RerankedCandidate` represents the minimal result produced by a reranking implementation:

```text
RerankedCandidate
├── chunk_id
└── score
```

The score is optional.

This is intentional.

A real reranker may produce a numerical relevance score, while `PassthroughReranker` deliberately produces:

```text
score = None
```

The reranking service later attaches this value to the trusted candidate's `reranker_score`.

---

# `RerankingResponse`

`RerankingResponse` represents the raw output from a reranker.

```text
RerankingResponse
├── results
└── descriptor
```

Results must:

* be a tuple;
* contain valid `RerankedCandidate` instances;
* contain no duplicate chunk IDs.

The response descriptor identifies the reranker that actually generated the result.

Cross-request validation is deliberately left to `RerankingService`, because only that service has access to both the request and response.

---

# `passthrough.py`

`passthrough.py` provides:

```text
PassthroughReranker
```

This is the **current active reranker implementation**.

It is intentionally a no-op.

```text
Fused Candidates
      │
      ▼
PassthroughReranker
      │
      ├── preserve order
      ├── apply limit
      └── score = None
      │
      ▼
Reranked Candidates
```

It does not perform:

* model inference;
* API calls;
* network access;
* semantic scoring;
* cross-encoding;
* learned ranking.

Its descriptor is:

```text
passthrough:internal
```

with no model or revision.

---

# Why the Passthrough Reranker Exists

The passthrough implementation allows the entire pipeline to be built around the `Reranker` abstraction **without requiring a real reranking model yet**.

Without it, the retrieval pipeline would need conditional branching:

```text
if reranking_enabled:
    rerank()
else:
    skip()
```

Instead, the pipeline can consistently execute:

```text
retrieve
   ↓
fuse
   ↓
rerank
   ↓
context
```

while the current reranker simply preserves the fused ordering.

This keeps the architecture ready for a real provider without coupling the rest of the application to the current implementation.

---

# Current Reranking Semantics

With `PassthroughReranker`:

```text
Fusion ranking
      │
      ▼
same ranking
      │
      ▼
apply limit
      │
      ▼
grounding context
```

There is currently **no additional relevance signal**.

Consequently:

```text
reranker_score = None
```

is meaningful and should not be interpreted as zero.

The service deliberately overwrites the reranker score with the current result, including `None`, so stale scores from previous reranking executions cannot survive.

---

# Future Real Reranker

The architecture is intentionally ready for a real reranker.

A future implementation could be:

```text
Reranker
   │
   ├── PassthroughReranker      ← current
   │
   ├── JinaReranker              ← future
   │
   ├── LocalCrossEncoderReranker ← future
   │
   └── OtherProviderReranker     ← future
```

For a Jina-based implementation, the expected responsibility would be approximately:

```text
RerankingRequest
      │
      ▼
Jina adapter
      │
      ├── send query
      ├── send candidate text
      ├── receive relevance scores
      └── map results to chunk IDs
      │
      ▼
RerankingResponse
```

The Jina adapter would **not** be allowed to become the source of candidate content.

Only the relevance result should come back from the provider.

---

# `resolver.py`

`resolver.py` provides:

```text
RerankerResolver
```

It acts as an immutable registry of available reranking implementations.

```text
reranker_id
     │
     ▼
RerankerResolver
     │
     ▼
Reranker implementation
```

For example:

```text
"passthrough"
       │
       ▼
PassthroughReranker
```

A future configuration could register:

```text
"jina"
       │
       ▼
JinaReranker
```

---

# Immutable Registry

The resolver validates the registry during construction.

It ensures:

* the registry is a mapping;
* every value is a `Reranker`;
* normalized IDs are unique;
* registry keys match the reranker's descriptor ID.

The internal mapping is exposed through an immutable `MappingProxyType`.

This prevents runtime code from unexpectedly registering or unregistering rerankers.

---

# Resolving a Reranker

The main operation is:

```text
resolve(reranker_id)
```

The ID is normalized and looked up.

If no implementation exists, the resolver raises:

```text
RerankerResolutionError
```

instead of returning `None`.

The resolver also exposes:

```text
contains(reranker_id)
available_ids
count
```

for configuration and diagnostics.

---

# Why Use a Resolver?

The resolver keeps selection separate from execution.

```text
Configuration
      │
      ▼
reranker_id = "passthrough"
      │
      ▼
RerankerResolver
      │
      ▼
PassthroughReranker
      │
      ▼
RerankingService
```

Later:

```text
Configuration
      │
      ▼
reranker_id = "jina"
      │
      ▼
RerankerResolver
      │
      ▼
JinaReranker
      │
      ▼
RerankingService
```

The service itself does not need to know how the implementation was selected.

---

# `service.py`

`service.py` contains:

```text
RerankingService
```

This is the **application-facing trust boundary** for reranking.

Its responsibilities include:

* constructing the canonical request;
* invoking the configured reranker;
* validating the response;
* rejecting fabricated candidate identities;
* checking response cardinality;
* validating descriptor identity;
* preserving trusted candidate provenance;
* applying reranker ordering;
* attaching reranker scores.

---

# Reranking Service Flow

```text
Trusted RetrievalCandidate[]
             │
             ▼
       RerankingRequest
             │
             ▼
        Reranker
             │
             ▼
      RerankingResponse
             │
       ┌─────┴─────┐
       │ validation │
       └─────┬─────┘
             │
             ▼
      Trusted candidates
             │
             ▼
      Updated ordering
             │
             ▼
       Grounding Context
```

---

# Response Validation

The service validates the reranker response against the request.

The checks include:

### Response Type

The result must be a `RerankingResponse`.

### Descriptor Consistency

The response descriptor must exactly match the configured reranker's descriptor.

This prevents a provider adapter from silently claiming that another provider/model produced the result.

### Cardinality

The reranker may return fewer candidates than the requested limit.

It may not return more than:

```text
min(request.limit, request.candidate_count)
```

This deliberately permits future rerankers that filter candidates as well as reorder them.

### Membership

Every returned chunk ID must already exist in the trusted input candidates.

This is a critical external-provider trust boundary.

---

# Candidate Materialization

The reranker only returns:

```text
chunk_id
score
```

The service reconstructs the actual result using the original trusted candidate.

```text
Reranker result
├── chunk_id
└── score
       │
       ▼
lookup original candidate
       │
       ▼
trusted RetrievalCandidate
       │
       └── attach reranker_score
```

The provider therefore cannot alter:

* content;
* metadata;
* provenance;
* document identity;
* version identity;
* existing retrieval scores.

The provider controls only the reranking result.

---

# Applying Reranker Scores

The service attaches the result to:

```text
RetrievalScores.reranker_score
```

If the result score is:

```text
None
```

the resulting candidate explicitly has:

```text
reranker_score = None
```

This is the expected behavior for the current passthrough implementation.

---

# Applying Reranker Ordering

The returned candidates are materialized **in exactly the order supplied by the reranker**.

Therefore:

```text
Input:
A
B
C

Reranker:
C
A
B

Service output:
C
A
B
```

The actual candidate objects still originate from the original trusted input.

This means reranking changes the **ordering**, not the underlying knowledge objects.

---

# Empty Candidate Set

An empty reranking request is valid.

The service immediately returns:

```text
()
```

without invoking the reranker.

This keeps zero-result retrieval behavior clean and predictable.

---

# `instrumented.py`

`instrumented.py` provides:

```text
InstrumentedReranker
```

It is a telemetry wrapper around another `Reranker`.

```text
             RerankingService
                    │
                    ▼
          InstrumentedReranker
                    │
                    ▼
             Actual Reranker
```

The wrapper does not change the reranking contract.

It records execution lifecycle information while preserving the wrapped implementation's response and exception behavior.

---

# Instrumentation Responsibilities

The wrapper records information such as:

* start time;
* execution duration;
* success;
* failure;
* timeout;
* reranker identity;
* call ID.

It deliberately does **not** persist:

* query text;
* candidate content.

This maintains the content-minimizing telemetry boundary.

---

# Instrumented Execution

The lifecycle is approximately:

```text
rerank(request)
      │
      ▼
start telemetry
      │
      ▼
record start time
      │
      ▼
wrapped_reranker.rerank()
      │
      ├───────────────┐
      │               │
      ▼               ▼
   success          failure
      │               │
      ▼               ▼
 complete         fail/timeout
 telemetry          telemetry
      │               │
      └───────┬───────┘
              ▼
          return/raise
```

The wrapper measures elapsed time using a monotonic clock while recording timestamps using UTC.

---

# Telemetry Failure Isolation

Telemetry itself should not break reranking.

The instrumentation methods use safe wrappers around telemetry operations.

Therefore, if telemetry persistence fails, the underlying reranker should still be allowed to execute and return its normal result.

This keeps observability subordinate to the actual retrieval pipeline.

---

# Provider Error Handling

Known provider failures are represented through the retrieval reranking error hierarchy.

The instrumented wrapper recognizes `RerankerProviderError` and records:

* timeout when appropriate;
* otherwise a provider failure.

It then re-raises the original exception.

Unexpected exceptions are also recorded and re-raised rather than silently swallowed.

---

# Health Checks

The `Reranker` abstraction exposes:

```text
health_check() -> bool
```

The default implementation returns `True`.

Stateless/local implementations may use the default behavior.

An external implementation may override it with a lightweight provider health check.

Importantly, a successful health check is **not a guarantee** that a future reranking request will succeed.

---

# Current Runtime Configuration

At the current stage, the package supports the architecture required for real reranking, but the actual production reranker is still the passthrough implementation.

Therefore the current effective behavior is:

```text
Retrieval
    │
    ▼
Fusion
    │
    ▼
PassthroughReranker
    │
    ├── no model
    ├── no external API
    ├── no network request
    ├── no reranking score
    └── preserve fused ordering
    │
    ▼
Grounding Context
```

The surrounding architecture should therefore **not be documented as currently performing learned reranking**.

It is more accurate to describe it as:

> **Reranking infrastructure implemented, provider/model-based reranking not yet activated.**

---

# Future Jina Integration

The package is intentionally compatible with a future Jina-based implementation.

A potential future architecture would be:

```text
                    RerankingService
                           │
                           ▼
                    InstrumentedReranker
                           │
                           ▼
                       JinaReranker
                           │
                           ▼
                    Jina Reranking API
                           │
                           ▼
                  relevance scores/order
                           │
                           ▼
                 RerankingResponse
                           │
                           ▼
              trusted candidate materialization
```

The future Jina adapter should implement only the `Reranker` contract.

The rest of the pipeline should remain unchanged.

That is the primary architectural benefit of the current design.

---

# Replacing Passthrough With a Real Reranker

The intended migration path is:

```text
CURRENT

RerankerResolver
      │
      ▼
PassthroughReranker
      │
      ▼
RerankingService
```

becomes:

```text
FUTURE

RerankerResolver
      │
      ▼
JinaReranker
      │
      ▼
RerankingService
```

No changes should be required to:

* vector retrieval;
* lexical retrieval;
* fusion;
* grounding context;
* answer generation.

Only the concrete `Reranker` implementation and its configuration need to change.

---

# Why This Boundary Matters

Without this abstraction, a future external reranker could become deeply coupled to the retrieval system.

The current architecture avoids that:

```text
Retrieval
   │
   ▼
Fusion
   │
   ▼
Generic Reranker Contract
   │
   ├── current: Passthrough
   ├── future: Jina
   ├── future: Cross Encoder
   └── future: Other Provider
   │
   ▼
Trusted Reranking Service
   │
   ▼
Grounding
```

This makes reranking an interchangeable infrastructure capability.

---

# Security / Trust Model

External rerankers must be treated as **untrusted result producers**.

The trust boundary is:

```text
Trusted candidates
       │
       ▼
External / provider reranker
       │
       ▼
Untrusted IDs + scores
       │
       ▼
Validation
       │
       ├── membership
       ├── cardinality
       ├── descriptor
       └── uniqueness
       │
       ▼
Trusted candidates again
```

The provider never gets authority to create new knowledge identities.

It can only rank the candidates that the application has already retrieved.

This design is particularly important for future external APIs.

---

# Data Flow With Current Implementation

The actual current pipeline is:

```text
Customer Query
      │
      ▼
Query Preparation
      │
      ▼
Vector Retrieval ─────┐
                      │
Lexical Retrieval ────┤
                      ▼
                    Fusion
                      │
                      ▼
             PassthroughReranker
                      │
                      │ same order
                      ▼
              Grounding Context
                      │
                      ▼
             Grounded Response
```

There is currently no learned relevance transformation between fusion and grounding.

---

# Data Flow With Future Real Reranker

Once a real provider is introduced:

```text
Customer Query
      │
      ▼
Query Preparation
      │
      ▼
Vector Retrieval ─────┐
                      │
Lexical Retrieval ────┤
                      ▼
                    Fusion
                      │
                      ▼
              Real Reranker
                      │
              ┌───────┴───────┐
              │               │
         relevance score   ordering
              │               │
              └───────┬───────┘
                      ▼
              Grounding Context
                      │
                      ▼
             Grounded Response
```

The rest of the pipeline remains unchanged.

---

# Testing Strategy

## Base Contract

Test that every implementation:

* exposes a descriptor;
* accepts valid requests;
* rejects invalid requests appropriately;
* returns only requested candidates;
* respects limits;
* maintains unique candidate IDs.

## Models

Test:

* descriptor normalization;
* invalid identifiers;
* invalid candidate types;
* duplicate candidate IDs;
* invalid limits;
* non-finite scores;
* duplicate response IDs.

## Passthrough

Test that:

```text
input ordering == output ordering
```

and:

```text
output count <= limit
```

Also verify:

```text
reranker_score = None
```

through the service.

## Resolver

Test:

* valid resolution;
* ID normalization;
* duplicate IDs;
* descriptor/key mismatch;
* unavailable IDs;
* available ID listing.

## Service

Test:

* response type validation;
* descriptor validation;
* candidate membership;
* cardinality;
* ordering;
* score attachment;
* preservation of original candidate data.

## Instrumentation

Test:

* successful execution;
* provider failures;
* timeouts;
* unexpected exceptions;
* telemetry failures;
* call ID handling;
* health-check delegation.

---

# Design Principles

## Provider Agnostic

The package does not depend on Jina or any other provider.

## Replaceable

A real reranker can replace passthrough without changing downstream retrieval code.

## Trust Preserving

Rerankers cannot fabricate knowledge candidates.

## Immutable

Requests, responses, descriptors, and candidates use immutable contracts.

## Deterministic When No Model Is Available

The passthrough implementation gives predictable behavior while the real provider is not yet integrated.

## Observable

Any reranker can be wrapped with `InstrumentedReranker`.

## Explicit Identity

Every reranker identifies itself through a stable descriptor.

## Bounded Output

Reranking cannot return more candidates than allowed.

## Provider Errors Stay Typed

Provider failures remain distinguishable from malformed responses and application-level validation failures.

---

# Complete Package Flow

```text
                         Retrieval Candidates
                                │
                                ▼
                              Fusion
                                │
                                ▼
                       RerankingRequest
                                │
                                ▼
                     ┌────────────────────┐
                     │ RerankerResolver   │
                     └─────────┬──────────┘
                               │
                 ┌─────────────┴──────────────┐
                 │                            │
                 ▼                            ▼
       PassthroughReranker             Future Real Reranker
                 │                    (e.g. Jina / Cross-Encoder)
                 │                            │
                 └─────────────┬──────────────┘
                               ▼
                     InstrumentedReranker
                               │
                               ▼
                       RerankingService
                               │
                    ┌──────────┴──────────┐
                    │                     │
               Validate                Materialize
               response                candidates
                    │                     │
                    └──────────┬──────────┘
                               ▼
                    Reranked RetrievalCandidate[]
                               │
                               ▼
                       Grounding Context
```

---

# Summary

The `packages/knowledge/retrieval/reranking/` package establishes the complete infrastructure boundary for second-stage retrieval ranking.

Its six components have clear responsibilities:

```text
base.py
   │
   └── abstract Reranker contract

models.py
   │
   └── immutable request/response contracts

passthrough.py
   │
   └── current no-op implementation

resolver.py
   │
   └── implementation selection

service.py
   │
   └── validation + trusted candidate materialization

instrumented.py
   │
   └── telemetry wrapper
```

### Current state

```text
Real reranker:          ❌ Not yet implemented/active
Passthrough:            ✅ Implemented
Reranker abstraction:   ✅ Implemented
Resolver:               ✅ Implemented
Validation boundary:    ✅ Implemented
Telemetry wrapper:      ✅ Implemented
External-provider path: ✅ Architecture ready
Jina integration:       ⏳ Future implementation
```

The key architectural contract is:

```text
                    Fusion
                      │
                      ▼
              Reranker abstraction
                      │
          ┌───────────┴───────────┐
          │                       │
     Passthrough              Future Provider
      (current)              (e.g. Jina)
          │                       │
          └───────────┬───────────┘
                      ▼
              RerankingService
                      │
                      ▼
             Trusted Candidates
                      │
                      ▼
              Grounding Context
```

The package is therefore **fully prepared for real reranking without pretending that real reranking is already happening**. The current system uses passthrough semantics, while the abstraction, resolver, trust boundary, telemetry, validation, and composition points are already in place for introducing a real reranking provider later.
