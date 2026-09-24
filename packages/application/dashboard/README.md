# Dashboard Application Layer

## Overview

The `packages/application/dashboard/` package provides the **read-oriented application layer for operational, AI, retrieval, support, knowledge, conversation, and trace analytics**.

It sits between the dashboard/API layer and the database repositories. Its responsibility is to:

* validate dashboard query inputs;
* enforce consistent time-range and pagination semantics;
* query optimized dashboard repositories;
* aggregate operational and AI metrics;
* calculate derived rates and percentages;
* expose immutable application-facing models;
* provide trace, AI-run, LLM, retrieval, audit, support, conversation, and knowledge views;
* provide analytics caching where appropriate;
* keep repository and persistence concerns out of dashboard consumers;
* avoid mutating business state.

The package is fundamentally a **read/query boundary**.

```text
Dashboard / API
       │
       ▼
┌──────────────────────────────────────┐
│     Application Dashboard Layer      │
│                                      │
│  Overview                            │
│  Analytics                           │
│  Trace Explorer                      │
│  AI Runs                             │
│  LLM Calls                           │
│  Retrieval Runs                      │
│  Audit Events                        │
│  Support Analytics                   │
│  Conversation Analytics              │
│  Knowledge Health                    │
└──────────────────┬───────────────────┘
                   │
                   ▼
          Dashboard Repositories
                   │
                   ▼
              PostgreSQL
```

The application layer converts persistence records into stable dashboard-facing objects instead of exposing database models directly. The trace query service, for example, explicitly maps repository records into immutable `DashboardTraceSummary` objects.

---

# Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── application/
        └── dashboard/
            ├── __init__.py
            ├── models.py
            ├── analytics_contract.py
            ├── analytics_cache.py
            ├── analytics_repository.py
            │
            ├── get_overview.py
            ├── get_ai_analytics.py
            ├── get_support_analytics.py
            ├── get_conversation_analytics.py
            ├── get_knowledge_health.py
            │
            ├── query_traces.py
            ├── query_ai_runs.py
            ├── query_llm_calls.py
            ├── query_retrieval_runs.py
            │
            └── ...
```

The exact repository implementation may evolve, but the application package maintains the same architectural boundary:

```text
Application Query
        │
        ▼
Validation
        │
        ▼
Dashboard Repository
        │
        ▼
Persistence Records
        │
        ▼
Immutable Dashboard Model
```

---

# Responsibilities

The dashboard package can be divided into four major responsibilities.

## 1. Dashboard Overview

Provides a high-level operational snapshot containing metrics for areas such as:

* API traffic;
* AI runs;
* LLM usage;
* retrieval;
* escalations;
* tickets;
* feedback;
* knowledge.

`GetDashboardOverview` obtains a repository snapshot and transforms it into dashboard sections without modifying database state.

---

## 2. Detailed Analytics

Detailed analytics services provide focused views into:

* AI execution;
* customer conversations;
* support operations;
* knowledge-base health.

These services build application-level analytical results from repository aggregates rather than requiring dashboard clients to understand database schemas.

---

## 3. Operational Explorers

The package exposes query services for investigating individual execution records:

```text
Trace
 │
 ├── API requests
 ├── AI runs
 ├── LLM calls
 ├── Retrieval runs
 └── Audit events
```

This enables an operator to move from a high-level metric into progressively more detailed operational information.

---

## 4. Analytics Infrastructure

The analytics contract, cache, and repository components provide shared infrastructure for retrieving and reusing analytical data.

The intention is to keep:

```text
Dashboard business/query logic
```

separate from:

```text
Repository / caching implementation
```

---

# Core Application Models

The dashboard package uses immutable data structures extensively.

Typical application models include:

```text
DashboardTimeRange
DashboardPagination
DashboardPage
DashboardMetric
DashboardOverviewSection
DashboardOverviewResult
```

and detailed result types such as:

```text
DashboardTraceSummary
DashboardRetrievalRun
Dashboard AI analytics
Dashboard support analytics
Dashboard conversation analytics
Knowledge health results
```

The use of immutable models creates a stable contract between the dashboard application layer and its consumers.

---

# Time Range

Dashboard queries operate over an explicit reporting interval.

Conceptually:

```text
started_at ─────────────────────── ended_at
     │                                │
     └──────── reporting window ──────┘
