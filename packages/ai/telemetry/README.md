# AI Telemetry

## Overview

The `telemetry` package provides the observability and persistence layer for the AI subsystem.

It records operational information about:

* orchestration stages;
* retrieval runs;
* retrieval candidates;
* reranker calls;
* timing and latency;
* provider/model identity;
* lifecycle status;
* errors and retryability;
* candidate ranks and scores;
* selection into the final grounding context;
* bounded fingerprints and identifiers.

The package is intentionally designed around a **content-minimizing telemetry model**.

It records enough information to answer questions such as:

```text
How long did retrieval take?
Which retrieval strategy was used?
How many vector/lexical candidates were produced?
How many candidates survived fusion and reranking?
Which candidates were selected for context?
How long did reranking take?
Which reranker/model handled the request?
Did the reranker fail or timeout?
Which orchestration stage failed?
Was an error retryable?
```

But it deliberately avoids storing:

```text
customer message text
raw prompts
generated answers
query text
retrieved chunk content
candidate content
conversation context
```

Instead, sensitive textual values are represented through bounded fingerprints where appropriate. The retrieval recorder explicitly states that query text and retrieved chunk content are never persisted.

---

# Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── ai/
        └── telemetry/
            ├── retrieval_recorder.py
            ├── reranker_recorder.py
            ├── stage_event_sink.py
            └── README.md
```

| File                    | Responsibility                                                                           |
| ----------------------- | ---------------------------------------------------------------------------------------- |
| `retrieval_recorder.py` | Accumulates and persists retrieval-run telemetry and candidate-level ranking information |
| `reranker_recorder.py`  | Persists reranker invocation lifecycle, timing, status, and bounded identity information |
| `stage_event_sink.py`   | Persists orchestration-stage events through a short database transaction                 |

---

# Architecture

The three components observe different layers of the AI pipeline.

```text
                         AI Orchestration
                                │
                                │ stage events
                                ▼
                    ┌──────────────────────┐
                    │ DatabaseStageEvent   │
                    │ Sink                 │
                    └──────────┬───────────┘
                               │
                               ▼
                         stage_events


                         Retrieval Pipeline
                                │
              ┌─────────────────┼──────────────────┐
              │                 │                  │
              ▼                 ▼                  ▼
           Vector            Lexical             Fusion
              │                 │                  │
              └─────────────────┼──────────────────┘
                                │
                                ▼
                           Reranking
                                │
                                ▼
                       Grounding Context
                                │
                                ▼
                    RetrievalTelemetryRecorder
                                │
                                ▼
                        retrieval_run
                                │
                                ▼
                     retrieval_candidates


                           Reranker
                              │
                              ▼
                   RerankerTelemetryRecorder
                              │
                              ▼
                       reranker_calls
```

The telemetry layer therefore captures both:

1. **coarse-grained workflow events**, and
2. **fine-grained retrieval/reranking execution details**.

---

# Core Design Principles

## 1. Telemetry must not contain customer content

The telemetry layer deliberately avoids persisting:

* customer messages;
* prompts;
* generated responses;
* retrieved document content;
* retrieved chunk text;
* conversation context.

The stage-event sink explicitly prohibits customer messages, prompts, generated answers, retrieved content, and conversation context from event metadata.

---

## 2. Fingerprints instead of raw text

When telemetry needs to correlate textual input, it stores a SHA-256 fingerprint.

For example:

```text
query text
    │
    ▼
SHA-256
    │
    ▼
query_fingerprint
```

The retrieval recorder uses SHA-256 for query/candidate content fingerprints.

This allows equality/correlation analysis without storing the original text.

---

## 3. Telemetry is operational, not application data

The telemetry layer records information useful for:

* debugging;
* performance analysis;
* provider monitoring;
* retrieval-quality analysis;
* failure investigation;
* latency analysis;
* operational dashboards.

It should not become a secondary storage system for customer conversations or knowledge-base content.

---

# 1. Retrieval Telemetry

## `RetrievalTelemetryRecorder`

`RetrievalTelemetryRecorder` is a **request-scoped retrieval telemetry accumulator**.

Its responsibility is to observe a complete retrieval pipeline and eventually persist:

```text
retrieval run
+
candidate telemetry
```

The recorder keeps candidate information in memory during the retrieval process and persists it when the run is finalized.

---

# Retrieval Lifecycle

The lifecycle is:

```text
start()
   │
   ▼
