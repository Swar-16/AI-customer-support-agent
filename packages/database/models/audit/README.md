# Audit Database Models

## Overview

The `packages/database/models/audit/` package contains the SQLAlchemy persistence models for the application's **audit and operational observability layer**.

```text
AI-customer-support-agent/
└── packages/
    └── database/
        └── models/
            └── audit/
                ├── api_request.py
                └── audit_event.py
```

The package contains two complementary models:

| Model             | Purpose                                                                   |
| ----------------- | ------------------------------------------------------------------------- |
| `APIRequestModel` | Durable record of an HTTP/API request and its operational outcome         |
| `AuditEventModel` | Immutable record of security-relevant and business-relevant state changes |

Both tables use the PostgreSQL `audit` schema.

The conceptual separation is:

```text
                    AUDIT
                      │
          ┌───────────┴───────────┐
          │                       │
          ▼                       ▼
    API Request              Audit Event
          │                       │
          │                       │
          ▼                       ▼
HTTP/operational          Business/security
activity                   state mutation
```

---

# 1. `api_request.py`

## `APIRequestModel`

`APIRequestModel` represents one **durable HTTP/API request record**.

Its purpose is to answer operational questions such as:

* Which endpoint was called?
* When did the request start?
* When did it finish?
* How long did it take?
* What HTTP status was returned?
* Did the request succeed?
* Which trace was associated with it?
* Which authenticated user initiated it?
* Which stable application error occurred?

These responsibilities are explicitly described by the model itself.

The table name is:

```text
audit.api_requests
```

---

## Request Identity

Each request receives a UUIDv7 primary key:

```text
id
```

and is correlated with the broader request/trace lifecycle using:

```text
trace_id
```

The model uses a database-generated UUIDv7 for its primary key.

Conceptually:

```text
API Request
    │
    ├── id
    └── trace_id
          │
          └── related application activity
```

The `trace_id` is indexed for correlation queries.

---

## HTTP Request Information

The model records:

```text
method
route_template
request_path
status_code
outcome
```

The supported HTTP methods are:

```text
GET
POST
PUT
PATCH
DELETE
OPTIONS
HEAD
```

and the database validates them through a `CHECK` constraint.

`route_template` is optional, while the actual `request_path` is required.

---

## Outcome Classification

Requests are categorized into:

```text
success
client_error
server_error
```

The model also validates the relationship between `outcome` and HTTP status:

```text
success
    → status_code < 400
    → error_code must be NULL

client_error
    → 400–499

server_error
    → >= 500
```

This is enforced at the database level through `valid_outcome_status`.

---

## Error Information

When relevant, an API request can record:

```text
error_code
exception_type
```

These fields allow operational systems to distinguish stable application errors from the underlying Python exception type.

The `error_code` is separately indexed to make error-oriented investigations efficient.

---

## Actor Information

An API request can optionally be associated with the authenticated actor:

```text
actor_user_id
actor_role
```

`actor_user_id` references:

```text
support.users.id
```

with `ON DELETE SET NULL`.

This means audit history can remain even if the corresponding user is later removed.

The actor identifier is indexed together with request start time for operational queries.

---

## Client Information

The model optionally records:

```text
client_ip
user_agent
```

along with:

```text
request_size_bytes
response_size_bytes
```

The size fields cannot be negative.

The model is deliberately **not** intended to become a raw request/response dump.

The source explicitly prohibits storing:

* sensitive headers;
* authorization tokens;
* cookies;
* unrestricted request bodies;
* unrestricted response bodies.

---

## Latency

Request duration is persisted as:

```text
latency_ms
```

and must be non-negative.

It also has a dedicated descending index:

```text
idx_api_requests_latency
```

which supports identifying slow requests.

---

## Timing

The request lifecycle contains:

```text
started_at
completed_at
recorded_at
```

The database guarantees:

```text
completed_at >= started_at
```

`recorded_at` defaults to the database's current timestamp.

---

## Metadata

Additional structured information can be stored in PostgreSQL `JSONB`:

```text
metadata
```

The Python attribute is:

```text
metadata_
```

and maps explicitly to the database column named `metadata`.

This provides extensibility without turning the core schema into an unstructured event payload.

---

# 2. `audit_event.py`

## `AuditEventModel`

`AuditEventModel` represents an **immutable business/security audit event**.