```

The time range is passed into repository queries rather than allowing each individual dashboard service to implement its own date filtering rules.

This gives the dashboard a consistent interpretation of:

* current reporting windows;
* historical analysis;
* operational time periods.

---

# Pagination

Detailed explorers use a common pagination model.

A typical query consists of:

```text
limit
offset
```

and returns:

```text
items
total
limit
offset
has_more
next_offset
```

This allows dashboard consumers to navigate potentially large datasets without loading an entire operational history.

For example, `QueryDashboardTracesCommand` combines the reporting interval, pagination, and optional trace/conversation/AI-run/status filters.

---

# Dashboard Overview

## `get_overview.py`

`GetDashboardOverview` provides the primary high-level dashboard snapshot.

The service:

1. validates the command;
2. opens a Unit of Work;
3. obtains the dashboard overview repository;
4. requests an aggregate snapshot;
5. transforms the snapshot into application-level sections;
6. returns the result.

It does not mutate or commit business state.

---

# Overview Sections

The overview is divided into logical dashboard sections.

The implementation currently builds sections for:

```text
API Traffic
AI Runs
LLM Usage
Retrieval
Escalations
Tickets
Feedback
Knowledge
```

The overview result assembles these sections from a single repository snapshot.

This gives the dashboard a structure such as:

```text
DashboardOverviewResult
│
├── API
├── AI Runs
├── LLM
├── Retrieval
├── Escalation
├── Tickets
├── Feedback
└── Knowledge
```

---

# API Metrics

The API section provides metrics such as:

```text
total_requests
successful_requests
client_error_requests
server_error_requests
error_rate
average_latency
p95_latency
```

The application layer calculates the error rate from client and server errors rather than requiring consumers to reconstruct the metric themselves.

---

# AI Run Metrics

The AI-run section provides:

```text
total_runs
completed_runs
failed_runs
cancelled_runs
running_runs
success_rate
average_latency
```

The success rate is calculated using completed runs relative to total runs.

---

# LLM Metrics

LLM analytics include:

```text
total_calls
successful_calls
failed_calls
timeout_calls
total_tokens
input_tokens
output_tokens
cached_input_tokens
estimated_cost
```

This makes the dashboard useful for both operational monitoring and AI cost analysis.

---

# Detailed Analytics

## `get_ai_analytics.py`

The AI analytics use case provides deeper information about the AI subsystem than the overview.

It is intended for questions such as:

```text
How many AI runs occurred?
How many completed successfully?
How many failed?
What was the average latency?
Which pipeline stages contributed to failures?
How much LLM activity occurred?
```

The important distinction is:

```text
Overview
   │
   └── compact operational snapshot

AI Analytics
   │
   └── detailed AI-focused analysis
```

---

# Conversation Analytics

## `get_conversation_analytics.py`

Conversation analytics provide aggregated information about customer conversations.

The application boundary keeps these results separate from the conversation lifecycle use cases.

Conversation lifecycle operations answer:

```text
"What should happen to this conversation?"
```

Dashboard analytics answer:

```text
"What has been happening across conversations?"
```

This separation prevents reporting code from becoming coupled to conversation mutation workflows.

---

# Support Analytics

## `get_support_analytics.py`

Support analytics provide an operational view of customer-support activity.

This layer is intended for metrics and aggregates such as:

```text
support workload
ticket activity
escalations
resolution behavior
support outcomes
```

The use case consumes repository-level aggregates rather than loading individual business entities unnecessarily.

---

# Knowledge Health

## `get_knowledge_health.py`

Knowledge-health analytics provide an operational view of the knowledge/retrieval subsystem.

This allows the dashboard to monitor whether the knowledge layer is behaving as expected.

Relevant dimensions may include:

```text
knowledge availability
retrieval activity
zero-result behavior
retrieval health
knowledge coverage
```

The important architectural distinction is that the dashboard **observes** the knowledge subsystem; it does not modify knowledge records.

---

# Trace Explorer

## `query_traces.py`

`QueryDashboardTraces` provides the trace-explorer application service.

It accepts:

```text
time_range
pagination
trace_id
conversation_id
ai_run_id
status
```

The status is normalized to lowercase and validated against the repository's supported trace statuses.

---

# Trace Summary

A trace summary contains information such as:

```text
trace_id
first_seen_at
last_seen_at
status

