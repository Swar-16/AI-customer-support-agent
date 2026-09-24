# Dashboard Repositories

## Overview

The `packages/database/repositories/dashboard/` package contains the **read-only database repositories that power the operational dashboard and observability views** of the AI customer-support system.

These repositories sit at the database/infrastructure boundary and translate PostgreSQL data into dashboard-oriented read models and analytics results.

```text
                  Dashboard / Application
                             │
                             ▼
                 Dashboard Repository Layer
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
       Overview          Explorers           Analytics
          │                  │                  │
          │       ┌──────────┼──────────┐       │
          │       │          │          │       │
          ▼       ▼          ▼          ▼       ▼
       KPI      API       Audit       LLM     Aggregates
                Trace     Retrieval
                          Runs
                             │
                             ▼
                        PostgreSQL
```

The repositories are intentionally **read-only**. They do not mutate application state and do not own the transaction lifecycle.

---

## Files

```text
AI-customer-support-agent/
└── packages/
    └── database/
        └── repositories/
            └── dashboard/
                ├── api_request_repository.py
                ├── audit_event_repository.py
                ├── llm_call_repository.py
                ├── overview_repository.py
                ├── retrieval_run_repository.py
                ├── sqlalchemy_analytics_repository.py
                ├── trace_detail_repository.py
                └── trace_repository.py
```

| File | Responsibility |
|---|---|
| `overview_repository.py` | Produces the high-level dashboard KPI snapshot |
| `sqlalchemy_analytics_repository.py` | Produces detailed time-windowed conversation, AI, support, and knowledge analytics |
| `trace_repository.py` | Provides paginated trace-level summaries |
| `trace_detail_repository.py` | Reconstructs the complete correlated execution trace |
| `api_request_repository.py` | Queries sanitized HTTP/API request telemetry |
| `audit_event_repository.py` | Queries sanitized business-audit events |
| `llm_call_repository.py` | Queries LLM invocation, token, cost, and latency telemetry |
| `retrieval_run_repository.py` | Queries retrieval, embedding, and reranker execution telemetry |

---

# Architectural Role

These repositories are optimized for **dashboard reads**, not transactional application workflows.

```text
PostgreSQL
    │
    ├── API requests
    ├── Audit events
    ├── AI runs
    ├── LLM calls
    ├── Embedding calls
    ├── Retrieval runs
    ├── Reranker calls
    ├── Support tickets
    ├── Escalations
    ├── Feedback
    └── Knowledge state
            │
            ▼
    Dashboard Repositories
            │
            ▼
    Dashboard read models
            │
            ▼
    API / Dashboard UI
```

A key characteristic is that **aggregation and filtering are pushed into PostgreSQL wherever practical** rather than loading large ORM collections into Python.

For example, the API-request repository performs filtering, counting, ordering, and pagination in PostgreSQL.

The overview repository similarly performs SQL aggregation instead of materializing entire entity collections.

---

# Repository Categories

The eight files naturally fall into three groups.

## 1. Dashboard Overview

```text
overview_repository.py
sqlalchemy_analytics_repository.py
```

These answer questions such as:

- How many API requests occurred?
- What was API latency?
- How many AI runs succeeded or failed?
- How many LLM calls occurred?
- How many tokens were consumed?
- What was estimated LLM cost?
- How many retrieval runs produced zero results?
- How many tickets/escalations were created or resolved?
- What is the current knowledge inventory?
- What does the timeline look like?

---

## 2. Operational Explorers

```text
trace_repository.py
trace_detail_repository.py
api_request_repository.py
audit_event_repository.py
llm_call_repository.py
retrieval_run_repository.py
```

These support drill-down from aggregate dashboard information into individual execution records.

```text
Overview
   │
   ▼
Trace Explorer
   │
   ▼
Trace Detail
   │
   ├── API requests
   ├── AI runs
   ├── stage events
   ├── LLM calls
   ├── embeddings
   ├── retrieval
   ├── reranking
   ├── escalations
   ├── tickets
   ├── feedback
   └── audit events
```

---

# 1. `overview_repository.py`

## `DashboardOverviewRepository`

This repository provides the **top-level dashboard snapshot**.

Its output is:

```text
DashboardOverviewSnapshot
```

which contains separate summaries for:

```text
API traffic
AI runs
LLM usage
Retrieval
Escalations
Tickets
Feedback
Knowledge
```



### API Traffic

The API overview includes:

- total requests;
- successful requests;
- client errors;
- server errors;
- average latency;
- p95 latency.

These metrics are aggregated directly through PostgreSQL.

### AI Runs

The AI-run overview tracks:

