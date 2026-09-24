# Escalations Application Layer

## Overview

The `packages/application/escalations/` package owns the **application-level lifecycle of support escalations** in the AI customer-support system.

An escalation represents a transition from fully automated support toward **human support involvement**. The package provides the application commands and queries required to:

* create persistent escalations;
* validate escalation creation requests;
* prevent duplicate AI-generated escalations;
* detect idempotency conflicts;
* retrieve individual escalations;
* retrieve escalation history for a conversation;
* retrieve the active/recent escalation queue;
* update an escalation through its controlled lifecycle;
* enforce support-agent/admin authorization for lifecycle updates;
* send customer-visible notifications when escalation state changes;
* record escalation creation and update audit events;
* maintain trace, conversation, AI-run, and message correlations;
* expose detached application results instead of ORM entities.

The package deliberately separates **the decision to escalate** from **the persistence and lifecycle management of an escalation**.

The AI/orchestration layer decides that human intervention is required. The escalation application layer turns that decision into durable application state.

```text
Customer Message
       │
       ▼
AI Support Pipeline
       │
       ├── ANSWER
       ├── RETRIEVE
       ├── CLARIFY
       │
       └── ESCALATE
              │
              ▼
      CreateEscalation
              │
              ▼
       Persistent Escalation
              │
       ┌──────┴─────────┐
       │                │
       ▼                ▼
   Support Queue    Audit Event
       │
       ▼
   Human Review
       │
       ▼
 UpdateEscalation
       │
       ├── in_review
       ├── resolved
       └── dismissed
              │
              ▼
     Customer Notification
```

---

# Package Location

```text
AI-customer-support-agent/
└── packages/
    └── application/
        └── escalations/
            ├── __init__.py
            ├── create_escalation.py
            ├── query_escalations.py
            ├── update_escalation.py
            └── README.md
```

The package is an **application-layer boundary**. It coordinates repositories, Unit of Work, audit recording, authorization, and customer notifications without owning the underlying database models.

---

# Responsibilities

The package can be divided into three major responsibilities.

```text
Escalations Application
│
├── Creation
│   └── create_escalation.py
│
├── Query / Read
│   └── query_escalations.py
│
└── Lifecycle Mutation
    └── update_escalation.py
```

The responsibilities are intentionally separated.

| Area          | Responsibility                                      |
| ------------- | --------------------------------------------------- |
| Creation      | Establish a new escalation from a trusted workflow  |
| Query         | Retrieve escalation state/history/queue             |
| Update        | Move an escalation through its controlled lifecycle |
| Audit         | Record creation and lifecycle changes               |
| Notification  | Inform customers about relevant status changes      |
| Authorization | Restrict manual lifecycle changes                   |
| Idempotency   | Prevent duplicate AI-run escalations                |
| Validation    | Protect application and persistence contracts       |

---

# Architectural Boundary

The escalation application layer sits between upstream workflows and persistence.

```text
                 AI / Application Workflows
                           │
                           ▼
              ┌────────────────────────┐
              │ Escalation Application  │
              │        Layer            │
              └───────────┬────────────┘
                          │
          ┌───────────────┼────────────────┐
          │               │                │
          ▼               ▼                ▼
    Escalation       Audit Recorder   Notification Writer
    Repository             │                │
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                    Unit of Work
                           │
                           ▼
                       Database
```

The package does **not** decide whether a customer should be escalated.

Instead:

```text
Decision Layer
     │
     │ "Escalation required"
     ▼
Escalation Application Layer
     │
     │ persist / query / transition
     ▼
Escalation Repository
```

The creation command explicitly describes an escalation that has already been requested by orchestration or another trusted workflow; it does not make the escalation decision itself.

---

# Files

| File                   | Responsibility                                                                                                    |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `create_escalation.py` | Validates and persists new escalations, including AI-run idempotency and creation audit events                    |
| `query_escalations.py` | Retrieves individual escalations, conversation history, and dashboard/recent escalation queues                    |
| `update_escalation.py` | Performs authorized lifecycle transitions with row locking, notifications, audit events, and transaction handling |
| `README.md`            | Documents the complete escalation application layer                                                               |

