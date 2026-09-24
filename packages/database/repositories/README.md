# Database Repositories

## Overview

The `packages/database/repositories/` package is the **persistence-access layer of the AI customer-support system**.

It provides focused repository implementations between the application/domain layers and the PostgreSQL database:

```text
Application / Domain Services
            │
            ▼
    Repository Contracts
            │
            ▼
┌─────────────────────────────────┐
│  packages/database/repositories │
│                                 │
│   AI                            │
│   Knowledge                     │
│   Support                       │
│   Dashboard                     │
│   Audit                         │
└────────────────┬────────────────┘
                 │
                 ▼
        SQLAlchemy ORM Models
                 │
                 ▼
             PostgreSQL
```

The repository layer keeps database access out of application services while providing **domain-oriented querying, persistence, concurrency handling, aggregation, and retrieval operations**.

The detailed behavior of each subsystem belongs in its respective child README.

---

## Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── database/
        └── repositories/
            ├── ai/
            ├── audit/
            ├── dashboard/
            ├── knowledge/
            └── support/
```

The repository layer is divided according to the major persistence domains of the application.

| Package | Responsibility |
|---|---|
| `ai/` | AI execution, orchestration, provider telemetry, retrieval, classification, and decisions |
| `audit/` | API request history and immutable business audit events |
| `dashboard/` | Read-only analytics, operational metrics, traces, and observability |
| `knowledge/` | Knowledge documents, versions, chunks, embeddings, and retrieval |
| `support/` | Users, authentication, conversations, tickets, escalations, comments, and feedback |

---

# Repository Architecture

The repository layer can be viewed as five persistence domains:

```text
                         Database Repositories
                                  │
       ┌──────────────┬───────────┼───────────┬──────────────┐
       │              │           │           │              │
       ▼              ▼           ▼           ▼              ▼
      AI           Knowledge    Support     Audit        Dashboard
       │              │           │           │              │
       ▼              ▼           ▼           ▼              ▼
    AI state       RAG data    Customer     History      Analytics
    telemetry      retrieval   support     & audit      & traces
       │              │           │           │              │
       └──────────────┴───────────┴───────────┴──────────────┘
                                  │
                                  ▼
                              PostgreSQL
```

These packages are related but have deliberately separated responsibilities.

---

# 1. AI Repositories

```text
packages/database/repositories/ai/
```

The AI repository package is the persistence boundary for the **complete AI execution history**.

It covers:

- AI pipeline runs;
- orchestration stage events;
- LLM calls;
- embedding calls;
- retrieval runs;
- retrieval candidates;
- reranker calls;
- intent predictions;
- AI decisions.

The AI execution graph is represented approximately as:

```text
                         AI Run
                           │
             ┌─────────────┼─────────────┐
             │             │             │
             ▼             ▼             ▼
        Stage Events    LLM Calls    Embeddings
             │             │             │
             │             │             │
             │        ┌────┴────┐        │
             │        ▼         ▼        │
             │      Intent   Decision    │
             │
             └──────────────┬──────────────┐
                            ▼              │
                       Retrieval           │
                            │              │
                            ▼              │
                       Candidates          │
                            │              │
                            ▼              │
                         Reranker ─────────┘
```

The repositories are transaction-aware and generally non-committing; transaction ownership remains with the surrounding application/Unit-of-Work layer.

**Mental model:**

> `ai/` answers **"What happened during an AI execution?"**

---

# 2. Knowledge Repositories

```text
packages/database/repositories/knowledge/
```

The knowledge repository package manages the persisted **RAG knowledge lifecycle and retrieval infrastructure**.

Its responsibilities span:

```text
Document
   │
   ▼
Version
   │
   ▼
Chunks
   │
   ▼
Embeddings
   │
   ├──────────────► Vector Retrieval
   │
   └──────────────► Lexical Retrieval
                         │
                         ▼
                   Retrieval Matches
```

It contains repositories for:

- documents;
- document versions;
- chunks;
- embeddings;
- vector retrieval;
- lexical retrieval;

along with mapping and scoped retrieval infrastructure.

This package is therefore the database-side counterpart of the application's knowledge ingestion and retrieval layers.

**Mental model:**

> `knowledge/` answers **"What knowledge is stored, and how can it be retrieved?"**

---

# 3. Support Repositories

```text
packages/database/repositories/support/
```

The support repository package provides persistence for the **customer-support domain**.

It covers:

```text
Users
  │
  ├── Authentication
  │
  └── Administrator management

Conversations
  │
  ├── Messages
  └── Idempotent conversation starts

Human Support
  │
  ├── Escalations
  ├── Tickets
  └── Ticket Comments

Customer Experience
  │
  └── Feedback
