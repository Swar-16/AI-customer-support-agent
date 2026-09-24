# Support Database Models

## Overview

The `packages/database/models/support/` package contains the SQLAlchemy ORM models for the application's **core customer-support domain**.

These models persist the entities involved in:

* user identity and roles;
* local authentication;
* authentication sessions and refresh-token rotation;
* customer conversations;
* conversation messages;
* idempotent conversation creation;
* human-review escalations;
* support tickets;
* ticket comments;
* customer feedback.

All models belong to the PostgreSQL `support` schema and form the primary persistence layer for the application's customer-support workflows.

---

## Package Structure

```text
AI-customer-support-agent/
└── packages/
    └── database/
        └── models/
            └── support/
                ├── user.py
                ├── user_credential.py
                ├── auth_session.py
                ├── conversation.py
                ├── conversation_start_request.py
                ├── message.py
                ├── escalation.py
                ├── ticket.py
                ├── ticket_comment.py
                └── feedback.py
```

The models can be grouped into five closely related areas:

```text
                    SUPPORT DOMAIN
                          │
        ┌─────────────────┼──────────────────┐
        │                 │                  │
        ▼                 ▼                  ▼
     Identity          Conversation        Support Work
        │                 │                  │
        ├─ User           ├─ Conversation    ├─ Escalation
        ├─ Credential     ├─ Message         ├─ Ticket
        └─ Auth Session   └─ Start Request   └─ Comment
                                               │
                                               ▼
                                           Feedback
```

---

# 1. User and Authentication Models

## `user.py`

### `UserModel`

`UserModel` represents the **stable identity of a person or system actor** within the support platform.

It stores:

```text
id
external_id
email
display_name
role
status
created_at
updated_at
```

The model uses UUIDv7 identifiers and belongs to the `support.users` table.

### Roles

The database restricts roles to:

```text
customer
support_agent
admin
system
```

### Statuses

A user can be:

```text
active
disabled
deleted
```

These values are enforced at the database level.

`external_id` is unique when present, allowing integration with an external identity/customer system.

---

## `user_credential.py`

### `UserCredentialModel`

`UserCredentialModel` contains **local authentication credentials** for a user.

It is intentionally separate from `UserModel`.

A user may exist without local credentials, which supports:

* seeded users;
* system users;
* externally authenticated users;
* integration-test users.

The primary key is also the user's ID:

```text
support.users.id
        │
        ▼
support.user_credentials.user_id
```

This creates an effectively one-to-one user/credential relationship.

### Stored authentication information

The model stores:

```text
email_normalized
password_hash
failed_login_attempts
locked_until
password_changed_at
created_at
updated_at
```

Passwords themselves are never persisted; `password_hash` contains the Argon2id encoded password hash.

The database also guarantees:

```text
email_normalized = lower(trim(email_normalized))
failed_login_attempts >= 0
```

---

## `auth_session.py`

### `AuthSessionModel`

`AuthSessionModel` represents a **persisted refresh-token authentication session**.

The raw refresh token is deliberately never stored. Only its cryptographic hash is persisted.

The model contains concepts such as:

```text
user_id
family_id
refresh_token_hash
replaced_by_session_id
client_ip
user_agent
created_at
expires_at
last_used_at
revoked_at
revocation_reason
```

Sessions are associated with users and can be grouped into a `family_id` for refresh-token rotation and family-wide revocation.

### Rotation model

Refresh rotation forms a chain:

```text
Session A
   │
   ├── revoked
   │
   └── replaced_by_session_id
              │
              ▼
          Session B
              │
              ▼
          Session C
```

The database requires replacement relationships to originate from revoked sessions.

This is the persistence foundation used by the authentication services for refresh-token rotation and session revocation.

---

# 2. Conversation Models

## `conversation.py`

### `ConversationModel`

A conversation represents the **customer-support interaction container**.

It belongs to a user through:

```text
User
  │
  └── Conversation
```

The model stores:

```text
id
user_id
status
channel
title
next_message_sequence
created_at
updated_at
resolved_at
closed_at
```

### Conversation statuses

The database permits:

```text
open
waiting_for_customer
waiting_for_agent
escalated
resolved
closed
```

### Channels

Supported channels are:

```text
web
mobile
email
api
```

### Message sequencing

`next_message_sequence` provides a durable mechanism for assigning ordered message positions within a conversation.

---

## `message.py`

### `MessageModel`

`MessageModel` represents an individual message inside a conversation.

The hierarchy is:

```text
User
  │
  ▼
Conversation
  │
  ├── Message 0
  ├── Message 1
  ├── Message 2
  └── ...
```

Each message belongs to exactly one conversation and is deleted with that conversation.

### Message roles

The database allows:

```text
customer
assistant
support_agent
system
tool
```

### Ordering

Every message has:

```text
sequence_number
```

and `(conversation_id, sequence_number)` is unique.

Therefore, one conversation cannot contain two messages with the same sequence number.

The model also stores arbitrary JSONB metadata alongside:

```text
content
created_at
```

The Python attribute is `metadata_` because `metadata` is reserved by SQLAlchemy, while the actual database column remains `metadata`.

---

# 3. Conversation Start / Idempotency

## `conversation_start_request.py`

### `ConversationStartRequestModel`

This model represents a **durable idempotency and recovery record for starting a conversation**.

It exists because starting a conversation is more than simply inserting a conversation row.

The operation may involve:

```text
Conversation
+
First Customer Message
+
AI Processing
```

The model ensures the initial persistence boundary can be safely retried.

The raw API idempotency key is not stored. Instead, a SHA-256 digest scoped to the authenticated customer is persisted.

### Idempotency

The database enforces uniqueness for:

```text
(customer_id, idempotency_key_hash)
```

This prevents duplicate conversation-start operations for the same customer and key.

### Lifecycle

The request can move through:

```text
accepted
    │
    ▼
processing
    │
    ├──► completed
    │
    └──► failed
```

The database contains explicit constraints connecting status with processing tokens, expiration information, completion timestamps, and response snapshots.

This makes conversation startup recoverable and prevents inconsistent partial states.

---

# 4. Human-Review Escalation

## `escalation.py`

### `EscalationModel`

`EscalationModel` represents a **persistent request for human review**.

An escalation is a support-domain workflow entity, not merely AI telemetry. It can originate from:

```text
AI decision
response guardrail
system policy
manual/support intervention
```

### Escalation relationship

An escalation belongs to a conversation:

```text
Conversation
    │
    └── Escalation
```

It may optionally reference an AI run:

```text
Escalation
    │
    └── ai_run_id → ai.runs
```

The AI run is nullable because not every escalation originates from AI execution.

### Sources

Allowed escalation sources are:

```text
decision
guardrail
system
manual
```

### Priority

```text
low
normal
high
urgent
```

### Status

```text
open
in_review
resolved
dismissed
```

The database enforces consistency between status and `resolved_at`.

### Ticket separation

An escalation does **not** own a ticket directly.

Conceptually:

```text
  Escalation
     │
     │ may result in
     ▼
   Ticket
```

This keeps the reason for human review separate from the durable support work item.

The model also ensures that an AI run can correspond to at most one escalation through a partial unique index.

---

# 5. Support Tickets

## `ticket.py`

### `TicketModel`

A ticket represents a **durable support work item** owned and managed by support staff.

The model explicitly distinguishes a ticket from an escalation:

```text
Escalation
    = why human review became necessary

Ticket
    = durable work item used to perform/support that review
```

A ticket may originate from:

```text
customer
escalation
agent
system
```

### Ticket classification

Tickets have controlled:

```text
source
category
priority
status
```

Categories include:

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

Priorities include:

```text
low
normal
high
urgent
```

Statuses include:

```text
open
in_progress
waiting_for_customer
resolved
closed
reopened
```

### Lifecycle integrity

The model enforces relationships between status and lifecycle timestamps.

For example:

```text
resolved / closed
    ├── resolved_at must exist
    └── resolution_summary must exist

open / in_progress / waiting...
    ├── resolved_at must be NULL
    └── resolution_summary must be NULL
```

Similarly, `closed` requires `closed_at`, while active states cannot contain a close timestamp.

Assignment timestamps are also validated against the ticket's creation time.

---

# 6. Ticket Comments

## `ticket_comment.py`

### `TicketCommentModel`

Ticket comments provide the **append-only communication/history layer for support tickets**.

A comment belongs to a ticket:

```text
Ticket
  │
  ├── Comment
  ├── Comment
  └── Comment
```

Comments are intentionally append-only for the MVP. Corrections are represented by additional comments rather than mutating historical comments.

### Visibility

There are two visibility levels:

```text
customer
internal
```

`customer` comments are visible to customers and support staff.

`internal` comments are visible only to support personnel.

Customer-authored comments cannot be internal notes.

### Authors

Allowed author roles include:

```text
customer
support_agent
admin
system
```

The author itself may become unavailable without invalidating the historical comment because `author_id` uses `ON DELETE SET NULL`.

This is appropriate for historical support records.

---

# 7. Customer Feedback

## `feedback.py`

### `FeedbackModel`

`FeedbackModel` stores customer feedback for an **AI-generated assistant response**.

It intentionally connects three dimensions:

```text
Response Message
       │
       ├── what the customer evaluated
       │
       ▼
AI Run
       │
       ├── intent
       ├── decision
       ├── retrieval
       ├── generation
       ├── guardrails
       ├── latency
       └── token telemetry
```