api_request_count
ai_run_count

failed_api_request_count
failed_ai_run_count
running_ai_run_count

maximum_api_latency_ms
maximum_ai_latency_ms
```

This provides a compact operational representation of a distributed trace.

Conceptually:

```text
                    TRACE
                      │
          ┌───────────┴───────────┐
          │                       │
      API Requests             AI Runs
          │                       │
          ├── count               ├── count
          ├── failures            ├── failures
          └── latency             └── latency
```

---

# AI Run Explorer

## `query_ai_runs.py`

The AI-run explorer provides detailed inspection of individual AI pipeline executions.

It allows operators to correlate AI execution with:

```text
trace
conversation
triggering message
pipeline
status
latency
failure information
```

This is particularly useful when moving from a dashboard-level failure metric to the actual AI execution responsible for the failure.

---

# LLM Call Explorer

## `query_llm_calls.py`

The LLM-call query layer exposes provider-level execution information.

Typical operational dimensions include:

```text
provider
model
purpose
status
latency
token usage
cost
trace
AI run
```

This allows operators to move from:

```text
AI Run
   │
   ▼
LLM Calls
   │
   ├── provider/model
   ├── latency
   ├── tokens
   ├── status
   └── cost
```

without exposing raw prompts or generated customer-facing content as a dashboard requirement.

---

# Retrieval Run Explorer

## `query_retrieval_runs.py`

The retrieval-run query service provides detailed retrieval telemetry.

A retrieval result contains information including:

```text
id
ai_run_id
trace_id
conversation_id
embedding_call_id

retrieval_mode
profile_identity
query_fingerprint
query_character_count

requested_limit

vector_candidate_count
lexical_candidate_count
fused_candidate_count
reranked_candidate_count
selected_candidate_count

context_block_count
context_token_count

reranker_used
context_truncated
zero_result

vector_latency_ms
lexical_latency_ms
fusion_latency_ms
reranker_latency_ms
context_build_latency_ms
total_latency_ms

status
error_code

embedding provider/model information
embedding latency/status
reranker call counts
```

The application model explicitly uses a `query_fingerprint` rather than the original query text.

---

# Retrieval Filters

Retrieval runs can be filtered by:

```text
time range
trace ID
conversation ID
AI run ID
retrieval mode
profile identity
status
zero-result state
reranker usage
```

This allows operators to answer questions such as:

```text
Which retrieval profile produced zero results?

Which traces used reranking?

Which retrieval runs were slow?

Which AI runs experienced retrieval failures?

Which retrieval runs belong to a particular conversation?
```

---

# Retrieval Privacy Boundary

The dashboard retrieval model intentionally does not expose raw query text.

Instead:

```text
customer query
      │
      ▼
SHA-256 fingerprint
      │
      ▼
query_fingerprint
```

The underlying telemetry layer follows the same principle: textual query and retrieved content are represented through bounded fingerprints rather than persisted raw content.

This permits operational correlation without turning the dashboard into a secondary customer-content store.

---

# Audit Explorer

Although audit querying is implemented in the audit application package, the dashboard integrates with audit exploration through its query-facing functionality.

Audit queries support filters such as:

```text
event_type
entity_type
entity_id
action
actor_type
actor_id
trace_id
conversation_id
ai_run_id
occurred_from
occurred_to
limit
offset
```

The audit query layer maps persistence records into immutable `AuditEventView` objects.

---

# Entity Audit History

Dashboard operators can inspect the mutation history of a specific entity.

Conceptually:

```text
Entity
 │
 ├── created
 ├── updated
 ├── transitioned
 ├── escalated
 ├── resolved
 └── closed
