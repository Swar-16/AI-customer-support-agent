# Support Repositories

## Overview

The `packages/database/repositories/support/` package contains the **database persistence adapters for the customer-support subsystem**.

These repositories sit between the application/domain services and the SQLAlchemy models:

```text
Application / Domain
        │
        ▼
Support Repositories
        │
        ▼
  SQLAlchemy Models
        │
        ▼
    PostgreSQL
```

The package covers the persistence needs of:

- users and administrator management;
- authentication credentials and sessions;
- conversations;
- conversation messages;
- idempotent conversation starts;
- escalations;
- support tickets;
- ticket comments;
- customer feedback;
- repository-level errors.

The repositories deliberately remain **transaction-aware but transaction-agnostic**: they use the supplied SQLAlchemy `Session`, stage/flush changes, and leave commit/rollback to the surrounding Unit of Work.

---

## Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── database/
        └── repositories/
            └── support/
                ├── auth_repository.py
                ├── conversation_repository.py
                ├── conversation_start_request_repository.py
                ├── errors.py
                ├── escalation_repository.py
                ├── feedback_repository.py
                ├── message_repository.py
                ├── ticket_comment_repository.py
                ├── ticket_repository.py
                └── user_repository.py
```

### File Responsibilities

| File | Responsibility |
|---|---|
| `user_repository.py` | User persistence, lookup, administrator-management concurrency |
| `auth_repository.py` | Credentials and refresh-token session persistence |
| `conversation_repository.py` | Conversation persistence, lifecycle, and message-sequence allocation |
| `message_repository.py` | Conversation-message persistence and history queries |
| `conversation_start_request_repository.py` | Idempotent conversation-start processing and leases |
| `escalation_repository.py` | Escalation persistence, lifecycle, and support queues |
| `ticket_repository.py` | Support-ticket persistence, lifecycle, relationships, and queues |
| `ticket_comment_repository.py` | Append-only ticket comments and visibility-aware history |
| `feedback_repository.py` | Customer feedback persistence, review lifecycle, and analytics queries |
| `errors.py` | Shared repository-level exception types |

---

# Architectural Role

The support repositories are **persistence adapters**, not application services.

```text
API / Application Service
          │
          ▼
    Domain / DTOs
          │
          ▼
   Support Repository
          │
          ▼
 SQLAlchemy ORM Model
          │
          ▼
     PostgreSQL
```

They are responsible for:

- constructing database queries;
- translating repository operations into SQLAlchemy operations;
- enforcing persistence-level validation;
- providing efficient relationship queries;
- supporting row-level locking where concurrency matters;
- implementing atomic database operations;
- returning persistence models to the application layer.

They are **not** responsible for:

- authentication policy;
- password hashing;
- JWT generation/verification;
- AI generation;
- authorization decisions;
- ticket business workflows;
- conversation orchestration;
- committing unrelated application transactions.

For example, `AuthRepository` explicitly leaves password hashing, token generation, and token verification to the application/security layer.

---

# Common Transaction Model

Most repositories follow the same pattern:

```text
Application Service
        │
        ▼
  Unit of Work
        │
        ├── UserRepository
        ├── ConversationRepository
        ├── MessageRepository
        ├── TicketRepository
        ├── EscalationRepository
        ├── FeedbackRepository
        └── ...
        │
        ▼
      commit()
```

Repositories generally:

```text
add()
  ↓
flush()
  ↓
caller-controlled commit
```

They do not independently commit application transactions.

For example, `ConversationRepository` explicitly states that transaction commits are outside its responsibility.

This allows several related mutations to remain atomic:

```text
Conversation mutation
       +
    Message
       +
   Escalation
       +
   Audit event
       │
       ▼
single Unit of Work
       │
       ▼
     commit
```

---

# 1. `user_repository.py`

## `UserRepository`

`UserRepository` provides persistence operations for support users.

It handles:

- user lookup by ID;
- lookup by external identity;
- user creation;
- row-level locking;
- active-administrator counting;
- administrator-management concurrency.



### Administrator Concurrency

The repository uses a PostgreSQL **transaction-level advisory lock** to serialize administrator-management operations.

```text
Admin mutation
      │
      ▼
pg_advisory_xact_lock(...)
      │
      ▼
inspect active admins
      │
      ▼
perform mutation
      │
      ▼
commit / rollback
      │
      ▼
