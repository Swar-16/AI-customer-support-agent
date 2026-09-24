# Retrieval Fusion

## Overview

The `packages/knowledge/retrieval/fusion/` package is responsible for combining independently ranked retrieval results into a single, deterministic ranking.

It sits between the individual retrieval mechanisms and the downstream reranking/context-building stages of the knowledge-retrieval pipeline.

```text
Vector Retrieval ───────┐
                        │
Lexical Retrieval ──────┼──► Fusion ──► Unified Ranking
                        │
Other Retrieval ────────┘
```

The folder contains two files:

```text
packages/
└── knowledge/
    └── retrieval/
        └── fusion/
            ├── base.py
            ├── reciprocal_rank.py
            └── README.md
```

The two modules establish:

* the **generic fusion contract** through `base.py`;
* the **Reciprocal Rank Fusion (RRF) implementation** through `reciprocal_rank.py`.

---

# Responsibilities

The fusion layer is intentionally focused on ranking aggregation.

It does **not**:

* perform vector search;
* perform lexical search;
* generate embeddings;
* retrieve documents;
* rerank using a separate ML model;
* construct the final LLM context.

Instead, it receives already-ranked candidates from retrieval providers and produces a unified `FusionResult`.

```text
Retrieval Services
       │
       ├── ranked vector candidates
       ├── ranked lexical candidates
       └── other ranked candidates
       │
       ▼
RetrievalFusionStrategy
       │
       ▼
FusionResult
       │
       ▼
Reranking / Context Construction
```

---

# `base.py`

`base.py` defines the provider-neutral abstraction used by fusion implementations.

Its primary responsibilities are defining:

* `FusionInput`;
* `FusionResult`;
* `RetrievalFusionStrategy`.

These contracts allow the application layer to select a fusion algorithm without depending on a specific implementation.

---

# `FusionInput`

`FusionInput` represents the input to a fusion operation.

Conceptually:

```text
FusionInput
├── query
└── rankings
```

`query` identifies the canonical retrieval query.

`rankings` contains the independently ranked candidate sequences that need to be combined.

The abstraction allows the fusion layer to accept:

```text
Ranking 1
Ranking 2
Ranking 3
...
Ranking N
```

rather than coupling the fusion algorithm to specific retrieval technologies.

This is important because vector, lexical, hybrid, or future retrieval strategies can all provide ranked candidates through the same contract.

---

# `FusionResult`

`FusionResult` represents the output of a fusion operation.

```text
FusionResult
├── query
└── candidates
```

The result preserves the canonical query and provides a single ordered candidate collection.

This allows downstream services to consume the result without knowing:

* which fusion algorithm was used;
* how many retrieval rankings were supplied;
* how candidates were aggregated.

The result therefore acts as the stable boundary between fusion and later retrieval stages.

---

# `RetrievalFusionStrategy`

`RetrievalFusionStrategy` defines the interface implemented by concrete fusion algorithms.

A strategy exposes:

```text
strategy_id
fuse(fusion_input, limit)
```

The application layer can therefore depend on the abstraction:

```text
RetrievalFusionStrategy
        │
        ├── ReciprocalRankFusion
        │
        └── future fusion strategies
```

This makes the fusion algorithm replaceable without changing the surrounding retrieval pipeline.

---

# Why a Fusion Abstraction Exists

Different retrieval systems produce scores that are often not directly comparable.

For example:

```text
Vector Search
    similarity = 0.91

Lexical Search
    BM25 = 14.7
```

Comparing these values directly would not necessarily be meaningful.

The fusion abstraction allows algorithms such as RRF to combine **ranking information** instead of assuming that every retrieval mechanism produces scores on the same scale.

---

# `reciprocal_rank.py`

`reciprocal_rank.py` provides the concrete:

```text
ReciprocalRankFusion
```

implementation of `RetrievalFusionStrategy`.

Its strategy identifier is:

```text
reciprocal_rank_fusion
```

The implementation uses classic Reciprocal Rank Fusion.

---

# Reciprocal Rank Fusion

RRF assigns a contribution to a candidate based on its position within each ranking.

For a candidate at rank `r`:

```text
RRF contribution = 1 / (k + r)
```

where `k` is a configurable positive integer.

The default value is:

```text
k = 60
```

A candidate appearing in multiple rankings accumulates the contribution from every ranking.

For example:

```text
Vector ranking:
    A → rank 1
    B → rank 2

Lexical ranking:
    B → rank 1
    C → rank 2
```

The resulting fusion scores are conceptually:

```text
A = 1 / (60 + 1)

B = 1 / (60 + 2)
  + 1 / (60 + 1)

C = 1 / (60 + 2)
```

Thus, candidates consistently appearing near the top of multiple rankings receive stronger combined scores.

---

# Why RRF Uses Rank Instead of Raw Scores

The implementation intentionally does not assume that raw retrieval scores are comparable.

Instead:

```text
Vector scores ──► rank
                     │
Lexical scores ─► rank
                     │
Other scores ───► rank
                     │
                     ▼
                   RRF
```

This makes the algorithm suitable for heterogeneous retrieval systems.

A vector similarity score and a lexical relevance score can have completely different numerical scales while their ranking positions remain meaningful.

---

# Candidate Identity

Candidates are identified by:

```text
chunk_id
```

When the same chunk appears in multiple rankings, it is treated as one logical candidate.

```text
Ranking A               Ranking B
─────────               ─────────
chunk-X rank 1          chunk-X rank 4
       │                       │
       └──────────┬────────────┘
                  ▼
             one candidate
                  │
                  ▼
          accumulated RRF score
```

This prevents duplicate chunks from appearing multiple times in the fused result.

---

# Candidate Aggregation

Internally, `ReciprocalRankFusion` maintains a private accumulator for each unique chunk.

The accumulator tracks:

```text
candidate
fusion_score
best_rank
rank_sum
```

The mutable accumulator is intentionally private.

The public retrieval models remain immutable while temporary mutable state is used internally during aggregation.

This keeps the external retrieval contracts safe from mutation.

---

# Merging Candidates

When the same chunk appears in multiple rankings, its retrieval information is merged.

The merged candidate:

* combines retrieval methods;
* preserves available retrieval scores;
* receives the accumulated RRF score.

For retrieval methods, the implementation forms a union:

```text
methods =
    canonical.methods
    ∪ incoming.methods
```

This preserves the fact that the chunk was discovered by multiple retrieval mechanisms.

---

# Score Merging

Source-specific retrieval scores are merged independently.

The supported score fields include:

```text
vector_distance
vector_similarity
lexical_score
reranker_score
fusion_score
```

The current fusion operation calculates `fusion_score` itself, so any incoming fusion score is deliberately ignored during score merging.

Other scores are preserved when present.

---

# Conflicting Scores

If both candidates contain the same source-specific score and their values disagree, fusion does not silently choose one.

For example:

```text
Candidate A:
vector_similarity = 0.91

Candidate B:
vector_similarity = 0.84
```

for the same `chunk_id` is considered inconsistent provenance.

The implementation raises `FusionInputError`.

This is an intentional integrity check.

```text
Same chunk
    │
    ├── matching provenance → merge
    │
    └── conflicting provenance → reject
```

The fusion layer therefore does not hide upstream data inconsistencies.

---

# Candidate Provenance Validation

Candidates sharing the same `chunk_id` must describe the same persisted knowledge chunk.

The implementation validates:

```text
version_id
document_id
chunk_index
content
document_title
section_title
metadata
```

If any of these differ, the candidates cannot safely be merged.

The fusion operation raises `FusionInputError` rather than silently selecting one candidate's data.

This is particularly important because the fused candidate may later become grounding evidence for an AI-generated answer.

---

# Deterministic Ordering

RRF scores can occasionally be equal.

The implementation therefore uses deterministic tie-breakers.

Candidates are ordered by:

```text
1. fusion score descending
2. best observed rank ascending
3. total rank sum ascending
4. chunk_id ascending
```

Conceptually:

```text
Higher fusion score
        │
        ▼
Better best rank
        │
        ▼
Lower rank sum
        │
        ▼
Stable chunk ID
```

The tie-breakers do not change the RRF score itself.

They ensure that equal-scoring candidates always produce reproducible output.

---

# Candidate Limit

The `fuse()` operation accepts a positive `limit`.

After candidates are aggregated and deterministically sorted, only the first `limit` candidates are returned.

```text
All unique candidates
        │
        ▼
RRF aggregation
        │
        ▼
Deterministic sorting
        │
        ▼
[:limit]
        │
        ▼
FusionResult
```

This prevents unnecessary candidates from propagating into later pipeline stages.

---

# Empty Input

An empty `FusionInput` is valid.

The result is:

```text
FusionResult(
    query=<same query>,
    candidates=()
)
```

No error is raised simply because retrieval produced no candidates.

This allows "no knowledge found" to remain a valid retrieval outcome rather than being confused with a system failure.

---

# Input Validation

`ReciprocalRankFusion` validates its configuration and inputs.

## RRF Parameter

`k` must:

* be an integer;
* not be a boolean;
* be greater than zero.

Invalid values result in `TypeError` or `ValueError`.

---

## Fusion Input

The `fusion_input` must be a `FusionInput`.

Invalid input types are rejected before fusion begins.

---

## Limit

The output limit must:

* be an integer;
* not be a boolean;
* be greater than zero.

This prevents ambiguous or invalid candidate limits.

---

# Mathematical Safety

The implementation validates intermediate RRF values.

Ranks must be:

```text
positive integers
```

RRF contributions must be:

```text
numeric
finite
positive
```

The final fusion score must also be:

```text
finite
non-negative
```

Invalid numerical state results in `RetrievalFusionError`.

This prevents malformed numerical values from propagating into ranking decisions.

