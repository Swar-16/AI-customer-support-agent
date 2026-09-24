# AI Database Models

## Overview

The `packages/database/models/ai/` package contains the SQLAlchemy persistence models for the **AI execution, reasoning, retrieval, provider-call, and orchestration telemetry layer**.

These models collectively describe what happened during an AI pipeline execution without making the database layer responsible for actually running the AI pipeline.

The package persists information at several levels:

```text
AI Pipeline Execution
│
├── Run
│   └── run.py
│
├── Orchestration Stages
│   └── stage_event.py
│
├── LLM Provider Calls
│   └── llm_call.py
│
├── Embedding Provider Calls
│   └── embedding_call.py
│
├── Retrieval
│   ├── retrieval_run.py
│   └── retrieval_candidate.py
│
├── Reranking
│   └── reranker_call.py
│
└── Structured AI Outcomes
    ├── intent_prediction.py
    └── decision.py
```

Together, these models allow the system to reconstruct an AI execution from the top-level run down to individual provider calls, retrieval candidates, ranking stages, intent predictions, and final routing decisions.

---

# Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── database/
        └── models/
            └── ai/
                ├── run.py
                ├── stage_event.py
                ├── retrieval_run.py
                ├── retrieval_candidate.py
                ├── reranker_call.py
                ├── embedding_call.py
                ├── intent_prediction.py
                ├── llm_call.py
                ├── decision.py
                └── README.md
```

All nine models belong to the PostgreSQL `ai` schema.

They use the shared database declarative base and SQLAlchemy 2.x typed mappings.

---

# Model Responsibility Map

| File                     | Model                     | Primary responsibility                                       |
| ------------------------ | ------------------------- | ------------------------------------------------------------ |
| `run.py`                 | `AIRunModel`              | Represents one complete AI pipeline execution                |
| `stage_event.py`         | `AIStageEventModel`       | Records lifecycle events for individual orchestration stages |
| `llm_call.py`            | `LLMCallModel`            | Records individual LLM provider invocations                  |
| `embedding_call.py`      | `EmbeddingCallModel`      | Records embedding-provider invocations                       |
| `retrieval_run.py`       | `RetrievalRunModel`       | Records one complete retrieval execution                     |
| `retrieval_candidate.py` | `RetrievalCandidateModel` | Records candidate provenance, ranking, scores, and selection |
| `reranker_call.py`       | `RerankerCallModel`       | Records one reranking invocation                             |
| `intent_prediction.py`   | `IntentPredictionModel`   | Persists structured intent-classification results            |
| `decision.py`            | `AIDecisionModel`         | Persists the final structured AI routing/action decision     |

---

# High-Level Architecture

The models form a connected execution graph rather than nine unrelated tables.

```text
                         AI RUN
                    ┌──────────────┐
                    │ AIRunModel   │
                    └──────┬───────┘
                           │
          ┌────────────────┼──────────────────────┐
          │                │                      │
          ▼                ▼                      ▼
   Stage Events       LLM Calls             Embedding Calls
          │                │                      │
          │                ├──────────┐           │
          │                │          │           │
          │                ▼          ▼           ▼
          │             Intent     Decision   Retrieval
          │            Prediction                 │
          │                                       ▼
          │                                 Retrieval Run
          │                                       │
          │                             ┌─────────┴─────────┐
          │                             ▼                   ▼
          │                         Candidates          Reranker Call
          │                             │
          │                             ▼
          │                       Final Context
          │
          ▼
       Lifecycle
```

This makes it possible to trace:

```text
Customer request
      ↓
AI run
      ↓
orchestration stages
      ↓
intent classification
      ↓
decision
      ↓
retrieval
      ↓
embedding call
      ↓
candidate generation
      ↓
fusion / reranking
      ↓
LLM generation
```

without storing the complete customer conversation or raw retrieval content in telemetry tables.

---

# 1. `run.py` — AI Run

## `AIRunModel`

`AIRunModel` represents the **top-level execution boundary** for an AI pipeline.

Conceptually:

```text
Conversation
     │
     ▼
Trigger Message
     │
     ▼