```

The package contains repositories for users, authentication sessions, conversations, messages, conversation-start idempotency, escalations, tickets, comments, feedback, and repository errors.

Unlike the dashboard package, these repositories primarily support **transactional application workflows**.

They use the caller-provided SQLAlchemy session and leave commit/rollback to the surrounding Unit of Work.

They also contain concurrency-sensitive operations such as:

- row-level locking;
- atomic sequence allocation;
- processing leases;
- administrator concurrency protection;
- lifecycle-safe mutations.

**Mental model:**

> `support/` answers **"How is customer-support state persisted and changed safely?"**

---

# 4. Audit Repositories

```text
packages/database/repositories/audit/
```

The audit package provides persistence for two complementary forms of operational history:

```text
APIRequestRepository
        │
        ▼
HTTP/API request history


AuditEventRepository
        │
        ▼
Business/security audit history
```



Audit events are treated as immutable historical records: the repository does not expose update or delete operations.

The audit repositories therefore support:

- API request history;
- business state-change history;
- trace-based audit reconstruction;
- entity history;
- operational investigation.

They also follow the general repository transaction model: persistence operations are staged in the caller's transaction rather than independently committed.

**Mental model:**

> `audit/` answers **"What happened at the HTTP and business-event level?"**

---

# 5. Dashboard Repositories

```text
packages/database/repositories/dashboard/
```

The dashboard package is the **read-side repository layer**.

It provides:

- overview KPIs;
- operational analytics;
- API request exploration;
- audit exploration;
- LLM-call exploration;
- retrieval-run exploration;
- trace summaries;
- detailed trace reconstruction.



The architecture is intentionally different from the transactional support repositories:

```text
PostgreSQL
    │
    ├── API requests
    ├── Audit events
    ├── AI runs
    ├── LLM calls
    ├── Retrieval
    ├── Support
    └── Knowledge
            │
            ▼
    Dashboard Repositories
            │
            ▼
      Dashboard Read Models
            │
            ▼
       Dashboard / API
```

These repositories are **read-only** and optimized for analytics, filtering, aggregation, and operational exploration.

Large analytics operations are intentionally pushed into PostgreSQL rather than materializing large ORM collections in Python.

**Mental model:**

> `dashboard/` answers **"What is happening across the system, and what happened during a particular execution?"**

---

# Cross-Domain Relationships

The five repository groups are not isolated.

A typical customer request may produce a chain like:

```text
                    Customer Request
                           │
                           ▼
                      API Request
                           │
                           ▼
                         AI Run
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
          LLM Calls    Retrieval    Decisions
                           │
                     ┌─────┴─────┐
                     ▼           ▼
                  Embedding   Reranker
                      └────┬───┘
                           │
                           ▼
                    Assistant Response
                           │
             ┌─────────────┼─────────────┐
             │             │             │
             ▼             ▼             ▼
        Conversation   Feedback      Escalation
                                           │
                                           ▼
                                         Ticket
```

Different repository packages own different parts of this graph:

```text
API Request       → audit/
AI Run            → ai/
Retrieval         → ai/ + knowledge/
Conversation      → support/
Escalation        → support/
Ticket            → support/
Feedback          → support/
Audit Event       → audit/
Dashboard Trace   → dashboard/
```

The dashboard layer then correlates information across these domains using identifiers such as:

```text
trace_id
ai_run_id
conversation_id
ticket_id
escalation_id
```

This enables an operational view of a complete request without forcing individual repositories to become responsible for unrelated domains.

---

# Repository vs Application Responsibilities

A core architectural boundary is maintained throughout the package.

```text
┌──────────────────────────────────────────┐
│          Application / Domain            │
│                                          │
│  Business rules                          │
│  Authorization                           │
│  Orchestration                           │
│  AI decisions                            │
│  Workflow coordination                   │
│  API contracts                           │
└────────────────────┬─────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────┐
│             Repository Layer             │
│                                          │
│  Persistence                             │
│  Queries                                 │
│  Filtering                               │
│  Aggregation                             │
│  Mapping                                 │
│  Concurrency primitives                  │
│  Database-specific operations            │
└────────────────────┬─────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────┐
│              SQLAlchemy                  │
│              PostgreSQL                  │
└──────────────────────────────────────────┘
```

Repositories should not become application services.

They should not own:

- authorization policy;
- password hashing;
- JWT generation;
- AI model invocation;
- prompt construction;
- customer-facing workflow decisions;
- notification orchestration;
- API response formatting.

The detailed child READMEs document these boundaries for each domain.

---

# Transaction Model

The default transactional pattern is:

```text
Application Service
       │
       ▼
   Unit of Work
       │
       ├── Repository A
       ├── Repository B
       ├── Repository C
       │
       ▼
   flush / database operations
       │
       ▼
     commit()
```

Repositories generally do **not** independently commit application transactions.

This allows multiple repository operations to participate in one atomic business operation.

For example:

```text
Create / update conversation
        +
Persist message
        +
Create escalation
        +
Create ticket
        +
Write audit event
        │
        ▼
    One transaction