```

The audit history is ordered and returned through application-level views.

---

# Trace-to-Audit Correlation

A distributed trace can also be used to retrieve related business audit events.

```text
trace_id
   │
   ├── API activity
   ├── AI execution
   ├── retrieval
   └── business mutations
```

`GetTraceAuditEvents` provides this correlation by querying audit events associated with a trace ID.

This is important because operational telemetry and business audit history represent different dimensions of the same request.

---

# Analytics Contract

## `analytics_contract.py`

The analytics contract defines the interface between dashboard application services and the analytics implementation.

The purpose is dependency inversion.

The application services should depend on:

```text
Analytics Contract
```

rather than directly depending on a particular cache, SQL query implementation, or database strategy.

Conceptually:

```text
Dashboard Use Cases
        │
        ▼
Analytics Contract
        │
   ┌────┴─────┐
   ▼          ▼
Cache      Repository
```

This makes the analytics subsystem easier to test and replace.

---

# Analytics Repository

## `analytics_repository.py`

The repository provides the persistence-facing implementation used by dashboard analytics.

Its responsibility is to retrieve aggregated data efficiently.

The dashboard layer should prefer:

```text
SQL aggregates
```

over:

```text
load thousands of ORM records
→ calculate everything in Python
```

This is especially important for:

* large trace volumes;
* API request history;
* AI runs;
* LLM calls;
* retrieval runs;
* support activity.

---

# Analytics Cache

## `analytics_cache.py`

The analytics cache provides a reusable caching layer for expensive dashboard computations.

The cache exists to prevent repeatedly executing expensive aggregate queries when the same dashboard data is requested repeatedly.

Conceptually:

```text
Dashboard Query
      │
      ▼
   Cache?
   /    \
 hit    miss
  │       │
  │       ▼
  │   Repository
  │       │
  │       ▼
  │     Cache
  │       │
  └───────┘
      │
      ▼
 Dashboard Result
```

Caching is particularly useful for:

* frequently refreshed overview dashboards;
* expensive aggregate queries;
* analytics pages viewed by multiple operators;
* repeated reporting intervals.

Caching must remain an optimization rather than the source of truth.

---

# Repository vs Cache

The architectural relationship is:

```text
                 ┌───────────────┐
                 │ Dashboard     │
                 │ Application   │
                 │ Service       │
                 └───────┬───────┘
                         │
                         ▼
                 Analytics Contract
                         │
                  ┌──────┴──────┐
                  │             │
                  ▼             ▼
                Cache       Repository
                                │
                                ▼
                            Database
```

The database remains authoritative.

A cache miss must always be able to fall back to the repository.

---

# Unit of Work Integration

Dashboard queries use a `UnitOfWorkFactory`.

For example, trace querying validates the supplied factory and opens a Unit of Work around the repository operation.

The pattern is:

```python
with uow_factory() as uow:
    repository = ...
    records = repository.query(...)
    return application_views
```

This gives dashboard reads:

* consistent session management;
* explicit repository access;
* predictable lifecycle;
* clean dependency injection;
* easy unit testing.

---

# Repository Contract Validation

Application services do not blindly assume repository wiring is correct.

For example, the overview service checks that:

```text
uow.dashboard_overview
```

exists and has the expected repository type. Otherwise it raises a dashboard persistence-contract error.

The same philosophy is used throughout the query layer.

This turns configuration/wiring mistakes into explicit application errors instead of obscure attribute errors later in execution.

---

# Read-Only Design

The dashboard package is intentionally read-oriented.

Its normal execution pattern is:

```text
Validate
   │
   ▼
Open Unit of Work
   │
   ▼
Query repository
   │
   ▼
Map records
   │
   ▼
