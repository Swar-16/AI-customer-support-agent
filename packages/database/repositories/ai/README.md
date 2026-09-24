# AI Repositories

## Overview

The `packages/database/repositories/ai/` package contains the SQLAlchemy repository layer for the application's **AI execution, orchestration, provider telemetry, retrieval, classification, and decision records**.

These repositories sit between application services and the AI-related database models:

```text
Application / AI Services
          │
          ▼
packages/database/repositories/ai/
          │
          ▼
packages/database/models/ai/
          │
          ▼
      PostgreSQL
```

The repositories provide a controlled persistence interface for AI execution data without embedding database access throughout the application layer.

They are intentionally:

* **transaction-aware**;
* **query-focused**;
* **validation-aware**;
* **free of AI/business decision logic**;
* generally **non-committing**.

The surrounding Unit of Work owns the actual transaction commit/rollback boundary.

---

# Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── database/
        └── repositories/
            └── ai/
                ├── ai_run_repository.py
                ├── stage_event_repository.py
                ├── llm_call_repository.py
                ├── embedding_call_repository.py
                ├── retrieval_repository.py
                ├── reranker_call_repository.py
                ├── intent_prediction_repository.py
                └── decision_repository.py
```

The eight repositories correspond to the major persistence components of the AI execution graph.

| File                              | Repository                   | Primary responsibility                  |
| --------------------------------- | ---------------------------- | --------------------------------------- |
| `ai_run_repository.py`            | `AIRunRepository`            | AI pipeline run lifecycle and lookup    |
| `stage_event_repository.py`       | `AIStageEventRepository`     | Append-only orchestration stage events  |
| `llm_call_repository.py`          | `LLMCallRepository`          | LLM invocation telemetry                |
| `embedding_call_repository.py`    | `EmbeddingCallRepository`    | Embedding-provider telemetry            |
| `retrieval_repository.py`         | `RetrievalRepository`        | Retrieval runs and candidate provenance |
| `reranker_call_repository.py`     | `RerankerCallRepository`     | Reranker invocation telemetry           |
| `intent_prediction_repository.py` | `IntentPredictionRepository` | Historical intent predictions           |
| `decision_repository.py`          | `AIDecisionRepository`       | Historical AI decisions                 |

---

# AI Persistence Graph

These repositories are not eight unrelated database adapters.

They represent different levels of the same AI execution:

```text
                         AI RUN
                           │
             ┌─────────────┼─────────────┐
             │             │             │
             ▼             ▼             ▼
        Stage Events    LLM Calls    Embedding Calls
             │             │             │
             │        ┌────┴────┐        │
             │        ▼         ▼        │
             │     Intent    Decision    │
             │   Prediction              │
             │                           │
             └─────────────┬─────────────┘
                           │
                           ▼
                    Retrieval Run
                           │
                           ▼
                 Retrieval Candidates
                           │
                           ▼
                     Reranker Call
```

The repositories allow this execution history to be persisted and queried without making the repository layer responsible for actually running the AI pipeline.

---

# Common Repository Contract

All eight repositories receive an SQLAlchemy `Session`:

```python
repository = SomeRepository(session)
```

The constructor rejects a `None` session.

The repository then operates against that session but does not normally own the transaction.

The common pattern is:

```text
Repository
    │
    ├── validate input
    │
    ├── construct SQLAlchemy statement
    │
    ├── execute against Session
    │
    └── return model/result
```

For writes:

```text
Repository.add(...)
       │
       ▼
session.add(...)
       │
       ▼
Unit of Work
       │
       ▼
commit / rollback
```

For flush-dependent workflows:

```text
Repository.flush()
       │
       ▼
session.flush()
```

The repositories therefore do **not** call `commit()` themselves. This keeps transaction ownership at the Unit-of-Work/application boundary.

---

# 1. `ai_run_repository.py`

## `AIRunRepository`

`AIRunRepository` is the persistence adapter for top-level **AI pipeline executions**.

It works with:

```text
AIRunModel
```

and provides the root persistence object from which the other AI records can be correlated.

Its responsibilities include:

* creating/persisting AI runs;
* retrieving a run by ID;
* finding runs by trace;
* finding runs by conversation;
* finding runs triggered by a message;
* retrieving runs associated with response messages;
* querying run lifecycle/status information;
* updating lifecycle fields.

### Execution Identity

An AI run can be connected to:

```text
trace_id
conversation_id
trigger_message_id
response_message_id
```

This enables queries such as:

```text
Conversation
    │
    ▼