┌──────────────────────┐
│      AI Run          │
│                      │
│ pipeline_version     │
│ trace_id             │
│ status               │
│ timing               │
│ error                │
└──────────────────────┘
```

An AI run belongs to a conversation and is associated with the message that triggered the execution.

It can also optionally reference a response message and a parent AI run.

The model therefore provides the root correlation point for most AI telemetry.

---

## Run Identity

The model uses UUIDv7 for its primary key and separately stores a UUIDv7 `trace_id`.

Conceptually:

```text
id
└── identity of this persisted AI execution

trace_id
└── distributed execution correlation
```

This allows a trace to span multiple related operations while retaining a specific identity for the individual AI run.

---

## Run Lifecycle

The database constrains the run status to:

```text
running
completed
failed
cancelled
```

The normal lifecycle is:

```text
              ┌────────────┐
              │  running   │
              └─────┬──────┘
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
     completed    failed   cancelled
```

The model persists the state; application orchestration is responsible for deciding when transitions occur.

---

## Timing

The run stores:

```text
started_at
completed_at
total_latency_ms
```

This provides whole-pipeline latency.

Individual components have their own timing records, so operators can move from:

```text
Total AI latency
      ↓
Stage latency
      ↓
Provider-call latency
      ↓
Retrieval/reranker latency
```

---

# 2. `stage_event.py` — AI Stage Events

## `AIStageEventModel`

`AIStageEventModel` represents a **single lifecycle event inside an AI run**.

A stage event can represent:

```text
stage_started
stage_completed
stage_failed
```

The model supports stages such as:

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

These allowed values are enforced at the database level.

---

## Stage Event Relationship

```text
AIRunModel
    │
    ├── stage_event
    ├── stage_event
    ├── stage_event
    ├── stage_event
    └── ...
```

The stage event references `ai.runs.id` with cascade deletion.

---

## Payload Invariants

The model deliberately validates event semantics.

For example:

```text
stage_started
    ├── duration = NULL
    ├── error_code = NULL
    └── retryable = NULL

stage_completed
    ├── error_code = NULL
    └── retryable = NULL

stage_failed
    ├── error_code != NULL
    └── retryable != NULL
```

These constraints prevent inconsistent telemetry records from being stored.

---

# 3. `llm_call.py` — LLM Provider Calls

## `LLMCallModel`

`LLMCallModel` represents **one invocation of an LLM provider**.

It is intentionally separate from `AIRunModel`.

One AI run can therefore contain multiple LLM calls:

```text
AIRun
  │
  ├── LLM call → intent classification
  ├── LLM call → query rewrite
  ├── LLM call → answer generation
  └── LLM call → action decision
```

The supported purposes include:

```text
intent_classification
query_rewrite
answer_generation
action_decision
escalation_summary
guardrail_validation
conversation_summary
conversation_title
other
```

The database constrains these values.

---

## Provider Identity

Each LLM call records:

```text
provider
model
purpose
```

and can optionally reference a prompt version.

This gives an execution record such as:

```text
AI Run
 │
 └── LLM Call
      ├── provider = ...
      ├── model = ...
      ├── purpose = answer_generation
      └── prompt_version_id = ...
```

---

## Usage and Cost

The model tracks operational usage such as:

```text
input_tokens
output_tokens
cached_input_tokens
total_tokens
estimated_cost_usd
latency_ms
```

Values are constrained to prevent negative token/cost/latency data. Temperature is also constrained to the valid range `0–2`.

This makes the model useful for:

* provider monitoring;
* model comparison;
* cost analysis;
* token-usage analysis;
* latency analysis.

---

# 4. `embedding_call.py` — Embedding Provider Calls

## `EmbeddingCallModel`

This model records **an embedding-provider invocation**.

It is important to distinguish:

```text
EmbeddingCallModel
    ≠
Persisted Knowledge Chunk Embedding
```

The model tracks the **provider operation**, not the actual vector stored for a knowledge chunk.

It supports:

```text
query
document_ingestion
reindex
evaluation
other
```

as embedding-call purposes.

---

## Typical Uses

### Query-time embedding

```text
Customer Query
     ↓
Embedding Provider
     ↓
EmbeddingCallModel
```

### Knowledge ingestion

```text
Knowledge Version
     ↓
Chunk batch
     ↓
Embedding Provider
     ↓
EmbeddingCallModel
```

### Reindexing

```text
Existing Knowledge
     ↓
New Embedding Profile
     ↓
Embedding Provider
     ↓
