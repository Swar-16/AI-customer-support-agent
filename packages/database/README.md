# Database Layer

## Overview

The `packages/database/` package is the **persistence infrastructure layer** of the AI customer-support system.

It provides the common database foundation used by the application:

```text
Application / Domain Services
            │
            ▼
       Unit of Work
            │
            ▼
       Repositories
            │
            ▼
       ORM Models
            │
            ▼
        SQLAlchemy
            │
            ▼
        PostgreSQL
```

The database layer deliberately separates:

- database schema/model definitions;
- database querying and persistence;
- transaction management;
- SQLAlchemy session/engine configuration.

This keeps application services focused on business workflows rather than database mechanics.

---

## Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── database/
        ├── base.py
        ├── session.py
        ├── models/
        │   ├── support/
        │   ├── ai/
        │   ├── knowledge/
        │   ├── audit/
        │   └── config/
        │
        ├── repositories/
        │   ├── support/
        │   ├── ai/
        │   ├── knowledge/
        │   ├── audit/
        │   └── dashboard/
        │
        └── unit_of_work/
            ├── base.py
            ├── sqlalchemy_uow.py
            └── knowledge.py
```

At this level, the package can be understood as three major components plus shared infrastructure:

| Component | Responsibility |
|---|---|
| `base.py` | Shared SQLAlchemy declarative base and metadata |
| `session.py` | Engine and SQLAlchemy session-factory creation |
| `models/` | ORM representation of persistent application data |
| `repositories/` | Database queries and persistence operations |
| `unit_of_work/` | Session lifecycle and transaction boundaries |

---

# Architecture

The database layer follows a clear dependency direction:

```text
                    APPLICATION
                         │
                         ▼
                  Unit of Work
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
       Repositories              Transaction
            │                    Management
            ▼
         Models
            │
            ▼
       SQLAlchemy
            │
            ▼
        PostgreSQL
```

The important distinction is:

> **Models describe persistence, repositories perform persistence operations, and the Unit of Work controls the transaction.**

---

# 1. Database Foundation

## `base.py`

`base.py` provides the shared SQLAlchemy declarative infrastructure.

It defines:

```text
MetaData
    │
    └── naming convention
            │
            ▼
     Declarative Base
            │
            ▼
       All ORM Models
```

The project uses a centralized SQLAlchemy naming convention for indexes, unique constraints, check constraints, foreign keys, and primary keys.

The shared `Base` is built from this metadata and is inherited by the ORM models.

This gives the entire database model layer consistent SQLAlchemy metadata and predictable constraint names.

---

# 2. Database Sessions

## `session.py`

`session.py` is responsible for creating the SQLAlchemy database engine and session factory.

Conceptually:

```text
Application Configuration
          │
          ▼
     database_url
          │
          ▼
     create_engine()
          │
          ▼
     sessionmaker
          │
          ▼
    SQLAlchemy Session
```

The session factory is created with:

- `pool_pre_ping=True`;
- `autoflush=False`;
- `expire_on_commit=False`.



The factory itself does not eagerly open a database connection. Connections are acquired when a `Session` actually performs database work.

The module also exposes the default application `SessionLocal` configured from the application's database settings.

---

# 3. Database Models

```text
packages/database/models/
```

The `models/` package contains the SQLAlchemy ORM representation of the application's persistent state and telemetry.

It is organized into major domains:

```text
models/
│
├── support/
│   └── Customer-support operational state
│
├── ai/
│   └── AI execution and telemetry
│
├── knowledge/
│   └── RAG / knowledge persistence
│
├── audit/
│   └── API and business history
│
└── config/
    └── Versioned application configuration
```



### Support

Stores the core customer-support state:

```text
User
 ├── Credentials
 ├── Auth Sessions
 └── Conversations
       ├── Messages
       ├── Escalations
       │      └── Tickets
       │             └── Comments
       └── Feedback
```



### AI

Represents AI execution and telemetry:

```text
AI Run
 ├── Stage Events
 ├── LLM Calls
 ├── Embedding Calls
 ├── Retrieval
 │    └── Candidates
 ├── Reranker Calls
 ├── Intent Prediction
 └── Decision
```



### Knowledge

Represents the versioned RAG knowledge lifecycle:

```text
Document
   │
   ▼
Version
   │
   ▼
Chunk
   │
   ▼