optional attach_embedding_call()
   │
   ▼
record_vector()
   │
   ▼
record_lexical()
   │
   ▼
record_fusion()
   │
   ▼
record_reranking()
   │
   ▼
record_final()
   │
   ▼
complete()
```

If retrieval fails:

```text
start()
   │
   ▼
retrieval processing
   │
   ▼
fail()
```

---

# Starting a Retrieval Run

The `start()` method creates a new `RetrievalRunModel`.

It captures information including:

* AI run ID;
* trace ID;
* conversation ID;
* retrieval mode;
* profile identity;
* configuration fingerprint;
* query fingerprint;
* query character count;
* requested candidate limit;
* stage candidate counts;
* context statistics;
* whether reranking is enabled;
* latency placeholders;
* lifecycle status;
* selected metadata.

The query itself is **not persisted**.

Instead:

```text
original query
      │
      ├── character count
      │
      └── SHA-256 fingerprint
```

is recorded.

---

# Retrieval Run Identity

A retrieval run receives a UUIDv7:

```python
run_id = uuid7()
```

The recorder then stores this identifier internally:

```text
self._run_id
```

The identifier is exposed through:

```python
retrieval_run_id
```

This gives downstream telemetry, especially reranker telemetry, a stable reference to the retrieval run.

---

# Retrieval Modes

The recorder derives retrieval mode from the configured retrieval profile.

Possible modes are:

```text
hybrid
vector
lexical
```

The logic is:

```text
vector enabled + lexical enabled
        ↓
      hybrid

vector enabled only
        ↓
      vector

otherwise
        ↓
      lexical
```

---

# Retrieval Profile Telemetry

The run records:

```text
profile_identity
configuration_fingerprint
final_candidate_limit
vector_enabled
lexical_enabled
reranking_enabled
```

This makes telemetry interpretable even when retrieval configuration changes over time.

A historical retrieval run can therefore be associated with the configuration that produced it without persisting the full profile object.

---

# Embedding Call Association

`attach_embedding_call()` associates an embedding invocation with an existing retrieval run.

```text
Retrieval Run
      │
      └── embedding_call_id
```

The embedding call ID must be a UUID.

The run must still have:

```text
status = "started"
```

before the association can be made.

This creates a useful trace:

```text
AI Run
  │
  └── Retrieval Run
          │
          └── Embedding Call
```

---

# Retrieval Stage Recording

The recorder tracks four intermediate retrieval stages.

## Vector Retrieval

```python
record_vector(candidates, latency_ms)
```

Records:

* number of vector candidates;
* vector latency;
* vector rank for every candidate.

---

## Lexical Retrieval

```python
record_lexical(candidates, latency_ms)
```

Records:

* number of lexical candidates;
* lexical latency;
* lexical rank.

---

## Fusion

```python
record_fusion(candidates, latency_ms)
```

Records:

* fused candidate count;
* fusion latency;
* fusion rank.

---

## Reranking

```python
record_reranking(candidates, latency_ms)
```

Records:

* reranked candidate count;
* reranker latency;
* reranker rank.

---

# Final Candidate Recording

```python
record_final(candidates)
```

assigns each candidate its final retrieval rank.

The recorder maintains candidate identity across all stages using:

```text
candidate.chunk_id
```

This allows the same candidate to be tracked through:

```text
vector rank
    ↓
lexical rank
    ↓
fusion rank
    ↓
reranker rank
    ↓