Conversation and customer IDs additionally support ownership validation and dashboard aggregation.

### Rating

Ratings must be:

```text
1 ≤ rating ≤ 5
```

### Review lifecycle

Feedback can be:

```text
pending
reviewed
actioned
dismissed
```

The database requires reviewed/actioned/dismissed feedback to contain review information while pending feedback cannot contain review metadata.

### One feedback record per response

The model enforces:

```text
UNIQUE(response_message_id)
```

Therefore:

```text
One assistant response
        │
        └── at most one FeedbackModel
```

A later application service can update that record rather than creating duplicate feedback entries.

The model also indexes feedback by customer, conversation, AI run, status, rating, helpfulness, and reason codes for operational dashboards and analysis.

---

# Complete Domain Relationship

The ten models form a connected support-domain persistence graph:

```text
                         ┌──────────────────┐
                         │      User        │
                         └───────┬──────────┘
                                 │
              ┌──────────────────┼─────────────────┐
              │                  │                 │
              ▼                  ▼                 ▼
       UserCredential       AuthSession       Conversation
                                                    │
                         ┌──────────────────────────┼───────────────┐
                         │                          │               │
                         ▼                          ▼               ▼
                     Messages                Escalations       Start Requests
                         │                          │
                         │                          ▼
                         │                       Tickets
                         │                          │
                         │                          ▼
                         │                    Ticket Comments
                         │
                         ▼
                  Feedback
                         │
                         └──────────► AI Run
```

The actual foreign-key direction is intentionally more precise than this conceptual diagram, but this represents the business relationships between the models.

---

# Core Lifecycle

A typical customer interaction can be understood as:

```text
1. User exists
       │
       ▼
2. Authentication / session established
       │
       ▼
3. Conversation started
       │
       ▼
4. Customer message persisted
       │
       ▼
5. AI support pipeline executes
       │
       ├── response
       │
       ├── feedback
       │
       └── escalation if required
                   │
                   ▼
                Ticket
                   │
                   ▼
             Ticket Comments
```

This separates the conversational lifecycle from the support-work lifecycle.

---

# Security Model

The support models contain several deliberate security boundaries.

## Passwords

Raw passwords are never persisted.

```text
Password
   │
   ▼
Argon2id
   │
   ▼
password_hash
```

## Refresh Tokens

Raw refresh tokens are never persisted.

```text
Refresh Token
     │
     ▼
Cryptographic Hash
     │
     ▼
AuthSessionModel
```

## Idempotency Keys

Raw conversation-start idempotency keys are not persisted; a SHA-256 digest is used instead.

## Internal Ticket Comments

Customer-authored comments cannot be marked as internal.

---

# State Integrity

A major design characteristic of these models is that important business invariants are enforced **at the database layer**, not exclusively in Python.

Examples include:

```text
User
 ├── valid role
 └── valid status

Credential
 ├── normalized email
 ├── non-empty hash
 └── non-negative failed attempts

Session
 ├── expiration > creation
 ├── valid revocation state
 └── replacement requires revocation

Conversation
 ├── valid status
 ├── valid channel
 └── valid message sequence

Message
 └── unique sequence within conversation

Start Request
 ├── unique idempotency key per customer
 └── valid lifecycle state

Escalation
 ├── valid source
 ├── valid priority/status
 └── valid resolution state

Ticket
 ├── valid source/category/priority/status
 ├── valid assignment state
 └── valid resolution/closure state

Comment
 ├── valid author role
 ├── valid visibility
 └── customer visibility restriction

Feedback
 ├── rating 1–5
 ├── valid review state
 └── one feedback per response
```

This makes persistence itself a final line of defense against invalid domain state.

---

# UUIDv7 Identifiers

The support entities generally use PostgreSQL UUID columns with UUIDv7 server-side generation.

For example, users and conversations use:

```text
server_default = uuidv7()
```

This provides application-wide UUID identifiers while retaining an ordering characteristic useful for database indexes.

---

# Timestamp Strategy

The support models consistently use timezone-aware timestamps.

Typical fields include:

```text
created_at
updated_at
resolved_at
closed_at
expires_at
locked_until
revoked_at
last_used_at
```

Database defaults generally use:

```text
now()
```

with timezone-aware SQLAlchemy `DateTime` columns.

This allows the application to persist a consistent UTC-oriented timeline while performing presentation/localization at higher layers.

---

# JSONB Metadata

Several support entities support extensible metadata using PostgreSQL `JSONB`.

Examples include:

```text
Message.metadata
Ticket.metadata
TicketComment.metadata
Feedback.reason_codes / metadata
Conversation-start response snapshots
```

The Python ORM attribute is sometimes named `metadata_` because SQLAlchemy reserves `metadata` for its declarative metadata object.

For example, `MessageModel` explicitly maps Python `metadata_` to the database column `metadata`.