```text
total
completed
failed
cancelled
running
average latency
```



### LLM Usage

LLM metrics include:

```text
call counts
input tokens
output tokens
cached input tokens
total tokens
estimated cost
average latency
```

along with successful, failed, and timed-out calls.

### Retrieval

Retrieval metrics include:

- total runs;
- success/failure/timeout counts;
- zero-result runs;
- reranked runs;
- average latency;
- average selected candidates;
- average context tokens.

### Support

The snapshot also includes escalation, ticket, and feedback health.

For tickets, it distinguishes time-windowed creation/resolution metrics from current active-ticket state.

### Knowledge

Knowledge metrics include document and version inventory/status:

```text
documents created
active documents
archived documents
versions created
published versions
processing versions
ready versions
failed versions
```



---

# 2. `sqlalchemy_analytics_repository.py`

## `SQLAlchemyDashboardAnalyticsRepository`

This is the **deeper analytics engine** behind the dashboard.

It implements the dashboard analytics repository contract and provides:

```text
Conversation Analytics
AI Analytics
Support Analytics
Knowledge Health
```



Unlike the lightweight overview repository, this class performs a much broader set of analytics queries across AI, support, and knowledge tables.

---

## Analytics Session Isolation

Analytics queries use a dedicated SQLAlchemy session with a **transaction-local PostgreSQL statement timeout**.

```text
     Analytics request
            │
            ▼
        new Session
            │
            ▼
SET LOCAL statement_timeout
       │
       ▼
analytics queries
       │
       ├── success
       │
       └── timeout/error
       │
       ▼
session closes
```

The timeout is configured transaction-locally so it does not leak through the connection pool. PostgreSQL query cancellation is translated into `DashboardAnalyticsQueryTimeoutError`.

The configured timeout is bounded to a maximum of **120 seconds**.

---

## Conversation Analytics

Conversation analytics cover:

```text
conversation creation
conversation closure
escalations
customer messages
assistant messages
average messages/conversation
escalation rate
closure duration
status distribution
timeline
```



Timeline queries use PostgreSQL time buckets and generate empty buckets where appropriate, giving the dashboard a continuous timeline rather than only returning intervals containing events.

---

## AI Analytics

AI analytics span the complete AI pipeline:

```text
AI Runs
   │
   ├── LLM Calls
   ├── Retrieval Runs
   ├── Reranker Calls
   ├── Embedding Calls
   ├── Intent Predictions
   ├── AI Decisions
   └── Guardrail Stage Events
```

The result includes operational counts, latency summaries, token/cost data, provider/model distributions, error distributions, and timelines.

This makes this repository the primary source for deeper AI observability analytics.

---

## Support Analytics

Support analytics cover:

```text
tickets
escalations
feedback
resolution duration
current ticket backlog
status distributions
priority distributions
category distributions
feedback ratings
```



---

## Knowledge Health

Knowledge health tracks:

```text
documents
versions
chunks
embeddings
missing chunks
missing embeddings
processing backlog
embedding coverage
processing duration
document status
content types
visibility
version status
ingestion status
failure codes
```



This makes the analytics repository useful not only for business dashboards but also for monitoring RAG knowledge-base health.

---

# 3. `trace_repository.py`

## `DashboardTraceRepository`

This repository provides the **trace explorer summary layer**.

A trace represents the correlated execution path across HTTP and AI activity.

```text
Trace ID
   │
   ├── HTTP requests
   └── AI runs
```

The repository combines these two event sources into one PostgreSQL event stream and aggregates them by `trace_id`.

### Trace Summary

A trace summary contains:

```text
trace_id
first_seen_at
last_seen_at
status
API request count
AI run count
failed API request count
failed AI run count
running AI run count
maximum API latency
maximum AI latency
```



### Derived Status

Trace status is derived as:

```text
running AI run exists
        │
        ▼
     running

otherwise failures exist
        │
        ▼
      error

    otherwise
        │
        ▼
     success
```



### Filtering

The explorer supports:

```text
time range
trace ID
conversation ID
AI run ID
status
pagination
```

and returns newest traces first.

---

# 4. `trace_detail_repository.py`

## `DashboardTraceDetailRepository`

Where `trace_repository.py` provides a summary, `trace_detail_repository.py` reconstructs the **full correlated trace**.

It is effectively the dashboard's deep-dive read model.

```text
Trace
 │
 ├── API requests
 ├── AI runs
 ├── stage events
 ├── LLM calls
 ├── embedding calls
 ├── retrieval runs
 ├── retrieval candidates
 ├── reranker calls
 ├── escalations
 ├── tickets
 ├── feedback
 └── audit events
```