---

# Escalation Lifecycle

The lifecycle is intentionally constrained.

```text
             ┌──────────────┐
             │     open     │
             └──────┬───────┘
                    │
          ┌─────────┼─────────┐
          │         │         │
          ▼         ▼         ▼
      in_review  resolved  dismissed
          │
          ├───────────────┐
          ▼               ▼
       resolved        dismissed
```

Valid states are:

```text
open
in_review
resolved
dismissed
```

The lifecycle transition rules are:

```text
open
 ├──> in_review
 ├──> resolved
 └──> dismissed

in_review
 ├──> resolved
 └──> dismissed

resolved
 └──> terminal

dismissed
 └──> terminal
```

Terminal states cannot transition further.

The update implementation explicitly defines both the valid status set and the allowed transition graph.

---

# Escalation Sources

Escalations can originate from different trusted sources:

```text
decision
guardrail
system
manual
```

These represent the source of the escalation request, not necessarily the actor who later resolves it.

For example:

```text
AI Decision
    │
    ▼
source = "decision"
```

or:

```text
Guardrail
    │
    ▼
source = "guardrail"
```

Manual/system escalation requests can also be created without an AI run.

The creation command validates the source against the supported set.

---

# Escalation Priorities

Supported priorities are:

```text
low
normal
high
urgent
```

Priority is stored independently from lifecycle status.

For example:

```text
status   = open
priority = urgent
```

means the escalation remains open but requires urgent handling.

The distinction allows operational queues to prioritize active escalations without changing their lifecycle semantics.

---

# Creation

## `create_escalation.py`

`CreateEscalation` is responsible for turning a trusted escalation request into persistent application state.

Its command contains:

```text
conversation_id
source
reason_code
trace_id
ai_run_id
trigger_message_id
reason_summary
priority
handoff_summary
metadata
```

The command is immutable and validated before persistence.

---

# Creation Contract

The creation command validates:

### Required identifiers

```text
conversation_id → UUID
```

Optional identifiers:

```text
trace_id
ai_run_id
trigger_message_id
```

must also be valid UUIDs when supplied.

### Source

The source must be one of:

```text
decision
guardrail
system
manual
```

### Priority

The priority must be one of:

```text
low
normal
high
urgent
```

### Text fields

The application imposes explicit length limits:

```text
reason_code       ≤ 100
reason_summary    ≤ 2,000
handoff_summary   ≤ 5,000
```

### Metadata

Metadata is also bounded:

```text
maximum keys        = 100
maximum serialized  = 20,000 characters
```

These limits protect the application boundary from unrestricted payload growth.

---

# Creation Flow

Conceptually:

```text
CreateEscalationCommand
          │
          ▼
       Validate
          │
          ▼
   Open Unit of Work
          │
          ▼
   Validate repositories
          │
          ▼
  Check existing escalation
          │
       ┌──┴──┐
       │     │
     none   exists
       │     │
       ▼     ▼
    create  validate
       │     │
       │     └── return existing
       │
       ▼
      flush
       │
       ▼
   Audit event
       │
       ▼
     commit
       │
       ▼
CreateEscalationResult
```

---

# AI-Run Idempotency

AI-generated escalations are idempotent by `ai_run_id`.

When an AI run already has an active escalation, a retry should not create another active escalation.

The creation implementation therefore searches for an existing active escalation associated with the AI run.

The behavior is:

```text
First attempt
AI Run X
   │
   ▼
Create escalation
   │
   ▼
Escalation E1


Retry
AI Run X
   │
   ▼
Existing E1?
   │
   ▼
Return existing escalation
```

This protects against duplicate escalation records caused by:

* provider retries;
* worker retries;
* transaction replay;
* duplicate workflow invocation.

---

# Idempotency Conflict Detection

Finding an existing escalation is not enough.

The package verifies that the existing escalation actually belongs to the same logical request.

It compares fields including:

```text
conversation_id
source
reason_code
trigger_message_id
```

If conflicting values are detected, an `EscalationIdempotencyConflictError` is raised rather than silently reusing the existing escalation.

This prevents a malformed retry from accidentally attaching itself to an unrelated escalation.

---

# Manual/System Escalations

AI-run idempotency only applies when an `ai_run_id` exists.

Manual and system escalations without an AI run are intentionally not deduplicated because separate human/system actions may legitimately represent separate escalations.

---

# Creation Audit

Successful escalation creation produces an audit event:

```text
event_type  = escalation.created
entity_type = escalation
action      = created
```

The event records:

```text
actor
trace_id
conversation_id
ai_run_id
before_state
after_state
trigger_message_id
occurred_at
```

The initial after-state includes key lifecycle fields such as:

```text
status
priority
source
reason_code
```

The creation implementation records this audit event after persistence has generated the escalation ID.

---

# Audit Actor Resolution

The escalation source influences the audit actor during creation.

AI-driven sources:

```text
decision
guardrail
```

are recorded as:

```text
AuditActorType.AI
```

Other creation paths use:

```text
AuditActorType.SYSTEM
```

This distinguishes the origin of the escalation from a later human support-agent action.

---

# Querying Escalations

## `query_escalations.py`

The query layer provides three major read operations:

```text
GetEscalation
ListConversationEscalations
ListEscalations
```

All three are read-only application services.

---

# Get One Escalation

`GetEscalation` retrieves an escalation by ID.

The flow is:

```text
GetEscalationQuery
       │
       ▼
EscalationRepository.get_by_id()
       │
       ├── missing → EscalationDoesNotExistError
       │
       ▼
TicketRepository
       │
       ▼
EscalationView
```

If a linked ticket exists, it is included in the resulting application view.

---

# Linked Ticket

The query layer can enrich an escalation with its linked support ticket.

The application view contains:

```text
ticket_id
ticket_number
ticket_reference
status
```

The human-facing reference is formatted as:

```text
TKT-XXXXXXXX
```

For example:

```text
ticket_number = 42
ticket_reference = TKT-00000042
```

The mapping validates that both the ticket ID and ticket number exist before exposing the linked-ticket view.

---

# Conversation Escalation History

`ListConversationEscalations` retrieves escalation history for a specific conversation.

```text
Conversation
     │
     ├── Escalation 1
     ├── Escalation 2
     ├── Escalation 3
     └── ...
```

The repository query is constrained by the conversation ID and limit, and results are converted into detached `EscalationView` objects.

---

# Escalation Queue

`ListEscalations` provides the operational queue/recent-history view.

It supports:

```text
active_only
status
priority
reason_code
limit
offset
```

When `active_only=True`, the repository uses the active-escalation query.

Otherwise it queries recent escalations using the supplied filters.

---

# Pagination

The queue uses offset pagination:

```text
limit
offset
```

The implementation fetches one additional record:

```text
fetch_limit = limit + 1
```

This allows it to determine whether another page exists without requiring a separate count query.

```text
Requested:
limit = 20

Database:
fetch 21

Returned:
items = first 20
has_more = true if record 21 exists
```

The extra record is not exposed to the caller.

---

# Pagination Contract

The query layer enforces:

```text
limit ≤ 200
offset ≥ 0
```

`status`, `priority`, and `reason_code` are normalized to lowercase.

When `active_only=True`:

```text
status       must not be supplied
reason_code  must not be supplied
```

because active queue selection and historical filtering represent different query modes.

---

# Escalation Views

The query layer does not return raw SQLAlchemy models.

Instead, escalation persistence records are transformed into application-level views.

The view contains:

```text
escalation_id
conversation_id
ai_run_id
trigger_message_id

source
reason_code
reason_summary
priority
status

handoff_summary
metadata

created_at
updated_at
resolved_at

linked_ticket
```

The conversion explicitly validates required persistence fields before creating the view.

This keeps ORM state out of the API/application boundary.

---

# Lifecycle Updates

## `update_escalation.py`

