# Application Packages

## Overview

The `packages/` directory contains the major **architectural building blocks of the AI customer-support system**.

Each package owns a distinct responsibility and communicates with the others through explicit contracts rather than allowing implementation details to leak across boundaries.

```text
AI-customer-support-agent/
└── packages/
    │
    ├── config/
    ├── application/
    ├── ai/
    ├── knowledge/
    ├── guardrails/
    └── database/
```

At the highest level:

```text
                         Customer Request
                                │
                                ▼
                     ┌────────────────────┐
                     │    Application     │
                     │   Use-Case Layer   │
                     └─────────┬──────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
                ▼              ▼              ▼
               AI         Knowledge      Guardrails
                │              │              │
                └──────────────┼──────────────┘
                               │
                               ▼
                          Persistence
                               │
                               ▼
                           Database
```

`config/` provides validated configuration across these components.

---

# Package Map

| Package | Primary Responsibility |
|---|---|
| `config/` | Centralized application configuration and validation |
| `application/` | Business use cases, workflows, authorization, and application orchestration |
| `ai/` | AI interpretation, decisioning, retrieval coordination, generation, and AI telemetry |
| `knowledge/` | Trusted knowledge lifecycle, ingestion, embeddings, retrieval, and grounding |
| `guardrails/` | Deterministic safety validation of proposed AI responses |
| `database/` | Persistence, repositories, ORM models, sessions, and transactions |

These boundaries are intentional: each package has a focused role while remaining composable with the others. 

---

# 1. `config/`

```text
packages/config/
```

`config/` is the **central configuration boundary**.

It loads environment-specific configuration, validates it, normalizes values, and exposes a cached typed `Settings` object.

```text
Environment
     │
     ▼
.env / .env.test / .env.production
     │
     ▼
Pydantic Settings
     │
     ▼
Validation
     │
     ▼
Normalized Settings
     │
     ▼
All Packages
```

It supplies configuration for areas such as:

- authentication and browser security;
- PostgreSQL;
- LLM providers;
- embeddings;
- retrieval/RAG;
- knowledge uploads;
- provider capacity and retries;
- conversation context;
- dashboard analytics.

The package defines **configuration**, not execution. For example, it can define retry limits, but the resilience layer is responsible for actually performing retries.

---

# 2. `application/`

```text
packages/application/
```

`application/` is the **business workflow and use-case layer**.

It coordinates authentication, conversations, AI-assisted answering, knowledge retrieval, escalations, tickets, feedback, auditing, observability, dashboards, and administrative users.

Its major areas are:

```text
application/
├── ai/
├── audit/
├── auth/
├── composition/
├── conversations/
├── dashboard/
├── escalations/
├── feedback/
├── knowledge/
├── observability/
├── tickets/
└── users/
```

A typical application operation follows:

```text
Request
  │
  ▼
Validation
  │
  ▼
Authorization
  │
  ▼
Business Invariants
  │
  ▼
Unit of Work
  │
  ├── Repository Operations
  ├── Audit
  └── Related Services
  │
  ▼
Commit
  │
  ▼
Application Result
```



The application layer therefore acts as the **coordination point between external callers and lower-level AI, knowledge, persistence, and infrastructure capabilities**.

---

# 3. `ai/`

```text
packages/ai/
```

`ai/` is the **core AI domain boundary**.

It transforms customer-support input into a controlled AI outcome by coordinating:

```text
Intent
   ↓
Decision
   ↓
Evidence / Retrieval
   ↓
Generation
   ↓
Guardrails
   ↓
Outcome
   ↓
Telemetry
```



Its major responsibilities include:

- intent interpretation;
- workflow decisions;
- retrieval coordination;
- response generation;
- deterministic responses;
- guardrail coordination;
- structured AI errors;
- execution telemetry.

The package is intentionally provider-independent. Provider SDKs should remain behind provider-specific adapters rather than becoming dependencies of orchestration.

The AI package **coordinates capabilities rather than owning infrastructure** such as raw SQL, HTTP routing, authentication, or provider SDK initialization.

---

# 4. `knowledge/`

```text
packages/knowledge/
```

`knowledge/` is the complete **RAG knowledge subsystem**.

It manages the lifecycle from authoritative source material to retrieval-ready evidence:

```text
Document
   │
   ▼
Version
   │
   ▼
Parse → Normalize → Chunk
   │
   ▼
Chunks
   │
   ▼
Embeddings
   │
   ▼
Retrieval
   │
   ▼
Grounding Context
   │
   ▼
AI Generation
```



Its major areas are:

```text
knowledge/
├── domain/
├── application/
├── ingestion/
├── embeddings/
├── retrieval/
├── repositories/
└── uow.py
```



The package deliberately distinguishes:

```text
Authoritative
─────────────
Documents
Versions
Source Content

Derived
───────
Chunks
Embeddings
```

This preserves provenance and allows derived artifacts to be regenerated when source, chunking, or embedding configuration changes.

The knowledge subsystem ends at **trusted retrieval evidence / grounding context**; it does not generate the final customer answer.

### Current Retrieval Note

The retrieval architecture supports:

```text
Vector Retrieval
       +
Lexical Retrieval
       ↓
     Fusion
       ↓
 Optional Reranking
       ↓
Grounding Context
```

A learned/provider-based reranker is **not currently active**; the current reranker is a passthrough implementation, while the architecture is prepared for a future provider such as Jina.

---

# 5. `guardrails/`

```text
packages/guardrails/
```

`guardrails/` is the deterministic **safety checkpoint between AI generation and customer exposure**.

```text
Generated Response
       │
       ▼
Guardrail Context
       │
       ▼
Ordered Policies
       │
       ▼
Guardrail Result
┌───────┼────────┐
▼       ▼        ▼
PASS    REFUSE  ESCALATE
```



The package currently separates:

```text
models.py
    Contracts and outcomes

policies.py
    Individual safety rules

evaluator.py
    Deterministic policy orchestration

errors.py
    Guardrail subsystem failures
```

The evaluator is deliberately a coordinator; policy-specific detection remains inside individual policies.

Guardrails do **not**:

- generate responses;
- query retrieval infrastructure;
- mutate AI state;
- execute business actions.

They evaluate the proposed response using a narrow immutable context.

---

# 6. `database/`

```text
packages/database/
```

`database/` is the **persistence infrastructure layer**.

It provides:

```text
ORM Models
Repositories
Unit of Work
Sessions
SQLAlchemy
PostgreSQL
```



Its structure is:

```text
database/
├── base.py
├── session.py
├── models/
├── repositories/
└── unit_of_work/
```

The responsibilities are deliberately separated:

```text
Models
    → What is persisted?

Repositories
    → How is it queried/persisted?

Unit of Work
    → How is it transacted?

Session
    → How does SQLAlchemy connect?
```



The database layer covers the major persistence domains:

```text
support/
    Customer-support state

ai/
    AI execution and telemetry

knowledge/
    RAG persistence

audit/
    Business and operational history

dashboard/
    Read-oriented analytics
```

The Unit of Work ensures that repositories participating in one business operation share a SQLAlchemy session and transaction boundary.

---

# How the Packages Work Together

The six packages form a layered architecture rather than six independent modules.

```text
                         ┌───────────────┐
                         │    CONFIG     │
                         │  Environment  │
                         │   & Settings  │
                         └───────┬───────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────┐
│                     APPLICATION                         │
│                                                         │
│ Auth • Conversations • Tickets • Escalations • Users    │
│ Feedback • Dashboard • Knowledge • AI • Audit           │
└───────────────┬───────────────────────┬─────────────────┘
                │                       │
                ▼                       ▼
        ┌──────────────┐         ┌──────────────┐
        │      AI      │◄────────│   KNOWLEDGE  │
        │              │         │              │
        │ Intent       │         │ Ingestion    │
        │ Decision     │         │ Embeddings   │
        │ Generation   │         │ Retrieval    │
        │ Telemetry    │         │ Grounding    │
        └──────┬───────┘         └──────┬───────┘
               │                        │
               └───────────┬────────────┘
                           ▼
                    ┌──────────────┐
                    │  GUARDRAILS  │
                    │              │
                    │ Pass/Refuse/ │
                    │ Escalate     │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   DATABASE   │
                    │              │
                    │ Models       │
                    │ Repositories │
                    │ UoW          │
                    └──────┬───────┘
                           │
                           ▼
                       PostgreSQL
```

---

# End-to-End Customer Request

A typical grounded customer-support request crosses the package boundaries like this:

```text
                    Customer Request
                           │
                           ▼
                    APPLICATION
                           │
                           ▼
                     Conversation
                           │
                           ▼
                           AI
                           │
                  ┌────────┴────────┐
                  ▼                 ▼
              Intent            Decision
                                    │
                                    ▼
                              KNOWLEDGE
                                    │
                           ┌────────┴────────┐
                           ▼                 ▼
                       Retrieval        Grounding
                           │                 │
                           └────────┬────────┘
                                    ▼
                               Generation
                                    │
                                    ▼
                              GUARDRAILS
                                    │
                         ┌──────────┼──────────┐
                         ▼          ▼          ▼
                        PASS      REFUSE    ESCALATE
                         │          │          │
                         ▼          ▼          ▼
                      Answer     Safe Path   Human Support
                         │
                         ▼
                    APPLICATION
                         │
                         ├── Persist conversation
                         ├── Record audit
                         └── Record telemetry
                                  │
                                  ▼
                              DATABASE
```

This separation allows the system to evolve individual capabilities without turning the entire application into one tightly coupled pipeline.

---

# Architectural Boundaries

The intended ownership can be summarized as:

| Concern | Package |
|---|---|
| Environment and global settings | `config` |
| Business workflows and use cases | `application` |
| AI interpretation and orchestration | `ai` |
| Trusted knowledge and RAG | `knowledge` |
| Response safety | `guardrails` |
| Durable persistence | `database` |

The distinction is especially important between **AI, knowledge, and guardrails**:

```text
AI
"What should the system do and how should the response be produced?"

Knowledge
"What trusted evidence is available?"

Guardrails
"Can this proposed response safely become the customer-facing outcome?"
```

