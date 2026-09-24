# Audit

## Overview

The `audit` package provides the **application-layer contracts, recording service, and query services for immutable audit events** in the customer-support system.

It is responsible for exposing a clean application interface around audit-event persistence without requiring callers to work directly with the underlying database model.

```text
packages/application/audit/
├── models.py
├── recorder.py
└── query_audit_events.py
```

The package is organized around three responsibilities:

```text
models.py
    │
    ├── Input contracts
    ├── Actor representation
    ├── Audit event view
    └── Query filters
    │
    ▼
recorder.py
    │
    └── Record immutable audit events
    │
    ▼
query_audit_events.py
    │
    ├── Get one event
    ├── List events
    ├── Entity history
    └── Trace history
```

The three modules deliberately separate **data contracts**, **write behavior**, and **read behavior**.

---

# Location

```text
AI-customer-support-agent/
└── packages/
    └── application/
        └── audit/
            ├── models.py
            ├── recorder.py
            └── query_audit_events.py
```

This package sits under `packages/application`, making it an application-layer boundary around the audit subsystem.

---

# Responsibilities

The package provides four primary capabilities:

1. Define the application-facing audit contracts.
2. Record audit events within an existing database transaction.
3. Query individual audit events.
4. Query audit history by entity or trace.

The package does **not** expose raw database models as its primary application API.

Instead, persisted audit rows are converted into immutable `AuditEventView` objects.

---

# Module Structure

## `models.py`

Defines the application-layer types used by both recording and querying:

* `AuditActor`
* `AuditRecord`
* `AuditEventView`
* `AuditEventQuery`

These models describe **what an audit event is** and **what information is required to create or query one**.

---

## `recorder.py`

Contains:

```python
AuditEventRecorder
```

This service is responsible for creating audit-event records.

Its key design characteristics are:

* uses an existing SQLAlchemy `Session`;
* does not create or commit its own transaction;
* validates JSON payloads;
* flushes the newly created event;
* returns an application-level `AuditEventView`.

---

## `query_audit_events.py`

Contains:

```python
AuditEventQueryService
```

This service provides read-side operations for audit events.

It supports:

* retrieving a single event;
* listing events using filters;
* retrieving an entity's audit history;
* retrieving events associated with a trace.

---

# Architectural Model

The package follows a simple application-layer separation:

```text
                  Application Layer
                         │
              ┌──────────┴──────────┐
              │                     │
              ▼                     ▼
       AuditEventRecorder    AuditEventQueryService
              │                     │
              │                     │
              ▼                     ▼
        SQLAlchemy Session    SQLAlchemy Session
              │                     │
              └──────────┬──────────┘
                         ▼
                 Persisted Audit Data
```

The application layer works with application contracts rather than exposing persistence structures directly.

---

# Domain Concepts

## Audit Actor

An audit event records **who or what caused an action**.

The actor is represented by:

```python
@dataclass(frozen=True, slots=True)
class AuditActor:
    actor_type: str
    actor_id: str | None = None
```

The actor therefore consists of:

```text
actor_type
actor_id
```

`actor_id` is optional because some actor types may not have a concrete identifier.

---

# `AuditActor`

`AuditActor` is immutable because it is declared with:

```python
@dataclass(frozen=True, slots=True)
```

This makes it suitable as a value object within an audit-recording request.

The model validates that:

* `actor_type` is a string;
* `actor_type` is not empty after trimming;
* `actor_id`, when supplied, is a string;
* `actor_id`, when supplied, is not empty after trimming.

Whitespace is normalized before the values are stored.

---

# `AuditRecord`

`AuditRecord` represents the information needed to **create an audit event**.

It contains the audit event's core attributes, including:

* actor information;
* action information;
* entity information;
* payload/context information;
* correlation information.

The model is immutable and slot-based.

Conceptually:

```text
AuditRecord
├── Actor
├── Action
├── Entity
├── Payload
└── Correlation / trace information
```

This is the write-side contract consumed by `AuditEventRecorder`.

---

# `AuditEventView`

`AuditEventView` represents an audit event **after it has been persisted and read back by the application layer**.

It provides a persistence-independent view of the event.

