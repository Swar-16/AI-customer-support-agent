# Application Layer

## Overview

The `packages/application/` package is the **application-service boundary** of the AI customer-support agent.

It coordinates business use cases across authentication, conversations, AI-assisted answering, knowledge retrieval, escalations, tickets, feedback, auditing, observability, dashboards, and administrative user management.

The application layer sits between the external interfaces/infrastructure and the domain, persistence, and AI subsystems.

```text
                    API / Workers / Internal Callers
                               │
                               ▼
                    ┌──────────────────────┐
                    │   Application Layer  │
                    │  packages/application│
                    └──────────┬───────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
       Domain / AI         Persistence         Infrastructure
       Services            / Repositories       / Providers
```

The layer is intentionally responsible for **use-case orchestration, authorization, validation, transaction boundaries, lifecycle rules, and application-level DTOs**, while lower layers own persistence and infrastructure implementation.

---

# Package Structure

```text
packages/application/
│
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

Each subpackage owns a distinct application capability.

| Package          | Application responsibility                                                      |
| ---------------- | ------------------------------------------------------------------------------- |
| `ai/`            | Bridges AI decisioning with knowledge retrieval and grounded answer generation  |
| `audit/`         | Records and queries business audit history                                      |
| `auth/`          | Registration, login, token authentication, sessions, refresh, and logout        |
| `composition/`   | Wires providers, AI pipelines, knowledge services, and application services     |
| `conversations/` | Owns the customer conversation lifecycle and AI message processing              |
| `dashboard/`     | Provides operational analytics and investigation queries                        |
| `escalations/`   | Manages the lifecycle of cases transferred to human support                     |
| `feedback/`      | Collects, reviews, and queries customer feedback on AI responses                |
| `knowledge/`     | Translates AI requests into knowledge retrieval contexts and maps evidence back |
| `observability/` | Persists sanitized HTTP/API telemetry                                           |
| `tickets/`       | Manages support-ticket creation, comments, queries, and lifecycle updates       |
| `users/`         | Provides administrative user provisioning and access management                 |

---

# Architectural Role

The application layer is the place where **business workflows are assembled**.

It is not simply a collection of CRUD wrappers.

A typical operation crosses several concerns:

```text
Authenticated Request
        │
        ▼
Application Command / Query
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
        ├── Repository operations
        ├── Audit
        ├── Notifications
        └── Related application services
        │
        ▼
Commit
        │
        ▼
Detached Application Result
```

This pattern keeps callers independent of database models and persistence mechanics.

---

# Major Application Domains

## 1. AI

The `ai/` package contains application-level integration around AI-generated answers.

It connects already-understood AI decisions with the knowledge application layer and grounded generation.

Conceptually:

```text
Intent / Decision
       │
       ▼
Answer Service
       │
       ├── Retrieval Context
       ├── Query Preparation
       ├── Grounding
       ├── Evidence Mapping
       └── Response Generation
       │
       ▼
Grounded Answer
```

The application AI layer deliberately does not own:

* intent classification itself;
* retrieval implementation;
* embedding infrastructure;
* vector/lexical repositories;
* provider-specific infrastructure.

Instead, it composes those capabilities through application contracts.

---

# 2. Authentication

The `auth/` package owns the application's authentication lifecycle.

```text
Registration
     │
     ▼
User + Credential + Session
     │
     ▼
Login ───────────────► Access / Refresh Tokens
     │
     ▼
Authenticated Principal
     │
     ├── Refresh
     ├── Logout
     └── Access Authentication
```

It covers:

* user registration;
* password hashing;
* login;
* JWT access-token validation;
* refresh-token rotation;
* session management;
* logout;
* current-user resolution.

Authentication deliberately separates:

```text
Cryptographic concerns
        │
        ├── PasswordHasher
        └── TokenService

Persistence concerns
        │
        └── Unit of Work / repositories

Application workflows
        │
        ├── Register
        ├── Login
        ├── Refresh
        ├── Logout
        └── Authenticate
```

Important security invariants include persisted session revocation, refresh-token single-use behavior, token-family reuse detection, role consistency, and timezone-aware authentication timestamps.

---

# 3. Conversations

The `conversations/` package is the central application boundary for customer conversations.

It manages:

* conversation creation;
* initial-message acceptance;
* idempotency;
* customer-message processing;
* AI execution;
* response persistence;
* escalation;
* title generation;
* closing;
* conversation/message queries;
* bounded AI conversation context;
* lifecycle notifications.

The central workflow is:

```text
Customer Message
       │
       ▼