EmbeddingCallModel
```

---

## Lifecycle

Embedding calls use:

```text
started
success
failed
timeout
```

The database ensures that successful calls have completed timestamps and dimensions, while failures/timeouts contain error information.

The model also tracks:

```text
provider
model
provider revision
input count
input character count
dimensions
latency
request fingerprint
```

Raw text and vectors are explicitly excluded.

---

# 5. `retrieval_run.py` — Retrieval Execution

## `RetrievalRunModel`

`RetrievalRunModel` represents **one complete retrieval operation**.

It covers the complete retrieval pipeline:

```text
Query Preparation
       ↓
Vector Retrieval
       ↓
Lexical Retrieval
       ↓
Fusion
       ↓
Optional Reranking
       ↓
Context Selection
```

The model explicitly avoids storing the raw query or retrieved chunk content.

---

## Retrieval Mode

The supported modes are:

```text
vector
lexical
hybrid
```

---

## Candidate Counters

A retrieval run records counts for different stages:

```text
vector_candidate_count
lexical_candidate_count
fused_candidate_count
reranked_candidate_count
selected_candidate_count
```

This provides a compact view of the retrieval pipeline:

```text
Vector candidates ──────┐
                        │
Lexical candidates ─────┤
                        ▼
                      Fusion
                        │
                        ▼
                    Reranking
                        │
                        ▼
                   Final Context
```

---

## Context Statistics

The model can also capture:

```text
context_block_count
context_token_count
context_truncated
zero_result
```

This makes it possible to distinguish:

```text
No results
    vs
Results found but context truncated
    vs
Results successfully selected
```

---

## Retrieval Latency

Latency can be captured independently for:

```text
vector_latency_ms
lexical_latency_ms
fusion_latency_ms
reranker_latency_ms
context_build_latency_ms
total_latency_ms
```

This enables bottleneck analysis across the retrieval pipeline.

---

# 6. `retrieval_candidate.py` — Retrieval Candidates

## `RetrievalCandidateModel`

A retrieval run describes **the retrieval operation**.

A retrieval candidate describes **what participated in that operation**.

```text
Retrieval Run
    │
    ├── Candidate A
    ├── Candidate B
    ├── Candidate C
    └── Candidate D
```

Each candidate retains source identity:

```text
chunk_id
version_id
document_id
```

and belongs to a retrieval run.

---

## Ranking History

The model preserves ranking information across the retrieval pipeline:

```text
vector_rank
lexical_rank
fusion_rank
reranker_rank
final_rank
```

This is extremely useful for debugging ranking behavior.

For example:

```text
Candidate X

Vector rank       = 4
Lexical rank      = 1
Fusion rank       = 2
Reranker rank     = 5
Final rank        = 5
```

---

## Score History

The corresponding scores can include:

```text
vector_similarity
lexical_score
fusion_score
reranker_score
final_score
```

The system therefore does not collapse every ranking signal into one opaque value.

---

## Context Selection

Each candidate has:

```text
selected_for_context
rejection_reason
```

This distinguishes:

```text
Retrieved
   ↓
Ranked
   ↓
Selected / Rejected
```

The model can therefore explain why a candidate participated in retrieval but did not reach the final grounding context.

---

## Content Privacy

The model may store a bounded `content_fingerprint`, but not the actual retrieved content.

This maintains provenance without turning telemetry into another copy of the knowledge base.

---

# 7. `reranker_call.py` — Reranker Invocation

## `RerankerCallModel`

`RerankerCallModel` records **one reranking operation** associated with a retrieval run.

```text
Retrieval Run
     │
     ▼
Candidate Set
     │
     ▼
Reranker Call
     │
     ▼
Reordered Candidates
```

It supports:

* deterministic passthrough reranking;
* local reranking models;
* external reranking providers.

The model explicitly forbids persistence of raw query and candidate content.

---

## Provider Identity

A reranker call stores:

```text
reranker_id
provider
model
revision
```

and can also store a provider request ID.

---

## Candidate Cardinality

The model tracks:

```text
input_candidate_count
requested_limit
output_candidate_count
```

with database constraints ensuring:

```text
output_candidate_count
    ≤ input_candidate_count

output_candidate_count
    ≤ requested_limit
```

---

## Lifecycle

The lifecycle is:

```text
started
success
failed
timeout
```

The database enforces consistency between lifecycle state, completion timestamp, latency, and error code.

Conceptually:

```text
started
   │
   ├── success
   │
   ├── failed
   │
   └── timeout