final rank
```

---

# Candidate Telemetry

Internally, candidate state is represented by:

```python
_CandidateTelemetry
```

with:

```text
candidate
vector_rank
lexical_rank
fusion_rank
reranker_rank
final_rank
```

This is deliberately request-scoped state.

The candidate information remains in memory until finalization.

---

# Candidate Scores

When candidate telemetry is persisted, the recorder stores:

```text
vector_similarity
lexical_score
fusion_score
reranker_score
final_score
```

The final score is selected according to the highest applicable ranking signal:

```text
reranker_score
      ↓
fusion_score
      ↓
valid vector_similarity
      ↓
lexical_score
```

The implementation gives reranker score precedence over fusion score, followed by valid vector similarity and lexical score.

---

# Selected Candidates

The final grounding context determines which candidates were actually selected.

The recorder creates:

```text
selected_for_context
```

based on whether the candidate's chunk ID exists in the final context's chunk IDs.

Selected candidates receive:

```text
selected_for_context = true
```

while non-selected candidates receive:

```text
selected_for_context = false
rejection_reason = "not_selected_for_context"
```

This makes it possible to analyze the gap between:

```text
retrieved candidates
```

and:

```text
actual grounding context
```

---

# Candidate Metadata

Persisted candidate metadata includes:

```text
chunk_index
methods
```

The retrieval methods are normalized into sorted values.

This provides additional diagnostic information without storing the candidate's actual content.

---

# Candidate Content Privacy

The candidate's actual content is never stored.

Instead:

```text
candidate.content
       │
       ▼
SHA-256
       │
       ▼
content_fingerprint
```

This provides a bounded identity/correlation mechanism without duplicating knowledge-base content into telemetry.

---

# Completing Retrieval

`complete()` receives:

```text
GroundingContext
completed_at
total_latency_ms
context_build_latency_ms
```

It then:

1. validates the context and timing values;
2. identifies selected chunks;
3. converts in-memory candidate telemetry to database models;
4. verifies the run still exists;
5. verifies the run is still `"started"`;
6. persists candidate records;
7. marks the run successful;
8. records counts and latency;
9. commits the transaction.

---

# Retrieval Completion Metrics

A successful run records:

```text
vector_candidate_count
lexical_candidate_count
fused_candidate_count
reranked_candidate_count
selected_candidate_count
context_block_count
context_token_count
vector_latency_ms
lexical_latency_ms
fusion_latency_ms
reranker_latency_ms
context_build_latency_ms
total_latency_ms
```

It also records:

```text
reranker_used
context_truncated
```

These values make the retrieval pipeline measurable end-to-end.

---

# Retrieval Failure

`fail()` finalizes an active retrieval run as failed.

It records:

```text
completed_at
total_latency_ms
error_code
error_message
timeout
```

The recorder verifies that the run exists and is still in:

```text
started
```

state before marking it failed.

This prevents accidental modification of already-finalized telemetry.

---

# Retrieval State Machine

Conceptually:

```text
             ┌──────────────┐
             │    started   │
             └──────┬───────┘
                    │
          ┌─────────┴─────────┐
          │                   │
          ▼                   ▼
       complete()           fail()
          │                   │
          ▼                   ▼
      succeeded             failed
```

Once finalized, the run should not be mutated through the normal recorder lifecycle.

---

# Retrieval Transaction Model

The recorder uses a Unit of Work factory:

```python
uow_factory
```

and requires a `RetrievalRepository`.

The recorder itself does not treat the request's entire retrieval lifecycle as one open database transaction.

Instead, the initial run is persisted and committed, and finalization later persists candidate information and updates the run.

This keeps database transactions short.

---

# 2. Reranker Telemetry

## `RerankerTelemetryRecorder`

`RerankerTelemetryRecorder` records the lifecycle of a reranker invocation.

Its purpose is narrower than retrieval telemetry:

```text
retrieval run
      │
      ▼
reranker invocation
      │
      ├── started
      ├── succeeded
      ├── failed
      └── timed out
```

The recorder stores identifiers, counts, timing, lifecycle state, and bounded fingerprints rather than query/candidate content.

---

# Retrieval Run Dependency

A reranker call belongs to a retrieval run.

Therefore:

```text
RetrievalRun
      │
      └── RerankerCall