ProcessCustomerMessage
       │
       ├── Conversation Context
       ├── AI Pipeline
       ├── Knowledge Retrieval
       ├── Grounding
       ├── Response Generation
       ├── AI Run / Decision Evidence
       └── Escalation when required
       │
       ▼
Customer Response
```

Conversation processing deliberately avoids holding business transactions open while external AI providers are called.

The package also applies safeguards around:

* idempotency;
* processing leases;
* replay data;
* customer-data exposure;
* internal/system messages entering AI context;
* repeated closure;
* escalation information disclosure.

---

# 4. Knowledge

The `knowledge/` package provides the application boundary between AI workflows and the knowledge subsystem.

Its central responsibility is translation:

```text
AI Understanding
      │
      ▼
Knowledge Retrieval Request
      │
      ▼
Retrieval Query Context
      │
      ▼
Knowledge Retrieval
      │
      ▼
Grounding Context
      │
      ▼
Provider-Neutral Evidence
```

A key architectural rule is the separation between:

```text
AI-derived semantic hints
```

and:

```text
trusted application-controlled retrieval constraints
```

AI-derived entities such as order IDs or issue types are retrieval hints; they are not authorization information.

The package also maps knowledge grounding results into AI-facing evidence without coupling the AI layer to knowledge persistence models.

---

# 5. Escalations

The `escalations/` package owns the durable lifecycle of support escalations.

The AI/orchestration layer decides **that** escalation is required.

The application escalation layer decides **how that escalation becomes durable application state**.

```text
AI Decision
    │
    ▼
Create Escalation
    │
    ▼
Support Queue
    │
    ▼
Human Review
    │
    ▼
Update Escalation
    │
    ├── in_review
    ├── resolved
    └── dismissed
```

Responsibilities include:

* escalation creation;
* duplicate prevention;
* idempotency;
* queue/history queries;
* lifecycle updates;
* authorization;
* customer notifications;
* audit recording;
* trace/conversation/AI-run correlation.

This keeps escalation persistence separate from the AI decision itself.

---

# 6. Tickets

The `tickets/` package owns the support-ticket lifecycle.

```text
Create
  │
  ▼
Active Ticket
  │
  ├── Comments
  ├── Assignment
  ├── Priority / Category
  ├── Status Changes
  │
  ▼
Resolved / Closed
  │
  ▼
Reopened
```

The package supports:

* customer-created tickets;
* agent/admin-created tickets;
* system/escalation-created tickets;
* escalation-to-ticket conversion;
* customer-visible and internal comments;
* customer ticket queries;
* staff queues;
* assignments;
* lifecycle updates;
* optimistic concurrency;
* audit;
* notifications.

Ticket creation from escalation reuses the core ticket-creation workflow rather than duplicating its validation and idempotency rules.

---

# 7. Feedback

The `feedback/` package manages customer feedback on AI-generated responses.

Its lifecycle is:

```text
              ┌───────────┐
              │  pending  │
              └─────┬─────┘
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
      reviewed   actioned  dismissed
          │
       ┌──┴──┐
       ▼     ▼
   actioned dismissed
```

It provides:

* customer feedback submission;
* response/AI-run provenance validation;
* conversation ownership validation;
* duplicate/conflict handling;
* staff review;
* lifecycle transitions;
* optimistic concurrency;
* customer/staff-specific views;
* filtering and pagination;
* audit events.

Feedback is therefore treated as an application workflow rather than a generic database record.

---

# 8. Audit

The `audit/` package provides the application-level business audit boundary.

It separates:

```text
Audit Contracts
       │
       ├── Recording
       │
       └── Querying
```

Audit records represent **what business state changed**, while technical telemetry represents **how the system executed**.

The package supports:

* immutable audit representations;
* event recording;
* filtered event queries;
* entity history;
* trace-oriented audit history;
* actor information;
* structured event payloads.

Audit recording participates in the caller's transaction rather than independently deciding transaction durability.

This allows operations such as:

```text
Business Mutation
      │
      ├── State Change
      ├── Audit Event
      └── Commit Together
```

---

# 9. Dashboard

The `dashboard/` package is the application's **read-only operational analytics boundary**.

It provides high-level and detailed views over:

* API activity;
* AI runs;
* LLM usage;
* retrieval;
* escalations;
* tickets;
* feedback;
* conversations;
* knowledge health.

It also provides operational explorers:

```text
Trace
 │
 ├── API Requests
 ├── AI Runs
 ├── LLM Calls
 ├── Retrieval Runs
 └── Audit Events
