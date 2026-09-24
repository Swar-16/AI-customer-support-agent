# Database Models

## Overview

The `packages/database/models/` package contains the SQLAlchemy ORM models that define the application's **persistent domain and telemetry data structures**.

It is the model layer between the application's repositories/services and PostgreSQL:

```text
Application / Domain Services
            │
            ▼
       Repositories
            │
            ▼
   packages/database/models/
            │
            ▼
        PostgreSQL
```

The package is organized by business and technical responsibility rather than keeping all database entities in a single module.

---

## Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── database/
        └── models/
            ├── support/
            ├── audit/
            ├── ai/
            ├── knowledge/
            ├── config/
            ├── __init__.py
            └── _helpers.py
```

The package currently exposes models from the following domains:

```text
┌────────────────────────────────────────────────────┐
│                  DATABASE MODELS                   │
├────────────────────────────────────────────────────┤
│                                                    │
│  support     → Customer/support operational data   │
│  ai          → AI execution & telemetry            │
│  knowledge   → Knowledge/RAG persistence           │
│  audit       → API & business audit history        │
│  config      → Versioned application configuration │
│                                                    │
└────────────────────────────────────────────────────┘
```

The package initializer exports the model classes from these domains as a common model-level import surface.

---

# Domain Model Groups

## 1. `support/`

The `support` models represent the **core customer-support application state**.

They cover:

* users and roles;
* local credentials;
* authentication sessions;
* conversations;
* messages;
* conversation-start idempotency;
* escalations;
* tickets;
* ticket comments;
* customer feedback.

The models use the PostgreSQL `support` schema.

Conceptually:

```text
User
 │
 ├── Credentials
 ├── Auth Sessions
 │
 └── Conversations
       │
       ├── Messages
       ├── Escalations
       │      │
       │      └── Tickets
       │             └── Comments
       │
       └── Feedback
```

This is the primary **operational domain** of the customer-support system.

---

## 2. `ai/`

The `ai` models persist information about **AI pipeline execution and its individual stages**.

The package covers:

* complete AI runs;
* orchestration stage events;
* LLM calls;
* embedding calls;
* retrieval runs;
* retrieval candidates;
* reranker calls;
* intent predictions;
* final AI decisions.

All nine models belong to the PostgreSQL `ai` schema.

The overall relationship is:

```text
AI Run
  │
  ├── Stage Events
  │
  ├── LLM Calls
  │      ├── Intent Prediction
  │      └── Decision
  │
  ├── Embedding Calls
  │
  └── Retrieval Runs
         │
         ├── Candidates
         └── Reranker Calls
```

These models provide **execution facts and structured AI telemetry**, rather than implementing the AI pipeline itself.

---

## 3. `knowledge/`

The `knowledge` models represent the persistence hierarchy behind the application's **knowledge base and RAG system**.

The hierarchy is:

```text
Knowledge Document
        │
        ▼
Document Version
        │
        ▼
Knowledge Chunk
        │
        ▼
Chunk Embedding
```

Each layer has a distinct purpose:

```text
Document
    = stable knowledge identity

Version
    = exact source revision

Chunk
    = retrieval-ready unit

Embedding
    = model/provider-specific vector artifact
```

This separation allows source versions, chunks, and embeddings to evolve independently. For example, changing an embedding model does not require recreating the underlying document or chunks.

The models themselves stop at the **knowledge-artifact boundary**. Chunking, embedding generation, vector search, retrieval, reranking, and context construction are handled by higher application/domain layers.

---

## 4. `audit/`

The `audit` models provide the application's **operational and business audit history**.

They contain two complementary concepts:

```text
APIRequestModel
    → HTTP/API execution history

AuditEventModel
    → Business/security state-change history
```

This gives the system two different perspectives:

```text
API Request
     │
     └── "What happened at the API boundary?"

Audit Event
     │
     └── "What business/security action happened?"
```

Audit events are designed to remain historically useful even when the operational record they refer to is later removed, and business audit events are append-only.

---

## 5. `config/`

The `config` model group contains persistence for **versioned application configuration**, including prompt configuration.

At the current model export level this includes:

```text
PromptVersionModel
```

The purpose is to keep configuration that affects application/AI behavior versioned and persisted rather than treating it as an entirely ephemeral runtime concern.

---

# How the Domains Connect

These model groups are separate, but they form one larger system.

A simplified end-to-end flow is:

```text
                         USER
                          │
                          ▼
                    Conversation
                          │
                          ▼
                       Message
                          │
                          ▼
                     AI Pipeline
                          │
             ┌────────────┼────────────┐
             │            │            │
             ▼            ▼            ▼
          Intent       Retrieval      LLM
             │            │            │
             └────────────┼────────────┘
                          │
                          ▼
                       Decision
                          │
                 ┌────────┴────────┐
                 │                 │
                 ▼                 ▼
              Response         Escalation
                                     │
                                     ▼
                                   Ticket
                                     │
                                     ▼
                                  Comments

Knowledge ──► Retrieval ──► AI Pipeline