```

The retrieval run must already have been committed before `start_call()` executes because the reranker call's retrieval-run ID is a foreign key.

This creates an important ordering constraint:

```text
start retrieval
      ↓
commit retrieval run
      ↓
start reranker call
```

---

# Starting a Reranker Call

`start_call()` validates:

```text
RerankingRequest
RerankerDescriptor
timezone-aware started_at
```

It then creates a UUIDv7 call ID and persists:

```text
retrieval_run_id
trace_id
reranker_id
provider
model
revision
query_fingerprint
input_candidate_count
requested_limit
output_candidate_count = 0
status = started
provider_request_id = None
error_code = None
error_message = None
started_at
completed_at = None
```

---

# Reranker Query Privacy

The reranker query text is not persisted.

Instead:

```text
request.query.text
       │
       ▼
SHA-256
       │
       ▼
query_fingerprint
```

---

# Candidate Identity Fingerprint

The reranker recorder also produces:

```text
candidate_identity_fingerprint
```

This is generated from the candidate chunk IDs rather than their content.

The digest begins with a versioned domain separator:

```text
reranker-candidates-v1
```

and then incorporates each candidate's UUID bytes with length framing.

Conceptually:

```text
candidate chunk IDs
       │
       ▼
versioned hash input
       │
       ▼
SHA-256
       │
       ▼
candidate_identity_fingerprint
```

This allows candidate-set identity to be correlated without storing candidate text.

---

# Reranker Descriptor

The reranker descriptor supplies:

```text
reranker_id
provider
model
revision
```

These fields allow telemetry to answer:

```text
Which reranker was used?
Which provider served it?
Which model version was involved?
Was a particular revision involved?
```

---

# Completing a Reranker Call

`complete_call()` requires:

```text
call_id
RerankingResponse
completed_at
latency_ms
optional provider_request_id
```

It validates the response and completion timing, retrieves the existing started call, and marks it successful.

The persisted result includes:

```text
completed_at
latency_ms
output_candidate_count
provider_request_id
status = succeeded
```

---

# Failed Reranker Call

`fail_call()` records:

```text
completed_at
latency_ms
error_code
error_message
provider_request_id
```

Both error fields are normalized and must be non-empty strings.

The existing call must still be in:

```text
started
```

state before it can be marked failed.

---

# Timed-Out Reranker Call

`timeout_call()` records timeout completion separately.

It stores:

```text
completed_at
latency_ms
provider_request_id
```

and delegates lifecycle transition to:

```text
repository.mark_timeout()
```

This makes timeout distinguishable from an ordinary provider failure.

---

# Reranker State Machine

```text
                 ┌───────────┐
                 │  started  │
                 └─────┬─────┘
                       │
          ┌────────────┼─────────────┐
          │            │             │
          ▼            ▼             ▼
      complete()     fail()       timeout()
          │            │             │
          ▼            ▼             ▼
     succeeded       failed       timed_out
```

The recorder explicitly rejects attempts to finalize an already-finalized call.

---

# Reranker Repository Dependency

The recorder expects the Unit of Work to expose:

```python
reranker_calls: RerankerCallRepository | None
```

The repository is required to be:

```text
RerankerCallRepository
```

and unavailable/mismatched repositories produce explicit runtime/type errors.

---

# 3. Orchestration Stage Event Sink

## `DatabaseStageEventSink`

`DatabaseStageEventSink` implements the generic:

```text
TelemetrySink
```

interface and persists each `StageTelemetryEvent` to the database.

Its key design characteristic is that every event is written in a **short, independent transaction**.

---

# Stage Event Flow

```text
Orchestration
     │
     ▼
StageTelemetryEvent
     │
     ▼
DatabaseStageEventSink.emit()
     │
     ▼
AIStageEventModel
     │
     ▼
AIStageEventRepository
     │
     ▼