Unlike `APIRequestModel`, which records an HTTP operation, this model records a meaningful **domain state mutation or security-relevant action**.

Examples explicitly covered by the model include:

* ticket creation and updates;
* escalation creation and resolution;
* feedback submission and review;
* knowledge document/version lifecycle changes.

The table name is:

```text
audit.audit_events
```

---

## Append-Only Design

Audit events are explicitly append-only.

Repositories must not expose update or delete operations for this model.

Conceptually:

```text
Business action
      │
      ▼
Append Audit Event
      │
      ▼
Historical record
      │
      └── never mutated
```

This makes the model suitable for reconstructing historical activity.

---

## Why Correlation IDs Do Not Use Foreign Keys

The model intentionally does **not** use foreign keys for its entity correlation identifiers.

For example:

```text
entity_id
conversation_id
ai_run_id
```

are stored as identifiers rather than strict relational dependencies.

The reason is explicit in the model:

> Audit history must remain attributable even if the corresponding operational record is later archived or deleted.

Therefore:

```text
Operational record
      │
      └── may eventually disappear

Audit event
      │
      └── remains historically attributable
```

This is an important distinction from normal operational tables.

---

# Event Identity

Each audit event has a UUIDv7 primary key:

```text
id
```

generated by PostgreSQL.

The event itself identifies:

```text
event_type
entity_type
entity_id
action
```

Together these describe:

```text
What happened?
      │
      ├── event_type
      │
      └── action

To what?
      │
      ├── entity_type
      └── entity_id
```

---

# Actor Model

An audit event records who or what caused the event through:

```text
actor_type
actor_id
```

Supported actor types are:

```text
customer
agent
admin
system
ai
```

The database enforces actor identity rules:

```text
system / ai
    → actor_id must be NULL

customer / agent / admin
    → actor_id may identify the actor
```

This cleanly distinguishes human actors from system-generated and AI-generated events.

---

# Correlation Context

Audit events can optionally carry:

```text
trace_id
conversation_id
ai_run_id
```

This allows an audit event to be correlated with:

```text
HTTP request
      │
      ▼
Trace
      │
      ▼
Conversation
      │
      ▼
AI run
      │
      ▼
Business state mutation
```

The fields are indexed according to these operational investigation paths.

---

# Before / After State

Audit events can optionally store:

```text
before_state
after_state
```

as PostgreSQL `JSONB`.

This allows a mutation to retain structured state context:

```text
Before
  │
  ▼
Business operation
  │
  ▼
After
```

For example, a ticket update can potentially capture the relevant state transition without requiring the audit layer to query the operational table later.

---

# Reason and Metadata

An event can additionally contain:

```text
reason
metadata
```

`reason` is free-form text, while `metadata` is structured JSONB.

As with `APIRequestModel`, the Python ORM property is:

```text
metadata_
```

while the actual database column is:

```text
metadata
```

---

# Event Timing

Two timestamps are maintained:

```text
occurred_at
recorded_at
```

Both are timezone-aware and default to the database current time.

The distinction allows the system to conceptually separate:

```text
occurred_at
    = when the business event happened

recorded_at
    = when the audit record was persisted
```

---

# Relationship Between the Two Models

The two tables answer different questions.

## API Request

```text
Who called what API?
        │
        ▼
What HTTP result occurred?
        │
        ▼
How long did it take?
```

## Audit Event

```text
What business/security action happened?
        │
        ▼
Which entity changed?
        │
        ▼
Who/what caused it?
        │
        ▼
What was the state transition?
```

Together:

```text
                         AUDIT
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
       APIRequestModel            AuditEventModel
              │                         │
        HTTP activity             Domain activity
              │                         │
              ├──── trace_id ───────────┤
              │                         │
              └──── actor/context ──────┘
```

---

# Example End-to-End Flow

A customer updates a ticket through the API.

The system may produce:

```text
1. HTTP request
       │
       ▼
audit.api_requests
       │
       ├── method = PATCH
       ├── route_template = ticket endpoint
       ├── status_code = 200
       ├── outcome = success
       ├── latency_ms = ...
       └── trace_id = ...

2. Business mutation
       │
       ▼
audit.audit_events
       │
       ├── event_type = ...
       ├── entity_type = ticket
       ├── entity_id = ...
       ├── action = ...
       ├── actor_type = customer/agent
       ├── actor_id = ...
       ├── before_state = ...
       ├── after_state = ...
       └── trace_id = ...
```