Return result
```

It should not:

```text
modify conversations
create AI runs
change tickets
update knowledge
alter support state
```

Dashboard mutation workflows belong to their respective application packages.

---

# Derived Metrics

The application layer is responsible for dashboard-friendly derived metrics.

For example:

```text
error rate
success rate
latency summaries
cost metrics
```

are calculated from repository aggregates.

A generic percentage operation follows:

```text
percentage = numerator / denominator × 100
```

with zero-denominator protection.

This ensures dashboard consumers receive presentation-ready values without duplicating business calculations.

---

# Missing Data vs Zero

An important distinction is preserved between:

```text
0
```

and:

```text
no data
```

For latency metrics, the overview can return:

```text
value = 0
metadata.has_data = false
```

when no latency observations exist.

When data exists:

```text
value = measured latency
metadata.has_data = true
```

This prevents the dashboard from incorrectly interpreting missing observations as actual zero latency.

---

# Operational Drill-Down

The dashboard architecture is designed for progressive investigation.

```text
                  Overview
                     │
          ┌──────────┼──────────┐
          │          │          │
          ▼          ▼          ▼
       AI Runs     API       Retrieval
          │                     │
          ▼                     ▼
      LLM Calls            Retrieval Runs
          │
          ▼
       Trace
          │
          ▼
      Audit Events
```

An operator can therefore move from:

```text
"What is wrong?"
```

to:

```text
"Which subsystem?"
```

to:

```text
"Which execution?"
```

to:

```text
"Which business event?"
```

without requiring the dashboard frontend to understand the underlying database structure.

---

# Trace Correlation Model

The major identifiers used throughout the dashboard are:

```text
trace_id
conversation_id
ai_run_id
```

They provide different levels of correlation.

### `trace_id`

Represents the distributed request/execution boundary.

### `conversation_id`

Represents the customer conversation.

### `ai_run_id`

Represents a particular AI processing execution.

This allows queries such as:

```text
Trace
 │
 ├── Conversation
 │
 ├── AI Run
 │      │
 │      ├── LLM Calls
 │      └── Retrieval Runs
 │
 └── Audit Events
```

---

# Privacy and Data Minimization

The dashboard is an operational system and must not become a secondary customer-content repository.

The surrounding telemetry architecture explicitly avoids storing:

* customer message text;
* raw prompts;
* generated answers;
* query text;
* retrieved document content;
* retrieved chunk content;
* conversation context.

Instead, it favors:

```text
IDs
counts
timestamps
status
latency
configuration identity
bounded metadata
fingerprints
```

This is particularly important for dashboard and observability data because such systems often have broader operator access than ordinary customer-facing workflows.

---

# Fingerprints

Where textual correlation is necessary, the system uses fingerprints.

```text
Sensitive text
     │
     ▼
SHA-256
     │
     ▼
Fingerprint
```

This allows the dashboard to answer:

```text
"Have these requests used the same query?"
```

without requiring:

```text
"Store the original customer query."
```

The retrieval telemetry implementation explicitly records a query fingerprint and character count instead of the query itself.

---

# Error Handling

Dashboard services use explicit application-level error hierarchies.

Typical categories include:

```text
Dashboard query error
        │
        ├── validation error
        ├── persistence contract error
        └── invalid persisted record
```

This is preferable to exposing raw infrastructure exceptions directly to API consumers.

---

# Immutable Results

Dashboard results are designed to be immutable.

For example:

```text
@dataclass(frozen=True, slots=True)
```

is used for query commands and result objects.

This provides:

* predictable result contracts;
* no accidental mutation after query completion;
* safe reuse by API serializers;
* easier testing;
* cleaner separation from ORM state.

---

# Application-to-Repository Mapping

The dashboard layer performs explicit mapping:

```text
Database Record
      │
      ▼
Validation
      │
      ▼
Application Model
      │
      ▼
Dashboard API
```

For example:

```text
TraceSummaryRecord
        │
        ▼