lock released
```

This is particularly important when preventing concurrent operations from leaving the system without an active administrator.

The repository therefore provides a database-level concurrency primitive for a security-sensitive invariant.

---

# 2. `auth_repository.py`

## `AuthRepository`

`AuthRepository` handles persistence for:

```text
UserCredentialModel
AuthSessionModel
UserModel
```

Its responsibilities are intentionally limited to persistence of:

- local credentials;
- refresh-token sessions;
- active-session queries;
- session revocation.



### Credential Queries

Credentials can be retrieved by:

```text
user_id
email_normalized
```

and optionally locked using:

```python
with_for_update()
```



### Refresh Sessions

Sessions can be located by:

```text
session_id
refresh_token_hash
```

and optionally locked for mutation.

### Active Sessions

The repository can retrieve sessions that are simultaneously:

```text
revoked_at IS NULL
AND
expires_at > now
```

with newest sessions returned first.

The repository never receives a plaintext refresh token; application/security services are responsible for token handling.

---

# 3. `conversation_repository.py`

## `ConversationRepository`

This repository owns persistence for the **conversation aggregate**.

Its responsibilities include:

- conversation creation;
- conversation retrieval;
- row locking;
- customer conversation listing;
- recent conversation queries;
- conversation counts;
- message sequence allocation;
- title assignment;
- lifecycle transitions.



### Conversation Locking

```text
get_by_id_for_update()
        │
        ▼
PostgreSQL FOR UPDATE
        │
        ▼
safe conversation mutation
```

This allows lifecycle changes to be serialized.

### Message Sequence Allocation

One of the most important operations is:

```text
allocate_message_sequence()
```

The repository atomically increments the conversation's sequence counter and returns the allocated number.

```text
Conversation
    │
    └── next_message_sequence
              │
              ▼
       atomic UPDATE ... RETURNING
              │
              ▼
        allocated sequence
```

PostgreSQL serializes concurrent updates to the same conversation row while allowing independent conversations to proceed concurrently.

This is why sequence allocation belongs here rather than inside `MessageRepository`.

### Atomic Title Assignment

`set_title_if_absent()` implements compare-and-set semantics:

```text
conversation.title IS NULL
        │
        ▼
set generated title
```

This prevents retries or concurrent title generators from overwriting an existing title.

### Lifecycle

The repository exposes persistence-level lifecycle helpers for:

```text
resolved
escalated
closed
```

with appropriate timestamp handling.

---

# 4. `message_repository.py`

## `MessageRepository`

`MessageRepository` manages persisted conversation messages.

It is deliberately narrower than `ConversationRepository`.

```text
ConversationRepository
    └── owns message sequence allocation

MessageRepository
    └── owns message persistence/history
```

The repository explicitly does not allocate sequence numbers, load conversations, generate AI responses, or apply business logic.

### Message History

Messages can be retrieved:

- by message ID;
- by conversation;
- as recent conversation history;
- before a specified message sequence.



### LLM Context Support

`get_recent_by_conversation()` retrieves the most recent messages efficiently and then returns them in chronological order.

```text
Database query:
newest → oldest

Returned:
oldest → newest
```

This makes it directly useful for constructing bounded conversation context for an LLM.

### Trigger-Aware Context

`get_recent_before_sequence()` is designed for processing a customer message that has already been committed.

The triggering message itself is excluded so it does not appear twice:

```text
customer_message
       +
conversation_context
```



---

# 5. `conversation_start_request_repository.py`

## `ConversationStartRequestRepository`

This repository implements the persistence side of **idempotent conversation-start processing**.

Its design addresses concurrent/retried requests:

```text
Client request
      │
      ▼
idempotency key
      │
      ▼
hashed key
      │
      ▼
ConversationStartRequest
      │
      ▼
processing lease
      │
      ▼
AI execution
      │
      ▼
completed / failed
```

The raw idempotency key is deliberately never stored by this repository.

### Idempotency Lookup

Requests can be located using:

```text
customer_id
idempotency_key_hash
```

with an optional row lock.

### Processing Leases

`acquire_processing_lease()` atomically claims:

```text
accepted
```

requests or reclaims expired processing requests.

It prevents another processor from taking over an active lease.

Conceptually:

```text
accepted
   │
   ▼
processing
   │
   ├── active lease → another worker owns it
   │
   └── expired lease → can be reclaimed
```

### Token Ownership

Terminal completion requires the same processing token that acquired the lease.

```text
Worker A
   │
   ├── token A
   │
   ▼
