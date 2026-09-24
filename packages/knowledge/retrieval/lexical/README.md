# Lexical Retrieval

## Overview

The `packages/knowledge/retrieval/lexical/` package provides the **lexical-search side of the knowledge retrieval pipeline**.

Its responsibility is to translate an application-level `RetrievalQuery` into a backend-independent lexical search request, execute that request through the configured lexical repository, and normalize the returned matches into the application's common `RetrievalCandidate` representation.

The package is intentionally separated into two layers:

```text
packages/
└── knowledge/
    └── retrieval/
        └── lexical/
            ├── repository.py
            ├── service.py
            └── README.md
```

The architecture is:

```text
RetrievalQuery
      │
      ▼
LexicalRetrievalService
      │
      ▼
LexicalSearchRequest
      │
      ▼
LexicalRetrievalRepository
      │
      ▼
Backend Lexical Search
      │
      ▼
Lexical Matches
      │
      ▼
RetrievalCandidate[]
```

This package therefore acts as the **application boundary around lexical knowledge search**.

---

# Responsibilities

| Component       | Responsibility                                                                                                                            |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `repository.py` | Defines the repository-side contract and lexical search request/match abstractions used to communicate with the underlying search backend |
| `service.py`    | Provides the application-facing lexical retrieval service and converts repository results into canonical retrieval candidates             |

The separation keeps backend-specific search infrastructure away from the rest of the retrieval pipeline.

---

# Architectural Position

Lexical retrieval is one of the independent retrieval branches used by the broader knowledge-retrieval system.

```text
                         Retrieval Query
                               │
                ┌──────────────┴──────────────┐
                │                             │
                ▼                             ▼
        Vector Retrieval               Lexical Retrieval
                │                             │
                │                       ┌─────┴─────┐
                │                       │           │
                │                 Service      Repository
                │                       │           │
                │                       └─────┬─────┘
                │                             │
                └──────────────┬──────────────┘
                               ▼
                             Fusion
                               │
                               ▼
                           Reranking
                               │
                               ▼
                       Grounding Context
```

The lexical package does not perform fusion or context construction.

It produces ranked lexical candidates that can subsequently be combined with other retrieval sources.

---

# `service.py`

`service.py` contains:

```text
LexicalRetrievalService
```

This is the **application-facing lexical retrieval service**.

Its responsibilities are explicitly:

* validate lexical retrieval inputs;
* construct a backend-agnostic lexical search request;
* invoke the configured repository;
* translate backend lexical rank/score into `RetrievalScores`;
* preserve candidate provenance and existing scores;
* translate known repository failures into lexical retrieval service errors.

The service therefore acts as an anti-corruption boundary between the repository/backend representation and the application's retrieval models.

---

# Dependency Injection

`LexicalRetrievalService` receives its repository through its constructor:

```text
LexicalRetrievalService(
    repository=...
)
```

It does not create the repository itself.

The constructor validates that:

1. the repository is not `None`;
2. it provides a callable `search` method.

This keeps infrastructure composition outside the service and makes the service straightforward to unit test with a repository implementation or test double.

---

# Search API

The main application operation is:

```text
search(
    query: RetrievalQuery,
    limit: int
)
    -> tuple[RetrievalCandidate, ...]
```

The service accepts the common retrieval-layer `RetrievalQuery` rather than exposing backend-specific request types to callers.

This is an important boundary:

```text
Application
    │
    ▼
RetrievalQuery
    │
    ▼
LexicalRetrievalService
    │
    ▼
LexicalSearchRequest
    │
    ▼
Repository / Backend
```

---

# Input Validation

Before accessing the repository, the service validates the search arguments.

## Query

`query` must be an instance of:

```text
RetrievalQuery
```

Invalid query types result in `TypeError`.

## Limit

`limit` must be:

* an integer;
* not a boolean;
* greater than zero.

Therefore:

```text
limit = True
```

is rejected even though Python considers `bool` a subclass of `int`.

A non-positive limit results in `ValueError`.

This ensures invalid search requests never reach the repository.

---

# Building the Search Request

After validation, the service translates the generic retrieval query into:

```text
LexicalSearchRequest
```

The request contains the relevant lexical-search fields:

```text
query.text
query.filters
limit
```

Conceptually:

```text
RetrievalQuery
├── text
├── filters
└── ...
       │
       ▼
LexicalSearchRequest
├── query_text = query.text
├── filters = query.filters
└── limit
```

This prevents the repository from needing to understand the broader `RetrievalQuery` abstraction.

---

# Repository Invocation

The service delegates actual lexical searching to:

```text
repository.search(request)
```

The repository is therefore responsible for communicating with the underlying lexical-search technology.

The service does not contain backend-specific search logic.

```text
LexicalRetrievalService
          │
          ▼
LexicalSearchRepository
          │
          ▼
Search Backend
```

This separation allows the backend to be replaced without changing application-level lexical retrieval behavior.

---

# Repository Result Normalization

Repository matches are converted into the common:

```text
RetrievalCandidate
```