commit
```

---

# Persisted Stage Information

The sink maps the event into:

```text
ai_run_id
trace_id
conversation_id
trigger_message_id
event_type
stage
duration_ms
error_code
retryable
metadata
occurred_at
```

---

# Stage Timestamp

The sink records:

```python
datetime.now(timezone.utc)
```

for:

```text
occurred_at
```

This ensures the database event timestamp is generated using UTC-aware datetime semantics.

---

# Stage Event Transactions

The transaction boundary is intentionally narrow:

```text
create event model
       │
       ▼
open UoW
       │
       ▼
repository.add()
       │
       ▼
commit()
       │
       ▼
close UoW
       │
       ▼
orchestration continues
```

No provider call is executed inside this transaction.

This prevents telemetry persistence from unnecessarily extending provider/database transaction scope.

---

# Stage Event Validation

`emit()` requires:

```text
StageTelemetryEvent
```

and rejects other values.

The Unit of Work must provide:

```text
AIStageEventRepository
```

otherwise the sink raises an explicit error.

---

# Telemetry Boundaries

The package effectively has three telemetry scopes.

## Stage Scope

Captures:

```text
orchestration lifecycle
errors
duration
retryability
```

through:

```text
DatabaseStageEventSink
```

---

## Retrieval Scope

Captures:

```text
retrieval configuration
retrieval stages
candidate rankings
candidate scores
context selection
context size
latency
```

through:

```text
RetrievalTelemetryRecorder
```

---

## Reranker Scope

Captures:

```text
reranker identity
provider/model
candidate-set identity
input/output counts
latency
provider request ID
status
errors
timeouts
```

through:

```text
RerankerTelemetryRecorder
```

---

# End-to-End Observability Model

These components can be correlated using shared identifiers:

```text
AI Run
  │
  ├── trace_id
  │
  ├── orchestration stage events
  │
  └── Retrieval Run
          │
          ├── embedding_call_id
          │
          ├── retrieval candidates
          │
          └── Reranker Call
                  │
                  └── provider request ID
```

This enables an operational trace such as:

```text
AI Run
  ↓
retrieval stage started
  ↓
retrieval completed
  ↓
reranker started
  ↓
reranker completed
  ↓
context constructed
  ↓
generation stage
```

without storing the actual customer conversation or knowledge-base content.

---

# Transaction Strategy

The telemetry implementation deliberately avoids long-running transactions.

## Retrieval

The retrieval run is committed when started.

Later candidate information and final run status are committed during completion/failure.

---

## Reranker

Every lifecycle transition is persisted through its own short Unit of Work:

```text
start_call()
    → commit

complete_call()
    → commit

fail_call()
    → commit

timeout_call()
    → commit
```

---

## Stage Events

Every stage event uses a short transaction:

```text
emit()
    → add event
    → commit
```

---

# Why Short Transactions Matter

AI provider calls and retrieval operations may take significant time.

The telemetry layer therefore avoids patterns such as:

```text
BEGIN TRANSACTION
    ↓
call embedding provider
    ↓
call reranker
    ↓
call LLM
    ↓
COMMIT
```

Instead:

```text
provider operation
    ↓
telemetry event
    ↓
short INSERT/UPDATE transaction
```

This reduces lock duration and avoids holding database resources while waiting for external services.

---

# Validation Philosophy

The telemetry package performs aggressive input validation.

Common validation rules include:

```text
UUID fields → UUID or None
timestamps → timezone-aware datetime
latencies → non-negative integers
text fields → non-empty strings
candidate collections → tuple[RetrievalCandidate, ...]
retrieval profile → RetrievalProfile
responses → expected domain response types
repositories → expected repository implementations
```

This is important because telemetry errors should be detected at the telemetry boundary rather than silently creating malformed observability data.

---

# Time Validation

All externally supplied telemetry timestamps must be timezone-aware.

The shared validation pattern is:

```text
datetime instance?
    │
    ├── no → TypeError
    │
    ▼
timezone information present?
    │
    ├── no → ValueError
    │
    ▼