```

The dashboard consumes telemetry and application data rather than duplicating telemetry collection.

A key architectural separation is:

```text
Business Audit
"What changed?"

Technical Telemetry
"How did it execute?"

Dashboard Analytics
"What patterns are visible?"
```

Dashboard results are exposed as application-level models rather than ORM entities.

Sensitive textual data is minimized; retrieval queries are represented through bounded fingerprints rather than storing raw customer query content.

---

# 10. Observability

The `observability/` package currently provides the application boundary for recording completed HTTP/API requests.

```text
HTTP / Middleware
         │
         │ sanitized telemetry
         ▼
   RecordAPIRequest
         │
         ▼
API Request Repository
         │
         ▼
      Database
```

Only sanitized telemetry should cross this boundary.

Raw:

* request bodies;
* response bodies;
* cookies;
* authorization headers;
* API keys;
* arbitrary sensitive headers

must not become durable API-request telemetry.

The service uses a Unit of Work and repository abstraction rather than directly managing database statements.

---

# 11. Users

The `users/` package provides administrative user-management workflows.

It covers two major operations:

```text
Initial Administrator Bootstrap
             │
             ▼
     Administrative Access
             │
             ▼
       Access Management
```

The package supports:

* controlled first-admin provisioning;
* password hashing;
* administrative role/status changes;
* session revocation after access changes;
* concurrency protection;
* audit events.

Access changes are treated as security-sensitive operations rather than ordinary CRUD updates.

For example:

```text
Change Role / Status
        │
        ▼
Revoke Existing Sessions
        │
        ▼
Record Audit
        │
        ▼
Commit Atomically
```

This prevents stale authentication sessions from continuing to operate with outdated authorization.

---

# 12. Composition

The `composition/` package is the **composition root** for the application layer.

It converts configuration and infrastructure dependencies into fully wired application services.

Its responsibilities include composing:

* LLM providers;
* embedding providers;
* ingestion strategies;
* vector/lexical retrieval;
* fusion and reranking;
* grounding;
* knowledge application services;
* answer services;
* request-scoped AI pipelines;
* the top-level `ApplicationServices` container.

Conceptually:

```text
Configuration
      │
      ▼
Composition Factories
      │
      ├── AI / LLM
      ├── Embeddings
      ├── Knowledge
      ├── Retrieval
      ├── Answer Generation
      └── Application Services
      │
      ▼
Application Runtime
```

The composition layer is responsible for **wiring**, not implementing the business behavior of the services it creates.

---

# Cross-Domain Architecture

The application packages are not isolated. They form a coordinated workflow.

A typical customer-support request can move through the system as follows:

```text
                     Customer Request
                            │
                            ▼
                    Authentication
                            │
                            ▼
                     Conversation
                            │
                            ▼
                  Process Customer Message
                            │
                            ▼
                       AI Pipeline
                            │
                ┌───────────┴───────────┐
                │                       │
                ▼                       ▼
             Decision              Knowledge
                │                  Application
                │                       │
                │                       ▼
                │                 Retrieval
                │                       │
                │                       ▼
                │                 Grounding
                │                       │
                └───────────┬───────────┘
                            ▼
                     Answer Service
                            │
                   ┌────────┴─────────┐
                   │                  │
                   ▼                  ▼
                Answer            Escalation
                   │                  │
                   │                  ▼
                   │               Ticket
                   │
                   ▼
                Feedback
                   │
                   ▼
                 Audit
                   │
                   ▼
              Dashboard
```

---

# Application Layer Interaction Model

The major relationships can be summarized as:

```text
┌──────────────────────────────────────────────────────────┐
│                    Application Layer                     │
│                                                          │
│  Auth ───────► Conversations ───────► AI / Knowledge     │
│                    │                         │           │
│                    │                         ▼           │
│                    │                    Answer Service   │
│                    │                                     │
│                    ├──────► Escalations ─────► Tickets   │
│                    │                                     │
│                    └──────► Feedback                     │
│                                                          │
│  Users ─────────► Administrative Access                  │
│                                                          │
│  Audit ─────────► Business History                       │
│  Observability ─► API Telemetry                          │
│  Dashboard ────► Operational Read Models                 │
│                                                          │
│  Composition ──► Wires the complete application          │
└──────────────────────────────────────────────────────────┘
```

---

# Common Application-Layer Patterns

Across the subpackages, several patterns are used consistently.

## Command / Query Separation

Mutating operations generally use explicit command objects:

```text
Command
   │
   ▼
