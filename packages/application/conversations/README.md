# Conversations Application Layer

## Overview

The `packages/application/conversations/` package contains the application-layer use cases responsible for the complete lifecycle of customer conversations.

```text
AI-customer-support-agent/
└── packages/
    └── application/
        └── conversations/
            ├── accept_conversation_start.py
            ├── assign_conversation_title.py
            ├── close_conversation.py
            ├── conversation_context.py
            ├── conversation_notification.py
            ├── get_conversation_messages.py
            ├── process_customer_message.py
            ├── query_conversations.py
            ├── start_conversation.py
            └── start_conversation_errors.py
```

This layer sits between the authenticated API/application boundary and the AI, database, audit, escalation, retrieval, and telemetry subsystems.

The package is responsible for:

* starting conversations;
* accepting the first customer message;
* enforcing idempotency for conversation creation;
* processing customer messages through the AI/RAG pipeline;
* persisting AI-run and decision evidence;
* creating customer-visible responses;
* escalating conversations to human support;
* generating conversation titles;
* closing conversations;
* retrieving conversations;
* retrieving conversation messages;
* exposing historical feedback safely;
* constructing bounded conversation context for AI processing;
* writing deterministic lifecycle notifications;
* protecting customer data from accidental exposure through logs, telemetry, prompts, and replay records.

---

# Architectural Role

The conversation application layer orchestrates several independent subsystems.

```text
                         Authenticated Request
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │ Conversation Application │
                    │         Layer            │
                    └────────────┬─────────────┘
                                 │
             ┌───────────────────┼───────────────────┐
             │                   │                   │
             ▼                   ▼                   ▼
        Conversation          AI Pipeline          Queries
        Lifecycle             Processing           / Views
             │                   │                   │
             ▼                   ▼                   ▼
       PostgreSQL           Orchestrator        Safe DTOs
             │                   │
             │          ┌────────┼─────────┐
             │          ▼        ▼         ▼
             │       Intent   Retrieval   Generation
             │          │        │         │
             │          └────────┼─────────┘
             │                   ▼
             │              Guardrails
             │                   │
             │             ┌─────┴─────┐
             │             ▼           ▼
             │          Response   Escalation
             │
             └─────────────── Audit / Telemetry
```

The package deliberately separates **business transactions** from potentially long-running AI/provider operations.

---

# Files and Responsibilities

| File                           | Primary Responsibility                                                                                              |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `accept_conversation_start.py` | Atomically accept a new conversation's first customer message and establish durable idempotency state               |
| `start_conversation.py`        | Orchestrate idempotent conversation startup, processing leases, AI execution, replay, and optional title generation |
| `process_customer_message.py`  | Execute the AI/RAG pipeline for a customer message and persist the resulting business state                         |
| `assign_conversation_title.py` | Generate and conditionally persist an LLM-based conversation title                                                  |
| `conversation_context.py`      | Build bounded, safe historical context for AI processing                                                            |
| `conversation_notification.py` | Append deterministic customer-visible lifecycle notifications                                                       |
| `query_conversations.py`       | Retrieve conversation metadata with authorization and pagination                                                    |
| `get_conversation_messages.py` | Retrieve safe chronological conversation messages with AI-run and feedback information                              |
| `close_conversation.py`        | Close conversations atomically and record the closure audit event                                                   |
| `start_conversation_errors.py` | Define errors specific to idempotent conversation startup                                                           |

---

# Core Conversation Lifecycle

A normal new conversation follows this lifecycle:

```text
Customer submits first message
             │
             ▼
       StartConversation
             │
             ▼
   AcceptConversationStart
             │
             ├── Validate customer
             ├── Validate message
             ├── Validate channel
             ├── Validate idempotency key
             ├── Create conversation
             ├── Create first message
             ├── Create idempotency record
             └── Record audit event
             │
             ▼
       Acquire processing lease
             │
             ▼
    ProcessCustomerMessage
             │
             ├── Load conversation context
             ├── Create AI run
             ├── Execute AI pipeline
             ├── Persist AI evidence
             ├── Generate response
             └── Escalate if required
             │
             ▼
      Persist terminal result
             │
             ▼
      Assign title (optional)
             │
             ▼
        Return result
```

The acceptance transaction is intentionally completed before any LLM, embedding, retrieval, or reranker provider is invoked.

---

# 1. `accept_conversation_start.py`

## Purpose

`AcceptConversationStart` handles the **durable acceptance of the first message of a new conversation**.

A successful first-message acceptance creates exactly:

```text
Conversation
+
First Customer Message
+
Conversation-Start Idempotency Record
+
Conversation-Created Audit Event
```

No AI/provider operation occurs inside this transaction.

---

## Command

`AcceptConversationStartCommand` contains:

```text
principal
idempotency_key
customer_message
trace_id
channel
title
```

The command is immutable and validates its input.

Only:

```text
AuthRole.CUSTOMER
```

may create a customer conversation.

---

## Supported Channels

The allowed channels are:

```text
web
mobile
email
api
```

---

## Idempotency Key

Idempotency keys must:

* be strings;
* contain 16–255 characters;
* contain no surrounding whitespace;
* contain only visible ASCII characters.

The key itself is not stored directly.

Instead:

```text
idempotency_key
       │
       ▼
SHA-256
       │
       ▼
idempotency_key_hash
```

This allows durable deduplication without persisting the raw key.

---

## Request Fingerprint

The accepted request also receives a deterministic fingerprint based on:

```text
customer_message
channel
title
```

The payload is canonicalized before hashing.

Therefore:

```text
same customer
+
same idempotency key
+
same request payload
```

can safely replay the original request.

However:

```text
same customer
+
same idempotency key
+
different request payload
```

produces an idempotency conflict.

---

## Initial Persistence

The conversation starts as:

```text
status = open
```

The first customer message receives:

```text
sequence_number = 1
```

The conversation's next sequence becomes:

```text
next_message_sequence = 2
```

UUIDv7 identifiers are generated for:

```text
conversation_id
customer_message_id
request_id
```

---

## Transaction Boundary

The acceptance transaction follows:

```text
Validate customer
       │
       ▼
Create conversation
       │
       ▼
Flush
       │
       ▼
Create first message
       │
       ▼
Flush
       │
       ▼
Create idempotency record
       │
       ▼
Flush
       │
       ▼
Validate persisted state
       │
       ▼
Record audit event
       │
       ▼
Commit
```

All records roll back together if a later operation fails.

---

## Concurrent Requests

A database uniqueness constraint protects the customer-scoped idempotency key.

If two requests race:

```text
Request A ──┐
            ├── same customer + same key
Request B ──┘
```

one request wins the database constraint.

The losing request reloads the durable idempotency record and resolves it against the request fingerprint.

This provides database-backed idempotency rather than relying only on application-level checks.

---

# 2. `start_conversation.py`

## Purpose

`StartConversation` is the **higher-level orchestration use case** for creating and processing a new conversation from its first customer message.

It combines:

```text
AcceptConversationStart
+
Processing Lease
+
ProcessCustomerMessage
+
Terminal Replay Snapshot
+
Best-Effort Title Assignment
```

---

## Why It Is Separate From Acceptance

The first customer message must become durable before the AI pipeline starts.

Therefore:

```text
Conversation creation
        │
        ▼
Commit
        │
        ▼
AI processing
```

rather than:

```text
Conversation creation
        │
        ▼
AI processing
        │
        ▼
Commit everything
```

The second design would keep a database transaction open while waiting on external AI providers.

The implementation explicitly avoids this.

---

# Conversation Start Transaction Model

The workflow uses multiple short transactions:

```text
Transaction 1
─────────────
Accept conversation
Persist first message
Persist idempotency record
Audit
Commit
        │
        ▼
Transaction 2
─────────────
Acquire processing lease
Commit
        │
        ▼
NO BUSINESS TRANSACTION
─────────────
Run AI pipeline
        │
        ▼
Transaction 3
─────────────
Persist terminal replay result
Commit
        │
        ▼
Transaction 4
─────────────
Optional title assignment
Commit
```

This architecture prevents long-running provider operations from holding database transactions.

---

# Processing Lease

A processing lease prevents multiple workers from processing the same accepted request simultaneously.

The default processing lease is:

```text
2 minutes
```

The lease contains:

```text
processing_token
processing_expires_at
```

A worker must successfully acquire the lease before invoking the AI pipeline.

---

# Lease States

The workflow can encounter:

```text
No existing terminal result
        │
        ▼
Acquire lease
        │
   ┌────┴─────┐
   │          │
 acquired   unavailable
   │          │
   ▼          ▼
process    inspect state
```

If another request currently owns the lease, the system can return a safe retry-oriented state.

If the lease has expired, another attempt may reclaim processing.

---

# Terminal Replay

Once processing finishes, the result is serialized into a sanitized replay snapshot.

The snapshot contains controlled application state such as:

```text
conversation_id
customer_message_id
ai_run_id
trace_id
pipeline_stage
intent
decision
assistant_message_id
escalation_id
response
succeeded
failure_code
failure_retryable
```

It deliberately excludes:

* prompts;
* customer conversation context;
* retrieved content;
* provider errors;
* unrestricted metadata.

This allows repeated requests with the same idempotency key to return a stable result.

---

# Replay Semantics

A subsequent request using the same idempotency key can become:

```text
replayed = true
created  = false
```

when a terminal result already exists.

This is particularly important for:

* browser retries;
* mobile network retries;
* HTTP timeout retries;
* load-balancer retries;
* client-side duplicate submissions.

---

# Title Generation

Title generation is deliberately non-critical.

The workflow is:

```text
AI processing complete
       │
       ▼
Persist terminal result
       │
       ▼
Attempt title generation
```

If title generation fails:

```text
Customer response = unaffected
Conversation processing = unaffected
Terminal result = already durable
```

The failure is logged using low-cardinality metadata rather than raw customer/provider content.

---

# 3. `process_customer_message.py`

## Purpose

`ProcessCustomerMessage` is the central application use case that connects an accepted customer message to the complete AI support pipeline.

It coordinates:

* conversation validation;
* message persistence;
* conversation context;
* AI run creation;
* orchestration;
* intent classification;
* retrieval;
* embeddings;
* reranking;
* response generation;
* guardrails;
* decision evidence;
* escalation;
* assistant-message persistence;
* AI-run finalization;
* telemetry.

---

# Two Processing Modes

The service exposes two important entry points.

## `execute()`

Used when the service itself must accept and persist a new customer message.

```text
ProcessCustomerMessageCommand
        │
        ▼
Persist customer message
        │
        ▼
Start AI run
        │
        ▼
Execute pipeline
```

---

## `execute_accepted()`

Used when another transaction has already persisted the customer message.

This is the mode used by `StartConversation`.

```text
Accepted customer message
        │
        ▼
Load + validate existing message
        │
        ▼
Start AI run
        │
        ▼
Execute pipeline
```

The message is never inserted again.

---

# Critical Transaction Separation

The service explicitly separates:

### Acceptance transaction

```text
Conversation
Customer Message
AI Run
       │
       ▼
COMMIT
```

from:

### AI execution

```text
LLM
Embedding
Retrieval
Reranking
Guardrails
```

and finally:

### Finalization transaction

```text
Intent Prediction
Decision
Escalation
Assistant Message
AI Run Completion
       │
       ▼
COMMIT
```

This prevents external provider latency from holding business transactions.

---

# AI Run

Every processed message gets an AI run.

The run records:

```text
trace_id
conversation_id
trigger_message_id
pipeline_version
status
```

The run initially enters:

```text
running
```

and eventually becomes:

```text
completed
```

or:

```text
failed
```

---

# Conversation Context

Before pipeline execution, prior conversation messages are converted into bounded AI context using `ConversationContextBuilder`.

The current triggering message is supplied separately.

This prevents internal records from leaking into prompts.

---

# Pipeline Construction

`ProcessCustomerMessage` builds a request-scoped pipeline containing components such as:

```text
Orchestrator
Intent Provider
LLM Call Recorder
Embedding Provider
Embedding Telemetry
Retrieval Telemetry
Reranker Telemetry
Stage Event Sink
Grounded Response Generator
Answer Service
```

The service also supplies:

```text
retrieval profile
grounding budget
embedding descriptor
knowledge application
query embedding cache
```

---

# Pipeline Terminal States

Successful customer-visible processing can terminate in:

```text
GUARDRAILS_COMPLETED
```

or:

```text
ESCALATED
```

A failed pipeline terminates in:

```text
FAILED
```

---

# Approved Response

For:

```text
GUARDRAILS_COMPLETED
```

the persisted assistant message contains:

```text
approved generated response
```

and is marked:

```text
message_kind = assistant_response
feedback_eligible = true
```

---

# Escalation

For:

```text
ESCALATED
```

the customer-visible message is **not** the generated candidate that caused escalation.

Instead, the application persists an application-controlled customer notice.

The generated candidate remains internal.

The stored message is marked:

```text
message_kind = escalation_notice
feedback_eligible = false
```

---

# Escalation Reasons

The application maps structured reason codes to controlled human-readable summaries.

Examples include:

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

Unknown future reason codes fall back to a generic controlled summary.

---

# Escalation Priority

Priority is determined from trusted structured reason codes.

The current mapping is:

```text
Urgent
──────
security_sensitive_request
sensitive_action_claim
safety_restriction

High
────
human_approval_required
policy_conflict
unsupported_operational_claim
severe_customer_dissatisfaction

Normal
──────
other supported reasons
```

Customer text, generated responses, arbitrary metadata, and provider output do not determine priority.

---

# Human Handoff Summary

The escalation handoff summary is generated exclusively from controlled structured values:

```text
escalation source
intent
reason code
application-controlled reason summary
```

It does not include:

* customer message;
* generated answer;
* prompt;
* provider error;
* unrestricted metadata.

---

# Failed Processing

If the pipeline produces a known failure:

```text
AIState.stage = FAILED
```

the service persists:

```text
error_code
error_message
total_latency_ms
completed_at
```

and returns a failure result.

The public application result does not expose an assistant response for failed processing.

---

# Unexpected Exceptions

Unexpected infrastructure/programming exceptions are allowed to escape.

The Unit of Work can therefore roll back the transaction rather than accidentally committing partial state.

A best-effort recovery path attempts to mark an already-committed running AI run as:

```text
PIPELINE_EXECUTION_ABORTED
```

without replacing the original exception.

---

# 4. `assign_conversation_title.py`

## Purpose

`AssignConversationTitle` provides optional LLM-generated titles for conversations.

It is intentionally separated from the critical message-processing path.

The title system follows:

```text
First customer message
        │
        ▼
Prompt Builder
        │
        ▼
LLM
        │
        ▼
Title Generator
        │
        ▼
Validated Title
        │
        ▼
Conditional Database Update
```

---

# Title Assignment Status

The service defines:

```text
ASSIGNED
ALREADY_TITLED
LOST_RACE
DISABLED
```

---

# Ownership

Only the customer who owns the conversation may request generated title assignment.

The conversation is checked before provider invocation and again before persistence.

---

# Race-Safe Persistence

Title generation happens outside the business transaction.

After generation:

```text
set_title_if_absent()
```

is used.

If another request has already assigned a title:

```text
LOST_RACE
```

is returned and the winning title is returned.

This avoids overwriting an existing title.

---

# LLM Instrumentation

Title generation uses:

```text
InstrumentedLLMProvider
+
LLMCallTelemetryRecorder
```

with:

```text
purpose = conversation_title
temperature = 0
```

The provider call therefore remains observable without coupling title generation to the conversation transaction.

---

# Disabled Mode

When title generation is disabled:

```text
status = DISABLED
title = None
source = None
```

No provider call occurs.

---

# 5. `conversation_context.py`

## Purpose

`ConversationContextBuilder` converts historical messages into a bounded representation suitable for AI stages.

Its primary goals are:

* privacy;
* predictable prompt size;
* provider-cost control;
* deterministic serialization;
* protection against internal-role leakage.

---

# Default Context Limits

```text
max_messages               = 12
max_characters             = 8,000
max_characters_per_message = 2,000
```

The configuration requires all values to be positive.

---

# Allowed Roles

Only:

```text
customer
assistant
```

are included.

Internal/system roles are ignored.

Therefore messages such as:

```text
support_agent
system
internal
telemetry
```

cannot silently enter AI conversation context through this boundary.

---

# Excluded Information

The context contains only:

```text
sequence_number
role
content
```

It does not contain:

* message IDs;
* database identifiers;
* metadata;
* telemetry;
* prompts;
* decisions;
* retrieval results;
* tickets;
* escalation records;
* provider errors.

---

# Context Selection

Messages are first normalized and ordered chronologically.

When the overall character budget is exceeded, the builder prioritizes the most recent messages.

```text
Oldest
  │
  ▼
...
Recent
  │
  ▼
Current AI context
```

---

# Message Truncation

Individual messages exceeding:

```text
2,000 characters
```

are truncated using:

```text
... [truncated]
```

The truncation marker is application-controlled.

---

# JSON Serialization

The context is serialized as JSON:

```json
{
  "messages": [
    {
      "content": "...",
      "role": "customer",
      "sequence_number": 12
    }
  ]
}
```

Deterministic JSON serialization ensures customer-authored quotes, newlines, role-like text, delimiters, and prompt fragments cannot change message boundaries.

Customer content remains data rather than instructions.

---

# 6. `conversation_notification.py`

## Purpose

`ConversationNotificationWriter` appends deterministic, customer-visible lifecycle notifications to conversation history.

Examples include:

```text
ticket_created
ticket_in_progress
ticket_waiting_for_customer
ticket_resolved
ticket_closed
ticket_reopened

escalation_in_review
escalation_resolved
escalation_dismissed
```