valid
```

For retrieval and reranker telemetry, naive datetimes are rejected.

---

# Latency Validation

Latency values must be:

```text
integer
+
non-negative
```

Boolean values are rejected even though Python treats them as integers.

For example:

```text
100
0
2500
```

are valid.

But:

```text
True
-1
1.5
```

are invalid.

The retrieval and reranker recorders enforce this explicitly.

---

# Error Metadata

Errors are represented using structured fields rather than storing arbitrary provider exception objects.

Typical fields are:

```text
error_code
error_message
timeout
retryable
```

This makes operational analysis easier.

For example:

```text
error_code = "provider_timeout"
timeout = true
```

can be queried directly without parsing an exception string.

---

# Trace Correlation

The telemetry components support trace-oriented correlation through:

```text
trace_id
ai_run_id
conversation_id
trigger_message_id
retrieval_run_id
reranker_call_id
provider_request_id
```

This enables tracing across application layers and external provider calls.

---

# Privacy Model

The telemetry package follows a **data minimization** approach.

## Stored

```text
IDs
fingerprints
counts
ranks
scores
latencies
status
provider/model identity
error codes
bounded metadata
timestamps
```

## Not Stored

```text
customer message text
query text
retrieved chunk content
candidate content
prompts
generated answers
conversation context
```

The retrieval and reranker recorders explicitly implement this distinction using fingerprints.

---

# Relationship With Retrieval

The telemetry layer does not perform retrieval itself.

Instead:

```text
Retrieval Engine
       │
       ├── vector results
       ├── lexical results
       ├── fused results
       ├── reranked results
       └── final results
              │
              ▼
    RetrievalTelemetryRecorder
```

The recorder observes the retrieval pipeline and converts its runtime state into persistent telemetry.

---

# Relationship With Reranking

Similarly, the telemetry recorder does not rerank candidates.

Instead:

```text
Reranker
   │
   ├── request
   ├── response
   └── error
        │
        ▼
RerankerTelemetryRecorder
```

The recorder provides lifecycle observability around the actual reranker operation.

---

# Relationship With Orchestration

`DatabaseStageEventSink` receives events emitted by orchestration.

```text
AI Orchestrator
       │
       ▼
StageTelemetryEvent
       │
       ▼
TelemetrySink
       │
       ▼
DatabaseStageEventSink
       │
       ▼
AIStageEventRepository
```

This keeps orchestration logic independent from the concrete database persistence mechanism.

---

# Repository Abstraction

The telemetry components depend on repository abstractions rather than directly manipulating database sessions.

Examples:

```text
RetrievalRepository
RerankerCallRepository
AIStageEventRepository
```

The Unit of Work provides these repositories.

This keeps persistence mechanics outside the telemetry recorders.

---

# Unit of Work Protocols

Each telemetry component defines the minimum Unit of Work interface it requires.

For example:

```text
RetrievalTelemetryUnitOfWork
    └── retrieval

RerankerTelemetryUnitOfWork
    └── reranker_calls

StageEventTelemetryUnitOfWork
    └── stage_events
```

Each also requires:

```text
__enter__()
__exit__()
commit()
```

This keeps the telemetry components decoupled from a concrete Unit of Work implementation.

---

# Testing Strategy

The telemetry components are well suited to unit testing because dependencies are injected.

## Injected Dependencies

```text
uow_factory
retrieval_run_id provider
repository
```

can be replaced with test doubles.

---

# Retrieval Recorder Tests

Important cases include:

```text
start creates run
start cannot be called twice
missing repository
invalid profile
invalid prepared query
embedding call attachment
vector recording
lexical recording
fusion recording
reranking recording
final candidate recording
successful completion
failed completion
already-finalized run
candidate fingerprinting
query fingerprinting
candidate score selection
selected-for-context calculation
negative latency rejection
naive datetime rejection
```

---

# Reranker Recorder Tests

Important cases include:

```text
start_call creates call
retrieval run must exist
invalid descriptor
invalid request
successful completion
failed completion
timeout completion
missing call
already-finalized call
query fingerprinting
candidate identity fingerprinting
invalid latency
naive datetime
blank error code
blank error message
```

---

# Stage Event Sink Tests

Test:

```text
valid event persistence
invalid event type
missing repository
incorrect repository type
metadata copying
UTC timestamp generation
commit behavior
short transaction boundary
```

---

# Operational Questions This Package Enables

With the telemetry stored by these components, the system can answer questions such as:

### Retrieval Performance

```text
What is the average retrieval latency?
How much time is spent in vector search?
How much time is spent in lexical search?
How much time is spent in fusion?
How much time is spent reranking?
How much time is spent building context?
```

### Retrieval Quality

```text
How many candidates enter retrieval?
How many survive fusion?
How many survive reranking?
How many are finally selected?
Which ranking stage changes candidate order?
```

### Reranker Reliability

```text
Which provider/model is being used?
How often does it fail?
How often does it timeout?
What are its latency characteristics?
How many candidates does it process?
```

### Orchestration Reliability

```text
Which stage is failing?
Which failures are retryable?
How long does each stage take?
Which AI runs experienced failures?
```

---

# Example End-to-End Lifecycle

A typical retrieval/reranking execution can be represented as:

```text
1. AI orchestration begins
        │
        ▼
