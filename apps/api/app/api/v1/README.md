# API v1

## Overview

The `v1/` package contains the **versioned HTTP API surface** of the AI customer-support agent.

It is responsible for exposing application capabilities through FastAPI routes, handling HTTP-specific concerns, resolving authenticated principals and dependencies, translating requests into application commands/queries, and converting application results into versioned API responses.

```text
Client
  │
  │ HTTP / JSON
  ▼
┌─────────────────────────────────────────────┐
│                 API v1                      │
│          apps/api/app/api/v1/               │
│                                             │
│  Routing                                    │
│  HTTP validation                            │
│  Authentication / authorization boundaries  │
│  Request → Application command/query        │
│  Application result → API response          │
│  HTTP error/status translation              │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
              Application Layer
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
         AI        Knowledge     Persistence
```

The implementation deliberately keeps business workflows in `packages/application/` rather than embedding them inside the FastAPI route handlers.

---

# Directory Structure

```text
apps/api/app/api/v1/
│
├── __init__.py
├── router.py
│
├── auth.py
├── conversations.py
├── dashboard.py
├── escalations.py
├── feedback.py
├── health.py
├── knowledge.py
├── tickets.py
├── users.py
│
└── schemas/
    ├── README.md
    ├── auth.py
    ├── conversations.py
    ├── dashboard.py
    ├── escalations.py
    ├── feedback.py
    ├── knowledge.py
    ├── tickets.py
    └── users.py
```

The `schemas/` directory has its own detailed documentation and should be consulted for the individual request/response model contracts rather than duplicating those details here. The schemas form the typed HTTP boundary between this router layer and the application layer.

---

# Role in the API Architecture

The v1 layer is intentionally a **thin transport adapter**.

A typical request follows:

```text
HTTP Request
     │
     ▼
FastAPI Router
     │
     ├── Path/query/body parsing
     ├── Pydantic validation
     ├── Authentication dependency
     ├── Authorization dependency
     └── Trace/context extraction
     │
     ▼
Application Command / Query
     │
     ▼
Application Service
     │
     ├── Business rules
     ├── Authorization invariants
     ├── Transactions
     ├── Repositories
     └── AI / Knowledge services
     │
     ▼
Application Result
     │
     ▼
API Response Schema
     │
     ▼
HTTP Response
```

This mirrors the broader application architecture where application services own use-case orchestration and the API layer acts as an external interface.

---

# API Versioning

All routes in this package are mounted below:

```text
/v1
```

`router.py` defines the version prefix and composes the individual feature routers.

The version router registers:

```text
health
auth
conversations
escalations
tickets
feedback
dashboard
users
knowledge
```

including the specialized conversation/customer escalation routers.

Conceptually:

```text
API
│
├── /v1
│    │
│    ├── /health
│    ├── /auth
│    ├── /conversations
│    ├── /escalations
│    ├── /tickets
│    ├── /feedback
│    ├── /dashboard
│    ├── /users
│    └── /knowledge
│
└── future versions
     └── /v2
```

The version router is intentionally limited to **route composition** rather than business logic.

---

# Endpoint Modules

## `router.py`

`router.py` is the **composition root for API v1 routes**.

It does not implement endpoint behavior. Its job is to:

- define `/v1`;
- import feature routers;
- register them on the v1 router;
- provide one router for the parent API application.

This keeps API-version composition centralized.

---

## `auth.py`

`auth.py` exposes the authentication HTTP surface.

It handles workflows such as:

- customer registration;
- login;
- session refresh;
- current-user access;
- logout.

The router delegates authentication behavior to application services such as registration, login, current-user and session operations rather than implementing authentication logic itself.

Browser authentication also integrates with the API's refresh-cookie handling. Registration and login, for example, obtain application authentication results and then establish the refresh cookie at the HTTP boundary.

The corresponding Pydantic contracts live in `schemas/auth.py`; those schemas handle strict request validation and sensitive credential representation.

### Responsibility boundary

```text
auth.py
    HTTP authentication workflow

packages/application/auth/
    Authentication behavior and invariants

schemas/auth.py
    HTTP request/response representation
```

---

# `conversations.py`

`conversations.py` exposes the customer conversation lifecycle.

It connects HTTP requests to application services for:

- conversation creation;
- conversation queries;
- message retrieval;
- customer message processing;
- conversation closing;
- conversation-start processing;
- AI-generated response handling.

The router imports dedicated application commands/queries rather than performing persistence operations itself.