The first record answers **how the API operation behaved**.

The second answers **what business change occurred**.

---

# Indexing Strategy

Both models are heavily indexed around investigation and operational query patterns.

## API Requests

Indexes support queries by:

```text
trace
start time
route + start time
status + start time
outcome + start time
error + start time
actor + start time
latency
```

This supports dashboards, troubleshooting, latency analysis, error analysis, and request tracing.

## Audit Events

Indexes support:

```text
occurred time
event type + time
entity + time
actor + time
trace
conversation + time
AI run + time
```

This supports historical reconstruction and entity-centric audit investigations.

---

# Data Integrity

Both models rely heavily on database-level constraints.

## API requests

The database validates:

```text
HTTP method
outcome
status code
latency
request size
response size
completion timing
outcome/status consistency
```

## Audit events

The database validates:

```text
actor type
event type non-emptiness
entity type non-emptiness
action non-emptiness
actor identity rules
```

This ensures that audit records cannot easily enter obviously invalid states even when persistence occurs outside higher-level application validation.

---

# Security and Privacy Boundaries

The audit layer is intentionally **not a raw traffic recorder**.

For API requests, sensitive information such as:

```text
authorization tokens
cookies
sensitive headers
unrestricted request bodies
unrestricted response bodies
```

must not be stored.

The goal is to preserve useful operational information without turning the audit database into a repository of secrets or arbitrary payloads.

For business events, structured `before_state`, `after_state`, and `metadata` should therefore be populated according to the application's audit-data policy rather than used as unrestricted dumps.

---

# Timestamp and Correlation Philosophy

The two models together provide several levels of temporal and request correlation:

```text
API Request
│
├── started_at
├── completed_at
├── recorded_at
└── trace_id
       │
       ▼
Audit Event
│
├── occurred_at
├── recorded_at
├── trace_id
├── conversation_id
└── ai_run_id
```

This makes it possible to connect:

```text
HTTP operation
      ↓
request trace
      ↓
business operation
      ↓
conversation / AI execution
      ↓
historical audit event
```

---

# Model Responsibility Matrix

| File             | Model             | Responsibility                                          |
| ---------------- | ----------------- | ------------------------------------------------------- |
| `api_request.py` | `APIRequestModel` | Persist one HTTP/API request and its operational result |
| `audit_event.py` | `AuditEventModel` | Persist immutable business/security audit history       |

---

# What This Package Does Not Do

These models only define the **persistence representation**.

They do not themselves:

* intercept HTTP requests;
* create audit events;
* calculate application-level latency;
* decide which business actions require auditing;
* redact sensitive information;
* perform authorization;
* query audit history;
* generate dashboards.

Those responsibilities belong to the application-layer services, middleware, repositories, and observability/audit components.

---

# Design Principles

### 1. Separate operational telemetry from business audit history

`APIRequestModel` describes API execution, while `AuditEventModel` describes domain mutations.

### 2. Preserve historical auditability

Audit events intentionally avoid foreign-key dependencies on the records they describe.

### 3. Keep audit data append-only

Business audit events are immutable and should never be updated or deleted through repositories.

### 4. Support trace-based investigation

Both models expose `trace_id`, allowing operational and business records to be connected.

### 5. Enforce invariants in PostgreSQL

Important state relationships are represented as database constraints rather than relying exclusively on application code.

### 6. Avoid persisting secrets

The API request model explicitly prohibits raw credentials, tokens, cookies, and unrestricted payloads.

### 7. Preserve extensibility

Both models provide JSONB metadata for structured information that does not justify dedicated relational columns.

---

# Mental Model

The easiest way to remember this package is:

```text
                    AUDIT LAYER
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
   APIRequestModel                AuditEventModel
          │                             │
          │                             │
    "What happened               "What business/
     at the API?"                  security action
                                   happened?"
          │                             │
          ▼                             ▼
     HTTP execution              Domain mutation
          │                             │
          └─────────────┬───────────────┘
                        │
                        ▼
                 Trace / Context
```

In short:

> **`APIRequestModel` records the operational lifecycle and outcome of HTTP requests, while `AuditEventModel` preserves immutable, attributable business and security history. Together they provide the database foundation for tracing, operational investigation, compliance-oriented history, and reconstruction of important application activity.**