`UpdateEscalation` owns manual escalation lifecycle transitions.

Unlike escalation creation, this operation represents a **standalone support-agent/admin action after the original customer-message transaction has completed**.

Therefore, the service owns its own Unit of Work.

---

# Authorization

Only:

```text
SUPPORT_AGENT
ADMIN
```

roles can update escalation state.

The command requires an `AuthenticatedPrincipal` and validates the role before execution.

Conceptually:

```text
AuthenticatedPrincipal
        │
        ▼
      Role
     /    \
SUPPORT   ADMIN
 AGENT
     \    /
      allowed
```

Other roles are rejected at command validation time.

---

# Customer-Facing Messages

Lifecycle updates can contain a `customer_message`.

This field is intentionally constrained.

It:

* is normalized;
* has whitespace collapsed;
* must be a string when supplied;
* has a maximum length of 2,000 characters;
* is required for terminal transitions;
* is forbidden for non-terminal transitions.

The command explicitly documents that the message must **not** contain internal notes, provider errors, hidden prompts, unrestricted metadata, or handoff-only details.

---

# Terminal Transition Rules

For:

```text
resolved
dismissed
```

a customer-facing explanation is mandatory.

For:

```text
in_review
```

a customer message cannot be supplied because the application owns the standard review notification.

This produces a clean boundary between:

```text
Internal escalation state
```

and:

```text
Customer-visible communication
```

The command enforces these rules before the transaction starts.

---

# Row Locking

Lifecycle updates use a row-locking repository operation:

```text
get_by_id_for_update(...)
```

The conceptual sequence is:

```text
BEGIN
  │
  ▼
SELECT escalation FOR UPDATE
  │
  ▼
Validate current state
  │
  ▼
Apply transition
  │
  ▼
Notification
  │
  ▼
Audit event
  │
  ▼
COMMIT
```

This prevents concurrent support agents/workers from performing conflicting lifecycle transitions on the same escalation.

---

# Idempotent Lifecycle Updates

If:

```text
current_status == target_status
```

the operation is treated as an idempotent replay.

No second notification is appended and no additional transition audit event is generated.

The transaction is committed and the result indicates:

```text
changed = false
```

This is particularly useful for retries and duplicate operator requests.

---

# Transition Validation

Before modifying the escalation, the application validates the transition against the lifecycle graph.

```text
open
 ├── in_review
 ├── resolved
 └── dismissed

in_review
 ├── resolved
 └── dismissed

resolved
 └── no transitions

dismissed
 └── no transitions
```

Invalid transitions raise:

```text
InvalidEscalationTransitionError
```

with:

```text
escalation_id
current_status
target_status
```

available on the exception for structured error handling.

---

# Applying a Transition

A valid transition updates:

```text
status
updated_at
```

Terminal states additionally set:

```text
resolved_at
```

Non-terminal states clear `resolved_at`.

Therefore:

```text
open → in_review
```

does not establish a resolution timestamp.

While:

```text
in_review → resolved
```

sets:

```text
resolved_at = transition timestamp
```

---

# Customer Notifications

Successful lifecycle transitions produce customer-visible conversation notifications.

Supported mappings include:

```text
in_review
    ↓
escalation_in_review

resolved
    ↓
escalation_resolved

dismissed
    ↓
escalation_dismissed
```

The update service builds the notification using the target state and optional customer message.

---

# Notification Content

For `in_review`, the application provides a standard message informing the customer that a support specialist is reviewing the request.

For `resolved`:

```text
standard resolution prefix
+
customer explanation
```

For `dismissed`:

```text
standard closure prefix
+
customer explanation
```

Terminal notifications cannot be generated without the required customer-facing explanation.

---

# Notification Metadata

Notification metadata includes bounded operational identifiers such as:

```text
escalation_id
escalation_status
```

The notification is written through `ConversationNotificationWriter` inside the same Unit of Work as the escalation transition.

This ensures the lifecycle state and customer notification participate in the same transaction.

---

# Audit Integration

Lifecycle changes are audited using:

```text
AuditRecorder
```

and:

```text
RecordAuditEventCommand
```

An update event uses:

```text
event_type  = escalation.updated
entity_type = escalation
action      = updated
```

and records:

```text
actor
trace_id
conversation_id
ai_run_id
before_state
after_state
```

along with bounded metadata about the transition.

---

# Before / After Audit State

The audit state contains:

```text
status
priority
source
reason_code
resolved_at
updated_at
```

This provides enough information to reconstruct the lifecycle transition without storing unrestricted internal application state.

Example:

```text
before:
{
  status: "open",
  priority: "high",
  ...
}

after:
{
  status: "in_review",
  priority: "high",
  ...
}
```

---

# Audit Actor Mapping

For lifecycle updates:

```text
SUPPORT_AGENT
      │
      ▼
AuditActorType.AGENT

ADMIN
      │
      ▼
AuditActorType.ADMIN
```

No other role is accepted by the update command.

---

# Transaction Ordering

A successful lifecycle update follows this sequence:

```text
1. Open Unit of Work
        │
2. Validate repositories
        │
3. Lock escalation row
        │
4. Load current state
        │
5. Detect idempotent replay
        │
6. Validate transition
        │
7. Capture before-state
        │
8. Generate timestamp
        │
9. Apply lifecycle transition
        │
10. Flush database changes
        │
11. Append customer notification
        │
12. Record audit event
        │
13. Build detached result
        │
14. Commit
        │
15. Return result
```

This keeps escalation state, notification, and audit history transactionally coordinated.

---

# Update Result

A successful update returns a detached `UpdateEscalationResult`.

It contains:

```text
escalation_id
conversation_id
ai_run_id

previous_status
current_status

resolved_at
updated_at

changed
notification_message_id
```

This allows callers to understand exactly what happened without receiving the underlying SQLAlchemy entity.

---

# Persistence Contract Validation

The application layer validates Unit of Work wiring before relying on repositories.

For lifecycle updates it requires:

```text
active SQLAlchemy session
EscalationRepository
AuditEventRepository
```

Missing dependencies result in:

```text
EscalationPersistenceContractError
```

rather than an obscure runtime failure.

Similarly, query operations explicitly validate the availability of the escalation repository and, where required, the ticket repository.

---

# Clock Abstraction

Lifecycle updates accept an optional clock:

```python
Clock = Callable[[], datetime]
```

This allows production code to use UTC time while tests can inject deterministic timestamps.

The default implementation uses:

```text
datetime.now(timezone.utc)
```

The service also validates that injected clock values are timezone-aware.

This is important for deterministic tests and consistent timestamp storage.

---

# Error Hierarchy

## Creation Errors

```text
CreateEscalationError
├── CreateEscalationContractError
└── EscalationIdempotencyConflictError
```

Creation errors distinguish application contract problems from idempotency conflicts.

---

## Query Errors

The query layer includes errors for:

```text
escalation does not exist
repository contract failure
invalid persisted records
```

These allow callers to distinguish a missing escalation from infrastructure/application wiring problems.

---

## Update Errors

```text
UpdateEscalationError
├── EscalationDoesNotExistError
├── InvalidEscalationTransitionError
└── EscalationPersistenceContractError
```

The hierarchy gives API/application adapters a stable way to map domain/application failures into appropriate external responses.

---

# Separation of Concerns

The package deliberately avoids putting unrelated responsibilities into escalation management.

## This package owns

```text
Escalation persistence
Escalation queries
Escalation lifecycle
Escalation authorization
Escalation audit recording
Escalation notifications
Escalation idempotency
```

## This package does not own

```text
Whether AI should escalate
Intent classification
Decision-engine logic
Guardrail evaluation
LLM execution
Retrieval
Conversation processing
Ticket lifecycle
Authentication
Database schema definition
```

For example, the customer-message pipeline itself owns a broad set of repositories—including escalations, audits, AI runs, retrieval, reranking, and decisions—but the escalation package remains responsible specifically for the escalation lifecycle.