A particularly important responsibility here is translating AI pipeline outcomes into appropriate HTTP/application errors. Pipeline failures are classified into safe categories such as timeout, unavailable/rate-limited, or general pipeline failure after the underlying application transaction has committed.

The conversation API therefore sits at an important boundary:

```text
 Customer Message
      │
      ▼
v1/conversations.py
      │
      ▼
ProcessCustomerMessage
      │
      ▼
  AI Pipeline
      │
      ├── Answer
      ├── Escalation
      ├── Timeout
      ├── Unavailable
      └── Failure
      │
      ▼
Safe HTTP Result
```

The detailed representation rules belong to `schemas/conversations.py`; for example, assistant-message provenance and customer-safe feedback are explicitly represented there.

---

# `escalations.py`

`escalations.py` exposes the human-support escalation surface.

It supports operations around:

- escalation queues;
- escalation history;
- conversation-specific escalation history;
- escalation details;
- escalation state transitions;
- customer escalation status;
- linked tickets.

The main support escalation router is protected by role requirements for support agents and administrators.

The route layer performs basic HTTP-level query validation while leaving authoritative business/query validation to the application layer.

This separation is important because escalation transitions contain business rules that should not be duplicated inside FastAPI handlers.

---

# `tickets.py`

`tickets.py` provides the support-ticket HTTP API.

It covers:

```text
Create ticket
Create ticket from escalation
List tickets
Get ticket details
Update ticket
Add ticket comment
```

The router delegates directly to ticket application commands and queries such as:

```text
CreateTicketCommand
CreateTicketFromEscalationCommand
ListTicketsQuery
GetTicketQuery
UpdateTicketCommand
AddTicketCommentCommand
```



The API supports both customer-facing and staff-facing ticket access. Filtering includes ticket status, priority, category, assignment and active queue state.

Escalation-to-ticket conversion is explicitly role-restricted and supports idempotent behavior when an escalation already has a linked ticket.

Conceptually:

```text
Customer Conversation
        │
        ├── Customer creates ticket
        │
        └── Escalation
               │
               ▼
       Support Agent Review
               │
               ▼
        Ticket Creation
```

The request/response structures themselves are defined under `schemas/tickets.py`.

---

# `feedback.py`

`feedback.py` exposes feedback submission and support/admin review.

The main flows are:

```text
    Customer
        │
        ▼
  Submit feedback
        │
        ▼
AI response feedback
        │
        ▼
Support/Admin review
```

The endpoint delegates to:

```text
SubmitFeedbackCommand
ReviewFeedbackCommand
ListFeedbackQuery
GetFeedbackQuery
```

rather than directly interacting with feedback repositories.

Customer feedback is restricted to the appropriate customer context, while staff operations support filtered feedback queues.

This allows the feedback subsystem to serve both:

- customer experience;
- AI quality analysis;
- operational review.

The detailed feedback payload and status contracts remain in `schemas/feedback.py`.

---

# `dashboard.py`

`dashboard.py` exposes the operational and AI observability dashboard.

Unlike customer-facing endpoints, the dashboard is explicitly restricted to administrators.

It provides API access to application-level analytics including:

```text
Dashboard overview
Conversation analytics
AI analytics
Support analytics
Knowledge health
Trace queries
Trace details
LLM calls
Retrieval runs
API requests
Audit events
```

The router delegates these operations to dedicated dashboard application queries.

The overview endpoint aggregates operational, AI, retrieval, support, feedback and knowledge-management metrics over a selected reporting window.

The architecture is:

```text
Admin
  │
  ▼
/v1/dashboard
  │
  ├── Overview
  ├── Analytics
  ├── Traces
  ├── LLM calls
  ├── Retrieval runs
  ├── API requests
  ├── Audit events
  └── Knowledge health
        │
        ▼
Application Dashboard Queries
```

The response schemas convert application dashboard models into strict API representations.

---

# `knowledge.py`

`knowledge.py` exposes the administrative knowledge-management API.

It is the HTTP entry point for workflows such as:

```text
Document upload
Document creation
Document listing
Document retrieval
Version upload
Version creation
Version processing
Version embedding
Version publishing
Document archiving
```

The module imports dedicated knowledge application commands and queries for each operation.

Knowledge mutation endpoints use an administrator principal and trace context. Uploads additionally enforce HTTP-level file handling and configured upload limits before handing the operation to the application service.

The API also distinguishes different failure categories such as:

```text
400  Invalid upload/content
401  Authentication required
403  Administrator access required
404  Resource not found
409  Lifecycle conflict
413  Upload too large
415  Unsupported media type
422  Validation failure
500  Unexpected failure
```



