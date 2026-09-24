# Database Unit of Work

## Overview

The `packages/database/unit_of_work/` package provides the **transaction boundary between application services and the database repositories**.

Its primary responsibility is to ensure that multiple repositories participating in one application operation share the **same SQLAlchemy `Session` and database transaction**.

```text
Application Service
        │
        ▼
   Unit of Work
        │
        ├── Repository A
        ├── Repository B
        ├── Repository C
        └── Repository D
                │
                ▼
        Shared SQLAlchemy Session
                │
                ▼
             PostgreSQL
```

The application layer should depend on the Unit of Work abstraction rather than directly managing SQLAlchemy sessions.

---

## Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── database/
        └── unit_of_work/
            ├── base.py
            ├── sqlalchemy_uow.py
            └── knowledge.py
```

| File | Responsibility |
|---|---|
| `base.py` | Defines the framework-independent Unit of Work contract |
| `sqlalchemy_uow.py` | Main application-wide SQLAlchemy Unit of Work |
| `knowledge.py` | Knowledge-domain-specific SQLAlchemy Unit of Work |

---

# Why Unit of Work?

Repositories handle individual persistence operations, but a business operation frequently requires several repositories together.

For example:

```text
Customer request
      │
      ├── create conversation
      ├── persist message
      ├── create AI run
      ├── persist LLM call
      └── write audit event
              │
              ▼
          One transaction
```

Without a Unit of Work, each repository could accidentally use a different session or transaction.

The Unit of Work guarantees:

```text
One business operation
        │
        ▼
One Unit of Work
        │
        ▼
One SQLAlchemy Session
        │
        ▼
One transaction boundary
```

The main SQLAlchemy implementation explicitly documents that every repository exposed by the Unit of Work shares the exact same `Session`.

---

# 1. `base.py`

## `UnitOfWork`

`base.py` defines the **application-facing contract**.

It uses `Protocol`, so the application does not need to depend on SQLAlchemy-specific implementation details.

The contract provides:

```text
__enter__()
__exit__()
commit()
rollback()
flush()
```



### Purpose

The abstraction establishes this architectural boundary:

```text
Application
     │
     │ depends on
     ▼
 UnitOfWork Protocol
     ▲
     │ implemented by
     │
     └── SqlAlchemyUnitOfWork
```

This keeps SQLAlchemy session management out of application-level business logic.

---

# 2. `sqlalchemy_uow.py`

## `SqlAlchemyUnitOfWork`

`SqlAlchemyUnitOfWork` is the **main Unit of Work implementation for the application**.

It creates one SQLAlchemy session and initializes the repositories required by the different database domains.

The implementation covers repositories from:

```text
Audit
Support
AI
Dashboard
```

The repository set includes users, authentication, conversations, messages, escalations, tickets, feedback, AI runs, LLM calls, intent predictions, decisions, stage events, embeddings, retrieval, reranking, and dashboard repositories.

### Repository Composition

Conceptually:

```text
SqlAlchemyUnitOfWork
│
├── Audit
│   ├── api_requests
│   └── audit_events
│
├── Support
│   ├── users
│   ├── auth
│   ├── conversations
│   ├── conversation_start_requests
│   ├── messages
│   ├── escalations
│   ├── tickets
│   ├── ticket_comments
│   └── feedback
│
├── AI
│   ├── ai_runs
│   ├── llm_calls
│   ├── intent_predictions
│   ├── ai_decisions
│   ├── stage_events
│   ├── embedding_calls
│   ├── retrieval
│   └── reranker_calls
│
└── Dashboard
    ├── overview
    ├── trace
    ├── trace_detail
    ├── llm_calls
    ├── retrieval_runs
    ├── api_requests
    └── audit_events
```

All of these repositories are constructed using the **same session** when the Unit of Work is entered.

---

## Lifecycle

The intended usage is:

```text
with SqlAlchemyUnitOfWork() as uow:
    ...
    uow.commit()
```

The Unit of Work creates its session when entering the context.

When leaving:

```text
Exception
    │
    ▼
rollback
    │
    ▼