```

---

## Current Reranker Architecture

The persistence model is provider-neutral.

Therefore it can record:

```text
Passthrough reranker
        OR
Local model
        OR
External provider such as Jina
```

The database model does not require a particular reranker implementation.

**Important:** the current application architecture has the reranker boundary prepared for a real provider, but a real learned/provider reranker is not necessarily active yet. The model exists so the telemetry contract does not need to change when one is introduced.

---

# 8. `intent_prediction.py` — Intent Classification

## `IntentPredictionModel`

This model persists the structured result of AI intent classification.

An intent prediction belongs to an AI run and may optionally reference the LLM call that produced it.

```text
AI Run
  │
  └── LLM Call
        │
        ▼
Intent Prediction
```

---

## Stored Prediction

The model contains:

```text
intent
confidence
entities
needs_clarification
escalation_signals
reasoning_summary
```

This is the structured AI outcome, rather than the provider-call telemetry itself.

---

## Confidence

Confidence is stored using:

```text
Numeric(5,4)
```

and must remain within:

```text
0 ≤ confidence ≤ 1
```

---

## Escalation Signals

The database restricts escalation signals to the supported values:

```text
explicit_human_request
severe_customer_dissatisfaction
```

and ensures that the JSON structure is an array.

This allows downstream analytics to query escalation-related classification behavior without parsing free-form text.

---

# 9. `decision.py` — AI Decision

## `AIDecisionModel`

`AIDecisionModel` stores the structured routing/action decision produced by the AI pipeline.

Supported decision types include:

```text
answer
retrieve_information
perform_action
ask_clarification
escalate
```

---

## Relationship to LLM Calls

A decision belongs to an AI run and can optionally reference the LLM call that produced it:

```text
AI Run
   │
   └── LLM Call
          │
          ▼
       Decision
```

The LLM call uses `SET NULL` on deletion, so deleting the provider-call record does not destroy the final decision.

---

## Decision Information

The model stores:

```text
decision_type
confidence
reason_code
reason_summary
metadata
created_at
```

The decision is therefore the durable representation of **what the AI pipeline decided to do**, while the LLM call represents **how a provider was invoked to obtain an AI result**.

---

# Complete Relationship Graph

The nine models can be viewed together as follows:

```text
                                  ┌────────────────────┐
                                  │     AIRunModel     │
                                  │      ai.runs       │
                                  └─────────┬──────────┘
                                            │
             ┌──────────────────────────────┼──────────────────────────────┐
             │                              │                              │
             ▼                              ▼                              ▼
     ┌───────────────┐             ┌────────────────┐             ┌─────────────────┐
     │ Stage Events  │             │   LLM Calls    │             │Embedding Calls  │
     │               │             │                │             │                 │
     │ stage_event   │             │ llm_call       │             │ embedding_call  │
     └───────────────┘             └───────┬────────┘             └─────────────────┘
                                           │
                              ┌────────────┴─────────────┐
                              │                          │
                              ▼                          ▼
                    ┌──────────────────┐       ┌──────────────────┐
                    │ Intent Prediction│       │  AI Decision     │
                    │                  │       │                  │
                    │intent_prediction │       │    decision      │
                    └──────────────────┘       └──────────────────┘


                     Retrieval Path
                     ───────────────

                          AIRun
                            │
                            ▼
                ┌─────────────────────┐
                │   Retrieval Run     │
                │   retrieval_run     │
                └──────────┬──────────┘
                        │  |
                    ┌──────┴─────────┐
                    ▼               ▼
                Candidates       Reranker Call
                    │               │
                    │               │
                    ▼               ▼
                retrieval_       reranker_call
                candidate
```

---

# End-to-End AI Execution

A typical request may produce a graph like:

```text
Customer Message
       │
       ▼
    AI Run
       │
       ├──────────────────────────────┐
       │                              │
       ▼                              ▼
 Stage: received                 LLM Call
                                      │
                                      ▼
                               Intent Prediction
                                      │
                                      ▼
                               Stage: intent_classified
                                      │
                                      ▼
                                  Decision
                                      │
                                      ▼
                             Stage: decision_made
                                      │
                                      ▼
                               Retrieval Run
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                    ▼                 ▼                 ▼
             Embedding Call    Retrieval Candidates    ...
                    │                 │
                    │                 ▼
                    │            Fusion/Ranking
                    │                 │
                    │                 ▼
                    │           Reranker Call
                    │                 │
                    │                 ▼
                    │           Final Context
                    │                 │
                    └─────────────────┘
                                      │
                                      ▼
                                  LLM Call
                                      │
                                      ▼
                              Answer Generation
                                      │
                                      ▼
                              Stage: completed