This endpoint layer therefore acts as the bridge between administrative HTTP operations and the deeper `packages/knowledge/` application/domain architecture.

---

# `users.py`

`users.py` exposes administrative user-access management.

Currently its primary responsibility is changing a user's:

```text
role
status
```

The endpoint requires an administrator principal and delegates the mutation to `UpdateUserAccessCommand`.

The route also passes:

```text
target user
admin principal
trace ID
new role
new status
administrative reason
```

to the application service.

The application result is then converted into the API response.

The endpoint therefore intentionally does not implement:

- authorization policy;
- session revocation rules;
- user-access invariants;
- persistence.

Those remain application-layer responsibilities.

---

# `health.py`

`health.py` provides infrastructure-facing health endpoints.

It distinguishes between **liveness** and **readiness**.

## Liveness

```text
GET /v1/health
```

The liveness endpoint only verifies that the API process is alive.

It intentionally does not contact the database or external providers, making it appropriate for container/orchestrator liveness probes.

Response:

```json
{
  "status": "ok"
}
```

## Readiness

```text
GET /v1/health/ready
```

Readiness performs lightweight dependency checks.

Currently it checks the configured LLM provider through the provider abstraction. Provider-specific failures are converted into readiness state rather than becoming generic HTTP 500 errors.

Conceptually:

```text
/v1/health
    │
    └── "Is the HTTP process alive?"

/v1/health/ready
    │
    └── "Can this instance currently process AI requests?"
             │
             └── LLM provider health
```

A failed readiness check returns HTTP `503 Service Unavailable`.

---

# Authentication and Authorization

The v1 routes use shared dependencies from:

```text
apps/api/app/api/dependencies.py
```

Typical dependency categories include:

```text
ApplicationServicesDependency
CurrentPrincipalDependency
CustomerPrincipalDependency
AdminPrincipalDependency
TraceIdDependency
ClientIpDependency
UserAgentDependency
```

Role restrictions are applied at the HTTP boundary where appropriate.

For example:

```text
Customer endpoints
    → CustomerPrincipalDependency

Authenticated endpoints
    → CurrentPrincipalDependency

Admin endpoints
    → AdminPrincipalDependency / require_roles(...)

Support endpoints
    → require_roles(SUPPORT_AGENT, ADMIN)
```

However, these HTTP-level checks should not be treated as the sole location of authorization logic. Application services remain responsible for authoritative business authorization and invariants.

---

# Error Handling

v1 endpoints consistently expose structured API errors through:

```text
apps/api/app/api/schemas/errors.py
```

Feature routers define endpoint-specific status mappings.

Common statuses include:

```text
400  Invalid operation
401  Authentication required
403  Access denied
404  Resource not found
409  State/concurrency/lifecycle conflict
422  Request validation failure
500  Unexpected internal failure
503  Dependency/service unavailable
```

This gives clients a predictable HTTP error surface while application exceptions remain internal implementation details.

---

# Trace Context

Many mutating endpoints receive a `TraceIdDependency`.

The trace identifier is forwarded into application commands:

```text
           HTTP Request
                │
                ▼
         TraceIdDependency
                │
                ▼
       Application Command
                │
                ▼
Audit / Observability / AI telemetry
```

This is especially important for workflows involving:

- AI processing;
- knowledge mutations;
- tickets;
- feedback;
- authentication;
- administrative operations.

The API therefore participates in the broader observability architecture without owning telemetry persistence itself.

---

# Request and Response Schemas

The `schemas/` package is the lower-level contract layer for this directory.

Its purpose is to define:

- request models;
- response models;
- enums/literals;
- field constraints;
- normalization;
- safe API representations.

It intentionally separates these representations from ORM/domain models.

The relationship is:

```text
apps/api/app/api/v1/
│
├── auth.py
├── conversations.py
├── ...
│       │
│       └──── uses ────► schemas/*.py
│
└── schemas/
       │
       └── HTTP contracts
```

For example:

```text
CreateTicketRequest
        │
        ▼
    tickets.py
        │
        ▼
CreateTicketCommand
        │
        ▼
Application Service
        │
        ▼
CreateTicketResponse
```

The detailed field-level documentation belongs in `schemas/README.md`, so this README intentionally keeps that discussion at the architectural level.

---

# Relationship with the Application Layer

The most important dependency direction is:

```text
apps/api/app/api/v1/
            │
            ▼
packages/application/
            │
            ├── domain
            ├── repositories
            ├── AI
            ├── knowledge
            └── infrastructure abstractions
```

