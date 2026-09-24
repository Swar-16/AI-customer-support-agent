# API v1 Schemas

## Overview

The `schemas/` package contains the **Pydantic models that define the HTTP API contract for v1 endpoints**.

These schemas form the boundary between the external API and the internal application layer.

```text
              Client
                │
                │ HTTP / JSON
                ▼
┌──────────────────────────────┐
│       API v1 Schemas         │
│       apps/api/.../schemas   │
│                              │
│  Request validation          │
│  Response serialization      │
│  Enum / field constraints    │
│  API-safe representations    │
└──────────────┬───────────────┘
               │
               ▼
       Application Services
               │
               ▼
       Domain / AI / Database
```

The schemas intentionally keep the HTTP representation separate from ORM models and internal application/domain objects.

---

# Directory Structure

```text
apps/api/app/api/v1/schemas/
│
├── auth.py
├── conversations.py
├── dashboard.py
├── escalations.py
├── feedback.py
├── knowledge.py
├── tickets.py
└── users.py
```

| File | API Contract Area |
|---|---|
| `auth.py` | Registration, login, refresh, logout, authenticated-user and token responses |
| `conversations.py` | Conversation lifecycle, messages, AI processing and conversation responses |
| `dashboard.py` | Dashboard metrics, analytics, traces and operational views |
| `escalations.py` | Human-support escalation requests and responses |
| `feedback.py` | Customer feedback submission and administrative review |
| `knowledge.py` | Knowledge document/version management API contracts |
| `tickets.py` | Support-ticket creation, updates, comments and querying |
| `users.py` | Administrative user access and account-management contracts |

---

# Architectural Role

These files are **API contracts**, not business services.

Their responsibility is primarily:

```text
HTTP Input
    │
    ▼
Pydantic Request Model
    │
    ├── Type validation
    ├── Required/optional fields
    ├── Length/range constraints
    ├── Enum constraints
    ├── Normalization
    └── Cross-field validation
    │
    ▼
Application Service
    │
    ▼
Application Result
    │
    ▼
Pydantic Response Model
    │
    ▼
HTTP / JSON Output
```

This separation allows the API contract to evolve independently from internal persistence and domain representations.

---

# Common Schema Principles

## Strict Input Contracts

The schemas generally reject unexpected fields using:

```python
ConfigDict(
    extra="forbid",
    ...
)
```

For example, the conversation API explicitly uses this behavior so unsupported request properties are not silently ignored.

This provides a strict API boundary:

```json
{
  "message": "Where is my order?",
  "unexpected_internal_flag": true
}
```

should be rejected rather than silently accepting the unsupported property.

---

## Input Normalization

Where appropriate, schemas normalize user-provided strings.

Examples include:

- email normalization;
- display-name normalization;
- title normalization;
- whitespace trimming;
- customer messages;
- feedback comments;
- escalation customer messages.

For example, authentication schemas normalize email addresses before they enter the application layer.

Conversation schemas similarly normalize titles and reject blank messages.

---

## Explicit Constraints

Fields use Pydantic constraints to make API expectations executable.

Examples include:

```text
min_length
max_length
ge
le
Literal
UUID
datetime
SecretStr
```

For example, ticket schemas define explicit bounds for subjects, descriptions, priorities and statuses.

This means invalid requests are rejected at the API boundary instead of relying on downstream services to discover basic input errors.

---

# Request vs Response Models

The schema layer distinguishes between **incoming commands** and **outgoing representations**.

### Request

Represents what the client is allowed to provide.

```text
Client
  │
  ▼
Request Schema
  │
  ▼
Application Command
```

### Response

Represents what the API is allowed to expose.

```text
Application Result
  │
  ▼
Response Schema
  │
  ▼
Client
```

This distinction is particularly important for security-sensitive resources.

For example, the authentication response exposes user identity and token information without exposing internal persistence objects.

---

# 1. `auth.py`

```text
apps/api/app/api/v1/schemas/auth.py
```

`auth.py` defines the HTTP contracts for authentication operations.

It covers:

```text
Registration
Login
Refresh
Authenticated User
Token Pair
Authentication Result
Browser Access Token
Logout-related responses
```

Representative request models include:

```text
RegisterRequest
LoginRequest
RefreshSessionRequest
```

and response models include:

```text
AuthenticatedUserResponse
TokenPairResponse
AuthenticationResponse
BrowserAccessTokenResponse
```



Sensitive inputs such as passwords and refresh tokens use `SecretStr`, keeping credentials distinct from ordinary API strings.

The response layer also maps internal application authentication results into explicit API-safe representations rather than exposing internal application objects directly.

---

# 2. `conversations.py`

```text
apps/api/app/api/v1/schemas/conversations.py
```

`conversations.py` defines the API contract for the customer conversation lifecycle.

It covers:

```text
Conversation creation
Conversation listing
Conversation details
Messages
Starting conversations
Sending messages
AI processing results
Conversation closure
Feedback summaries
Idempotent start processing
```

The file defines controlled values for:

```text
ConversationChannel
    web
    mobile
    email
    api

ConversationStatus
    open
    waiting_for_customer
    waiting_for_agent
    escalated
    resolved
    closed
```



A particularly important part of this contract is the AI processing response.

A message-processing result can represent:

```text
                 Message Processing
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
      Answer        Escalation     Failure
          │             │             │
          ▼             ▼             ▼
   assistant ID    escalation ID   failure state
```

The schema explicitly prevents an unapproved generated candidate from being exposed when the pipeline escalates or fails.

The conversation-start schemas also encode idempotency and processing-lease states, allowing clients to distinguish completed, failed, replayed and currently-processing operations.

---

# 3. `dashboard.py`

```text
apps/api/app/api/v1/schemas/dashboard.py
```

`dashboard.py` exposes the HTTP representation of the operational dashboard.

It maps application-layer dashboard results into API-safe Pydantic responses.

It covers areas such as:

```text
Dashboard overview
Metrics
Time ranges
Trace summaries/details
LLM calls
Retrieval runs
API requests
Audit events
Analytics
Conversation analytics
AI analytics
Support analytics
Knowledge health
```

The schema imports the corresponding application dashboard result models rather than querying the database itself.

For example, `DashboardMetricResponse` converts an application `DashboardMetric` into a frozen, strict HTTP representation.

The architecture is therefore:

```text
Dashboard Repository / Query
          │
          ▼
Application Dashboard Result
          │
          ▼
     dashboard.py
          │
          ▼
      HTTP JSON
```

---

# 4. `escalations.py`

```text
apps/api/app/api/v1/schemas/escalations.py
```

`escalations.py` defines contracts for cases transferred to human support.

It represents:

```text
Escalation
Escalation queue
Escalation details
Linked tickets
Escalation transitions
```

Core states include:

```text
open
in_review
resolved
dismissed
```

with priorities:

```text
low
normal
high
urgent
```



The response model deliberately separates queue representation from detailed representation.

```text
EscalationResponse
        │
        └── Lightweight queue representation

EscalationDetailResponse
        │
        └── Includes linked ticket
```

This avoids requiring a ticket lookup for every escalation in a queue response.

Terminal transitions also require a customer-visible explanation, keeping internal diagnostic information out of that field.

---

# 5. `feedback.py`

```text
apps/api/app/api/v1/schemas/feedback.py
```

`feedback.py` defines customer-feedback and feedback-review contracts.

It covers two main workflows:

```text
Customer
   │
   ▼
Submit Feedback
   │
   ▼
Feedback Record
   │
   ▼
Dashboard / Support Review
   │
   ▼
Review / Action / Dismiss
```

Feedback statuses include:

```text
pending
reviewed
actioned
dismissed
```

and structured reason codes include categories such as:

```text
INCORRECT_ANSWER
INCOMPLETE_ANSWER
IRRELEVANT_ANSWER
OUTDATED_INFORMATION
UNCLEAR_ANSWER
MISSING_CITATION
UNSAFE_RESPONSE
SLOW_RESPONSE
OTHER
```



The customer submission contract links feedback to the assistant message and AI run that produced the response.

Administrative review uses optimistic concurrency through `expected_row_version`.

Duplicate reason codes are removed while preserving insertion order.

---

# 6. `knowledge.py`

```text
apps/api/app/api/v1/schemas/knowledge.py
```

`knowledge.py` exposes API contracts for the knowledge-management surface.

It bridges HTTP requests/responses with the internal knowledge application and domain models.

It covers concepts such as:

```text
Knowledge documents
Document versions
Document lists
Version lists
Uploads
Knowledge lifecycle state
Knowledge visibility
Content types
Ingestion state
```

The schemas explicitly import application results and knowledge-domain types rather than making the HTTP layer responsible for knowledge persistence.

The package uses a strict, frozen `KnowledgeAPIModel` base:

```python
ConfigDict(
    extra="forbid",
    frozen=True,
)
```



Response construction is explicit.

For example, a knowledge domain document is mapped into `KnowledgeDocumentSummaryResponse` through a controlled conversion method.

This prevents domain objects from becoming accidental API contracts.

---

# 7. `tickets.py`

```text
apps/api/app/api/v1/schemas/tickets.py
```

`tickets.py` defines contracts for support-ticket operations.

It covers:

```text
Ticket creation
Escalation → ticket creation
Ticket updates
Ticket responses
Ticket comments
Ticket querying/listing
Ticket lifecycle
```

Controlled ticket dimensions include:

```text
Source
Category
Priority
Status
Requester role
Comment author role
Comment visibility
```



Creation is represented separately from updates.

For example:

```text
CreateTicketRequest
        │
        ▼
Ticket creation

UpdateTicketRequest
        │
        ▼
Ticket lifecycle mutation
```

The update contract includes `expected_row_version`, supporting optimistic concurrency, and can explicitly assign/unassign agents or change status/category/priority.

The escalation-ticket contract deliberately does not accept identifiers that should be derived by the application service, such as the conversation, customer, triggering message, and escalation identifiers.

---

# 8. `users.py`

```text
apps/api/app/api/v1/schemas/users.py
```