### Trace Reconstruction

The repository starts with:

```text
trace_id
```

then progressively derives related IDs:

```text
trace
 │
 ├── AI run IDs
 │      │
 │      ├── LLM calls
 │      ├── embedding calls
 │      └── retrieval runs
 │               │
 │               ├── retrieval candidates
 │               └── reranker calls
 │
 └── audit events
        │
        ├── escalation IDs
        ├── ticket IDs
        └── feedback IDs
```



### Deterministic Ordering

Each collection is ordered chronologically with an ID tie-breaker.

For example:

```text
started_at ASC
id ASC
```

and retrieval candidates additionally use final rank.

### Security Boundary

The repository intentionally returns an **internal dashboard read model**, not an API-safe response.

Sensitive fields such as:

- LLM/provider error messages;
- ticket descriptions;
- ticket resolution summaries;
- escalation handoff summaries;
- feedback comments;
- arbitrary metadata

must be filtered by the application/API layer before being exposed externally.

This distinction is important:

```text
Database Trace Detail
        │
        ▼
Internal Dashboard Read Model
        │
        ▼
Application Sanitization
        │
        ▼
    API Response
```

---

# 5. `api_request_repository.py`

## `DashboardAPIRequestRepository`

This repository powers the **HTTP/API request explorer**.

It returns a deliberately sanitized:

```text
DashboardAPIRequestRecord
```

rather than exposing the complete API request model.



### Available Data

The dashboard representation includes:

```text
request ID
trace ID
HTTP method
route template
status code
outcome
error code
actor user ID
actor role
request/response sizes
latency
timestamps
```

Sensitive request details such as:

```text
concrete paths
client IP
user agent
exception type
unrestricted metadata
```

are deliberately excluded.

### Filters

Supported filters include:

```text
time range
trace
method
route template
status code
outcome
error code
actor
minimum latency
```

Pagination is bounded to a maximum of `500` records per query.

### Ordering

Results are newest-first:

```text
started_at DESC
id DESC
```



---

# 6. `audit_event_repository.py`

## `DashboardAuditEventRepository`

This repository provides the **business-audit event explorer**.

It exposes a sanitized dashboard representation:

```text
DashboardAuditEventRecord
```

rather than the complete audit-event payload.

### Audit Information

The dashboard record contains:

```text
event type
entity type
entity ID
action
actor type
actor ID
trace ID
conversation ID
AI run ID
whether before-state exists
whether after-state exists
whether a reason exists
occurrence timestamp
recording timestamp
```



The actual:

```text
before_state
after_state
reason
metadata
```

values are intentionally not selected by the explorer query.

### Actor Types

The repository recognizes:

```text
customer
agent
admin
system
ai
```



### Filtering

Events can be filtered by:

```text
time range
event type
entity type
entity ID
action
actor type
actor ID
trace ID
conversation ID
AI run ID
```

with deterministic newest-first ordering and bounded pagination.

---

# 7. `llm_call_repository.py`

## `DashboardLLMCallRepository`

This repository provides the **LLM invocation explorer**.

Its read model captures operational information without exposing raw model interaction content.

```text
DashboardLLMCallRecord
```

contains:

```text
AI run
trace
conversation
prompt version
purpose
provider
model
status
token counts
estimated cost
temperature
latency
error code
timestamps
```



### Deliberately Excluded

The repository does not expose:

```text
raw prompts
generated responses
provider error messages
provider request identifiers
```



This makes the explorer suitable for operational monitoring without automatically turning the dashboard into a prompt/content disclosure surface.

### Filters

The repository supports:

```text
time range
trace
conversation
AI run
purpose
provider
model
status
```



### Operational Metrics

It exposes:

- input tokens;
- output tokens;
- cached input tokens;
- total tokens;
- estimated USD cost;
- temperature;
- latency;
- error code.



---

# 8. `retrieval_run_repository.py`

## `DashboardRetrievalRunRepository`

This repository provides the **retrieval execution explorer**.

It is more detailed than the basic retrieval overview because it exposes the execution characteristics of individual retrieval runs.

### Retrieval Identity

The record includes:

```text
retrieval run ID
AI run ID
trace ID
conversation ID
retrieval mode
profile identity
query fingerprint
query character count
requested limit
```



Raw customer queries are intentionally not exposed.

### Candidate Pipeline Metrics

The repository records counts across the retrieval pipeline:

```text
vector candidates
lexical candidates
fused candidates
reranked candidates
selected candidates
context blocks
context tokens
```



This makes it possible to inspect how candidate volume changes through:

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
 Candidate Selection
       │
       ▼
 Grounding Context