AI Run
    │
    ├── Trace
    ├── Trigger Message
    └── Response Message
```

Multiple runs may legitimately exist for the same trigger message because retries or reprocessing can occur.

Similarly, `trace_id` is not assumed to be unique; multiple child runs may belong to the same trace.

### Role

`AIRunRepository` is effectively the **entry point into persisted AI execution history**.

---

# 2. `stage_event_repository.py`

## `AIStageEventRepository`

This repository persists **AI orchestration lifecycle events**.

It works with:

```text
AIStageEventModel
```

The repository is explicitly append-only:

* events can be added;
* events can be added in batches;
* pending events can be flushed;
* there are no update operations;
* there are no delete operations;
* the repository never commits.

### Stage Events

Supported event types include:

```text
stage_started
stage_completed
stage_failed
```

Supported pipeline stages include:

```text
received
context_built
intent_classified
decision_made
retrieval_completed
response_generated
guardrails_completed
action_proposed
action_completed
escalated
completed
failed
```

### Querying

Stage events can be retrieved:

```text
by event ID
by AI run
by trace
by conversation
by stage
by event type
by error code
by retryability
by time range
```

The run and trace queries return events chronologically.

The recent-event query is designed for dashboard/observability use and supports filtering plus pagination.

### Role

This repository provides the **timeline of orchestration activity inside an AI run**.

---

# 3. `llm_call_repository.py`

## `LLMCallRepository`

This repository manages persistence for individual **LLM provider invocations**.

It works with:

```text
LLMCallModel
```

Its responsibilities include:

* persisting LLM calls;
* retrieving calls by ID;
* retrieving calls by provider request ID;
* retrieving all calls belonging to an AI run;
* querying by pipeline purpose;
* querying failed/timeout calls;
* operational diagnostics;
* lifecycle updates.

### Provider Correlation

A provider request ID allows internal telemetry to be correlated with provider-side logs:

```text
Application
    │
    ▼
LLMCallRepository
    │
    ├── ai_run_id
    └── provider_request_id
             │
             ▼
       Provider telemetry
```

The repository normalizes and validates provider request identifiers before querying.

### Execution Order

LLM calls belonging to an AI run are returned in execution order using:

```text
started_at
id
```

as ordering keys.

### Important Boundary

The repository **does not**:

* invoke an LLM;
* calculate pricing;
* implement retry/backoff;
* decide whether a failure is retryable;
* make business decisions.

Those belong to higher layers.

---

# 4. `embedding_call_repository.py`

## `EmbeddingCallRepository`

This repository persists **embedding-provider call telemetry**.

It works with:

```text
EmbeddingCallModel
```

and handles the lifecycle and querying of embedding calls without committing transactions itself.

### Embedding Purposes

Supported purposes include:

```text
query
document_ingestion
reindex
evaluation
other
```

### Main Query Dimensions

Embedding calls can be retrieved by:

```text
call ID
provider request ID
AI run
knowledge version
provider
model
purpose
status
error code
time range
```

For example, the repository can retrieve calls belonging to a particular knowledge version, which is useful when investigating embedding operations during knowledge ingestion or reindexing.

### Role

This repository connects AI execution telemetry with the **knowledge/embedding subsystem** without implementing embedding generation itself.

---

# 5. `retrieval_repository.py`

## `RetrievalRepository`

This repository manages two related persistence objects:

```text
RetrievalRunModel
RetrievalCandidateModel
```

It therefore represents both:

```text
Retrieval execution
```

and:

```text
Candidate provenance
```

The repository explicitly distinguishes their lifecycle:

```text
Retrieval Run
    → lifecycle fields may be updated

Retrieval Candidate
    → append-only