Application Service
   │
   ▼
Mutation
```

Read operations use query objects and detached result models.

This prevents callers from depending directly on persistence entities.

---

## Unit of Work Boundaries

Application services generally receive a:

```python
UnitOfWorkFactory
```

rather than a pre-opened transaction.

This allows each operation to control its own transaction scope.

```text
 Application Service
       │
       ▼
  UnitOfWorkFactory
       │
       ▼
   Unit of Work
       │
       ├── Repository operations
       ├── Audit
       └── Related state changes
       │
       ▼
     Commit
```

---

## Authorization at the Application Boundary

Authorization is enforced before protected application operations are performed.

Examples include:

* customer ownership;
* support-agent/admin permissions;
* role consistency with persisted users;
* escalation lifecycle permissions;
* feedback review permissions;
* ticket visibility;
* administrative access changes.

The application layer therefore acts as a major security boundary.

---

## Detached Result Models

Application services generally return immutable/detached application models rather than exposing ORM entities.

```text
Database Model
      │
      ▼
Application Service
      │
      ▼
Detached DTO / View
```

This prevents database implementation details from leaking into APIs and higher-level application workflows.

---

# Audit and Observability

The application layer intentionally distinguishes several forms of system information.

```text
                    System Activity
                          │
             ┌────────────┼─────────────┐
             │            │             │
             ▼            ▼             ▼
          Business      Technical     Analytics
           Audit        Telemetry
             │            │             │
             ▼            ▼             ▼
       What changed?   How did it?   What patterns?
```

### Audit

Records business mutations and actors.

### Observability / Telemetry

Records technical execution characteristics such as timing, status, provider identity, and bounded identifiers.

### Dashboard

Aggregates and exposes operational information from these sources.

Keeping these concerns separate avoids turning one persistence model into an overloaded combination of audit log, telemetry store, and analytics database.

---

# Security and Privacy Principles

Security-sensitive invariants are distributed across the application packages but follow common principles.

## Identity

Authentication state is authoritative in persisted state, not merely in a valid JWT.

## Authorization

Authenticated identity and persisted user role/status must remain consistent.

## Ownership

Customers should only access resources belonging to them.

## Information Disclosure

Unauthorized access should not reveal whether another customer's resource exists where the application contract requires concealment.

## Sensitive Data

Raw passwords, refresh tokens, customer content, raw prompts, and other sensitive data should not be unnecessarily persisted in application telemetry or replay structures.

## Auditability

Security-sensitive mutations should generate corresponding audit events within the same transactional boundary where required.

## Session Revocation

Administrative access changes must invalidate existing authentication sessions where appropriate.

---

# Transaction and Concurrency Principles

The application layer uses transactions not merely for persistence, but to protect business invariants.

Common techniques include:

```text
Unit of Work
Row locking
Optimistic concurrency
Idempotency
Processing leases
Advisory locks
Atomic audit + mutation
```

Examples:

```text
Ticket update
    └── row version / stale-write protection

Feedback review
    └── optimistic concurrency

Initial admin provisioning
    └── concurrency protection

Conversation start
    └── idempotency + processing lease

Escalation creation
    └── duplicate prevention

Ticket from escalation
    └── atomic escalation/ticket workflow
```

---

# Read vs Write Responsibilities

The application layer contains both transactional workflows and read-oriented application services.

```text
                 Application Layer
                        │
             ┌──────────┴──────────┐
             │                     │
             ▼                     ▼
          Commands              Queries
             │                     │
             ▼                     ▼
      State-changing          Read-only
       workflows              projections
             │                     │
             ▼                     ▼
        UoW + Audit          Repository Reads
        + Notifications       + DTO Mapping