DashboardTraceSummary
```

The mapping validates the repository record before constructing the immutable application result.

---

# Query Validation

Commands validate their own structural requirements.

For example, trace queries verify:

```text
time_range → DashboardTimeRange
pagination → DashboardPagination
trace_id → UUID
conversation_id → UUID
ai_run_id → UUID
status → valid trace status
```

This moves invalid-input detection to the application boundary rather than allowing invalid values to reach SQL execution.

---

# Performance Philosophy

Dashboard queries should be optimized for **read-heavy analytical workloads**.

Preferred:

```text
Database aggregate
        │
        ▼
Small result set
        │
        ▼
Application mapping
```

Avoid:

```text
Database
   │
   ▼
Millions of ORM records
   │
   ▼
Python aggregation
```

The repository layer should therefore provide purpose-built aggregate queries wherever possible.

---

# Caching Philosophy

Caching is allowed for expensive analytical computations, but:

```text
Cache ≠ Source of Truth
```

The authoritative source remains the database.

A cache should therefore be:

* invalidatable;
* bounded;
* safe for stale reads where acceptable;
* transparent to application consumers;
* replaceable.

Dashboard correctness must not depend on cache availability.

---

# Testing Strategy

The dashboard application layer is well suited to isolated unit tests because dependencies are injected.

A typical test can supply:

```text
fake UOW factory
        │
        ▼
fake dashboard repository
        │
        ▼
application query
        │
        ▼
immutable result
```

Tests should cover:

### Input validation

* invalid UUIDs;
* invalid statuses;
* invalid time ranges;
* invalid pagination.

### Repository wiring

* missing repository;
* wrong repository type.

### Mapping

* valid repository records;
* missing required persisted values.

### Metrics

* zero denominators;
* missing latency;
* empty datasets;
* successful/failed counts.

### Pagination

* first page;
* later pages;
* empty page;
* `has_more` behavior.

### Correlation

* trace → AI run;
* AI run → LLM calls;
* AI run → retrieval;
* trace → audit events.

### Privacy

* raw customer text is not returned where prohibited;
* fingerprints are returned instead of sensitive textual values.

---

# Relationship With Other Application Packages

The dashboard package should remain a consumer of operational data rather than becoming the owner of those domains.

```text
packages/application/
│
├── conversations/
│       │
│       └── owns conversation lifecycle
│
├── audit/
│       │
│       └── owns audit querying/lifecycle
│
├── AI-related application services/
│       │
│       └── own AI execution workflows
│
└── dashboard/
        │
        └── observes and aggregates
```

This separation prevents reporting concerns from leaking into transactional business workflows.

---

# Relationship With AI Telemetry

The dashboard consumes telemetry produced by the AI subsystem.

The telemetry layer records:

```text
orchestration stages
retrieval runs
retrieval candidates
reranker calls
latency
provider/model identity
lifecycle status
errors
candidate ranks
selection statistics
```

while intentionally avoiding customer-content persistence.

The dashboard therefore becomes the **read/visualization boundary over telemetry**, rather than duplicating telemetry collection logic.

---

# Retrieval Dashboard Flow

The retrieval subsystem can be represented as:

```text
Customer Request
      │
      ▼
Embedding
      │
      ▼
Vector Search ─────┐
                   │
Lexical Search ────┤
                   ▼
                 Fusion
                   │
                   ▼
                Reranking
                   │
                   ▼
              Final Context
```

The dashboard can inspect aggregate statistics at each stage:

```text
vector_candidate_count
lexical_candidate_count
fused_candidate_count
reranked_candidate_count
selected_candidate_count

vector_latency
lexical_latency
fusion_latency
reranker_latency
context_build_latency
```

These fields are exposed by the retrieval dashboard model.

---

# Observability Separation

The system distinguishes between:

### Business Audit

```text
"What business state changed?"
```

and:

### Technical Telemetry

```text
"How did the system execute?"
```

and:

### Dashboard Analytics

```text
"What patterns are visible across executions?"
```

These should not be collapsed into one storage or application abstraction.

---

# Typical End-to-End Investigation

Suppose the overview reports a high AI failure rate.

An operator can follow:

```text
Dashboard Overview
       │
       ▼
AI Analytics
       │
       ▼
AI Run Explorer
       │
       ├───────────────┐
       ▼               ▼