---

# Relationship With AI Orchestration

The overall system can be viewed as:

```text
                  Customer Message
                         │
                         ▼
                AI Orchestration
                         │
              ┌──────────┴──────────┐
              │                     │
          automated              escalate
          response                   │
                                    ▼
                          CreateEscalation
                                    │
                                    ▼
                           Human Support Queue
                                    │
                           ┌────────┴────────┐
                           │                 │
                       in_review          terminal
                           │             /       \
                           ▼            ▼         ▼
                       Human Work    resolved  dismissed
                                         │         │
                                         └────┬────┘
                                              ▼
                                     Customer Notification
                                              │
                                              ▼
                                         Audit Event
```

The orchestration layer determines the workflow outcome; the escalation package persists and manages the resulting human-review case.

---

# Relationship With Customer-Message Processing

The customer-message processing workflow can produce escalation requests from reasons such as:

```text
security_sensitive_request
operational_lookup_unavailable
knowledge_unavailable
human_approval_required
customer_requested_human
severe_customer_dissatisfaction
policy_conflict
sensitive_action_claim
safety_restriction
unsupported_operational_claim
missing_generated_response
decision_response_mismatch
```

These reasons are translated into controlled escalation metadata rather than persisting unrestricted customer messages, prompts, generated responses, evidence, or provider errors.

This reinforces the package's role as a **controlled human-handoff boundary**.

---

# Data Minimization

Escalation metadata should remain bounded and operationally meaningful.

The surrounding message-processing layer explicitly builds allowlisted escalation metadata and excludes:

```text
customer messages
generated responses
conversation context
retrieved evidence
prompts
provider errors
unrestricted AI metadata
```

from escalation metadata.

This is important because escalations may be visible to human support operators and therefore should not become an uncontrolled dump of internal AI state.

---

# End-to-End Escalation Example

Consider an AI workflow that determines human approval is required.

### Step 1 — AI decision

```text
DecisionEngine
      │
      ▼
ESCALATE
```

### Step 2 — Application creates escalation

```text
CreateEscalationCommand
{
    conversation_id: ...,
    source: "decision",
    reason_code: "human_approval_required",
    ai_run_id: ...,
    priority: "normal"
}
```

### Step 3 — Persistence

```text
Escalation
status = open
```

### Step 4 — Audit

```text
escalation.created
```

### Step 5 — Support queue

```text
ListEscalations(active_only=True)
```

### Step 6 — Agent begins review

```text
open → in_review
```

### Step 7 — Customer notification

```text
escalation_in_review
```

### Step 8 — Agent resolves

```text
in_review → resolved
```

with a required customer-facing explanation.

### Step 9 — Customer notification

```text
escalation_resolved
```

### Step 10 — Audit

```text
escalation.updated
```

This provides a complete lifecycle from automated escalation decision through human resolution.

---

# Concurrency Model

The most important concurrency protection occurs during lifecycle updates.

```text
Agent A                         Agent B
   │                               │
   ▼                               ▼
get_by_id_for_update()       get_by_id_for_update()
   │                               │
   │ lock acquired                 │ waits
   ▼                               │
validate transition                │
   │                               │
update                             │
   │                               │
commit                             │
   │                               ▼
   │                         reads new state
   │                               │
   │                         validates transition
```

The row lock prevents both actors from independently applying a transition against the same stale state.

---

# Idempotency vs Concurrency

These solve different problems.

### Idempotency

Prevents:

```text
same AI run
   ↓
duplicate active escalations
```

### Row locking

Prevents:

```text
multiple concurrent lifecycle updates
   ↓
conflicting state transitions
```

Both are necessary.

```text
Creation
   └── AI-run idempotency

Update
   └── row-level locking
```

---

# Read/Write Separation

The package has a clear distinction between query and mutation operations.

```text
READ
│
├── GetEscalation
├── ListConversationEscalations
└── ListEscalations

WRITE
│
├── CreateEscalation
└── UpdateEscalation
```

Queries do not commit changes.

Creation and updates own transactional writes.