The recorder returns this type after inserting an event, while the query service uses it as the return type for reads.

This creates a consistent boundary:

```text
Database Model
      │
      ▼
AuditEventView
      │
      ▼
Application Code
```

Application callers therefore do not need to depend directly on the database model.

---

# `AuditEventQuery`

`AuditEventQuery` contains the filters used when retrieving audit events.

It allows callers to express constraints without constructing SQLAlchemy queries themselves.

The query model supports filtering around the audit-event dimensions represented by the package, including event/entity and correlation information, together with result limiting.

The query service translates this application-level object into database query conditions.

---

# Validation Strategy

The models use explicit runtime validation.

Invalid input is rejected at the contract boundary rather than allowing malformed audit data to reach persistence.

The general pattern is:

```text
Caller Input
     │
     ▼
Application Model
     │
     ├── valid ─────► continue
     │
     └── invalid ───► raise validation error
```

This is particularly important for audit records because audit data is intended to be durable historical information.

---

# Immutability

The audit application models use:

```python
@dataclass(frozen=True, slots=True)
```

This is important for audit-related data because the objects represent historical facts or commands describing historical facts.

Once constructed, callers should not mutate:

* actor information;
* event information;
* query parameters;
* event views.

---

# Recording Audit Events

## `AuditEventRecorder`

`AuditEventRecorder` is the write-side service.

It receives an existing SQLAlchemy session:

```text
AuditEventRecorder
       │
       ▼
SQLAlchemy Session
       │
       ▼
Audit Event Persistence
```

The recorder does not own the lifecycle of the surrounding database transaction.

---

# Transaction Ownership

A central design characteristic of `AuditEventRecorder` is that it **does not commit the transaction**.

The caller owns the transaction boundary.

Conceptually:

```python
with session.begin():
    recorder.record(...)
    other_operation(...)
```

The recorder participates in the transaction rather than creating an independent transaction.

This allows the audit event to participate in the same atomic unit of work as the operation being audited.

---

# Why Transaction Participation Matters

The intended relationship is:

```text
Business Operation
       │
       ├── succeeds
       │
       └── Audit Event
              │
              ▼
          same transaction
```

If the surrounding transaction rolls back, the audit write participates in that rollback.

The recorder therefore does not independently commit an audit event outside the caller's transaction.

---

# Recording Flow

The recording process can be represented as:

```text
AuditRecord
    │
    ▼
Validate / Normalize
    │
    ▼
Construct persistence model
    │
    ▼
Add to SQLAlchemy Session
    │
    ▼
Flush
    │
    ▼
Convert persisted model
    │
    ▼
AuditEventView
```

The database write is performed through the supplied session.

---

# Flush vs Commit

The recorder uses a flush operation rather than committing the transaction.

Conceptually:

```text
session.add(event)
       │
       ▼
session.flush()
       │
       ▼
Database receives INSERT
       │
       ▼
Transaction remains caller-owned
```

This allows database-generated values to become available while preserving transaction ownership.

---

# JSON Payload Handling

Audit events can contain structured payload data.

The recorder validates payloads before persistence.

The intent is to ensure that the payload can be represented as valid JSON-compatible data rather than arbitrary Python objects.

This protects the persistence boundary from unsupported values.

---

# Audit Event Conversion

After persistence, the recorder converts the database representation into:

```python
AuditEventView
```

This conversion keeps database-specific representation details out of the rest of the application.

```text
ORM Model
   │
   ▼
Conversion
   │
   ▼
AuditEventView
```

The same application-facing representation is then used by the query service.

---

# Querying Audit Events

## `AuditEventQueryService`

The read-side service is:

```python
AuditEventQueryService
```

It provides application-level query methods over persisted audit events.

Its purpose is to hide query construction from application callers.

---

# Single Event Lookup

The service supports retrieving an individual audit event.

Conceptually:

```text
Event ID
   │
   ▼
AuditEventQueryService
   │
   ▼
Database Query
   │
   ▼
AuditEventView | None
```

If the requested event does not exist, the service can represent that absence without exposing raw persistence details.

---

# Listing Events

The query service supports filtered event retrieval.

The flow is:

```text
AuditEventQuery
       │
       ▼
AuditEventQueryService
       │
       ▼
SQLAlchemy Query
       │
       ▼
Persisted Events
       │
       ▼
AuditEventView[]
```

The application therefore does not need to construct SQLAlchemy filter expressions directly.

---

# Entity History

One of the important query operations is retrieving the history of an entity.

Conceptually:

```text
Entity
  │
  ▼
AuditEventQueryService
  │
  ▼
Events concerning entity
  │
  ▼
Chronological audit history
```

This allows callers to reconstruct the recorded sequence of changes/actions associated with an entity.

---

# Trace History

The service also supports querying events by trace correlation.

Conceptually:

```text
Trace ID
   │
   ▼
AuditEventQueryService
   │
   ▼
All matching audit events
   │
   ▼
AuditEventView[]
```

Trace-based queries are useful when multiple application operations belong to the same distributed or workflow execution.

---

# Entity vs Trace Queries

These two query dimensions answer different questions.

### Entity history

```text
"What happened to this entity?"
```

### Trace history

```text
"What audit events occurred during this execution/trace?"
```

Both are exposed through the same application query service.

---

# Query Result Boundary

The query service returns application-level views rather than raw ORM instances.

```text
SQLAlchemy ORM
      │
      ▼
AuditEventView
      │
      ▼
Application caller
```

This prevents persistence-layer implementation details from leaking into higher application layers.

---

# Read/Write Separation

The package separates write and read responsibilities:

```text
                  Audit Package
                       │
             ┌─────────┴─────────┐
             │                   │
             ▼                   ▼
        Write Side           Read Side
             │                   │
             ▼                   ▼
      AuditEventRecorder   AuditEventQueryService
             │                   │
             ▼                   ▼
       Create events        Query events
```

The shared models provide the contracts between these operations.

---

# Complete Data Flow

The package can be viewed as:

```text
                    AuditRecord
                         │
                         ▼
               AuditEventRecorder
                         │
                    SQLAlchemy
                      Session
                         │
                         ▼
                 Persisted Event
                         │
                         ▼
                  AuditEventView
                         │
              ┌──────────┴──────────┐
              │                     │
              ▼                     ▼
     Individual Lookup       Query / History
              │                     │
              └──────────┬──────────┘
                         ▼
                AuditEventView[]
```

---

# Application Boundary

The package provides a deliberate boundary between application logic and persistence.

Without this boundary, application code could become coupled directly to ORM structures:

```text
Application
     │
     ▼
SQLAlchemy Model
     │
     ▼
Database
```

With this package:

```text
Application
     │
     ▼
Audit Application Service
     │
     ▼
Application Contracts
     │
     ▼
SQLAlchemy / Database
```

This makes the application-facing audit API more stable.

---

# Error Handling

Validation failures occur at the model/service boundaries.

The package does not silently accept malformed audit information.

Examples of invalid conditions include:

* empty actor types;
* invalid actor IDs;
* invalid payload structures;
* invalid query parameters;
* invalid event-record data.

Database-level failures remain database/session failures rather than being silently converted into successful audit operations.

---

# Usage Pattern — Recording

The intended conceptual usage is:

```python
record = AuditRecord(
    ...
)

event = recorder.record(record)
```

The caller supplies the session/transaction context.

The resulting value is an:

```python
AuditEventView
```

rather than a raw ORM object.

---

# Usage Pattern — Querying

A caller constructs an application-level query:

```python
query = AuditEventQuery(
    ...
)

events = query_service.list(query)
```

The query service translates that request into the underlying database query.

---

# Transactional Usage

A typical application flow is conceptually:

```text
BEGIN TRANSACTION
       │
       ▼
Perform application operation
       │
       ▼
Record audit event
       │
       ▼
Flush audit event
       │
       ▼
Perform remaining work
       │
       ▼
COMMIT
```

The recorder itself does not decide whether the transaction commits or rolls back.

---

# Why the Package Is Split into Three Files

The three-file organization provides clear responsibilities.

## `models.py`

Answers:

> What does an audit actor/event/query look like?

## `recorder.py`

Answers:

> How does the application record an audit event?

## `query_audit_events.py`

Answers:

> How does the application retrieve audit events and histories?