2. Stage event emitted
        │
        ▼
3. RetrievalTelemetryRecorder.start()
        │
        ▼
4. Retrieval run committed
        │
        ▼
5. Embedding call attached
        │
        ▼
6. Vector retrieval recorded
        │
        ▼
7. Lexical retrieval recorded
        │
        ▼
8. Fusion recorded
        │
        ▼
9. RerankerTelemetryRecorder.start_call()
        │
        ▼
10. Reranker executes
        │
        ├── success → complete_call()
        ├── failure → fail_call()
        └── timeout → timeout_call()
        │
        ▼
11. Retrieval reranking recorded
        │
        ▼
12. Final candidates recorded
        │
        ▼
13. GroundingContext created
        │
        ▼
14. RetrievalTelemetryRecorder.complete()
        │
        ▼
15. Context/generation orchestration continues
```

---

# Error Isolation

Telemetry persistence should not be confused with the actual AI operation.

The design of these classes keeps database interactions bounded and explicit.

For example, the stage-event sink opens a transaction only while persisting the event, and no provider call runs inside it.

Similarly, retrieval and reranker recorders validate lifecycle state before applying final transitions.

This prevents telemetry operations from accidentally becoming long-lived external-service transactions.

---

# Design Summary

The `telemetry` package can be understood as three complementary systems:

```text
┌─────────────────────────────────────────────┐
│              AI Telemetry                   │
├─────────────────────────────────────────────┤
│                                             │
│  Stage Events                               │
│  ────────────                               │
│  Orchestration lifecycle                   │
│                                             │
│  Retrieval Telemetry                        │
│  ───────────────────                        │
│  Search → Fusion → Reranking → Context      │
│                                             │
│  Reranker Telemetry                         │
│  ──────────────────                         │
│  Provider/model invocation lifecycle        │
│                                             │
└─────────────────────────────────────────────┘
```

The common principles are:

```text
short transactions
explicit validation
stable identifiers
structured lifecycle states
latency measurement
content minimization
fingerprinting instead of raw text
repository-based persistence
Unit of Work integration
```

---

# Summary

`packages/ai/telemetry` provides the AI system's persistent observability boundary.

`RetrievalTelemetryRecorder` tracks the complete retrieval pipeline, including retrieval configuration, vector/lexical/fusion/reranking stages, candidate ranks and scores, context selection, latency, and final success/failure state. It keeps query and candidate content out of persistence and uses fingerprints instead.

`RerankerTelemetryRecorder` tracks individual reranker calls from start through success, failure, or timeout, associating them with retrieval runs and recording provider/model identity, candidate counts, latency, request IDs, and bounded fingerprints.

`DatabaseStageEventSink` provides database-backed persistence for orchestration-stage events using short independent transactions, while explicitly preventing customer content, prompts, generated answers, retrieved content, and conversation context from being placed into event metadata.

Together, these components provide **deep operational visibility into the AI pipeline without turning telemetry into a copy of customer or knowledge-base data**.