processing
   │
   ▼
finish(token A) ──► success


Worker B
   │
   └── token B ──X cannot complete A's work
```

The final update requires:

```text
id = request_id
AND
status = processing
AND
processing_token = supplied token
```

before transitioning to `completed` or `failed`.

This prevents stale workers from completing a newer processor's request.

---

# 6. `escalation_repository.py`

## `EscalationRepository`

`EscalationRepository` persists support escalations and provides the query primitives needed by escalation workflows and support queues.

Supported states include:

```text
open
in_review
resolved
dismissed
```

and priorities:

```text
low
normal
high
urgent
```



### Lifecycle Locking

`get_by_id_for_update()` provides row-level locking for lifecycle transitions such as:

```text
open → in_review
open → resolved
in_review → resolved
open → dismissed
```



### Provenance Queries

Escalations can be found through:

```text
AI run
triggering message
conversation
```

This allows the application layer to connect an escalation back to the AI execution or customer interaction that caused it.

### Idempotent Escalation Detection

`get_active_for_ai_run()` retrieves the active escalation associated with an AI run.

This supports retry-safe behavior when multiple orchestration callbacks report the same escalation condition.

### Support Queues

The repository provides:

```text
list_recent()
list_active()
```

with filtering and pagination.

The active queue orders:

```text
urgent
high
normal
low
```

and prioritizes older records within the same priority.

---

# 7. `ticket_repository.py`

## `TicketRepository`

`TicketRepository` is the primary persistence adapter for support tickets.

It handles:

- ticket creation;
- lookup by UUID;
- lookup by human-facing ticket number;
- lookup by escalation;
- conversation-related queries;
- row-level locking;
- support/dashboard queues.



### Ticket Lifecycle

Supported ticket states include:

```text
open
in_progress
waiting_for_customer
resolved
closed
reopened
```

Active states are:

```text
open
in_progress
waiting_for_customer
reopened
```

Priorities include:

```text
low
normal
high
urgent
```

and ticket categories include domains such as:

```text
billing
refund
order
account
technical
security
product
general
other
```



### Row-Level Locking

Ticket lifecycle mutations should use:

```text
get_by_id_for_update()
```

before operations such as:

- assignment;
- priority changes;
- category changes;
- status transitions.



### Business Relationships

Tickets can be retrieved through relationships such as:

```text
conversation
escalation
ticket number
```

The escalation lookup is backed by a database uniqueness guarantee, allowing the repository to treat the relationship as at-most-one.

---

# 8. `ticket_comment_repository.py`

## `TicketCommentRepository`

This repository handles **append-only ticket comments**.

Its responsibilities are:

- persisting comments;
- retrieving comments;
- returning ticket comment history;
- applying visibility filters;
- querying recent operational comments.



### Comment Visibility

Two visibility levels are supported:

```text
customer
internal
```

and supported author roles include:

```text
customer
support_agent
admin
system
```



### Customer-Safe History

By default:

```text
include_internal = false
```

so only customer-visible comments are returned.

```text
Ticket comments
      │
      ├── customer ──► customer history
      │
      └── internal ──► support/admin only
```

The repository itself does **not** perform authorization; trusted application services must control whether internal comments may be requested.

### Operational Queries

Recent comments can be filtered by:

```text
visibility
author_role
```

with bounded pagination.

---

# 9. `feedback_repository.py`

## `FeedbackRepository`

`FeedbackRepository` manages customer feedback associated with assistant responses and AI runs.

Supported feedback states are:

```text
pending
reviewed
actioned
dismissed
```



### Main Responsibilities

The repository supports:

- feedback persistence;
- lookup by ID;
- row locking before review mutations;
- lookup by response message;
- lookup by AI run;
- bulk lookup for response messages;
- customer/conversation history;
- dashboard filtering.



### Idempotent Feedback

Feedback can be retrieved by:

```text
response_message_id
```

The database uniqueness constraint allows the application to treat this as an at-most-one relationship and supports idempotent feedback submission.

### Bulk Enrichment

`list_by_response_message_ids()` supports bounded bulk retrieval.

This is important when enriching conversation history without performing one database query per assistant response:

```text
100 response messages
        │
        ▼
1 bulk feedback query
```

rather than:

```text
100 response messages
        │
        ▼