This keeps data contracts separate from database write and read behavior.

---

# Dependency Direction

The dependency relationship is intentionally straightforward:

```text
models.py
   ▲
   │
   ├──────── recorder.py
   │
   └──────── query_audit_events.py
```

Both service modules depend on the application-level contracts.

The models do not depend on either service.

This keeps the contracts reusable.

---

# Design Principles

## 1. Application-facing contracts

Application code interacts through `AuditRecord`, `AuditEventView`, and query contracts rather than directly through persistence structures.

## 2. Immutable audit representations

Audit contracts are immutable, preventing accidental modification of historical information.

## 3. Caller-owned transactions

`AuditEventRecorder` participates in an existing SQLAlchemy transaction rather than committing independently.

## 4. Explicit validation

Malformed actor, event, payload, and query data is rejected early.

## 5. Read/write separation

Recording and querying are handled by separate application services.

## 6. Persistence isolation

ORM/database representations are converted into application-facing views.

## 7. Query encapsulation

Callers express query intent through application models rather than constructing SQLAlchemy statements themselves.

## 8. Correlation support

The query layer supports both entity-oriented history and trace-oriented investigation.

---

# Module Responsibility Matrix

| File                    | Primary Responsibility              | Main Consumers                                 |
| ----------------------- | ----------------------------------- | ---------------------------------------------- |
| `models.py`             | Audit contracts and immutable views | Recorder, Query Service, application callers   |
| `recorder.py`           | Record audit events                 | Application workflows                          |
| `query_audit_events.py` | Retrieve and filter audit history   | Application services / investigation workflows |

---

# Conceptual API

The package can be understood as exposing two primary application services:

```text
┌─────────────────────────────────────┐
│          Application Audit          │
├─────────────────────────────────────┤
│                                     │
│  AuditEventRecorder                 │
│      └── record(...)                │
│                                     │
│  AuditEventQueryService             │
│      ├── get(...)                   │
│      ├── list(...)                  │
│      ├── entity_history(...)        │
│      └── trace_history(...)         │
│                                     │
└─────────────────────────────────────┘
```

The exact method signatures should be treated according to the source implementation; this diagram represents the responsibilities exposed by the three modules.

---

# Security and Integrity Considerations

Audit data is intended to represent historical system activity, so the package emphasizes:

* immutable application contracts;
* explicit actor information;
* structured payload validation;
* controlled transaction participation;
* application-level query boundaries.

The recorder's lack of independent commit authority is particularly important because it prevents the audit component from unilaterally determining transaction durability.

---

# Operational Investigation Flow

The query service supports two natural investigation paths.

### Investigating an entity

```text
Entity Identifier
       │
       ▼
Entity History Query
       │
       ▼
Audit Events
       │
       ▼
Reconstruct Recorded Activity
```

### Investigating a workflow/trace

```text
Trace Identifier
       │
       ▼
Trace Query
       │
       ▼
Related Audit Events
       │
       ▼
Reconstruct Execution History
```

These capabilities make the audit package useful both for normal application workflows and for historical investigation.

---

# Summary

The `packages/application/audit/` package is the **application-layer interface for recording and querying immutable audit events**.

Its architecture is intentionally simple:

```text
                       Audit
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
       Models         Recorder        Queries
          │              │              │
          │              ▼              │
          │       Persist Audit Event   │
          │                             │
          └──────────────┬──────────────┘
                         ▼
                 AuditEventView
```

### `models.py`

Defines the immutable application contracts used throughout the audit subsystem.

### `recorder.py`

Provides transactional audit-event recording using an existing SQLAlchemy session and returns application-level event views.

### `query_audit_events.py`

Provides application-level read operations for individual events, filtered event lists, entity history, and trace history.

Together, the three files establish a clean boundary:

```text
Application Workflows
        │
        ▼
┌─────────────────────────────┐
│     application.audit       │
│                             │
│ Models                      │
│ Recorder                    │
│ Query Service               │
└──────────────┬──────────────┘
               │
               ▼
      Persistence Layer
               │
               ▼
          Audit Data
```

The package therefore keeps audit persistence concerns behind a small set of explicit, immutable application contracts and services.