```

### Writes

It supports:

```text
add_run(...)
add_candidate(...)
add_candidates(...)
flush(...)
```

### Candidate Queries

Candidates can be retrieved:

```text
by retrieval run
```

and optionally filtered to:

```text
selected_only=True
```

Results are ordered using final ranking information.

### Run Queries

Retrieval runs can be queried by:

```text
retrieval run ID
AI run
trace
time range
```

The repository therefore provides the persistence bridge between the AI run and the individual retrieval operation.

---

# 6. `reranker_call_repository.py`

## `RerankerCallRepository`

This repository manages persistence for **reranker execution telemetry**.

It works with:

```text
RerankerCallModel
```

and manages the lifecycle of a reranker call without committing the transaction itself.

### Correlation

Reranker calls can be located using:

```text
call ID
provider request ID
retrieval run
trace
```

Recent calls can also be filtered by:

```text
reranker
provider
model
status
error code
time range
pagination
```

### Architectural Note

The repository is **provider-neutral**.

The persistence layer can therefore record:

```text
   deterministic/pass-through reranking
                 OR
            local reranking
                 OR
       external reranking provider
```

The repository does not require a specific implementation.

This is especially relevant because the current architecture has the reranker boundary prepared for a real provider, but a learned/external reranker does not necessarily need to be active for the repository contract to exist.

---

# 7. `intent_prediction_repository.py`

## `IntentPredictionRepository`

This repository persists the results of **AI intent classification**.

It works with:

```text
IntentPredictionModel
```

Intent predictions are treated as historical inference evidence and are therefore effectively **append-only**.

The repository explicitly does not:

* run the classifier;
* interpret confidence;
* apply routing thresholds;
* decide escalation;
* mutate historical predictions;
* commit transactions.

### Query Dimensions

Predictions can be retrieved by:

```text
prediction ID
AI run
LLM call
intent
confidence
```

### Low-Confidence Queries

The repository supports caller-supplied confidence thresholds.

For example:

```text
get_low_confidence(threshold=...)
```

The repository validates that the supplied threshold is between `0` and `1`, but it does **not** decide what constitutes "low confidence".

That distinction keeps evaluation/business policy outside the persistence layer.

### Multiple Predictions

One AI run can have multiple predictions because of:

```text
retries
fallback classifiers
reclassification
```

The repository therefore does not assume one prediction per run.

---

# 8. `decision_repository.py`

## `AIDecisionRepository`

This repository persists **structured AI routing/action decisions**.

It works with:

```text
AIDecisionModel
```

Its responsibilities include:

* persisting decisions;
* retrieving decisions by AI run;
* retrieving decisions by LLM call;
* querying decision type;
* querying reason code;
* finding low-confidence decisions;
* retrieving escalation decisions;
* retrieving clarification requests;
* retrieving the latest decision for an AI run.

### Decision History

An AI run can contain multiple decisions.

For example:

```text
retrieve_information
        │
        ▼
      answer
```

or:

```text
retrieve_information
        │
        ▼
     escalate
```

Therefore the repository preserves decision history rather than assuming that a run has only one immutable decision record.

### Deterministic Decisions

A decision does not necessarily originate from an LLM.

`llm_call_id` may be `NULL` for decisions produced entirely by the deterministic `DecisionEngine`.

This is an important architectural boundary:

```text
AI Run
  │
  ├── LLM-generated decision
  │       └── llm_call_id
  │
  └── Deterministic decision
          └── no LLM call required
```

### Latest Decision

The repository provides:

```text
get_latest_for_ai_run(...)
```

because an AI run may evolve through multiple decisions.

---

# Cross-Repository Relationships

The eight repositories form a persistence graph.

```text
                          AIRunRepository
                                │
                                ▼
                              AI Run
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
          ▼                     ▼                     ▼
 StageEventRepository    LLMCallRepository    EmbeddingCallRepository
          │                     │
          │              ┌──────┴──────┐
          │              ▼             ▼
          │       IntentPrediction   Decision
          │         Repository       Repository
          │
          ▼
      Pipeline
      Timeline

AI Run
   │
   ▼
RetrievalRepository
   │
   ├── Retrieval Run
   │       │
   │       ▼
   │   Candidates
   │
   └── RerankerCallRepository