```

This gives the system an auditable technical representation of the AI pipeline without storing the complete sensitive content involved in every step.

---

# Foreign-Key Relationships

The important relationships are:

```text
ai.runs
   │
   ├── ai.stage_events
   ├── ai.llm_calls
   ├── ai.embedding_calls
   ├── ai.retrieval_runs
   ├── ai.intent_predictions
   └── ai.decisions

ai.retrieval_runs
   │
   ├── ai.retrieval_candidates
   └── ai.reranker_calls

ai.llm_calls
   │
   ├── ai.intent_predictions
   └── ai.decisions
```

Some relationships use cascading deletion while others use `SET NULL`.

The distinction is intentional:

```text
Child is meaningless without parent
    → CASCADE

Historical result should survive provider-call deletion
    → SET NULL
```

For example, intent predictions and decisions can preserve their AI outcome even if an associated LLM-call reference later disappears.

---

# Lifecycle vs Outcome vs Telemetry

The models can also be divided into three conceptual categories.

## Execution Lifecycle

```text
run.py
stage_event.py
```

These answer:

> What was the AI pipeline doing?

---

## Provider Telemetry

```text
llm_call.py
embedding_call.py
reranker_call.py
```

These answer:

> Which external/model operation happened, with what provider/model, latency, status, and usage?

---

## AI / Retrieval Outcomes

```text
intent_prediction.py
decision.py
retrieval_run.py
retrieval_candidate.py
```

These answer:

> What did the AI/retrieval system determine and what evidence participated in that result?

---

# Privacy and Data-Minimization Model

These tables are designed as **operational telemetry and structured-outcome storage**, not as a secondary content store.

The system intentionally avoids persisting:

```text
customer message text
raw prompts
generated answers
raw retrieval queries
retrieved chunk content
candidate content
conversation context
embedding vectors
```

Instead, it prefers:

```text
IDs
fingerprints
counts
ranks
scores
latencies
provider/model identifiers
status
error codes
bounded metadata
timestamps
```

The retrieval telemetry architecture explicitly follows this principle and uses fingerprints instead of raw query/content values.

---

# Fingerprints

Where correlation requires identifying a textual input without storing the input itself, the system uses bounded fingerprints.

For example:

```text
     Raw Query
        │
        ▼
     SHA-256
        │
        ▼
query_fingerprint
```

The same principle is used for retrieval and reranking telemetry.

This allows operators to answer:

> "Did these two operations process the same query?"

without storing the actual query text.

---

# Timing Strategy

Timing exists at multiple levels.

```text
AI Run
  └── total_latency_ms

Stage Event
  └── duration_ms

LLM Call
  └── latency_ms

Embedding Call
  └── latency_ms

Retrieval Run
  ├── vector_latency_ms
  ├── lexical_latency_ms
  ├── fusion_latency_ms
  ├── reranker_latency_ms
  ├── context_build_latency_ms
  └── total_latency_ms

Reranker Call
  └── latency_ms
```

This enables progressively deeper performance analysis:

```text
Why was the AI response slow?
        │
        ▼
AI run latency
        │
        ▼
Which stage?
        │
        ▼
Which provider operation?
        │
        ▼
Which retrieval/reranking component?
```

---

# Error Representation

Provider failures are represented structurally rather than by storing arbitrary exception objects.

Typical fields include:

```text
error_code
error_message
status
latency
provider_request_id
```

For provider calls, the common status vocabulary is:

```text
started
success
failed
timeout
```

This is used by both LLM and embedding telemetry and by reranker calls.

Structured error fields make operational queries possible:

```text
Find all provider timeouts
Find failures by provider
Find failures by model
Find slow calls
Find failed retrieval runs
```

without parsing exception strings.

---

# Database-Level Invariants

These models deliberately place important invariants inside PostgreSQL `CHECK` constraints.

Examples include:

```text
Status values
      ↓
Allowed lifecycle states

Confidence
      ↓
0 <= confidence <= 1

Latency
      ↓