```

### Latency

Stage-level latency is available for:

```text
vector
lexical
fusion
reranker
context building
total retrieval
```



### Embedding Correlation

The repository joins the associated embedding call and exposes:

```text
embedding provider
embedding model
dimensions
status
latency
error code
embedding call ID
```



### Reranker Correlation

Reranker calls are aggregated per retrieval run to provide:

```text
reranker call count
failed reranker calls
maximum reranker latency
```



The raw reranker request/response payload is not exposed.

---

# Common Query Contract

All explorer repositories follow a similar pattern:

```text
    Time Range
        +
    Optional Filters
        +
    Pagination
       │
       ▼
PostgreSQL Query
       │
       ├── filtered
       ├── counted
       ├── ordered
       └── paginated
       │
       ▼
Dashboard Read Models
```

Time ranges must be timezone-aware and ordered correctly.

Pagination is validated and bounded, generally with:

```text
limit > 0
limit <= 500
offset >= 0
```

The API, audit, LLM, retrieval, and trace explorers all follow this general discipline.

---

# Read-Only Design

Every repository in this folder is designed as a **read-side adapter**.

```text
Dashboard Request
       │
       ▼
Repository
       │
       ▼
SELECT / aggregation
       │
       ▼
   Read Model
```

There is no:

```text
INSERT
UPDATE
DELETE
COMMIT
```

business mutation performed by these repositories.

For example, `DashboardTraceRepository` explicitly documents that it never mutates or commits database state.

`DashboardTraceDetailRepository` likewise performs no writes and does not own the transaction.

---

# Data Sanitization Strategy

A major architectural concern in this folder is that **dashboard visibility must not automatically equal raw database visibility**.

Several repositories therefore define specialized dashboard read models.

```text
Raw ORM Model
      │
      ▼
Dashboard Repository
      │
      ├── select only required columns
      ├── aggregate sensitive values
      ├── expose fingerprints instead of raw content
      └── omit unrestricted metadata
      │
      ▼
Dashboard Read Model
```

Examples:

### API requests

Concrete request paths, IPs, user agents, and unrestricted metadata are excluded.

### Audit events

Actual state snapshots, reasons, and unrestricted metadata are excluded.

### LLM calls

Prompts, responses, provider errors, and provider request IDs are excluded.

### Retrieval runs

Raw queries, retrieved content, vectors, provider request IDs, error messages, and unrestricted metadata are excluded.

### Trace details

The full internal trace is available to trusted dashboard infrastructure, but the API/application layer must perform additional sanitization before exposing it externally.

---

# Trace Correlation Model

The dashboard repository layer uses `trace_id` as a major observability correlation key.

```text
                         trace_id
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
   API Requests          AI Runs           Audit Events
                            │
                ┌───────────┼───────────┐
                │           │           │
                ▼           ▼           ▼
             LLM Calls  Retrieval    Embeddings
                            │
                            ├── Candidates
                            │
                            └── Reranker Calls
```

The trace explorer summarizes this relationship, while the trace-detail repository reconstructs it.

---

# Analytics vs Explorer Queries

The folder intentionally separates **aggregate analytics** from **record-level exploration**.

## Analytics

```text
overview_repository.py
sqlalchemy_analytics_repository.py
```

Answer:

> "What happened over this time period?"

Examples:

```text
How many AI runs failed?
What was p95 API latency?
How much did LLM calls cost?
What is embedding coverage?
How many tickets were resolved?
```

## Explorers

```text
api_request_repository.py
audit_event_repository.py
llm_call_repository.py
retrieval_run_repository.py
trace_repository.py
trace_detail_repository.py
```

Answer:

> "Which specific execution/event caused this?"

Examples:

```text
Which trace failed?
Which API request was slow?
Which LLM invocation timed out?
Which retrieval run returned zero results?
Which audit event occurred?
What happened inside this trace?
```

---

# Current-State vs Time-Window Metrics

The dashboard distinguishes two kinds of measurements.

### Time-window metrics

These describe events occurring inside:

```text
[started_at, ended_at)
```

or the equivalent repository query window.

Examples:

```text
API requests
AI runs
LLM calls
retrieval runs
tickets created
feedback submitted
knowledge versions created
```

### Current-state metrics

These describe the state **at query time**.

Examples:

```text
active tickets
active escalations
current document status
current ticket status distribution
current knowledge inventory
```

The overview repository explicitly documents this distinction for active queues versus time-range events.

The analytics repository also explicitly treats support and knowledge distributions as current-state snapshots where appropriate.

---

# Performance Strategy

The dashboard layer is designed for potentially expensive read workloads.

## PostgreSQL-side aggregation

Large datasets are aggregated using SQL:

```text
COUNT
SUM
AVG
PERCENTILE_CONT
GROUP BY
FILTER
generate_series
```

rather than loading raw rows into Python.

The overview repository demonstrates this approach for API, AI, LLM, retrieval, ticket, feedback, and knowledge metrics.

## Bounded explorers

Explorer repositories enforce pagination limits.

## Dedicated analytics timeout

The deeper analytics repository uses a transaction-local PostgreSQL statement timeout so an expensive analytics query cannot run indefinitely.

---

# Deterministic Ordering

Dashboard explorers use deterministic ordering.

Typical ordering is:

```text
timestamp DESC
ID DESC
```

for list/explorer views.

For detailed traces, chronological order is preferred:

```text
timestamp ASC
ID ASC
```

This gives the dashboard stable pagination and reproducible trace timelines.

Examples include API requests, audit events, LLM calls, retrieval runs, traces, and trace-detail collections.

---

# Relationship With the Dashboard Application Layer

The repositories do not define the dashboard's API contract directly.

The intended flow is:

```text
    Dashboard API
        │
        ▼