```

This means a single AI run can be reconstructed from multiple persistence layers.

---

# End-to-End Example

Consider a customer message that enters the AI pipeline.

The repositories can capture the execution approximately as:

```text
1. AIRunRepository
       │
       └── create AI run

2. AIStageEventRepository
       │
       ├── stage_started: received
       ├── stage_completed: context_built
       └── ...

3. LLMCallRepository
       │
       └── persist intent-classification LLM call

4. IntentPredictionRepository
       │
       └── persist predicted intent

5. RetrievalRepository
       │
       ├── persist retrieval run
       └── persist candidates

6. RerankerCallRepository
       │
       └── persist reranking telemetry

7. LLMCallRepository
       │
       └── persist answer-generation call

8. AIDecisionRepository
       │
       └── persist resulting decision

9. AIStageEventRepository
       │
       └── stage_completed: response_generated
```

The repositories **record this process**. They do not themselves decide or execute the process.

---

# Transaction Boundary

One of the most important design characteristics across this package is:

> **Repositories do not own commits.**

For example:

```text
Application Service
       │
       ▼
Unit of Work
       │
       ├── AIRunRepository.add()
       ├── LLMCallRepository.add()
       ├── IntentPredictionRepository.add()
       ├── RetrievalRepository.add_run()
       ├── RetrievalRepository.add_candidate()
       └── AIDecisionRepository.add()
       │
       ▼
     commit()
```

This allows several AI telemetry records to participate in the same transaction.

If the application operation fails:

```text
rollback()
```

can discard all pending changes together.

---

# Validation Strategy

Repositories perform lightweight persistence-facing validation before interacting with the session.

Common validation includes:

```text
None session checks
model instance checks
UUID validation
string normalization
enum/value validation
limit validation
pagination validation
datetime-range validation
```

For example, stage-event filtering normalizes choices and validates identifiers, pagination, and date ranges before constructing its SQL statement.

This prevents malformed repository calls from silently producing misleading queries.

---

# Query Design

The repositories expose query methods around **real operational access patterns**, rather than exposing arbitrary SQL construction to callers.

Common query dimensions include:

```text
ID
AI run
trace
conversation
provider
model
provider request ID
status
purpose
event/stage
intent
decision type
reason code
time range
pagination
```

This allows higher-level services and dashboards to perform useful queries without knowing the database schema details.

---

# Observability and Dashboard Support

Several repository methods are explicitly designed for operational diagnostics and dashboard queries.

Examples include:

```text
Recent failed LLM calls
Recent embedding calls
Recent reranker calls
Recent stage events
Low-confidence predictions
Low-confidence decisions
Escalation decisions
Retrieval candidates
Runs by conversation
Runs by trace
```

The repository layer therefore acts as an important data-access boundary for the application's observability and analytics layers.

---

# Append-Only vs Mutable Data

Not every AI record has the same lifecycle.

| Repository                   | Persistence lifecycle                   |
| ---------------------------- | --------------------------------------- |
| `AIRunRepository`            | Run lifecycle can be updated            |
| `AIStageEventRepository`     | Append-only                             |
| `LLMCallRepository`          | Call lifecycle can be updated           |
| `EmbeddingCallRepository`    | Call lifecycle can be updated           |
| `RetrievalRepository`        | Runs can update; candidates append-only |
| `RerankerCallRepository`     | Call lifecycle can be updated           |
| `IntentPredictionRepository` | Historical predictions append-only      |
| `AIDecisionRepository`       | Historical decision evidence preserved  |

This distinction is important.

A lifecycle record such as an LLM call may transition:

```text
started → success
```

while an inference artifact such as an intent prediction represents historical evidence that should not later be rewritten.

---

# What These Repositories Do Not Do

The AI repository layer intentionally does **not** contain the actual AI intelligence.

It does not:

* call LLM providers;
* generate embeddings;
* perform vector search;
* rerank candidates;
* classify intents;
* decide whether to escalate;
* execute customer actions;
* calculate business policy;
* perform retry/backoff orchestration;
* own transactions;
* construct final AI responses.

Instead:

```text
AI / Application Services
        │
        │ execute intelligence
        ▼