>= 0

Token counts
      ↓
>= 0

Candidate counts
      ↓
>= 0

Reranker output
      ↓
<= input count
      ↓
<= requested limit

Completion timestamp
      ↓
>= start timestamp
```

This is important because application-level validation alone cannot protect the database from every possible write path.

---

# UUID Strategy

The models use PostgreSQL UUIDs with UUIDv7 server-side defaults.

This applies to the primary identifiers of the AI telemetry records.

Conceptually:

```text
INSERT
  │
  ▼
PostgreSQL
  │
  └── uuidv7()
       │
       ▼
    Record ID
```

This keeps identifier generation consistent across the persistence layer.

---

# Indexing Philosophy

Indexes are primarily designed around operational investigation.

Common dimensions include:

```text
AI run
Trace
Conversation
Provider
Model
Status
Purpose
Error code
Timestamp
Latency
Retrieval run
Stage
Decision type
Intent
```

This supports queries such as:

```text
Recent failed AI runs
Slow LLM calls
LLM cost by provider/model
Embedding failures
Retrieval runs with zero results
Reranker timeouts
Candidates selected for context
Intent distributions
Escalation signals
Decision distributions
```

The retrieval and reranker models in particular have indexes optimized around run, trace, provider/model, status, error, and latency investigations.

---

# Transaction Boundary

These models are persistence models only.

The telemetry/application layer decides **when** records are committed.

A key architectural principle is avoiding long-running database transactions around external AI operations.

Avoid:

```text
BEGIN
   │
   ├── call embedding provider
   ├── call reranker
   ├── call LLM
   └── COMMIT
```

Instead:

```text
Provider operation
      │
      ▼
Telemetry update
      │
      ▼
Short DB transaction
      │
      ▼
    COMMIT
```

The telemetry architecture explicitly uses short transactions for stage, retrieval, reranker, and provider-call lifecycle records.

---

# Relationship to AI Telemetry

These database models are consumed by the higher-level telemetry/application components.

For example:

```text
LLM Provider
     │
     ▼
LLM Instrumentation
     │
     ▼
LLM Call Recorder
     │
     ▼
LLMCallModel
```

Similarly:

```text
Retrieval Pipeline
     │
     ▼
Retrieval Telemetry Recorder
     │
     ├── RetrievalRunModel
     └── RetrievalCandidateModel
```

and:

```text
Reranker
     │
     ▼
Reranker Telemetry Recorder
     │
     ▼
RerankerCallModel
```

The application telemetry layer translates execution facts into these persistence models rather than embedding database concerns inside provider implementations.

---

# Relationship Between LLM Calls and AI Outcomes

A particularly important distinction is:

```text
LLMCallModel
    =
    "A provider invocation occurred."

IntentPredictionModel
    =
    "The AI classified the request as this intent."

AIDecisionModel
    =
    "The AI pipeline selected this routing/action."
```

For example:

```text
LLM Call
provider = groq
model = ...
purpose = intent_classification
status = success
latency = ...

             │
             ▼

Intent Prediction
intent = refund_request
confidence = ...
needs_clarification = false

             │
             ▼

Decision
decision_type = retrieve_information
reason_code = ...
```

This separation prevents provider telemetry from being confused with business-level AI outcomes.

---

# Relationship Between Retrieval and Embedding Calls

Embedding telemetry is also intentionally separate from retrieval telemetry.

```text
EmbeddingCallModel
    │
    └── "The embedding provider was called."

RetrievalRunModel
    │
    └── "The retrieval pipeline executed."

RetrievalCandidateModel
    │
    └── "These candidates participated in ranking."
```

For a semantic retrieval request:

```text
Customer Query
      │
      ▼
Embedding Call
      │
      ▼
Query Vector
      │
      ▼
Vector Search
      │
      ▼
Retrieval Run
      │
      ▼
Retrieval Candidates
```

This separation allows embedding-provider failures and retrieval-pipeline failures to be analyzed independently.

---

# Relationship Between Retrieval and Reranking

Reranking is a second-stage operation over retrieval candidates.

```text
Retrieval Run
      │
      ▼
Candidates
      │
      ▼
Reranker Call
      │
      ▼
Updated Candidate Ranking
      │
      ▼
Final Context
```

The candidate model retains both pre- and post-reranking information:

```text
fusion_rank
reranker_rank
final_rank