Embedding
```

This separates stable knowledge identity from source revisions, retrieval units, and vector artifacts.

### Audit

Provides durable operational history:

```text
Audit
 ├── API Request
 └── Audit Event
```

The two model types distinguish HTTP/operational activity from business/security state changes.

### Model Responsibilities

Models are responsible for database structure and persistence invariants, including:

- tables and columns;
- types;
- relationships;
- foreign keys;
- indexes;
- uniqueness;
- check constraints;
- server defaults;
- database-level lifecycle rules.

They do **not** implement application workflows.

---

# 4. Repositories

```text
packages/database/repositories/
```

Repositories are the **database-access adapters** used by application/domain services.

They sit between the application and ORM models:

```text
Application
    │
    ▼
Repositories
    │
    ▼
ORM Models
    │
    ▼
PostgreSQL
```

The repository hierarchy is divided into:

```text
repositories/
│
├── support/
├── ai/
├── knowledge/
├── audit/
└── dashboard/
```



### `support/`

Transactional customer-support persistence:

- users;
- authentication;
- conversations;
- messages;
- escalations;
- tickets;
- comments;
- feedback.



### `ai/`

Persistence for AI execution and telemetry:

- AI runs;
- stage events;
- LLM calls;
- embedding calls;
- retrieval;
- reranking;
- intent predictions;
- decisions.



### `knowledge/`

Persistence and retrieval infrastructure for:

- documents;
- versions;
- chunks;
- embeddings;
- vector retrieval;
- lexical retrieval.



### `audit/`

Persistence for:

- API request history;
- immutable business/security audit events.



### `dashboard/`

Read-oriented repositories for:

- operational metrics;
- analytics;
- traces;
- AI execution exploration;
- API request exploration;
- audit exploration.

They are designed primarily for read-side and analytical workloads rather than transactional mutation workflows.

---

# 5. Unit of Work

```text
packages/database/unit_of_work/
```

The Unit of Work provides the **transaction boundary** around repositories.

Its central guarantee is:

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



The package contains:

```text
unit_of_work/
├── base.py
├── sqlalchemy_uow.py
└── knowledge.py
```

The base contract defines the Unit of Work interface, while `SqlAlchemyUnitOfWork` provides the main application implementation and `SQLAlchemyKnowledgeUnitOfWork` provides a knowledge-focused variant.

---

## Transaction Model

Repositories generally **do not commit their own transactions**.

Instead:

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
     commit()
```

This allows several persistence operations to become one atomic business operation.



The Unit of Work uses explicit-commit semantics:

```python
with SqlAlchemyUnitOfWork() as uow:
    ...
    uow.commit()
```

If an exception occurs or the context exits without a commit, the transaction is rolled back and the session is closed.

---

# End-to-End Database Flow

A typical customer request can cross most of the database layer:

```text
                    Customer Request
                           │
                           ▼
                      API Request
                           │
                           ▼
                     Conversation
                           │
                           ▼
                        Message
                           │
                           ▼
                        AI Run
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
          LLM Calls    Retrieval    Embeddings
                           │
                           ▼
                     Knowledge Data
                           │
                           ▼
                       Decision
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
         Response                  Escalation
                                        │
                                        ▼
                                      Ticket
                                        │
                                        ▼
                                     Comments
```

Across the entire operation, audit records provide an additional historical/correlation layer.

The underlying persistence graph connects customer activity, AI execution, knowledge retrieval, support workflows, and audit history.

---

# Cross-Domain Relationship

The database is not a collection of unrelated tables.

A simplified view is:

```text
User
 │
 └── Conversation
       │
       └── Message
             │
             └── AI Run
                  ├── LLM Call
                  ├── Embedding Call
                  ├── Retrieval
                  │     └── Knowledge Chunk
                  │           └── Embedding
                  ├── Intent
                  └── Decision
                         │
                         └── Escalation
                               └── Ticket
                                    └── Comments

API Request ────────────────┐
                            │
Business Events ────────────┴──► Audit History
```

This allows the system to reconstruct both:

- **current operational state**, and
- **historical execution/context**.

---

# Database Layer Responsibilities

The `packages/database/` layer is responsible for:

- SQLAlchemy infrastructure;
- database sessions;
- ORM mappings;
- persistence queries;
- database-level constraints;
- relationships;
- transaction boundaries;
- repository composition;
- concurrency-sensitive database operations;
- analytical database reads.