100 individual queries
```



### Dashboard Queries

`list_recent()` supports filters such as:

```text
status
rating
helpful
reason_code
customer_id
conversation_id
created_from
created_to
```

and returns newest records first.

Aggregate analytics are intentionally separate from this paginated repository query.

---

# 10. `errors.py`

## Repository Error Contract

`errors.py` provides the shared base repository error hierarchy.

The root type is:

```python
RepositoryError
```

with specialized persistence errors such as:

```python
ConversationNotFoundError
```



This gives application services a stable error boundary instead of requiring them to interpret low-level SQLAlchemy exceptions.

Conceptually:

```text
RepositoryError
      │
      ├── ConversationNotFoundError
      │
      └── future repository-specific errors
```

Repository errors should represent **persistence-level conditions**, while application services remain responsible for translating them into use-case-specific errors when necessary.

---

# Cross-Repository Relationships

These repositories are intentionally interconnected through the support domain.

```text
                         User
                          │
             ┌────────────┼────────────┐
             │            │            │
             ▼            ▼            ▼
        AuthSession   Conversation   Feedback
                          │
                          ▼
                       Messages
                          │
             ┌────────────┴────────────┐
             │                         │
             ▼                         ▼
        Escalation                  Ticket
                                       │
                                       ▼
                                Ticket Comments
```

AI provenance adds another relationship:

```text
AI Run
  │
  ├── Conversation
  │
  ├── Escalation
  │
  └── Feedback
```

This allows application services and operational dashboards to navigate from customer interactions to support actions and AI outcomes.

---

# Concurrency Strategy

Concurrency is handled explicitly where support state is mutable.

## Row Locks

Repositories expose `FOR UPDATE` operations for lifecycle-critical entities:

```text
User
Conversation
Escalation
Ticket
Feedback
Authentication session
Credentials
```

Example:

```text
get_by_id_for_update()
        │
        ▼
database row lock
        │
        ▼
validate current state
        │
        ▼
      mutate
        │
        ▼
      commit
```

## Atomic SQL Operations

Some operations are better represented as atomic SQL updates than read-modify-write sequences.

Examples include:

```text
Conversation message sequence allocation
Conversation title compare-and-set
Conversation-start processing lease acquisition
Conversation-start terminal completion
Administrator advisory locking
```

These operations reduce race conditions by letting PostgreSQL enforce atomicity.

---

# Pagination and Query Discipline

The repositories provide bounded query APIs for operational screens and application use cases.

Common patterns include:

```text
limit
offset
```

with explicit validation.

Several repositories use a maximum page size of `500`, while some domain-specific queries use smaller defaults or limits.

The general principle is:

```text
Application query
      │
      ▼
validated bounded query
      │
      ▼
PostgreSQL
```

Repositories should not become unbounded data-export interfaces.

---

# Deterministic Ordering

Historical and operational queries generally use timestamp ordering combined with an ID as a deterministic tie-breaker.

For example:

```text
created_at DESC
id DESC
```

or:

```text
created_at ASC
id ASC
```

This prevents records with identical timestamps from appearing in unstable ordering across repeated queries.

Conversation messages are an important exception: their canonical ordering is based on:

```text
sequence_number
```

because message sequence belongs to the conversation aggregate.

---

# Validation Philosophy

The repositories perform persistence-boundary validation such as:

- UUID type checks;
- model type checks;
- pagination validation;
- enum/value validation;
- timezone-aware datetime validation;
- bounded text validation;
- boolean validation;
- state/relationship checks.

For example, feedback ratings are explicitly constrained to:

```text
1–5
```

and pagination is bounded to prevent invalid or excessive requests.

This does **not** replace application-level validation.

Instead:

```text
Application validation
        │
        ▼
Repository validation
        │
        ▼
Database constraints
```

provides defense at multiple boundaries.

---

# Authorization Boundary

Repositories generally **do not authorize callers**.

This is intentional.

For example, `TicketCommentRepository.list_recent()` explicitly states that it does not perform authorization and is intended for trusted support/admin application services.

Similarly, the repository can expose internal ticket comments when explicitly requested; the application layer must ensure that an unauthorized customer cannot request them.

The intended architecture is:

```text
Caller
  │
  ▼
Authentication
  │
  ▼
Authorization
  │
  ▼
Application Service
  │
  ▼
Repository
  │
  ▼