---

# No LLM

This component never invokes an LLM.

The content must already be application-controlled.

Raw provider output, internal summaries, audit metadata, and unrestricted support notes must never pass through this boundary.

---

# Notification Limits

```text
content:
    maximum 2,000 characters

metadata:
    maximum 30 keys
    maximum 5,000 serialized characters
```

Metadata keys must be strings and are normalized.

Metadata must also be JSON serializable.

---

# Reserved Safety Metadata

Every notification is stored as:

```text
message_kind = lifecycle_notice
notification_kind = <validated kind>
feedback_eligible = false
```

Caller metadata cannot overwrite these reserved fields.

---

# Message Representation

Notifications use:

```text
role = assistant
```

because they are customer-visible conversation events.

They are explicitly marked as lifecycle notices so downstream feedback logic can distinguish them from rateable AI responses.

---

# Transaction Ownership

`ConversationNotificationWriter` does not own the transaction.

The caller supplies the Unit of Work.

Therefore:

```text
Business Mutation
+
Notification
+
Audit
       │
       ▼
Same Transaction
```

can be maintained by the caller.

---

# 7. `query_conversations.py`

## Purpose

This module provides safe read operations for conversation metadata.

It exposes:

```text
GetConversation
ListConversations
```

---

# Supported Conversation States

```text
open
waiting_for_customer
waiting_for_agent
escalated
resolved
closed
```

---

# Supported Channels

```text
web
mobile
email
api
```

---

# `GetConversation`

Retrieves a single conversation after:

1. validating the principal;
2. verifying the requester exists;
3. verifying the requester is active;
4. verifying persisted role matches the authenticated role;
5. loading the conversation;
6. authorizing access.

---

# `ListConversations`

Supports:

```text
status
channel
customer_id
limit
offset
```

The maximum page size is:

```text
200
```

The default page size is:

```text
50
```

---

# Authorization

Customers are always restricted to:

```text
principal.user_id
```

Administrators may optionally specify another customer.

Support-agent access is intentionally denied until an explicit conversation-assignment model exists.

---

# Conversation Enumeration Protection

If a customer attempts to access another customer's conversation, the service reports the conversation as nonexistent rather than explicitly revealing that the conversation belongs to someone else.

This provides an important privacy boundary:

```text
Unauthorized conversation
        │
        ▼
"does not exist"
```

rather than:

```text
"exists but belongs to another customer"
```

---

# Detached Views

The query layer returns:

```text
ConversationView
```

rather than ORM entities.

The view contains:

```text
conversation_id
customer_id
status
channel
title
created_at
updated_at
resolved_at
closed_at
```

This keeps database session state out of application responses.

---

# 8. `get_conversation_messages.py`

## Purpose

`GetConversationMessages` retrieves a safe chronological page of conversation messages.

It combines:

```text
Messages
+
AI Run Provenance
+
Customer Feedback
```

into detached application views.

---

# Access Rules

Customers may read:

```text
their own conversations
```

Administrators may read:

```text
any conversation
```

Support-agent access remains disabled until explicit conversation assignment exists.

---

# Pagination

Default:

```text
limit  = 50
offset = 0
```

Maximum:

```text
200
```

The response includes:

```text
items
total
limit
offset
has_more
next_offset
```

---

# Message View

Each message exposes:

```text
message_id
conversation_id
role
content
sequence_number
created_at
ai_run_id
feedback_eligible
feedback
```

---

# Feedback View

Historical feedback is deliberately minimized.

The customer-safe feedback representation contains:

```text
feedback_id
rating
helpful
created_at
```

It excludes:

* review notes;
* customer comments;
* metadata;
* reason codes;
* reviewer identity.

---

# AI Run Association

Assistant messages may be associated with completed AI runs.

If multiple runs exist, the service selects the appropriate completed run.

Existing feedback with an explicit `ai_run_id` has precedence.

If feedback references a different run than the available completed runs, the service does not silently substitute another run.

---

# Feedback Eligibility

An assistant message is rateable only when:

```text
completed AI run exists
```

and:

```text
message is not an escalation notice
message is not a lifecycle notification
```

Explicit:

```text
feedback_eligible = false
```

always wins.

Historical assistant messages without the explicit metadata flag remain compatible when valid completed AI-run provenance exists.

---

# 9. `close_conversation.py`

## Purpose

`CloseConversation` transitions a conversation into the terminal:

```text
closed
```

state while recording the lifecycle change in the audit system.