This makes the application layer easier to reason about and test.

---

# Testing Strategy

The package is designed for isolated application-layer tests through dependency injection.

## Creation tests

Test:

* invalid conversation UUID;
* invalid source;
* invalid priority;
* oversized fields;
* invalid metadata;
* missing repository;
* new escalation creation;
* AI-run idempotent replay;
* idempotency conflict;
* audit event creation.

---

## Query tests

Test:

* missing escalation;
* successful lookup;
* linked ticket lookup;
* conversation history;
* active queue;
* historical queue;
* status filtering;
* priority filtering;
* reason-code filtering;
* pagination;
* `has_more`;
* invalid limit;
* invalid offset;
* invalid filter combinations.

---

## Update tests

Test:

* support-agent authorization;
* admin authorization;
* unauthorized roles;
* invalid transitions;
* terminal-state protection;
* required terminal customer message;
* forbidden non-terminal customer message;
* message normalization;
* message length limits;
* idempotent replay;
* notification generation;
* audit generation;
* before/after state;
* timezone-aware clock;
* repository contract failures.

---

# Design Principles

## 1. Escalation Is a Lifecycle

An escalation is not merely a boolean flag such as:

```text
needs_human = true
```

It has a controlled lifecycle:

```text
open
→ in_review
→ resolved / dismissed
```

---

## 2. Escalation Decisions Are External

This package persists the result of an escalation decision.

It does not determine whether the AI should escalate.

---

## 3. State Transitions Are Explicit

Every lifecycle transition is validated against an allowlist.

No arbitrary:

```text
current → target
```

transition is permitted.

---

## 4. Human Actions Are Authorized

Manual lifecycle changes require a trusted authenticated principal with:

```text
SUPPORT_AGENT
```

or:

```text
ADMIN
```

role.

---

## 5. Customer Communication Is Controlled

Customer-visible messages are:

* normalized;
* bounded;
* explicitly supplied;
* restricted to appropriate lifecycle transitions.

---

## 6. Audit Is Part of the Transaction

Escalation creation/update and corresponding audit events are coordinated through the same Unit of Work.

---

## 7. Notifications Are Transactionally Coordinated

A lifecycle transition and its customer-facing notification are produced inside the same transaction.

---

## 8. Idempotency Is Explicit

AI-run escalations are deduplicated deliberately rather than relying solely on database uniqueness errors.

---

## 9. ORM Models Stay Behind the Application Boundary

Queries return immutable application views/results instead of exposing SQLAlchemy entities.

---

## 10. Operational Metadata Is Bounded

Escalation metadata should contain only the information required for support operations and auditing.

---

# Summary

The `packages/application/escalations/` package is the **human-handoff application boundary** of the customer-support system.

Its complete responsibility can be summarized as:

```text
                     Escalation Application
                              │
             ┌────────────────┼────────────────┐
             │                │                │
             ▼                ▼                ▼
          CREATE            QUERY            UPDATE
             │                │                │
             │                │                │
       validate input     get one         authorize actor
       source/priority    conversation    lock row
       metadata limits    history         validate transition
             │            queue            update state
             │                │                │
             ▼                │                ▼
       idempotency            │          notification
             │                │                │
             ▼                │                ▼
       persist record         │          audit event
             │                │                │
             ▼                │                │
       creation audit         │                │
             │                │                │
             └────────────────┴────────────────┘
                              │
                              ▼
                     Customer Support System
```

The key invariants are:

```text
Escalation source is validated.
Priority is validated.
Escalation creation is idempotent for AI runs.
Idempotency conflicts are detected explicitly.
Lifecycle transitions are controlled.
Terminal states cannot be reopened.
Only support agents/admins can update escalations.
Terminal transitions require customer-facing explanations.
Customer notifications are generated for lifecycle changes.
Creation and updates produce audit events.
Queries return detached application views.
Persistence contracts are validated explicitly.
Timestamps are timezone-aware.
```

Together, these rules make the escalation layer a controlled boundary between **automated AI support and human customer-support operations**.