---

# Dependency Direction

The preferred dependency direction is broadly:

```text
                 External Interfaces
                         │
                         ▼
                  Application
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
         AI         Knowledge       Guardrails
          │              │              │
          └──────────────┼──────────────┘
                         │
                         ▼
                    Persistence
                         │
                         ▼
                      Database
```

Configuration is consumed across these layers:

```text
              config
             /  |  \
            /   |   \
           ▼    ▼    ▼
     application AI knowledge
                  │
                  ▼
              database
```

The application layer should coordinate lower-level capabilities through explicit abstractions rather than allowing interfaces or infrastructure components to implement business workflows directly.

---

# Separation of Concerns

A useful mental model for the entire `packages/` directory is:

```text
┌──────────────────────────────────────────────────────┐
│                     CONFIG                           │
│              "What are the settings?"                │
└─────────────────────────┬────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────┐
│                  APPLICATION                         │
│             "What use case is running?"              │
└───────────────┬───────────────────────┬──────────────┘
                │                       │
        ┌───────▼───────┐       ┌──────▼────────┐
        │      AI       │       │   KNOWLEDGE   │
        │ "How do we    │       │ "What trusted │
        │ reason?"      │       │ evidence?"    │
        └───────┬───────┘       └──────┬────────┘
                │                       │
                └───────────┬───────────┘
                            ▼
                   ┌────────────────┐
                   │   GUARDRAILS   │
                   │ "Is this safe  │
                   │  to expose?"   │
                   └───────┬────────┘
                           │
                           ▼
                   ┌────────────────┐
                   │    DATABASE    │
                   │ "How is state  │
                   │   persisted?"  │
                   └────────────────┘
```

---

# Cross-Cutting Principles

## Contract-driven architecture

Major packages communicate through explicit contracts instead of exposing implementation details.

## Provider independence

External AI, embedding, retrieval, and similar providers remain replaceable behind abstractions.

## Transaction boundaries

Database transactions are controlled through the Unit of Work rather than individual repository methods.

## Data minimization

Customer content, secrets, prompts, and other sensitive information should not be persisted merely for convenience.

Both AI telemetry and application observability intentionally favor bounded operational metadata over unrestricted content capture.

## Fail fast

Invalid configuration, malformed domain state, incompatible artifacts, and invalid provider results should fail explicitly rather than silently degrading.

## Separation of audit and telemetry

The architecture distinguishes:

```text
Audit
"What business state changed?"

Telemetry
"How did the system execute?"

Dashboard
"What operational patterns are visible?"
```



## Short-lived database transactions

Expensive external operations such as LLM calls, embedding requests, parsing, and retrieval work should not unnecessarily hold database transactions open.

---

# What Does Not Belong in `packages/`

The `packages/` directory is the architectural home for the system's reusable application/domain/infrastructure capabilities, but individual packages should remain bounded.

Avoid turning one package into a catch-all for:

```text
Unrelated business rules
Raw provider SDK usage
Raw SQL from application services
HTTP routing
Authentication inside AI code
Database transactions inside providers
Prompt logic inside persistence
Global configuration inside individual components
```

Each concern should live behind its appropriate package boundary.

---

# Overall System Mental Model

The entire architecture can be remembered as:

```text
                         CUSTOMER
                            │
                            ▼
                    ┌───────────────┐
                    │ APPLICATION   │
                    │   Workflows   │
                    └───────┬───────┘
                            │
             ┌──────────────┼──────────────┐
             │              │              │
             ▼              ▼              ▼
            AI         KNOWLEDGE      GUARDRAILS
             │              │              │
             │         Evidence            │
             │              │              │
             └──────────────┼──────────────┘
                            │
                            ▼
                         OUTCOME
                            │
                            ▼
                      PERSISTENCE
                            │
                            ▼
                        DATABASE

                CONFIG supports all layers
```

In terms of questions:

```text
config/
    → How should the application be configured?

application/
    → What business operation should happen?

ai/
    → How should the system interpret and respond?

knowledge/
    → What trusted evidence should support the response?

guardrails/
    → Is the proposed response acceptable?

database/
    → How is the resulting state persisted and queried?
```

---

# Summary

`packages/` is the **core architectural boundary of the AI customer-support system**.

Its six major packages divide responsibility cleanly:

```text
packages/
│
├── config/
│   └── Centralized configuration
│
├── application/
│   └── Business workflows and use cases
│
├── ai/
│   └── AI reasoning, orchestration, generation, telemetry
│
├── knowledge/
│   └── Knowledge lifecycle, RAG, embeddings, retrieval
│
├── guardrails/
│   └── Deterministic response safety
│
└── database/
    └── Persistence and transactions
```

Together they form the system's main execution path:

> **Configuration → Application Workflow → AI / Knowledge → Guardrails → Persistence**

while maintaining clear boundaries between **business orchestration, AI capabilities, trusted knowledge, response safety, and database infrastructure**.

The detailed READMEs inside each package remain the authoritative place for implementation-level behavior; this README is intentionally the architectural map for understanding how the packages fit together.