---

# Authorization

Allowed roles:

```text
customer
admin
```

Customers may close only conversations they own.

Administrators may close any conversation.

---

# Closure Flow

```text
Validate principal
       │
       ▼
Load conversation FOR UPDATE
       │
       ▼
Authorize ownership
       │
       ▼
Already closed?
   ┌───┴───┐
  yes      no
   │        │
   ▼        ▼
Return   mark closed
existing     │
state        ▼
          validate
             │
             ▼
           audit
             │
             ▼
           commit
```

---

# Closure State

A successfully closed conversation must have:

```text
status     = closed
resolved_at != null
closed_at   != null
updated_at  != null
```

The application validates these invariants after the repository mutation.

---

# Idempotent Closure

Repeated closure is safe.

If the conversation is already:

```text
closed
```

the operation returns the existing state with:

```text
changed = false
```

and does not create another audit event.

---

# Audit Event

A successful transition records:

```text
event_type = conversation.closed
action     = closed
entity_type = conversation
```

with before/after state information.

---

# 10. `start_conversation_errors.py`

## Purpose

This module contains the error hierarchy specific to the idempotent conversation-start workflow.

The base class is:

```python
StartConversationError
```

---

# Error Categories

## Validation

```text
StartConversationValidationError
```

Used for invalid:

* idempotency keys;
* customer messages;
* channels;
* titles.

---

## Authorization

```text
StartConversationAccessDeniedError
```

Used when the authenticated principal cannot start a customer conversation.

---

## Customer State

```text
ConversationStarterDoesNotExistError
ConversationStarterNotActiveError
ConversationStarterRoleMismatchError
```

These represent inconsistencies between authenticated identity and persisted user state.

---

## Idempotency

```text
ConversationStartIdempotencyConflictError
ConversationStartRequestExpiredError
```

The conflict error does not expose the request hash or message content.

The expiration error instructs the caller to create a new idempotency key.

The existing conversation and accepted message are not deleted.

---

## Processing Lease

```text
ConversationStartProcessingInProgressError
ConversationStartLeaseLostError
```

`ConversationStartProcessingInProgressError` contains:

```text
request_id
conversation_id
retry_after_seconds
```

This allows an API layer to safely translate the condition into a retry-oriented response.

---

## Replay

```text
ConversationStartReplayUnavailableError
```

Indicates that a terminal record exists but the sanitized replay snapshot is missing or unusable.

This represents persistence inconsistency rather than invalid customer input.

---

## Persistence Contract

```text
ConversationStartPersistenceContractError
```

Represents missing repositories, missing sessions, invalid generated IDs, or other internal persistence invariants.

---

# End-to-End Data Flow

The package can be understood as four major phases.

```text
┌──────────────────────────────────────────────┐
│ 1. ACCEPT                                    │
│                                              │
│ Customer → Validate → Idempotency → DB      │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ 2. PROCESS                                   │
│                                              │
│ Message → Context → AI/RAG → Decision       │
│                    │                         │
│                    ├── Response              │
│                    └── Escalation            │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ 3. FINALIZE                                  │
│                                              │
│ AI Evidence → Assistant Message → AI Run    │
│             → Escalation → Commit            │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ 4. ENRICH                                    │
│                                              │
│ Optional LLM Title / Lifecycle Notifications│
└──────────────────────────────────────────────┘
```

---

# Transaction Boundaries

One of the most important architectural properties of this package is the deliberate separation of transaction scopes.

## Short Database Transactions

Used for:

* accepting conversation starts;
* acquiring processing leases;
* persisting terminal replay state;
* finalizing AI business state;
* assigning titles;
* closing conversations.

## No Business Transaction During Provider Calls

External operations such as:

```text
LLM calls
embedding calls
retrieval
reranking
AI orchestration
```

run without holding the conversation's primary business transaction open.

This significantly reduces the risk of:

* long-lived database locks;
* connection exhaustion;
* transaction timeouts;
* rollback of already-accepted customer messages.

---

# Authentication Integration

Every protected conversation operation receives:

```text
AuthenticatedPrincipal
```

The principal contains trusted identity information supplied by the authentication layer.

The conversation layer nevertheless validates persisted user state before sensitive operations.

The general pattern is:

```text
AuthenticatedPrincipal
       │
       ▼
Load User
       │
       ├── missing       → error
       ├── inactive      → error
       ├── role mismatch → error
       └── valid
              │
              ▼
        Conversation authorization
```

This prevents stale authentication information from bypassing current user state.

---

# Audit Integration