representation.

For each match:

```text
Lexical Match
     │
     ├── candidate
     └── score
          │
          ▼
RetrievalCandidate
     │
     ├── methods += LEXICAL
     └── scores.lexical_score = match.score
```

The service does not create an entirely new candidate when the repository already provides one.

Instead, it creates an updated immutable candidate using `dataclasses.replace()`.

---

# Lexical Retrieval Method

Every returned candidate is marked with:

```text
RetrievalMethod.LEXICAL
```

The service adds this to the candidate's existing method set.

This means a candidate that was previously associated with another retrieval mechanism can retain that provenance:

```text
Before:
    methods = {VECTOR}

After lexical retrieval:
    methods = {VECTOR, LEXICAL}
```

This becomes particularly useful during hybrid retrieval and fusion because downstream components can determine which retrieval mechanisms discovered a candidate.

---

# Lexical Score Preservation

The repository-provided match score is stored as:

```text
candidate.scores.lexical_score
```

The service intentionally preserves this score as an **opaque lexical relevance signal**.

Higher layers must not assume that lexical scores are directly comparable with vector similarity scores.

For example:

```text
Lexical:
    lexical_score = 14.7

Vector:
    vector_similarity = 0.91
```

These values do not necessarily belong to the same numerical scale.

The fusion layer can instead use ranking information to combine them.

---

# Existing Candidate Scores

The service updates only the lexical score:

```text
updated_scores = replace(
    candidate.scores,
    lexical_score=match.score
)
```

Other score fields are preserved.

For example:

```text
Before:
    vector_similarity = 0.91
    lexical_score = None
    reranker_score = None

After:
    vector_similarity = 0.91
    lexical_score = 14.7
    reranker_score = None
```

This prevents lexical retrieval from accidentally destroying information produced by other stages.

---

# Existing Candidate Provenance

Likewise, the service preserves the candidate's existing retrieval methods and adds `LEXICAL`.

This makes the candidate representation cumulative rather than destructive.

```text
Existing candidate
       │
       ├── existing methods
       ├── existing scores
       └── existing provenance
               │
               ▼
       Lexical normalization
               │
               ▼
       Updated candidate
```

This is important when retrieval branches converge on the same knowledge chunk.

---

# Immutability

The service uses immutable replacement rather than modifying candidates in place.

Conceptually:

```text
Original Candidate
       │
       │ unchanged
       ▼
Updated Candidate
```

This is consistent with the broader retrieval model design and prevents unexpected mutation of objects potentially shared with other retrieval components.

---

# Repository Errors

The service explicitly translates repository-level failures.

If the repository raises:

```text
LexicalRetrievalRepositoryError
```

the service converts it into:

```text
LexicalSearchError
```

while preserving the original exception as the cause.

```text
Repository
    │
    └── LexicalRetrievalRepositoryError
                 │
                 ▼
       LexicalRetrievalService
                 │
                 ▼
          LexicalSearchError
```

This keeps infrastructure-specific errors from leaking into application consumers.

The caller therefore deals with a lexical-service-level error contract rather than repository implementation details.

---

# Empty Search Results

An empty repository result is a valid outcome.

The service simply returns:

```text
()
```

rather than treating "no lexical matches" as an exception.

This distinction is important:

```text
No matches
    │
    └── valid retrieval outcome

Repository failure
    │
    └── LexicalSearchError
```

Downstream retrieval fusion can therefore combine an empty lexical ranking with other retrieval rankings when appropriate.

---

# `repository.py`

`repository.py` defines the repository-side abstraction used by `LexicalRetrievalService`.

Its purpose is to keep the actual lexical search backend behind an explicit repository boundary.

The service therefore depends on:

```text
LexicalRetrievalRepository
```

rather than on a concrete search engine implementation.

This supports the dependency direction:

```text
Application Service
        │
        ▼
Repository Contract
        │
        ▼
Concrete Backend Adapter
        │
        ▼
Search Engine
```

The repository contract is therefore the point where infrastructure-specific implementations can be substituted.

---

# `LexicalSearchRequest`

The repository receives a dedicated lexical-search request rather than the application's full retrieval query.

The request represents the information required by a lexical backend:

```text
LexicalSearchRequest
├── query_text
├── filters
└── limit
```

This gives the repository a focused contract.

The broader retrieval model does not need to leak into infrastructure code.

---

# Repository Match Contract

Repository search results contain both:

```text
candidate
score
```

The candidate provides the knowledge identity and content/provenance information.

The score provides the lexical backend's ranking signal.

The service then maps these into the canonical retrieval representation.

```text
Repository Match
├── candidate
└── score
      │
      ▼
Canonical RetrievalCandidate
├── candidate
├── methods += LEXICAL
└── scores.lexical_score = score
```

This makes the repository output deliberately lightweight while keeping the application-level model consistent.

---

# Separation of Concerns

The two files establish a clean boundary:

```text
┌────────────────────────────────────────┐
│        LexicalRetrievalService         │
│                                        │
│ Validation                             │
│ Request construction                   │
│ Repository invocation                  │
│ Candidate normalization                │
│ Score mapping                          │
│ Error translation                      │
└───────────────────┬────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────┐
│      LexicalRetrievalRepository        │
│                                        │
│ Backend abstraction                    │
│ Search request contract                │
│ Backend result contract                │
└───────────────────┬────────────────────┘
                    │
                    ▼
             Search Backend
```

The service knows **what the application needs**.

The repository knows **how the backend provides it**.

---

# Integration With Hybrid Retrieval

Lexical retrieval is designed to operate alongside other retrieval strategies.

A typical hybrid flow is:

```text
                    RetrievalQuery
                         │
            ┌────────────┴────────────┐
            │                         │
            ▼                         ▼
      Vector Service           Lexical Service
            │                         │
            ▼                         ▼
   Vector Candidates          Lexical Candidates
            │                         │
            └────────────┬────────────┘
                         ▼
                       Fusion
                         │
                         ▼
                    Reranking
                         │
                         ▼
                 Grounding Context
```

The lexical service therefore does not need to know anything about vector retrieval.

Its only job is to produce a correct lexical ranking in the common retrieval model.

---

# Why the Service Preserves Opaque Scores

Lexical search engines can use different relevance functions.

For example, a backend might use:

* BM25;
* TF-IDF;
* weighted term matching;
* field-specific relevance;
* another lexical scoring mechanism.

The service therefore stores the backend's score without interpreting its absolute magnitude.

```text
Backend score
      │
      ▼
lexical_score
      │
      ▼
Fusion / ranking layer
```

This keeps the service independent of the scoring implementation.

---

# Error Boundary Philosophy

The lexical package follows a clear error boundary:

```text
Invalid application input
        │
        ▼
TypeError / ValueError

Repository failure
        │
        ▼
LexicalSearchError

No matches
        │
        ▼
Empty candidate tuple
```

This allows callers to distinguish configuration/input problems from infrastructure failures and normal zero-result searches.

---

# Testing Considerations

The service is straightforward to unit test because its repository dependency is injected.

Important tests include:

### Constructor

* `None` repository;
* repository without `search`;
* non-callable `search`.

### Search Input

* invalid query type;
* boolean limit;
* non-integer limit;
* zero limit;
* negative limit.

### Request Construction

Verify that:

```text
query.text
query.filters
limit
```

are correctly transferred to `LexicalSearchRequest`.

### Repository Interaction

Verify that:

* the repository receives exactly one request;
* repository results are converted correctly;
* repository exceptions are translated.

### Candidate Normalization

Verify that:

```text
RetrievalMethod.LEXICAL
```

is added.

Verify that:

```text
lexical_score
```

is populated.

Verify that existing:

```text
methods
scores
provenance
```

remain intact.

### Empty Results

Verify that no matches return:

```text
()
```

rather than an exception.

---

# Design Principles

## Repository Abstraction

The application service does not depend directly on a search backend.

## Canonical Retrieval Models

Repository-specific results are normalized into the common `RetrievalCandidate` model.

## Immutable Updates

Existing candidates are updated through immutable replacement rather than mutation.

## Provenance Preservation

Existing retrieval methods and score information are retained.

## Opaque Lexical Scores

The service does not assume lexical scores are comparable to vector similarity.

## Explicit Error Translation

Infrastructure failures become application-level lexical retrieval errors.

## Fail Fast on Invalid Input

Invalid query and limit values are rejected before backend access.

## Backend Independence

A different lexical-search implementation can be introduced behind the repository contract without changing callers.

---

# End-to-End Flow

The complete lexical retrieval operation is:

```text
Application
    │
    ▼
RetrievalQuery
    │
    ▼
LexicalRetrievalService.search()
    │
    ├── validate query
    ├── validate limit
    │
    ▼
LexicalSearchRequest
    │
    ▼
LexicalRetrievalRepository.search()
    │
    ▼
Backend Matches
    │
    ▼
For each match
    │
    ├── preserve candidate
    ├── add LEXICAL method
    └── store lexical score
    │
    ▼
tuple[RetrievalCandidate, ...]
    │
    ▼
Fusion
```

---

# Summary

The `packages/knowledge/retrieval/lexical/` package provides a clean, backend-independent lexical retrieval boundary.

Its architecture is:

```text
repository.py
     │
     │ repository contract
     ▼
service.py
     │
     │ application orchestration
     ▼
RetrievalCandidate[]
```

The service performs the important normalization step:

```text
Lexical Backend Match
        │
        ▼
RetrievalCandidate
        │
        ├── methods += LEXICAL
        ├── lexical_score = backend score
        └── existing provenance preserved
```

The resulting candidates can then participate in the broader retrieval pipeline:

```text
Lexical Retrieval
       +
Vector Retrieval
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

The package therefore isolates **lexical-search infrastructure from application-level retrieval semantics**, while preserving candidate provenance, retrieval scores, immutable models, explicit error boundaries, and compatibility with hybrid retrieval.