Database
```

---

# What These Repositories Do Not Do

The support repository layer intentionally does **not** contain:

### Authentication logic

No:

- password hashing;
- password verification;
- JWT signing;
- JWT verification;
- token parsing;
- authentication policy.

`AuthRepository` only persists and retrieves authentication-related records.

### AI logic

No:

- prompt construction;
- model invocation;
- response generation;
- intent classification;
- retrieval;
- LLM decisions.

### Business orchestration

No:

- ticket workflow orchestration;
- escalation policy;
- customer authorization;
- notification dispatch;
- conversation response generation.

The repositories provide the primitives required by those higher layers.

---

# Typical Application Flow

A support request may cross several repositories inside one Unit of Work:

```text
Incoming customer request
          │
          ▼
Application Service
          │
          ├── ConversationRepository
          │       └── load/lock conversation
          │
          ├── MessageRepository
          │       └── load conversation history
          │
          ├── AI subsystem
          │       └── generate response
          │
          ├── MessageRepository
          │       └── persist assistant response
          │
          ├── FeedbackRepository
          │       └── later feedback
          │
          ├── EscalationRepository
          │       └── if human support required
          │
          └── TicketRepository
                  └── if escalation becomes a ticket
```

For a ticket workflow:

```text
Escalation
    │
    ▼
Ticket
    │
    ├── Ticket Comment
    ├── Assignment
    ├── Status changes
    └── Resolution
```

The application layer coordinates these operations; the repositories provide the database primitives.

---

# Design Principles

## 1. Unit-of-Work ownership

Repositories do not independently commit application transactions.

## 2. Explicit concurrency

Race-sensitive operations use row locks, atomic SQL updates, or PostgreSQL advisory locks.

## 3. Domain-oriented persistence

Methods describe support concepts such as:

```text
allocate_message_sequence()
acquire_processing_lease()
mark_resolved()
get_active_for_ai_run()
```

rather than exposing generic SQL operations.

## 4. Bounded queries

History and dashboard methods use explicit limits and pagination.

## 5. Deterministic results

Queries use stable ordering, often combining timestamps with IDs.

## 6. Authorization stays above persistence

Repositories provide data access; trusted application services decide who may access which data.

## 7. Sensitive data stays appropriately scoped

Authentication persistence stores hashes/credentials rather than requiring application services to expose plaintext secrets to repository consumers.

## 8. PostgreSQL is used deliberately

Concurrency-sensitive behavior takes advantage of PostgreSQL capabilities such as:

```text
FOR UPDATE
RETURNING
transaction-level advisory locks
atomic UPDATE expressions
```

rather than implementing concurrency entirely in Python.

---

# Overall Architecture

The ten files collectively form the persistence foundation for the support subsystem:

```text
                         SUPPORT SYSTEM
                              │
          ┌───────────────────┼────────────────────┐
          │                   │                    │
          ▼                   ▼                    ▼
   Authentication       Conversations           Support Ops
          │                   │                     │
          ▼                   ▼             ┌───────┴────────┐
   AuthRepository       Conversation        │                │
   UserRepository       Repository          ▼                ▼
          │                   │        Escalation         Ticket
          │                   ▼        Repository        Repository
          │             MessageRepo.         │                │
          │                   │              │                ▼
          │                   │              │          TicketComment
          │                   │              │          Repository
          │                   │              │
          └───────────────────┼──────────────┘
                              │
                              ▼
                         Feedback
                        Repository
                              │
                              ▼
                       PostgreSQL / UoW
```

Alongside the normal support workflow, conversation-start idempotency is handled independently:

```text
Conversation Start
        │
        ▼
ConversationStartRequestRepository
        │
        ├── idempotency lookup
        ├── processing lease
        ├── token ownership
        └── terminal completion
```

---

# Summary

`packages/database/repositories/support/` is the **persistence boundary for the customer-support subsystem**.

Its responsibilities can be summarized as:

```text
Users & Authentication
        │
        ├── UserRepository
        └── AuthRepository

Conversations
        │
        ├── ConversationRepository
        ├── MessageRepository
        └── ConversationStartRequestRepository

Human Support
        │
        ├── EscalationRepository
        ├── TicketRepository
        └── TicketCommentRepository

Customer Feedback
        │
        └── FeedbackRepository

Shared Persistence Errors
        │
        └── errors.py
```

The core architectural rule is:

> **Application services own business workflows and authorization; support repositories own efficient, validated, concurrency-aware persistence operations; the Unit of Work owns transaction boundaries.**

This keeps the support subsystem modular while still allowing PostgreSQL to enforce the concurrency and integrity guarantees required by authentication, conversations, escalations, tickets, and feedback.