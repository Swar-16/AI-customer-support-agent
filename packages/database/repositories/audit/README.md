# Audit Repositories

## Overview

The `packages/database/repositories/audit/` package provides the persistence layer for **HTTP/API request history and immutable business audit events**.

It contains two focused repositories:

```text
AI-customer-support-agent/
└── packages/
    └── database/
        └── repositories/
            └── audit/
                ├── audit_event_repository.py
                └── api_request_repository.py
```

Together they provide two complementary forms of operational history:

```text
APIRequestRepository
    → What HTTP/API traffic occurred?

AuditEventRepository
    → What business/security state changes occurred?
```

Both repositories operate on an injected SQLAlchemy `Session`, construct database queries, validate repository inputs, and stage writes. **Transaction commits remain outside the repositories**, under the application's Unit-of-Work boundary.

---

# Package Responsibilities

The audit repository layer has two distinct persistence responsibilities:

| Repository             | Purpose                         | Data character          |
| ---------------------- | ------------------------------- | ----------------------- |
| `AuditEventRepository` | Business/security audit history | Append-only, immutable  |
| `APIRequestRepository` | HTTP request/traffic history    | Durable request records |

The distinction is important:

```text
                    Audit Repository Layer
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
       API Request History           Business Audit History
              │                             │
              ▼                             ▼
      APIRequestModel              AuditEventModel
```

The repositories deliberately do not expose raw HTTP framework objects, make security decisions about what should be recorded, extract actor identity, or calculate request latency. Those responsibilities belong to the application/observability layer that creates the persistence models.

---

# 1. `audit_event_repository.py`

## `AuditEventRepository`

`AuditEventRepository` is the persistence adapter for **immutable business audit events**.

The repository explicitly exposes:

* no update operation;
* no delete operation.

Audit events are therefore treated as historical records rather than mutable business state.

It works with:

```text
AuditEventModel
```

and receives a SQLAlchemy `Session` during construction.

---

## Write Operations

### `add(event)`

Stages an `AuditEventModel` in the current transaction.

The method:

1. validates that the supplied object is an `AuditEventModel`;
2. adds it to the SQLAlchemy session;
3. does **not** flush;
4. does **not** commit.

### `flush()`

Explicitly flushes pending audit events to the database without committing the surrounding transaction.

This keeps transaction ownership with the caller/Unit of Work.

---

## Primary Lookups

### `get_by_id()`

Retrieves one audit event using its UUID.

The repository validates the UUID before constructing the query.

### `get_by_trace_id()`

Retrieves all audit events associated with a trace.

Results are ordered chronologically:

```text
occurred_at ASC
id ASC
```

The secondary ID ordering provides deterministic ordering when multiple events share the same timestamp.

This makes it possible to reconstruct the audit timeline associated with an execution trace.

---

## Entity History

### `get_entity_history()`

Retrieves the immutable history of a particular business entity.

The lookup uses:

```text
entity_type
entity_id
```

and returns events oldest-first:

```text
occurred_at ASC
id ASC
```

This ordering allows callers to inspect the lifecycle of an entity in mutation order.

Conceptually:

```text
Entity
  │
  ├── Event 1
  ├── Event 2
  ├── Event 3
  └── Event 4
```

This is useful for reconstructing how a business object changed over time.

---

# Audit Event Dashboard Queries

## `list_recent()`

`list_recent()` provides a flexible, paginated query for recent business audit events.

It supports filtering by:

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
```

and supports:

```text
limit
offset
```

Results are ordered newest-first:

```text
occurred_at DESC
id DESC
```

This method is intended as a **paginated dashboard/query primitive**. Aggregate dashboard metrics should be implemented separately rather than derived from this limited result set.

---

# Audit Actor Types

The repository recognizes the following audit actor types:

```text
customer
agent
admin
system
ai
```

The value is normalized to lowercase and validated against this fixed set.

This prevents arbitrary actor-type values from entering repository queries.

---

# Audit Validation

`AuditEventRepository` validates:

* model type;
* UUID parameters;
* required text;
* optional text;
* actor type;
* pagination;
* limits;
* datetime ranges.

The repository limits result sizes to a maximum of **500 records per query**.

Datetime filters must be timezone-aware, and:

```text
occurred_from <= occurred_to
```

must hold whenever both bounds are supplied.

---

# 2. `api_request_repository.py`

## `APIRequestRepository`

`APIRequestRepository` is the persistence adapter for **durable HTTP request records**.

It works with:

```text
APIRequestModel
```

and provides persistence and query functionality for recorded API traffic.

The repository deliberately does not:

* commit transactions;
* determine what request information is safe to record;
* extract actor identity;
* calculate latency;
* expose raw HTTP objects.

This creates a clean separation between:

```text
HTTP / Observability Layer
        │
        │ creates sanitized request record
        ▼