Conversation lifecycle operations are integrated with the audit subsystem.

Important events include:

```text
conversation.created
conversation.title_assigned
conversation.closed
```

Audit records are written as part of the relevant business transaction where the operation is transactional.

This provides:

```text
Business State
      +
Audit State
      │
      ▼
Atomic Commit
```

---

# AI and Telemetry Integration

`ProcessCustomerMessage` integrates the conversation layer with the AI subsystem.

The processing path can produce telemetry for:

```text
AI run
LLM calls
Embedding calls
Retrieval
Reranking
Stage events
Intent predictions
AI decisions
```

The application service does not treat telemetry as customer conversation storage.

Operational telemetry and business conversation data remain separate concerns.

---

# Privacy Boundaries

The package contains multiple explicit privacy boundaries.

## Conversation Context

Only customer/assistant content is included.

## Notifications

Only application-controlled text is accepted.

## Escalations

Only controlled reason summaries are exposed to human-support handoff records.

## Replay Snapshots

Only sanitized application-level results are stored.

## Query Views

Only customer-safe fields are returned.

## Feedback

Only the minimum customer-safe feedback fields are exposed.

## Logging

Title-generation failure logging records identifiers and exception type, not customer messages, prompts, provider responses, or raw exception text.

---

# Prompt-Injection Boundary

Customer messages are untrusted data.

The context builder serializes them into explicit JSON message structures.

The title-generation and AI-processing architecture therefore follows:

```text
Customer Content
      │
      ▼
Treat as DATA
      │
      ▼
Bound + Normalize
      │
      ▼
Explicit Prompt Boundary
      │
      ▼
AI Provider
```

Customer-authored text does not gain instruction authority merely because it appears in conversation history.

---

# Customer-Visible vs Internal Content

The package maintains a strong distinction between:

```text
Customer-visible
```

and:

```text
Internal AI/application state
```

### Customer-visible

* customer messages;
* approved assistant responses;
* controlled escalation notices;
* controlled lifecycle notifications;
* conversation title;
* safe feedback summary.

### Internal

* prompts;
* retrieved chunks;
* provider output before guardrails;
* AI decision evidence;
* provider errors;
* telemetry metadata;
* internal escalation reasoning;
* unrestricted model-generated candidates.

This distinction is especially important when persisting assistant messages.

---

# Conversation State Model

The supported lifecycle statuses are:

```text
open
   │
   ├── waiting_for_customer
   │
   ├── waiting_for_agent
   │
   ├── escalated
   │
   ├── resolved
   │
   └── closed
```

`ProcessCustomerMessage` accepts processing only for:

```text
open
waiting_for_customer
waiting_for_agent
escalated
```

Closed/resolved conversations are therefore prevented from accidentally accepting additional customer messages through this use case.

---

# Result Object Philosophy

The application layer generally returns immutable detached objects rather than ORM entities.

Examples:

```text
AcceptConversationStartResult
StartConversationResult
ProcessCustomerMessageResult
AssignConversationTitleResult
CloseConversationResult
ConversationView
ConversationMessageView
ConversationPage
ConversationMessagePage
```

This prevents callers from retaining SQLAlchemy entities after their Unit of Work has closed.

---

# Error Philosophy

Errors are divided into:

```text
Customer/Input Errors
        │
        ├── validation
        ├── authorization
        └── invalid lifecycle state

Idempotency/Concurrency Errors
        │
        ├── duplicate key conflict
        ├── request expired
        ├── processing in progress
        └── lease lost

Persistence Contract Errors
        │
        └── missing/inconsistent application state

AI Processing Errors
        │
        ├── timeout
        ├── unavailable
        └── pipeline failure
```

The package avoids leaking sensitive internal state through customer-facing exceptions wherever possible.

---

# Concurrency Strategy

Several parts of the package explicitly account for concurrent requests.

## Conversation Start

Database uniqueness handles competing idempotency keys.

## AI Processing

Processing leases ensure one active worker owns a start request.

## Terminal Persistence

The processing token ensures only the current lease owner can persist the terminal result.

## Title Assignment

`set_title_if_absent()` prevents concurrent title generation from overwriting a title already assigned by another request.

## Conversation Closure

The conversation is loaded with row-level locking before state mutation.

---

# UUIDv7 Usage

Conversation lifecycle identifiers are generated using UUIDv7 where new application records require generated IDs.

Examples include:

```text
conversation_id
customer_message_id
request_id
ai_run_id
processing_token
```

This provides sortable identifiers while preserving UUID semantics.

---