---

# Indexing Philosophy

Indexes primarily support the application's operational access patterns.

Common indexed dimensions include:

```text
user_id
conversation_id
created_at
status
priority
expires_at
family_id
ai_run_id
customer_id
ticket_id
```

This supports common workflows such as:

* finding a customer's conversations;
* loading conversation messages in order;
* finding active authentication sessions;
* recovering expired conversation-start operations;
* finding open escalations;
* managing ticket queues;
* retrieving ticket history;
* aggregating feedback;
* investigating AI-generated responses.

For example, authentication sessions include indexes for user history, session family, expiration, and active-user lookup.

---

# Persistence vs Application Logic

These models deliberately focus on **data representation and persistence invariants**.

They do not own higher-level workflows such as:

```text
login
logout
refresh-token rotation
conversation orchestration
AI generation
escalation decisions
ticket assignment
feedback review
```

Those behaviors belong to the application/domain services.

The ORM layer instead guarantees that when those services persist their results, the stored state satisfies the domain's structural constraints.

---

# Important Architectural Separations

## User vs Credential

```text
User
    = identity

Credential
    = local authentication mechanism
```

A user can therefore exist without a local password.

---

## Conversation vs Ticket

```text
Conversation
    = customer interaction

Ticket
    = support work item
```

A conversation does not automatically become a ticket.

---

## Escalation vs Ticket

```text
Escalation
    = reason human review became necessary

Ticket
    = durable work item for resolving the issue
```

This separation allows an escalation to remain a historical event/reason while support operations manage the resulting ticket independently.

---

## Message vs Feedback

```text
Message
    = conversational content

Feedback
    = customer's evaluation of an assistant response
```

Feedback additionally connects to the AI run so the system can correlate customer satisfaction with the complete AI execution path.

---

# Design Principles

### 1. Database-enforced invariants

Important business-state constraints are represented as PostgreSQL `CHECK`, `UNIQUE`, foreign-key, and partial-index constraints.

### 2. Security-sensitive data is represented safely

Passwords and refresh tokens are never stored in raw form.

### 3. Historical records remain meaningful

Ticket comments are append-only, and authentication/session relationships preserve rotation history.

### 4. Workflow state is explicit

Conversation, escalation, ticket, feedback, and conversation-start lifecycles are represented using controlled states.

### 5. Idempotency is durable

Conversation startup has a dedicated persistence model rather than relying solely on in-memory request handling.

### 6. AI telemetry remains connected to support workflows

Escalations and feedback can reference AI execution data without making the support models themselves responsible for AI orchestration.

### 7. Identity and authentication remain separate

User identity is not coupled to the existence of local credentials.

### 8. Operational queries are first-class

Indexes are designed around real support, authentication, conversation, escalation, ticket, and feedback access patterns.

---

# Responsibility Matrix

| File                            | Model                           | Primary Responsibility                      |
| ------------------------------- | ------------------------------- | ------------------------------------------- |
| `user.py`                       | `UserModel`                     | User identity, role, and account lifecycle  |
| `user_credential.py`            | `UserCredentialModel`           | Local authentication credentials            |
| `auth_session.py`               | `AuthSessionModel`              | Refresh-token sessions and rotation history |
| `conversation.py`               | `ConversationModel`             | Customer-support conversation lifecycle     |
| `conversation_start_request.py` | `ConversationStartRequestModel` | Idempotent/recoverable conversation startup |
| `message.py`                    | `MessageModel`                  | Ordered conversation messages               |
| `escalation.py`                 | `EscalationModel`               | Persistent human-review requests            |
| `ticket.py`                     | `TicketModel`                   | Durable support work items                  |
| `ticket_comment.py`             | `TicketCommentModel`            | Append-only ticket communication/history    |
| `feedback.py`                   | `FeedbackModel`                 | Customer evaluation of AI responses         |

---

# End-to-End Mental Model

The easiest way to understand this package is:

```text
                         USER
                          │
             ┌────────────┼─────────────┐
             │            │             │
             ▼            ▼             ▼
        Credentials   Auth Sessions  Conversations
                                         │
                                         ▼
                                      Messages
                                         │
                                         ├───────────────┐
                                         │               │
                                         ▼               ▼
                                     AI Response      Escalation
                                         │               │
                                         ▼               ▼
                                      Feedback         Ticket
                                                         │
                                                         ▼
                                                      Comments
```

The package therefore represents the **persistent operational backbone of the support system**.

At the center is the customer conversation. Authentication establishes who is interacting with the system; messages capture the interaction; AI processing can produce feedback and escalations; escalations can become support tickets; and tickets accumulate durable human-support history through comments.

The models intentionally preserve these concepts as separate entities so that each lifecycle can evolve independently while remaining connected through explicit foreign keys and database-enforced invariants.