APIRequestRepository
        │
        ▼
     Database
```

---

# API Request Writes

### `add(request_record)`

Stages an `APIRequestModel` in the current transaction.

It validates the model type before calling:

```python
session.add(...)
```

It does not flush or commit.

### `flush()`

Flushes pending API request records without committing the transaction.

---

# API Request Lookups

### `get_by_id()`

Retrieves one request record using its UUID.

### `get_by_trace_id()`

Retrieves HTTP requests associated with a trace.

The repository explicitly does **not** assume that a trace ID uniquely identifies a single request. A caller may reuse one correlation ID across multiple related HTTP requests.

Results are ordered chronologically:

```text
started_at ASC
id ASC
```

This makes the method suitable for reconstructing request activity within a trace.

---

# API Traffic Dashboard Queries

## `list_recent()`

`list_recent()` is the primary paginated API-request query used by the MVP dashboard.

It supports filters for:

```text
method
route_template
status_code
outcome
error_code
actor_user_id
trace_id
minimum_latency_ms
started_from
started_to
```

along with:

```text
limit
offset
```

Results are ordered newest-first:

```text
started_at DESC
id DESC
```

As with audit-event querying, aggregate metrics should be implemented separately rather than calculated from this paginated result.

---

# HTTP Method Validation

The repository recognizes:

```text
GET
POST
PUT
PATCH
DELETE
OPTIONS
HEAD
```

Methods are normalized to uppercase before validation.

---

# API Request Outcome Validation

Supported request outcomes are:

```text
success
client_error
server_error
```

Values are normalized to lowercase before validation.

---

# HTTP Status and Latency Validation

The repository validates:

### Status code

HTTP status codes must be integers in:

```text
100–599
```

### Minimum latency

`minimum_latency_ms` must be a non-negative integer.

The repository therefore treats latency as an already-computed persisted value rather than calculating it itself.

---

# Pagination

Both repositories use the same basic pagination rules.

```text
limit
    > 0
    <= 500

offset
    >= 0
```

Boolean values are explicitly rejected even though Python considers `bool` a subclass of `int`.

For `AuditEventRepository`, these rules are implemented by `_validate_limit()` and `_validate_pagination()`.

The equivalent validation exists in `APIRequestRepository`.

This provides a consistent bounded-query contract for dashboard consumers.

---

# Time-Range Validation

Both repositories require datetime filters to be **timezone-aware**.

For API requests:

```text
started_from
started_to
```

must contain timezone-aware `datetime` values when supplied.

For audit events:

```text
occurred_from
occurred_to
```

follow the same requirement.

Both enforce:

```text
from <= to
```

This prevents ambiguous or invalid time-window queries.

---

# Transaction Model

Neither repository commits transactions.

The intended usage is:

```text
Application / Observability Service
              │
              ▼
          Unit of Work
              │
       ┌──────┴──────┐
       │             │
       ▼             ▼
 APIRequestRepo   AuditEventRepo
       │             │
       └──────┬──────┘
              ▼
           flush()
              │
              ▼
           commit()
```

The repositories therefore remain persistence adapters rather than transaction managers.

This is particularly useful when an application operation needs to persist several related records atomically.

---

# Relationship Between the Two Repositories

Although both repositories belong to the `audit` package, they represent different layers of observability.

```text
                         AUDIT
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
       API Request History       Business Audit History
              │                         │
              ▼                         ▼
    "What happened at the       "What business/security
      HTTP boundary?"              action occurred?"
```

For example:

```text
HTTP Request
    │
    ▼
APIRequestRepository
    │
    │ records request-level activity
    ▼