AI Repository Layer
        │
        │ persist / retrieve evidence
        ▼
Database
```

For example, `LLMCallRepository` explicitly excludes provider invocation, pricing, retry policy, and business decisions.

Similarly, `AIDecisionRepository` stores decisions but does not execute decision logic, authorize actions, or determine escalation eligibility.

---

# Relationship to AI Models

Each repository is deliberately paired with an AI model:

```text
Repository                    Model
────────────────────────────────────────────────
AIRunRepository          →    AIRunModel

AIStageEventRepository   →    AIStageEventModel

LLMCallRepository        →    LLMCallModel

EmbeddingCallRepository  →    EmbeddingCallModel

RetrievalRepository      →    RetrievalRunModel
                              RetrievalCandidateModel

RerankerCallRepository   →    RerankerCallModel

IntentPredictionRepository
                         →    IntentPredictionModel

AIDecisionRepository     →    AIDecisionModel
```

The model defines the persistence structure and database constraints; the repository defines the application's supported database access patterns.

---

# Design Principles

## 1. Repository ≠ Business Logic

Repositories answer:

> "How do I persist or retrieve this record?"

They do not answer:

> "What should the AI system do?"

---

## 2. Unit of Work Owns Transactions

Repositories participate in transactions but do not commit them.

---

## 3. Historical AI Evidence Is Preserved

Stage events, intent predictions, decisions, and retrieval candidates are treated as evidence of what occurred rather than mutable application state.

---

## 4. Queries Match Operational Needs

Methods are provided for common access patterns such as:

```text
by AI run
by trace
by provider
by status
by time
by confidence
by decision type
```

rather than exposing raw SQL to callers.

---

## 5. Provider-Neutral Persistence

Provider-specific identifiers and metadata can be stored without making the repository dependent on a specific provider implementation.

This is especially important for:

```text
LLM
Embedding
Reranking
```

providers.

---

## 6. Correlation Is First-Class

The repositories consistently support identifiers such as:

```text
ai_run_id
trace_id
conversation_id
provider_request_id
retrieval_run_id
llm_call_id
```

This allows individual records to be reconstructed into a complete AI execution.

---

# Mental Model

The simplest way to understand this package is:

```text
                 "What happened during AI execution?"
                              │
                              ▼
                        AIRunRepository
                              │
        ┌─────────────────────┼──────────────────────┐
        │                     │                      │
        ▼                     ▼                      ▼
   Stage Events           Provider Calls          Retrieval
        │                /           \                │
        │               /             \               ▼
        │             LLM           Embedding     Candidates
        │               │                             │
        │          ┌────┴────┐                        ▼
        │          ▼         ▼                    Reranker
        │       Intent    Decision
        │
        └──────────────────────────────────────────────
```

The repository layer is therefore the **persistence and query boundary for the complete AI execution history**.

---

# Summary

`packages/database/repositories/ai/` provides eight focused repositories for the AI subsystem:

```text
ai_run_repository.py
    → AI execution lifecycle

stage_event_repository.py
    → orchestration timeline

llm_call_repository.py
    → LLM provider telemetry

embedding_call_repository.py
    → embedding provider telemetry

retrieval_repository.py
    → retrieval execution + candidate provenance

reranker_call_repository.py
    → reranking telemetry

intent_prediction_repository.py
    → intent classification evidence

decision_repository.py
    → AI routing/action decisions
```

Together they provide a clean persistence boundary between the AI/application layers and PostgreSQL:

```text
                  AI Pipeline
                      │
                      ▼
             Application Services
                      │
                      ▼
          ┌─────────────────────────┐
          │   AI Repository Layer   │
          │                         │
          │ Run                     │
          │ Stage Events            │
          │ LLM Calls               │
          │ Embedding Calls         │
          │ Retrieval               │
          │ Reranking               │
          │ Intent                  │
          │ Decisions               │
          └────────────┬────────────┘
                       │
                       ▼
                AI Database Models
                       │
                       ▼
                   PostgreSQL
```

The key architectural principle is:

> **The AI system performs the intelligence; these repositories persist and retrieve the evidence of what happened.**