Application Dashboard Service
        │
        ▼
Dashboard Repository
        │
        ▼
    PostgreSQL
```

For simple explorer records, the repository already returns sanitized read models.

For `TraceDetailRecord`, however, the result intentionally contains internal ORM objects, so an application-level mapper must sanitize it before returning an external response.

---

# End-to-End Dashboard Architecture

```text
                         PostgreSQL
                             │
       ┌─────────────────────┼──────────────────────┐
       │                     │                      │
       ▼                     ▼                      ▼
 Operational Data       AI Telemetry          Knowledge Data
       │                     │                      │
       └─────────────────────┼──────────────────────┘
                             │
                             ▼
                Dashboard Repository Layer
                             │
       ┌─────────────────────┼─────────────────────┐
       │                     │                     │
       ▼                     ▼                     ▼
   Overview             Explorers             Analytics
       │                     │                     │
       │             ┌───────┼────────┐            │
       │             │       │        │            │
       │             ▼       ▼        ▼            │
       │            API    Trace     LLM           │
       │             │       │        │            │
       │             │       ▼        │            │
       │             │ Trace Detail   │            │
       │             │       │        │            │
       │             │       └────────┘            │
       │             │                             │
       └─────────────┴─────────────────────────────┘
                             │
                             ▼
                    Dashboard Application
                             │
                             ▼
                         Dashboard UI
```

---

# Design Principles

## Read-only by design

These repositories exist to inspect system state, not mutate it.

## Database-side aggregation

Large analytics operations are pushed into PostgreSQL.

## Bounded access

Explorer endpoints use validated pagination and bounded result sizes.

## Sanitized read models

Sensitive raw fields are intentionally excluded from dashboard explorer models.

## Trace correlation

`trace_id`, `ai_run_id`, `conversation_id`, and related IDs provide cross-subsystem observability.

## Separation of overview and detail

Aggregated KPIs remain separate from detailed execution explorers.

## Current-state awareness

The dashboard distinguishes historical/time-window measurements from current queue/inventory state.

## Explicit timeout protection

Long-running analytics queries receive a transaction-local PostgreSQL statement timeout.

---

# Summary

`packages/database/repositories/dashboard/` is the **read-side persistence layer for operational visibility across the entire AI customer-support system**.

Its eight repositories provide three levels of visibility:

```text
                    Dashboard Repository Layer
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
       OVERVIEW            EXPLORERS           ANALYTICS
          │                   │                   │
          ▼                   ▼                   ▼
       KPIs              Individual Events    Time Series
       Health            Traces               Aggregates
       Queues            LLM Calls            AI Metrics
                         Retrieval             Support
                         Audit                 Knowledge
```

The most important flow is:

```text
High-Level Dashboard
        │
        ▼
overview_repository.py
        │
        ▼
Trace / Explorer
        │
        ▼
trace_repository.py
        │
        ▼
trace_detail_repository.py
        │
        ├── API Requests
        ├── AI Runs
        ├── LLM Calls
        ├── Embeddings
        ├── Retrieval
        ├── Reranking
        ├── Audit Events
        ├── Escalations
        ├── Tickets
        └── Feedback
```

Meanwhile, `sqlalchemy_analytics_repository.py` provides the deeper aggregate analytics layer across **conversation, AI, support, and knowledge health**.

The overall principle is:

> **The dashboard repository layer turns the system's operational database into efficient, bounded, correlated, and deliberately sanitized read models without taking ownership of business mutations or dashboard presentation logic.**