Application Use Case
    │
    ├── business mutation
    │
    ▼
AuditEventRepository
    │
    │ records business/security event
    ▼
Audit History
```

This separation prevents business audit semantics from being confused with generic HTTP traffic logging.

---

# Correlation

Both repositories support correlation through identifiers such as:

```text
trace_id
```

The audit-event repository additionally supports:

```text
conversation_id
ai_run_id
entity_id
actor_id
```

The API-request repository supports:

```text
actor_user_id
trace_id
```

This makes it possible for higher-level observability and dashboard services to connect:

```text
HTTP request
     │
     ▼
Trace
     │
     ├── AI execution
     ├── business operations
     └── audit events
```

The repositories themselves only persist/query these relationships; they do not perform cross-domain correlation logic.

---

# Separation of Concerns

The design intentionally divides responsibilities across layers.

```text
┌────────────────────────────────────────────┐
│ HTTP / Application / Observability Layer   │
│                                            │
│ • decides what is safe to record           │
│ • extracts actor information               │
│ • calculates request latency               │
│ • creates sanitized model instances        │
└──────────────────────┬─────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────┐
│ Audit Repositories                         │
│                                            │
│ • validate repository inputs               │
│ • construct SQL queries                    │
│ • stage persistence                        │
│ • retrieve historical records              │
└──────────────────────┬─────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────┐
│ SQLAlchemy Models / PostgreSQL             │
└────────────────────────────────────────────┘
```

This is especially explicit for `APIRequestRepository`, which does not decide what request data is safe to persist or calculate latency.

---

# Query Patterns

The two repositories provide three primary categories of access.

## Point Lookup

```text
get_by_id(...)
```

Used when a caller knows the exact record UUID.

## Correlation Lookup

```text
get_by_trace_id(...)
```

Used to reconstruct activity associated with a trace.

## Dashboard / Historical Query

```text
list_recent(...)
```

Used for filtered, paginated operational views.

The audit repository additionally provides:

```text
get_entity_history(...)
```

for reconstructing the lifecycle of a particular business entity.

---

# Repository Design Principles

## 1. Append-only audit history

Business audit events cannot be updated or deleted through the repository.

## 2. Durable request history

HTTP requests are represented as explicit persistence records rather than exposing raw framework request objects.

## 3. No transaction ownership

Repositories stage and flush changes but leave commits to the Unit of Work.

## 4. Bounded queries

All paginated queries enforce a maximum limit of 500.

## 5. Strict input validation

UUIDs, enums, pagination, status codes, text fields, and time ranges are validated before SQL execution.

## 6. Deterministic ordering

Queries use timestamps plus IDs as secondary ordering keys to provide stable results.

## 7. Dashboard-friendly access

`list_recent()` methods expose filtering and pagination needed by operational dashboards without turning the repository into an analytics engine.

## 8. No business decisions

Repositories persist and retrieve information; they do not decide what should be recorded or what business action should occur.

---

# Summary

`packages/database/repositories/audit/` provides the persistence boundary for two complementary historical data streams:

```text
┌───────────────────────────────────────────────────┐
│             Audit Repository Layer                │
├───────────────────────────────────────────────────┤
│                                                   │
│  APIRequestRepository                             │
│      │                                            │
│      ├── API request persistence                  │
│      ├── trace-based lookup                       │
│      ├── dashboard filtering                      │
│      └── HTTP/outcome validation                  │
│                                                   │
│  AuditEventRepository                             │
│      │                                            │
│      ├── immutable business audit persistence     │
│      ├── trace-based lookup                       │
│      ├── entity lifecycle history                 │
│      ├── dashboard filtering                      │
│      └── actor/event validation                   │
│                                                   │
└───────────────────────┬───────────────────────────┘
                        │
                        ▼
                SQLAlchemy Session
                        │
                        ▼
                  Unit of Work
                        │
                        ▼
                    PostgreSQL
```

The central architectural distinction is:

> **`APIRequestRepository` records HTTP-level activity, while `AuditEventRepository` preserves immutable business/security history.**

Both provide controlled, validated database access while leaving **business semantics, sanitization, correlation decisions, and transaction ownership to higher application layers**.