The API layer should **not** reverse this dependency.

Application services should not depend on FastAPI route handlers.

For example:

```text
GOOD

  FastAPI route
        │
        ▼
 CreateTicketCommand
        │
        ▼
packages/application/tickets/
        │
        ▼
repositories / domain


AVOID

Application service
    │
    └── FastAPI Request / Response
```

This keeps the application layer usable from other interfaces such as workers, scripts or future APIs.

---

# Relationship with AI and Knowledge

The v1 API is the external entry point for several AI-related workflows, but it does not implement the AI pipeline itself.

A customer message follows approximately:

```text
Client
  │
  ▼
POST /v1/conversations/...
  │
  ▼
conversations.py
  │
  ▼
ProcessCustomerMessage
  │
  ▼
AI Application / Pipeline
  │
  ├── Intent
  ├── Retrieval
  ├── Reranking
  ├── Answer generation
  ├── Decision
  └── Escalation
  │
  ▼
Application Result
  │
  ▼
API Response
```

Likewise, knowledge management follows:

```text
Admin
  │
  ▼
/v1/knowledge
  │
  ▼
knowledge.py
  │
  ▼
Knowledge Application
  │
  ├── Documents
  ├── Versions
  ├── Processing
  ├── Embeddings
  └── Publishing
```

The API layer therefore **exposes** these capabilities without becoming responsible for their implementation.

---

# API Surface Summary

| Module | Primary responsibility | Typical caller |
|---|---|---|
| `router.py` | Compose and mount all v1 routers | API application |
| `health.py` | Liveness/readiness | Infrastructure |
| `auth.py` | Authentication/session operations | Customers/browser |
| `conversations.py` | Conversations and AI message processing | Customers |
| `escalations.py` | Human-support escalation management | Support/admin |
| `tickets.py` | Support-ticket lifecycle | Customers/support |
| `feedback.py` | AI response feedback/review | Customers/support |
| `dashboard.py` | Operational/AI analytics | Admin |
| `users.py` | Administrative access management | Admin |
| `knowledge.py` | Knowledge management | Admin |

---

# Design Principles

## 1. Thin Routers

Route handlers should primarily:

```text
Parse
Validate
Authorize
Construct command/query
Call application service
Map result
Return HTTP response
```

They should not become large business workflows.

## 2. Application Layer Owns Business Rules

State transitions, authorization invariants, concurrency rules and transactional behavior belong to the application/domain layers.

## 3. Schemas Own HTTP Representation

Pydantic models define what enters and leaves the API. They should not become ORM models or application services.

## 4. Explicit Error Contracts

HTTP status codes and API error models should remain predictable across endpoints.

## 5. Versioned Stability

Breaking changes should be handled deliberately through API versioning rather than silently changing the meaning of existing v1 contracts.

## 6. Security at the Boundary

Authentication, role checks, sensitive response filtering and request validation should be enforced before untrusted HTTP data reaches deeper layers.

## 7. Observability Without Ownership

Routes provide trace/context information to application services, while audit and telemetry persistence remain outside the HTTP layer.

---

# Adding a New v1 Endpoint

A new feature should generally follow:

```text
1. Define request/response contracts
          │
          ▼
2. Add application command/query
          │
          ▼
3. Implement application workflow
          │
          ▼
4. Add FastAPI route
          │
          ▼
5. Apply authentication/authorization dependencies
          │
          ▼
6. Map application result → response schema
          │
          ▼
7. Register router in router.py
          │
          ▼
8. Test HTTP contract and error behavior
```

The route should remain thin enough that the underlying use case could be invoked without FastAPI.

---

# Mental Model

The `v1/` package is best understood as the **HTTP adapter for the application**:

```text
                         HTTP Clients
                              │
                              ▼
                     ┌─────────────────┐
                     │      /v1        │
                     │                 │
                     │    router.py    │
                     └────────┬────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
       Customer             Support             Admin
          │                   │                   │
    conversations        escalations          dashboard
    feedback             tickets              users
    auth                 feedback             knowledge
          │                   │                   │
          └───────────────────┼───────────────────┘
                              ▼
                    Application Services
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
             AI          Knowledge         Persistence
```

In short:

> **`apps/api/app/api/v1/` is the versioned FastAPI transport layer that turns HTTP requests into application commands/queries and application results into stable HTTP responses.**

The individual `schemas/` package defines the detailed API contracts beneath this layer, while `packages/application/` owns the actual use-case behavior.