LLM Calls        Retrieval Runs
       │               │
       └───────┬───────┘
               ▼
             Trace
               │
               ▼
         Audit Events
```

This is one of the primary architectural purposes of the dashboard application layer.

---

# Design Principles

## 1. Read-Only Application Boundary

Dashboard queries observe system state; they do not own domain mutations.

## 2. Repository-Based Analytics

Expensive analytical work should be delegated to optimized repositories.

## 3. Immutable Results

Dashboard consumers receive stable application-level models rather than live ORM entities.

## 4. Explicit Correlation

`trace_id`, `conversation_id`, and `ai_run_id` provide controlled cross-system correlation.

## 5. Privacy by Default

Operational dashboards should not store or expose customer content unnecessarily.

## 6. Fingerprint Sensitive Text

Use bounded fingerprints when textual correlation is required.

## 7. Cache as Optimization

A cache can improve performance but must never replace the database as the source of truth.

## 8. Short-Lived Database Work

Dashboard reads should use short Unit of Work scopes.

## 9. Validate at the Boundary

Invalid filters should fail before reaching persistence.

## 10. Separate Business Audit From Technical Telemetry

A business mutation and the technical execution that produced it are related but distinct concepts.

---

# Data Flow Summary

```text
                         Dashboard Client
                                │
                                ▼
                    Application Dashboard Layer
                                │
          ┌─────────────────────┼────────────────────────────┐
          │                     │                            │
          ▼                     ▼                            ▼
      Overview              Analytics                   Explorers
          │                     │                            │
          │             ┌───────┼────────┐             ┌─────┼─────┐
          │             │       │        │             │     │     │
          ▼             ▼       ▼        ▼             ▼     ▼     ▼
        API          AI       Support Conversation    Trace LLM Retrieval
        AI Runs      Analytics Analytics Analytics
        LLM
        Retrieval
        Escalation
        Tickets
        Feedback
        Knowledge      └────────────────────────────────────────────────┘
          │                                         │
          └─────────────────────┬───────────────────┘
                                ▼
                       Analytics Repository
                                │
                       ┌────────┴────────┐
                       │                 │
                       ▼                 ▼
                    Cache            Database
```

---

# Summary

`packages/application/dashboard/` is the application's **read-side observability and analytics boundary**.

It turns raw operational persistence into structured information for dashboards and operational tooling.

The package covers:

```text
┌────────────────────────────────────────────┐
│             Dashboard Application          │
├────────────────────────────────────────────┤
│                                            │
│  Overview                                  │
│    ├── API                                 │
│    ├── AI Runs                             │
│    ├── LLM                                 │
│    ├── Retrieval                           │
│    ├── Escalation                          │
│    ├── Tickets                             │
│    ├── Feedback                            │
│    └── Knowledge                           │
│                                            │
│  Detailed Analytics                        │
│    ├── AI                                  │
│    ├── Support                             │
│    ├── Conversations                       │
│    └── Knowledge Health                    │
│                                            │
│  Operational Explorers                     │
│    ├── Traces                              │
│    ├── AI Runs                             │
│    ├── LLM Calls                           │
│    ├── Retrieval Runs                      │
│    └── Audit Events                        │
│                                            │
│  Shared Infrastructure                     │
│    ├── Models                              │
│    ├── Analytics Contract                  │
│    ├── Analytics Repository                │
│    └── Analytics Cache                     │
│                                            │
└────────────────────────────────────────────┘
```

The core architectural pattern is:

```text
Validate
   │
   ▼
Query optimized repository
   │
   ▼
Map persistence records
   │
   ▼
Calculate application-level metrics
   │
   ▼
Return immutable dashboard result
```

The package therefore provides a clean boundary between **the operational state of the AI customer-support system and the interfaces used to understand that state**. It enables high-level monitoring, detailed drill-down, cross-system correlation, AI/retrieval analysis, support analytics, knowledge health monitoring, and audit investigation while preserving the separation between customer/business data, technical telemetry, and dashboard presentation.