```

The support and AI repository layers explicitly follow this transaction-aware/non-committing model.

The dashboard repositories are primarily read-only and do not participate in application mutation workflows.

---

# Concurrency and Database Guarantees

Where persistence operations are race-sensitive, repository implementations use PostgreSQL/SQLAlchemy capabilities rather than relying exclusively on application-level synchronization.

Examples include:

```text
FOR UPDATE
Atomic UPDATE ... RETURNING
Transaction-level advisory locks
Processing leases
Database constraints
Deterministic ordering
```

These mechanisms are particularly important for:

- conversation message sequencing;
- conversation-start idempotency;
- authentication sessions;
- administrator management;
- escalation lifecycle;
- ticket lifecycle;
- feedback state changes.

The repository layer therefore acts as a controlled place for **database-specific concurrency behavior** while keeping that complexity out of higher-level application services.

---

# Read vs Write Repositories

The repository hierarchy contains two broad persistence styles.

## Transactional repositories

Primarily:

```text
ai/
knowledge/
support/
audit/
```

These may persist domain state or operational records and participate in caller-controlled transactions.

## Read-oriented repositories

Primarily:

```text
dashboard/
```

These focus on:

- aggregation;
- analytics;
- filtering;
- pagination;
- trace reconstruction;
- operational exploration.

This distinction keeps analytical workloads conceptually separate from transactional workflows.

---

# Data Flow Through the Repository Layer

```text
                         Application
                              │
             ┌────────────────┼────────────────┐
             │                │                │
             ▼                ▼                ▼
           AI Ops          Support         Knowledge
             │                │                │
             ▼                ▼                ▼
        ai repositories  support repos   knowledge repos
             │                │                │
             └────────────────┼────────────────┘
                              │
                              ▼
                         PostgreSQL
                              │
             ┌────────────────┴────────────────┐
             │                                 │
             ▼                                 ▼
       Audit Repository                 Dashboard Repository
             │                                 │
             ▼                                 ▼
       Historical Data                  Read / Analytics Views
```

Audit data can be generated by application/observability workflows, while dashboard repositories consume persisted data from multiple domains to construct operational views.

---

# Design Principles

## 1. Domain separation

Repositories are grouped by persistence domain rather than exposing one giant generic repository layer.

## 2. Database access isolation

Application services should not need to construct arbitrary SQLAlchemy queries for normal persistence operations.

## 3. Transaction ownership stays above repositories

Repositories participate in transactions but generally do not decide when the application's transaction commits.

## 4. PostgreSQL is used deliberately

Database capabilities such as locking, atomic updates, aggregation, and constraints are used where they provide stronger correctness or performance.

## 5. Read models for analytics

Dashboard queries use specialized read-oriented models instead of exposing arbitrary ORM objects.

## 6. Bounded queries

Operational queries use explicit filters, pagination, and limits.

## 7. No business orchestration

Repositories persist and retrieve data; application services coordinate business workflows.

## 8. Stable contracts

Repository implementations provide a clean infrastructure boundary behind application/domain contracts.

---

# Repository Layer Mental Model

The easiest way to understand the entire package is:

```text
                         "Where is system state stored?"
                                      │
                                      ▼
                         Database Repository Layer
                                      │
       ┌──────────────────┬───────────┼───────────┬──────────────────┐
       │                  │           │           │                  │
       ▼                  ▼           ▼           ▼                  ▼
      AI             Knowledge     Support      Audit           Dashboard
       │                  │           │           │                  │
       ▼                  ▼           ▼           ▼                  ▼
  AI execution       RAG data     Customer    History           Analytics
  telemetry          retrieval    support     & events           & traces
       │                  │           │           │                  │
       └──────────────────┴───────────┴───────────┴──────────────────┘
                                      │
                                      ▼
                                  PostgreSQL
```

Or, in terms of questions:

```text
ai/
    → What happened during AI execution?

knowledge/
    → What knowledge exists and how is it retrieved?

support/
    → What is the current customer-support state?

audit/
    → What API/business events happened?

dashboard/
    → What does the overall system look like?
```

---

# Summary

`packages/database/repositories/` is the **database-facing persistence boundary for the entire AI customer-support application**.

It separates persistence concerns into five major domains:

```text
packages/database/repositories/
│
├── ai/
│   └── AI execution and telemetry
│
├── knowledge/
│   └── Knowledge lifecycle and retrieval
│
├── support/
│   └── Customer-support transactional state
│
├── audit/
│   └── API and business history
│
└── dashboard/
    └── Read-only analytics and observability
```

Together they provide a structured path from application/domain logic to PostgreSQL while keeping:

- business workflows above the repository layer;
- database access inside repositories;
- transaction ownership with the Unit of Work;
- analytical reads in dashboard repositories;
- AI persistence separate from AI decision logic;
- knowledge persistence separate from retrieval orchestration;
- audit history separate from business mutations.

The central architectural rule is:

> **Repositories own database persistence and querying; application/domain services own business behavior and orchestration; PostgreSQL owns durable state and database-level integrity.**