# Recommended Request Flow

For a new customer message submitted as the first message:

```text
API
 │
 ▼
StartConversation
 │
 ├── AcceptConversationStart
 │      │
 │      └── Commit accepted message
 │
 ├── Acquire processing lease
 │
 ├── ProcessCustomerMessage
 │      │
 │      └── AI/RAG pipeline
 │
 ├── Persist terminal replay result
 │
 └── Assign title safely
```

For subsequent messages:

```text
API
 │
 ▼
ProcessCustomerMessage.execute()
 │
 ├── Validate conversation
 ├── Persist message
 ├── Create AI run
 ├── Execute AI pipeline
 └── Finalize business result
```

For reading:

```text
API
 │
 ├── GetConversation
 │
 ├── ListConversations
 │
 └── GetConversationMessages
```

For lifecycle closure:

```text
API
 │
 ▼
CloseConversation
 │
 ├── Lock conversation
 ├── Validate ownership
 ├── Mark closed
 ├── Audit
 └── Commit
```

---

# Design Principles

## 1. Accept Before Processing

The customer's submitted message becomes durable before external AI execution starts.

## 2. Idempotency Is Durable

Idempotency is backed by database state rather than only in-memory request tracking.

## 3. AI Is Outside Business Transactions

LLM/provider latency must not hold the primary conversation transaction open.

## 4. Provider Output Is Untrusted

Generated content is only persisted after application-level validation and guardrail decisions.

## 5. Escalation Uses Controlled Content

Human-support handoff information is generated from structured application state rather than arbitrary model/customer text.

## 6. Optional Features Stay Optional

Conversation title generation cannot invalidate an otherwise successful customer message.

## 7. Customer Data Is Bounded

Conversation history, notifications, replay snapshots, and AI context all have explicit size/content boundaries.

## 8. Authorization Is Revalidated

Authenticated principals are checked against current persisted user state.

## 9. Internal State Is Not Automatically Customer-Visible

AI evidence, provider errors, prompts, telemetry, and internal metadata remain separate from customer-facing messages.

## 10. Audit and Business State Stay Consistent

Important lifecycle mutations are audited within their transaction.

---

# Maintenance Guidelines

When modifying this package, preserve the following invariants.

### Conversation Start

Do not remove the durable idempotency record.

### Idempotency

Never compare only the idempotency key. The request fingerprint must also match.

### Processing Lease

Do not persist a terminal result after losing ownership of the processing lease.

### Replay

Do not store prompts, retrieved content, customer context, or provider error text in replay snapshots.

### AI Processing

Do not hold a business Unit of Work open while calling external providers.

### Escalation

Do not expose the generated candidate that triggered escalation.

### Feedback

Do not make lifecycle notifications or escalation notices feedback targets.

### Context

Do not allow internal/system roles to enter the LLM conversation context.

### Notifications

Do not allow caller metadata to override reserved notification safety fields.

### Title Generation

Do not overwrite an already-existing title.

### Closing

Do not generate repeated closure audit events for an already closed conversation.

### Authorization

Do not expose the existence of another customer's conversation to an unauthorized requester.

---

# Summary

The `packages/application/conversations/` package is the central application boundary for customer conversation lifecycle management.

Its architecture can be summarized as:

```text
                       CONVERSATIONS
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
       Creation           Processing          Query
          │                  │                  │
          ▼                  ▼                  ▼
  AcceptConversation   ProcessCustomer      Get/List
       Start               Message          Conversations
          │                  │                  │
          │                  ├── Context        └── Messages
          │                  ├── Intent
          │                  ├── Retrieval
          │                  ├── Reranking
          │                  ├── Generation
          │                  ├── Guardrails
          │                  └── Escalation
          │
          ▼
      Idempotency
          │
          ▼
    Processing Lease
          │
          ▼
    Terminal Replay
          │
          ▼
    Optional Title
          
          ┌───────────────────────────────┐
          │                               │
          ▼                               ▼
   Lifecycle Notifications          Close Conversation
          │                               │
          └──────────────┬────────────────┘
                         ▼
                       Audit
```

The most important architectural invariant is that **conversation acceptance, AI processing, persistence, replay, enrichment, authorization, and customer-visible state are deliberately separated into explicit application responsibilities and transaction boundaries**.

This allows the conversation subsystem to remain:

* idempotent;
* concurrency-safe;
* transactionally consistent;
* AI-provider resilient;
* privacy-conscious;
* auditable;
* authorization-aware;
* replayable;
* and safe for long-running external AI operations.