close session
```

or:

```text
No commit()
    │
    ▼
rollback
    │
    ▼
close session
```

Only an explicit `commit()` allows changes to persist.

This is intentionally **explicit-commit semantics**.

---

# Transaction Semantics

The transaction rules are deliberately strict:

```text
┌───────────────────────────────┐
│ Unit of Work entered          │
│                               │
│ Create Session                │
│ Initialize repositories       │
└───────────────┬───────────────┘
                │
                ▼
        Application work
                │
       ┌────────┴────────┐
       │                 │
       ▼                 ▼
   commit()          exception /
       │             no commit()
       ▼                 │
   PERSIST              ▼
                    ROLLBACK
       │                 │
       └────────┬────────┘
                ▼
          Close Session
                │
                ▼
          Clear references
```

The implementation explicitly tracks whether `commit()` occurred using `_committed`.

---

## Explicit Commit

```python
with SqlAlchemyUnitOfWork() as uow:
    uow.tickets.create(...)
    uow.audit_events.record(...)

    uow.commit()
```

The call to `commit()` persists the transaction and marks the Unit of Work as committed.

---

## Forgotten Commit

If application code exits the context without calling `commit()`:

```python
with SqlAlchemyUnitOfWork() as uow:
    uow.tickets.create(...)
    # no commit
```

the transaction is rolled back.

This prevents accidental persistence caused simply by leaving the context manager.

---

## Exception Handling

If an exception escapes the context:

```python
with SqlAlchemyUnitOfWork() as uow:
    ...
    raise SomeError()
```

the Unit of Work rolls back the active transaction before closing the session.

This protects against partially applied application operations.

---

# Flush vs Commit

The Unit of Work exposes both operations.

### `flush()`

Synchronizes pending ORM changes with PostgreSQL **without committing**.

```text
Application changes
       │
       ▼
    flush()
       │
       ▼
PostgreSQL synchronization
       │
       ▼
Transaction remains open
```

This is useful when subsequent application logic needs database-generated effects or constraint validation before the final commit.

### `commit()`

Finalizes the transaction:

```text
Pending changes
      │
      ▼
   commit()
      │
      ▼
Persist transaction
```

---

# Session Safety

The Unit of Work prevents reuse outside its lifecycle.

Repository properties require an active Unit of Work. If accessed after the context has ended, a `RuntimeError` is raised.

After exiting, the implementation:

1. closes the session;
2. clears the session reference;
3. clears all repository references;
4. resets lifecycle state.



This prevents application code from accidentally retaining repositories backed by a closed session.

---

# Re-Entry Protection

A Unit of Work instance cannot be entered more than once.

```python
uow = SqlAlchemyUnitOfWork()

with uow:
    ...

with uow:
    ...
```

The implementation tracks `_entered` and raises an error if the same instance is entered again.

This keeps the lifecycle explicit and avoids ambiguous session ownership.

---

# 3. `knowledge.py`

## `SQLAlchemyKnowledgeUnitOfWork`

The knowledge subsystem has its own focused Unit of Work implementation.

It follows the same transaction principles as the main Unit of Work but exposes only the repositories required for knowledge operations.

```text
SQLAlchemyKnowledgeUnitOfWork
│
├── documents
├── versions
├── chunks
├── embeddings
├── embedding_calls
└── audit_events
```

These repositories all share the same SQLAlchemy session.

---

## Knowledge Transaction Boundary

The knowledge Unit of Work is useful for operations such as:

```text
Knowledge ingestion
      │
      ├── create/update document
      ├── create version
      ├── create chunks
      ├── persist embeddings
      ├── record embedding calls
      └── write audit events
             │
             ▼
         One transaction
```

This keeps related knowledge mutations atomic.

---

## Knowledge Lifecycle

Its lifecycle follows:

```text
Enter
 │
 ▼
Create Session
 │
 ▼
Initialize knowledge repositories
 │
 ▼
Application operation
 │
 ├── commit() ──────► persist
 │
 └── exception/no commit
              │
              ▼
           rollback
              │
              ▼
         close session