```

Dashboard and query services are predominantly read-oriented, while authentication, conversations, escalations, tickets, feedback, and knowledge lifecycle operations contain substantial mutation workflows.

---

# Application-Level Invariants

The application layer is where important cross-entity rules are enforced.

Examples include:

```text
Customer → owns conversation
Customer → owns ticket
Customer → owns feedback
Feedback → references valid AI response
AI run → belongs to conversation
Escalation → belongs to conversation
Ticket → may originate from escalation
User role → matches authenticated principal
Access change → revokes sessions
Audit → accompanies sensitive mutations
```

These invariants are intentionally kept above raw repositories so that database access alone cannot accidentally bypass application rules.

---

# Testing Philosophy

The application packages are designed around dependency injection and explicit contracts.

Typical test seams include:

* Unit of Work factories;
* repositories;
* clocks;
* password hashers;
* token services;
* LLM providers;
* embedding providers;
* retrieval services;
* rerankers;
* telemetry recorders;
* notification writers;
* orchestration observers.

Tests should primarily verify **application invariants and outcomes**, rather than simply asserting that a repository method was called.

Important test categories include:

```text
Authorization
Validation
Ownership
Concurrency
Idempotency
Transaction atomicity
Audit creation
Notification behavior
Visibility rules
Lifecycle transitions
Persistence contract failures
```

---

# Dependency Direction

The intended architecture is broadly:

```text
                External Interfaces
                       │
                       ▼
              Application Layer
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
      Domain          AI          Knowledge
      Logic        Contracts      Contracts
        │              │              │
        └──────────────┼──────────────┘
                       ▼
                  Persistence
                       │
                       ▼
                  PostgreSQL
```

The application layer should coordinate lower-level capabilities through explicit abstractions rather than allowing API handlers or infrastructure code to implement business workflows directly.

---

# Design Principles

## 1. Application Services Own Use Cases

A business operation should have a clear application boundary.

## 2. Persistence Is Encapsulated

Callers should not manipulate repositories or SQLAlchemy sessions directly.

## 3. Authorization Happens Before Sensitive Operations

Ownership and role checks are application invariants.

## 4. Transactions Protect Business Invariants

Related mutations, audits, and state changes should be committed consistently.

## 5. AI and Knowledge Remain Decoupled

AI semantic understanding should communicate with knowledge through application-level contracts.

## 6. Audit Is Different From Telemetry

Business history and technical execution data have different purposes.

## 7. Dashboards Are Read-Oriented

Operational analytics should not become another mutation layer.

## 8. Sensitive Data Is Minimized

Customer content and security-sensitive values should not be persisted merely for convenience.

## 9. Composition Is Centralized

Concrete providers and infrastructure implementations should be wired through the composition root.

## 10. Results Are Detached

Application callers receive stable DTOs/views instead of ORM objects.

---

# End-to-End Application Architecture

The complete application layer can be viewed as:

```text
                           APPLICATION
                                │
        ┌───────────────────────┼────────────────────────┐
        │                       │                        │
        ▼                       ▼                        ▼
   Identity & Access       Customer Support          AI / Knowledge
        │                       │                        │
   ┌────┴────┐          ┌───────┼────────┐       ┌───────┴────────┐
   │         │          │       │        │       │                │
  Auth     Users   Conversations Escal. Tickets  AI          Knowledge
   │         │          │       │        │       │                │
   └────┬────┘          └───┬───┴────────┘       └───────┬────────┘
        │                   │                            │
        │                   ▼                            ▼
        │               Feedback                    Grounded Answer
        │
        └──────────────────────┬─────────────────────────┘
                               │
                               ▼
                         Audit / Events
                               │
                               ▼
                         Observability
                               │
                               ▼
                           Dashboard

                    Composition
                         │
                         ▼
              Wires all application services
```

---

# Summary

`packages/application/` is the **orchestration and business-workflow boundary** of the AI customer-support agent.

Its twelve subpackages divide the system into clear application capabilities:

```text
ai              → grounded AI answer integration
audit           → business audit history
auth            → authentication and sessions
composition     → dependency composition
conversations   → customer conversation lifecycle
dashboard       → operational analytics
escalations     → human-support escalation lifecycle
feedback        → AI-response feedback lifecycle
knowledge       → AI ↔ knowledge retrieval boundary
observability   → sanitized API telemetry persistence
tickets         → support-ticket lifecycle
users           → administrative access management
```

Together they provide the application-level coordination needed to turn lower-level AI, knowledge, persistence, and infrastructure capabilities into **secure, transactional, auditable, and testable customer-support workflows**.

The most important architectural boundary is:

```text
                 Application Layer
                        │
        ┌───────────────┼────────────────┐
        │               │                │
        ▼               ▼                ▼
     Business          AI             Knowledge
    Workflows        Workflows        Workflows
        │               │                │
        └───────────────┼────────────────┘
                        │
                        ▼
                 Infrastructure
```

The application layer therefore serves as the **coordination point between business intent and technical infrastructure**, while keeping individual domains and infrastructure implementations independently replaceable.