`users.py` defines administrative user-access contracts.

It covers:

```text
Role changes
Account status changes
Administrative reason
Access-management response
```

Assignable roles are:

```text
customer
support_agent
admin
```

and manageable statuses are:

```text
active
disabled
```



An access mutation must change at least one of:

```text
role
status
```

and must include a non-empty administrative reason.

The response is intentionally sanitized:

```text
Included:
    user identity
    role
    status
    timestamp
    changed flag
    revoked session count

Excluded:
    credential hashes
    authentication sessions
    token material
```



The administrator's identity is also intentionally derived from the verified bearer token rather than being accepted from the request body.

---

# Relationship Between the Eight Schemas

The files collectively expose the major API surfaces of the application:

```text
                         API v1
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
       ▼                   ▼                   ▼
     Auth            Conversations          Users
       │                   │                   │
       │                   ▼                   │
       │                Feedback               │
       │                   │                   │
       │                   ▼                   │
       │              Escalations ───────► Tickets
       │
       ├───────────────────────────────────────┐
       │                                       │
       ▼                                       ▼
   Knowledge                                Dashboard
```

The schemas describe **how these capabilities appear over HTTP**; the underlying behavior remains in the application packages.

---

# API Boundary Flow

A normal endpoint follows this pattern:

```text
HTTP Request
     │
     ▼
FastAPI Route
     │
     ▼
Request Schema
     │
     ├── Parse
     ├── Validate
     └── Normalize
     │
     ▼
Application Service
     │
     ├── Authorization
     ├── Business Rules
     ├── AI / Knowledge
     └── Persistence
     │
     ▼
Application Result
     │
     ▼
Response Schema
     │
     ├── Sanitize
     ├── Transform
     └── Serialize
     │
     ▼
HTTP Response
```

This keeps HTTP-specific representation separate from internal architecture.

---

# Security and Data Exposure

The schema layer is also an important **data-exposure boundary**.

It should expose only information appropriate for the endpoint's caller.

Examples:

### Authentication

Secrets are represented using `SecretStr` for request credentials.

### Users

Credential hashes, authentication sessions and token material are explicitly excluded from administrative user responses.

### Conversations

Customer-facing feedback responses intentionally exclude internal comments, administrative review data, metadata and telemetry.

### Escalations

Customer-visible explanations are separated from internal diagnostic information.

### AI Responses

Conversation response contracts distinguish approved customer-visible responses from escalation/failure outcomes and do not expose unapproved generated candidates.

---

# Schema Layer vs Application Layer

The distinction is important:

```text
schemas/
    "What can enter/leave the HTTP API?"

application/
    "What should the system do?"

domain/
    "What does the business state mean?"

database/
    "How is that state persisted?"
```

For example:

```text
CreateTicketRequest
        │
        ▼
tickets.create_ticket
        │
        ▼
Ticket application/domain logic
        │
        ▼
Repository / Unit of Work
        │
        ▼
CreateTicketResponse
```

The schema should not become the place where ticket business rules are implemented.

It may validate **API-level constraints**, but business invariants belong in the application/domain layer.

---

# Schema Design Rules

When adding or modifying a schema in this directory:

### 1. Keep it HTTP-focused

The model should describe the public API representation rather than an ORM table.

### 2. Reject unexpected input

Use strict models for request contracts where appropriate.

### 3. Normalize deliberately

Only normalize values where the API contract explicitly requires it.

### 4. Validate at the boundary

Reject obviously invalid input before it reaches application services.

### 5. Do not expose internal objects directly

Use explicit conversion methods such as:

```text
from_application(...)
from_domain(...)
```

where appropriate.

### 6. Keep sensitive fields out of responses

Never expose credentials, token internals, private persistence state, or internal diagnostics merely because they exist internally.

### 7. Preserve concurrency contracts

Where application operations use optimistic concurrency, expose fields such as:

```text
expected_row_version
```

rather than hiding the concurrency requirement.

### 8. Keep business logic elsewhere

Schema validators should handle input-shape and representation concerns. Complex workflows and business invariants belong to the application/domain layers.

---

# Overall Mental Model

The easiest way to remember this directory is:

```text
                    apps/api
                       │
                       ▼
                      v1
                       │
                       ▼
                   schemas/
                       │
      ┌────────────────┼────────────────┐
      │                │                │
      ▼                ▼                ▼
   Requests         Validation       Responses
      │                │                │
      └────────────────┼────────────────┘
                       ▼
                Application Layer
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
       AI          Knowledge       Database
```

The eight files collectively provide the **typed, validated, sanitized HTTP contract** for the major v1 API surfaces:

```text
auth.py
    Authentication

conversations.py
    Customer conversations and AI message processing

dashboard.py
    Operational analytics

escalations.py
    Human-support escalation

feedback.py
    Customer feedback and review

knowledge.py
    Knowledge management

tickets.py
    Support tickets

users.py
    Administrative user access
```

The key architectural principle is:

> **`apps/api/app/api/v1/schemas/` defines the public HTTP shape of the system without becoming the system's business-logic layer.**