---

# Input Immutability

Fusion does not mutate the original retrieval candidates.

Instead, candidate changes are represented using immutable replacements.

```text
Original Candidate
        │
        │ unchanged
        ▼
Fusion Accumulator
        │
        ▼
Merged Candidate
```

This is important because the same retrieval candidates may be used by:

* telemetry;
* debugging;
* other ranking stages;
* evaluation;
* downstream processing.

---

# Error Model

The fusion layer distinguishes between different classes of failures.

### `FusionInputError`

Used when candidate inputs are internally inconsistent.

Examples include:

* conflicting provenance;
* conflicting retrieval scores;
* incompatible candidate data.

### `RetrievalFusionError`

Used for failures within the fusion algorithm itself.

Examples include:

* invalid rank;
* invalid RRF contribution;
* non-finite computed fusion score;
* invalid fusion configuration.

The distinction helps callers identify whether the problem originates from **upstream retrieval data** or the **fusion operation**.

---

# Complete Fusion Flow

The complete RRF process is:

```text
                   FusionInput
                       │
                       ▼
             Validate input + limit
                       │
                       ▼
              For each ranking
                       │
                       ▼
              For each candidate
                       │
                       ▼
              Calculate contribution
                  1 / (k + rank)
                       │
              ┌────────┴─────────┐
              │                  │
       first occurrence    existing chunk
              │                  │
              ▼                  ▼
        create accumulator   merge candidate
              │                  │
              └────────┬─────────┘
                       ▼
                Aggregate scores
                       │
                       ▼
             Validate provenance
                       │
                       ▼
             Deterministic sorting
                       │
                       ▼
                  Apply limit
                       │
                       ▼
                 FusionResult
```

---

# Position in the Retrieval Pipeline

The fusion package is used after retrieval and before final reranking/context construction.

```text
Query
 │
 ▼
Query Preparation
 │
 ▼
┌──────────────────┐
│ Vector Retrieval │
└────────┬─────────┘
         │
         │ ranking
         │
         ├─────────────────────┐
         │                     │
         ▼                     ▼
┌──────────────────┐    ┌──────────────────┐
│ Lexical Retrieval│    │ Other Retrieval  │
└────────┬─────────┘    └────────┬─────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
              ┌─────────────┐
              │    Fusion   │
              └──────┬──────┘
                     │
                     ▼
              Unified Ranking
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

This makes fusion an important boundary in the RAG architecture: it converts heterogeneous retrieval outputs into one canonical ranking.

---

# Extensibility

The abstraction in `base.py` allows additional fusion strategies to be added without changing consumers.

For example:

```text
RetrievalFusionStrategy
        │
        ├── ReciprocalRankFusion
        ├── WeightedScoreFusion
        ├── CombSUM
        ├── CombMNZ
        └── future strategy
```

The application layer can depend only on `RetrievalFusionStrategy`.

A new strategy therefore needs to implement the same fusion contract while leaving retrieval and downstream context construction unchanged.

---

# Design Principles

## Provider Neutrality

The fusion layer does not depend on whether rankings came from a vector database, lexical engine, or another retrieval system.

## Rank-Based Combination

RRF combines rankings rather than assuming raw scores are comparable.

## Determinism

Explicit tie-breakers ensure reproducible ordering.

## Provenance Integrity

Candidates representing the same chunk must agree on their structural and provenance information.

## Immutability

Input retrieval models are not modified during fusion.

## Fail Closed on Inconsistency

Conflicting upstream data is rejected rather than silently merged.

## Bounded Output

The fusion result is explicitly limited before moving downstream.

## Replaceable Strategy

Consumers depend on the generic `RetrievalFusionStrategy` abstraction rather than the RRF implementation.

---

# Summary

The `packages/knowledge/retrieval/fusion/` package provides the ranking-aggregation boundary of the retrieval system.

Its architecture is:

```text
base.py
   │
   ├── FusionInput
   ├── FusionResult
   └── RetrievalFusionStrategy
            │
            ▼
reciprocal_rank.py
   │
   └── ReciprocalRankFusion
            │
            ▼
      Unified Ranking
```

The default RRF implementation:

1. accepts multiple ranked candidate lists;
2. identifies candidates by `chunk_id`;
3. calculates `1 / (k + rank)` contributions;
4. accumulates contributions across rankings;
5. merges retrieval methods and source scores;
6. validates provenance consistency;
7. applies deterministic tie-breaking;
8. enforces the requested candidate limit;
9. returns an immutable `FusionResult`.

The key architectural contract is:

```text
Independent Retrieval Rankings
              │
              ▼
     RetrievalFusionStrategy
              │
              ▼
       ReciprocalRankFusion
              │
              ▼
     One Unified Ranking
              │
              ▼
       Downstream RAG
```

This keeps heterogeneous retrieval mechanisms composable while preserving deterministic ranking, provenance integrity, and a clean extension point for future fusion algorithms.