fusion_score
reranker_score
final_score
```

This makes ranking behavior inspectable instead of opaque.

---

# Current Reranker Status

The persistence model supports real reranker providers, but the architecture is intentionally provider-neutral.

At present:

```text
Reranker Boundary
       │
       ├── Passthrough implementation
       │
       └── Future external/provider implementation
              └── e.g. Jina
```

A future real reranker can be introduced without redesigning the persistence model because provider, model, revision, request identity, candidate counts, latency, status, and errors are already represented.

---

# What These Models Do Not Do

These models should remain persistence-focused.

They should **not**:

* execute LLM requests;
* call embedding providers;
* perform vector search;
* perform lexical search;
* execute reranking;
* construct prompts;
* classify intent;
* make routing decisions;
* perform retrieval;
* build grounding context;
* implement retries;
* own provider SDK behavior.

Instead:

```text
AI / Knowledge Application
          │
          ▼
Domain Services / Providers
          │
          ▼
Telemetry / Repositories
          │
          ▼
   Database Models
```

---

# Testing Considerations

Tests for these models should focus primarily on persistence invariants.

## Lifecycle Tests

Verify:

```text
started
success
failed
timeout
```

are represented correctly.

---

## Constraint Tests

Verify invalid values are rejected:

```text
negative latency
negative tokens
invalid status
invalid purpose
invalid confidence
invalid candidate counts
invalid lifecycle combinations
```

---

## Relationship Tests

Verify:

```text
AI Run
  → stage events

AI Run
  → LLM calls

AI Run
  → embedding calls

AI Run
  → retrieval runs

Retrieval Run
  → candidates

Retrieval Run
  → reranker calls

LLM Call
  → intent prediction

LLM Call
  → decision
```

---

## Privacy Tests

Ensure telemetry records never accidentally contain:

```text
raw customer queries
raw prompts
retrieved content
generated answers
vectors
conversation context
```

---

# Quick Mental Model

The nine files can be remembered as five layers:

```text
1. EXECUTION
   run.py
   stage_event.py

2. PROVIDER CALLS
   llm_call.py
   embedding_call.py
   reranker_call.py

3. RETRIEVAL
   retrieval_run.py
   retrieval_candidate.py

4. AI OUTCOMES
   intent_prediction.py
   decision.py

5. CORRELATION
   UUIDs
   trace IDs
   foreign keys
   timestamps
   fingerprints
```

Or, more simply:

```text
             WHAT HAPPENED?
                   │
                 AI Run
                   │
          ┌────────┴────────┐
          │                 │
       Stages        Provider Calls
                            │
                 ┌──────────┼──────────┐
                 ▼          ▼          ▼
               LLM      Embedding   Reranker
                 │                     │
                 ▼                     ▼
             AI Outcomes          Retrieval
                 │                     │
          ┌──────┴──────┐       ┌─────┴─────┐
          ▼             ▼       ▼           ▼
       Intent        Decision  Run       Candidates
```

---

# Summary

`packages/database/models/ai/` is the **persistent execution and telemetry model layer for the AI system**.

The nine models collectively provide visibility into the entire AI pipeline:

```text
AIRun
  │
  ├── Stage Events
  │
  ├── LLM Calls
  │      ├── Intent Predictions
  │      └── Decisions
  │
  ├── Embedding Calls
  │
  └── Retrieval Runs
         │
         ├── Retrieval Candidates
         │
         └── Reranker Calls
```

The design intentionally separates:

```text
Execution
   ≠
Provider telemetry
   ≠
Retrieval telemetry
   ≠
AI outcomes
```

while connecting everything through stable identifiers and foreign-key relationships.

The resulting persistence layer can answer questions such as:

* **Which AI run executed?**
* **Which stages completed or failed?**
* **Which LLM/provider/model was called?**
* **How many tokens were consumed?**
* **What did the intent classifier predict?**
* **What decision did the AI make?**
* **Was an embedding provider called successfully?**
* **How did retrieval perform?**
* **Which candidates participated in ranking?**
* **Which candidates reached grounding context?**
* **Was reranking used?**
* **Which provider/model performed reranking?**
* **Where did latency or failure occur?**

while maintaining the core privacy boundary:

> **Persist execution facts, structured outcomes, identifiers, rankings, timing, and bounded metadata — not raw customer/AI/knowledge content.**