It is **not** responsible for:

- API request handling;
- authentication policy;
- password hashing;
- JWT creation;
- AI model execution;
- prompt construction;
- RAG orchestration;
- customer-support business workflows;
- authorization decisions.

Those responsibilities belong to higher application/domain layers.

---

# Database Integrity

An important principle throughout the database layer is to enforce critical invariants as close to the database as practical.

Examples include:

```text
Enum/state validity
        │
Unique constraints
        │
Foreign-key integrity
        │
Lifecycle consistency
        │
Sequence / ordering guarantees
        │
AI telemetry consistency
        │
Knowledge versioning rules
```

The model layer therefore provides more than simple table mappings—it encodes persistence-level guarantees that should remain true regardless of which application path performs a database operation.

---

# Privacy and Data Boundaries

The database layer distinguishes **structured persistence metadata** from unrestricted application content.

AI telemetry is primarily concerned with execution facts such as:

- identifiers;
- timing;
- provider information;
- retrieval/ranking information;
- structured outcomes.

It is not intended to become a general-purpose store for raw customer queries, prompts, generated answers, retrieved documents, vectors, or conversation context.

Similarly, audit persistence is intended for operational and business history rather than unrestricted request/response payload capture.

---

# Design Principles

## Separation of Concerns

```text
Models       → What is persisted?
Repositories → How is it queried/persisted?
Unit of Work → How is it transacted?
Session      → How does SQLAlchemy connect?
```

## Transaction Ownership

Repositories participate in transactions; the Unit of Work owns commit/rollback.

## Domain Organization

Database entities and repositories are grouped by architectural domain rather than placed into a single global module.

## Database-Level Integrity

Important persistence invariants are enforced through PostgreSQL/SQLAlchemy constraints where appropriate.

## Explicit Persistence

Application code explicitly controls transaction completion.

## Infrastructure Isolation

Higher application layers should not need to manage raw SQLAlchemy session lifecycle.

---

# Typical Application Interaction

The intended flow is approximately:

```text
Application Service
       │
       ▼
Unit of Work
       │
       ├──────────────┐
       ▼              ▼
Repository       Repository
       │              │
       └──────┬───────┘
              ▼
            Models
              │
              ▼
          PostgreSQL
              │
              ▼
          commit()
```

For example:

```python
with SqlAlchemyUnitOfWork() as uow:
    conversation = uow.conversations.create(...)

    uow.messages.create(
        conversation_id=conversation.id,
        ...
    )

    uow.ai_runs.create(...)

    uow.audit_events.add(...)

    uow.commit()
```

The exact repository methods and domain-specific behavior should be understood from the READMEs inside `repositories/` and `unit_of_work/`.

---

# Mental Model

The easiest way to understand `packages/database/` is:

```text
                         DATABASE LAYER
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
       MODELS             REPOSITORIES         UNIT OF WORK
          │                    │                    │
   Define persistence    Query / mutate data   Manage transaction
          │                    │                    │
          └────────────────────┼────────────────────┘
                               │
                               ▼
                          SQLAlchemy
                               │
                               ▼
                           PostgreSQL
```

And across the application domains:

```text
SUPPORT
Customer state
    │
    ▼
AI
Execution & decisions
    │
    ▼
KNOWLEDGE
RAG persistence
    │
    ▼
AUDIT
Historical record
    │
    ▼
DASHBOARD
Operational read side
```

---

# Summary

`packages/database/` is the **central persistence infrastructure of the AI customer-support system**.

It connects application workflows to PostgreSQL through four clear layers:

```text
┌─────────────────────────────────────┐
│ Application / Domain                │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ Unit of Work                        │
│ Transaction boundary                │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ Repositories                        │
│ Persistence & queries               │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ ORM Models                          │
│ Persistent domain representation    │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ SQLAlchemy / PostgreSQL             │
└─────────────────────────────────────┘
```

The major persistence domains are:

```text
support/   → Customer-support state
ai/        → AI execution and telemetry
knowledge/ → RAG knowledge persistence
audit/     → Operational and business history
config/    → Versioned configuration
```

The database layer therefore provides the durable backbone connecting:

> **customer interactions → AI execution → knowledge retrieval → support operations → auditability**

while keeping database concerns isolated from the business and orchestration logic above it.