```

The implementation explicitly documents this transaction policy.

---

# Relationship Between the Three Files

The three files form a simple abstraction/implementation hierarchy:

```text
                     UnitOfWork
                     Protocol
                     base.py
                         │
              ┌──────────┴──────────┐
              │                     │
              ▼                     ▼
   SqlAlchemyUnitOfWork     SQLAlchemyKnowledgeUnitOfWork
     sqlalchemy_uow.py              knowledge.py
              │                     │
              ▼                     ▼
     Full application          Knowledge-focused
       repositories              repositories
              │                     │
              └──────────┬──────────┘
                         ▼
                    SQLAlchemy
                      Session
                         │
                         ▼
                     PostgreSQL
```

`base.py` defines **what a Unit of Work must provide**.

`sqlalchemy_uow.py` defines **the application's main transaction boundary**.

`knowledge.py` defines **a specialized transaction boundary for knowledge workflows**.

---

# Repository and Unit of Work Relationship

The repository layer and Unit of Work layer have different responsibilities.

```text
Repository
    │
    ├── query data
    ├── create entities
    ├── update entities
    ├── apply persistence-specific operations
    └── use provided Session
```

while:

```text
Unit of Work
    │
    ├── create Session
    ├── create repositories
    ├── group repositories into one transaction
    ├── commit
    ├── rollback
    ├── flush
    └── close Session
```

Therefore, repositories should not independently decide when the surrounding business transaction is committed.

---

# Architectural Boundary

The intended dependency direction is:

```text
Application
    │
    ▼
Unit of Work abstraction
    │
    ▼
Repository contracts / implementations
    │
    ▼
SQLAlchemy
    │
    ▼
PostgreSQL
```

The application should not need to know how sessions are created, how they are closed, or how rollback is performed.

That responsibility is centralized in the Unit of Work.

---

# Design Principles

## Shared Session

Repositories participating in the same Unit of Work share one SQLAlchemy `Session`.

## Explicit Commit

A transaction is persisted only when application code explicitly calls `commit()`.

## Safe Rollback

Exceptions and forgotten commits result in rollback.

## Centralized Transaction Management

Transaction lifecycle is handled by the Unit of Work rather than individual repositories.

## Repository Composition

A Unit of Work provides a convenient collection of related repositories for one business operation.

## Lifecycle Safety

Repositories become unavailable after the Unit of Work exits.

## Abstraction First

Application code can depend on the `UnitOfWork` protocol instead of directly depending on SQLAlchemy session management.

---

# Typical Usage

The main application pattern is:

```python
with SqlAlchemyUnitOfWork() as uow:
    conversation = uow.conversations.create(...)

    uow.messages.create(
        conversation_id=conversation.id,
        ...
    )

    uow.ai_runs.create(...)

    uow.audit_events.record(...)

    uow.commit()
```

Conceptually:

```text
with UoW
   │
   ├── Session created
   │
   ├── repositories initialized
   │
   ├── application workflow
   │      │
   │      ├── repository operation
   │      ├── repository operation
   │      └── repository operation
   │
   ├── commit()
   │
   └── Session closed
```

For knowledge-specific workflows:

```python
with SQLAlchemyKnowledgeUnitOfWork(session_factory) as uow:
    ...
    uow.flush()
    ...
    uow.commit()
```

---

# Summary

`packages/database/unit_of_work/` provides the **transaction-management boundary for database operations**.

Its responsibilities can be summarized as:

```text
base.py
    ↓
Defines the Unit of Work contract

sqlalchemy_uow.py
    ↓
Main application-wide SQLAlchemy transaction boundary

knowledge.py
    ↓
Specialized transaction boundary for knowledge workflows
```

The central guarantee is:

> **One Unit of Work = one shared SQLAlchemy Session = one controlled transaction boundary.**

The repository layer performs database operations; the Unit of Work determines how those operations participate in a transaction.

The resulting architecture keeps transaction management centralized, makes multi-repository operations atomic, prevents accidental commits, and keeps application services independent of direct SQLAlchemy session management.