Audit ──────► API activity + business state changes
```

The `ai` and `knowledge` model groups therefore provide persistence around the AI/RAG execution path, while `support` represents the customer-facing operational state.

---

# Public Model Surface

`models/__init__.py` acts as the central export surface for the model package.

It exposes the major model classes from:

```text
support
audit
config
ai
knowledge
```

including:

```python
UserModel
ConversationModel
MessageModel
TicketModel
APIRequestModel
AuditEventModel
PromptVersionModel
AIRunModel
LLMCallModel
IntentPredictionModel
AIDecisionModel
KnowledgeDocumentModel
KnowledgeDocumentVersionModel
KnowledgeChunkModel
KnowledgeChunkEmbeddingModel
```

along with the remaining domain models.

This allows higher-level database code to use the model package as a stable import surface instead of depending on every individual module path.

---

# Shared Model Infrastructure

## `_helpers.py`

The `_helpers.py` module contains small reusable utilities shared by model definitions.

One current helper is:

```python
enum_check_sql(...)
```

which generates PostgreSQL `CHECK` expressions for string-backed `StrEnum` values.

This keeps repetitive enum validation logic consistent across model definitions.

---

# Persistence Responsibilities

The model layer is responsible for defining:

* database table mappings;
* columns and types;
* relationships;
* foreign keys;
* indexes;
* uniqueness constraints;
* check constraints;
* server defaults;
* persistence-level lifecycle invariants.

It is **not** responsible for implementing the workflows that use those models.

For example:

```text
Models
   │
   ├── define AI run
   ├── define conversation
   ├── define ticket
   └── define knowledge chunk
        │
        ▼
Services / Repositories
   │
   ├── execute AI pipeline
   ├── manage conversations
   ├── process tickets
   └── ingest/retrieve knowledge
```

This separation keeps the ORM layer focused on persistence rather than application behavior.

---

# Database Integrity

A recurring design principle across the model groups is that important invariants are enforced at the **database level** where appropriate.

Examples include:

* valid enum/state values;
* unique identifiers;
* lifecycle consistency;
* valid foreign-key relationships;
* ordered message sequences;
* ticket state transitions;
* audit-event structure;
* AI telemetry constraints;
* knowledge publication/versioning rules.

This prevents invalid states from being introduced merely because a particular application path failed to validate them.

---

# Identifiers and Relationships

The model layer consistently uses stable identifiers and explicit relationships to connect entities across the system.

The resulting graph allows the application to trace relationships such as:

```text
User
  → Conversation
      → Message
          → AI Run
              → LLM / Retrieval / Embedding telemetry
                  → Decision

AI Run
  → Escalation
      → Ticket
          → Comments
```

Knowledge artifacts connect into the retrieval side:

```text
Document
  → Version
      → Chunk
          → Embedding
              ↓
         Retrieval
```

Audit records provide an additional historical/correlation layer across these operations.

---

# Privacy Boundary

The database model layer intentionally separates **structured execution metadata from raw application content**.

In particular, AI telemetry is designed to record execution facts, identifiers, timing, provider information, rankings, and structured outcomes rather than raw customer queries, prompts, retrieved documents, generated answers, vectors, or conversation context.

Similarly, the audit layer is not intended to become a raw request/response recorder containing tokens, cookies, sensitive headers, or unrestricted payloads.

This keeps the database useful for:

```text
debugging
observability
analytics
reproducibility
auditability
```

without unnecessarily turning telemetry tables into content stores.

---

# Architectural Mental Model

The easiest way to understand `packages/database/models/` is as **five persistence domains**:

```text
┌────────────────────────────────────────────────────┐
│                 DATABASE MODELS                    │
│                                                    │
│  SUPPORT                                           │
│  Customer-facing operational state                 │
│                                                    │
│  AI                                                │
│  AI execution and telemetry                        │
│                                                    │
│  KNOWLEDGE                                         │
│  RAG knowledge artifacts                           │
│                                                    │
│  AUDIT                                             │
│  Operational and business history                  │
│                                                    │
│  CONFIG                                            │
│  Versioned application configuration               │
│                                                    │
└────────────────────────────────────────────────────┘
```

Or as a runtime flow:

```text
                  SUPPORT
                     │
                     ▼
                Conversation
                     │
                     ▼
                AI Pipeline
                /         \
               /           \
              ▼             ▼
        KNOWLEDGE          AI
        Documents       Execution
        Versions        Telemetry
        Chunks          Decisions
        Embeddings      Retrieval
              \             /
               \           /
                ▼         ▼
                  Response
                     │
                     ▼
             Support / Escalation
                     │
                     ▼
                   Ticket

                    +
                    │
                    ▼
                  AUDIT
          API + Business History
```

---

# Summary

`packages/database/models/` is the **central ORM model layer of the application**, organizing persistence around the major architectural domains.

| Domain       | Purpose                                                                              |
| ------------ | ------------------------------------------------------------------------------------ |
| `support/`   | Customer identity, conversations, tickets, escalations, feedback, and authentication |
| `ai/`        | AI execution, provider calls, retrieval, ranking, intent, and decisions              |
| `knowledge/` | Documents, versions, chunks, and embeddings used by the knowledge/RAG system         |
| `audit/`     | API activity and immutable business/security audit history                           |
| `config/`    | Persisted/versioned application configuration such as prompt versions                |

Together, these models provide the persistent backbone connecting **customer interactions → AI execution → knowledge retrieval → support operations → audit history**, while keeping persistence concerns separate from the services that execute those workflows.
