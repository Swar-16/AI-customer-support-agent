# Ticket Application Services

## Overview

The `packages/application/tickets/` package contains the application-layer use cases for the **support-ticket lifecycle**.

It provides the application boundary for:

* creating support tickets;
* creating tickets from escalations;
* adding append-only ticket comments;
* retrieving individual tickets and their visible comment history;
* listing customer tickets and support queues;
* updating ticket lifecycle state;
* assigning and unassigning support agents;
* maintaining optimistic concurrency;
* validating ticket ownership and authorization;
* generating customer-facing notifications;
* recording ticket audit events.

The folder currently contains five application services:

```text
packages/application/tickets/
│
├── create_ticket.py
├── create_ticket_from_escalation.py
├── add_ticket_comment.py
├── query_tickets.py
├── update_ticket.py
└── README.md
```

Together they form the ticket application workflow:

```text
                         ┌──────────────────────┐
                         │      Ticketing       │
                         │   Application Layer  │
                         └──────────┬───────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
          ▼                         ▼                         ▼
    Ticket Creation          Ticket Comments            Ticket Queries
          │                         │                         │
          ▼                         ▼                         ▼
 create_ticket.py           add_ticket_comment.py      query_tickets.py
          │
          ▼
 escalation creation
          │
          ▼
create_ticket_from_escalation.py

                         │
                         ▼
                  Ticket Mutations
                         │
                         ▼
                  update_ticket.py
```

The services share common architectural conventions:

```text
Command / Query DTO
        │
        ▼
Application Service
        │
        ▼
Authorization + Domain Validation
        │
        ▼
Unit of Work
        │
        ▼
Repositories / Models
        │
        ├──────────────► Audit
        │
        └──────────────► Notifications
```

---

# Responsibilities of the Folder

The ticket application layer sits between authenticated callers / orchestration code and the persistence layer.

It is responsible for enforcing **application-level invariants** before ticket state is persisted.

It does not directly expose SQLAlchemy sessions to callers.

Instead, operations are expressed through:

* immutable command/query DTOs;
* application services;
* Unit of Work boundaries;
* repositories;
* detached result objects.

The five files collectively implement the ticket lifecycle:

```text
CREATE
  │
  ├── customer
  ├── agent
  ├── system
  └── escalation
        │
        ▼
     ACTIVE
        │
        ├── comment
        ├── assign
        ├── priority/category changes
        └── status transition
                │
                ▼
          RESOLVED / CLOSED
                │
                ▼
             REOPENED
```

---

# File Responsibilities

| File                               | Primary responsibility                                                             |
| ---------------------------------- | ---------------------------------------------------------------------------------- |
| `create_ticket.py`                 | Create tickets through customer, agent, escalation, or system paths                |
| `create_ticket_from_escalation.py` | Convert an active escalation into a ticket atomically                              |
| `add_ticket_comment.py`            | Add authenticated customer-visible or internal comments                            |
| `query_tickets.py`                 | Retrieve ticket details, visible comments, customer ticket lists, and staff queues |
| `update_ticket.py`                 | Perform controlled ticket mutations and lifecycle transitions                      |

---

# 1. `create_ticket.py`

`create_ticket.py` contains the core ticket creation use case.

Its main service is:

```python
CreateTicket
```

and its primary command is:

```python
CreateTicketCommand
```

The service supports four ticket sources:

```text
customer
agent
escalation
system
```

---

## Creation Paths

The command distinguishes authenticated and internal creation.

### Customer

A customer can create a ticket only for themselves.

The customer identity is derived from:

```python
principal.user_id
```

and the source becomes:

```text
customer
```

A customer cannot create a ticket on behalf of another user.

---

### Support Agent / Administrator

Support agents and administrators must supply:

```text
customer_id
```

Their default source is:

```text
agent
```

They may explicitly create an:

```text
escalation
```

source ticket when an `escalation_id` is provided.

---

### Internal Creation

When:

```python
principal is None
```

the operation is considered an internal creation path.

Internal creation requires:

```text
customer_id
source
```

and only these sources are allowed:

```text
escalation
system
```

---

# Ticket Validation

Ticket creation validates:

```text
conversation_id
trace_id
customer_id
source_message_id
escalation_id
```

as UUIDs where supplied.

Supported categories are:

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

Supported priorities are:

```text
low
normal
high
urgent
```

---

# Ticket Text Limits

Creation enforces:

```text
subject      <= 300 characters
description  <= 20,000 characters
```

Text is normalized using whitespace collapsing:

```text
"  payment    failed  "
          ↓
"payment failed"
```

Blank values are rejected.

---

# Ticket Metadata

Creation metadata is:

```text
Mapping[str, Any]
```

with:

```text
maximum keys:       100
maximum serialized: 20,000 characters
```

Metadata keys must be strings, cannot be blank, and duplicate normalized keys are rejected. Metadata must also be JSON serializable.

After validation, metadata is stored immutably using `MappingProxyType`.

---

# Creation Transaction

`CreateTicket` exposes two execution modes.

## `execute()`

```python
execute(command)
```

creates its own Unit of Work and commits the operation.

```text
validate
   ↓
create UoW
   ↓
execute_in_uow()
   ↓
commit
   ↓
return result
```

---

## `execute_in_uow()`

```python
execute_in_uow(command=..., uow=...)
```

runs inside an already-active transaction.

It:

* validates the command;
* validates required repositories;
* loads the conversation;
* validates the customer;
* validates conversation ownership;
* validates source message;
* validates escalation;
* performs idempotency checks;
* creates the ticket;
* flushes it;
* records the audit event.

It **does not commit**.

This is essential for workflows that must create a ticket atomically with another operation, such as escalation conversion.

---

# Ticket Creation Validation

Before creating a ticket, the service verifies:

```text
conversation exists
        │
        ▼
customer exists
        │
        ▼
customer is active
        │
        ▼
customer has role "customer"
        │
        ▼
customer owns conversation
```

---

# Source Message Validation

If:

```text
source_message_id
```

is supplied, the message must:

1. exist;
2. belong to the requested conversation.

Otherwise the service raises:

```text
TicketSourceMessageDoesNotExistError
TicketSourceMessageMismatchError
```

---

# Escalation Validation

If an escalation ID is supplied, the service first checks whether a ticket is already linked to that escalation.

```text
existing ticket?
       │
   ┌───┴───┐
  yes      no
   │        │
   ▼        ▼
return    validate
existing  escalation
result
```

The escalation must:

* exist;
* belong to the same conversation;
* have status `open` or `in_review`.

Otherwise the appropriate application error is raised.

---

# Ticket Idempotency

Escalation-linked ticket creation is idempotent.

If a ticket already exists for the escalation, the service returns it rather than creating another ticket.

However, provenance must match:

```text
conversation_id
customer_id
source
source_message_id
```

If these conflict, the operation raises:

```text
TicketIdempotencyConflictError
```

---

# Initial Ticket State

New tickets are created with:

```text
status = open
assigned_agent_id = None
resolution_summary = None
assigned_at = None
resolved_at = None
closed_at = None
```

---

# Ticket Audit

Every newly created ticket records:

```text
event_type = ticket.created
action     = created
entity_type = ticket
```

The audit event includes:

* actor;
* trace ID;
* conversation ID;
* resulting status;
* priority;
* category;
* source;
* assignee;
* escalation;
* ticket number;
* source message ID.

---

# `CreateTicketResult`

The detached result contains:

```text
ticket_id
ticket_number
ticket_reference
conversation_id
customer_id
escalation_id
status
priority
category
created
```

The public reference is generated as:

```text
TKT-{ticket_number:08d}
```

For example:

```text
TKT-00001234
```

---

# 2. `create_ticket_from_escalation.py`

This file provides a specialized application workflow:

```python
CreateTicketFromEscalation
```

Its purpose is to convert an active escalation into a durable support ticket.

---

# Escalation Conversion Flow

```text
Escalation
    │
    ▼
load escalation
    │
    ▼
load conversation
    │
    ▼
derive customer
    │
    ▼
CreateTicket.execute_in_uow()
    │
    ▼
Ticket
    │
    ├── created?
    │       │
    │       ▼
    │   notification
    │
    ▼
commit
```

Both the escalation and conversation are loaded inside the same Unit of Work.

---

# Authorization

Only:

```text
support_agent
admin
```

may convert escalations into tickets.

---

# Reuse of Core Creation Logic

The escalation workflow does **not** duplicate ticket creation logic.

Instead it constructs:

```python
CreateTicketCommand(...)
```

with:

```text
source = escalation
source_message_id = escalation.trigger_message_id
escalation_id = command.escalation_id
```

and invokes:

```python
CreateTicket.execute_in_uow(...)
```

This keeps ticket creation invariants centralized in `create_ticket.py`.

---

# Escalation Notification

If a new ticket is actually created, the service writes a customer-visible conversation notification:

```text
notification_kind = ticket_created
```

The notification contains the ticket reference and informs the customer that the escalation has become a support ticket.

If the ticket already existed, no duplicate creation notification is emitted because the notification is conditional on:

```python
result.created
```

---

# 3. `add_ticket_comment.py`

This file implements append-only ticket comments.

Main service:

```python
AddTicketComment
```

Main command:

```python
AddTicketCommentCommand
```

---

# Comment Visibility

Two visibility modes are supported:

```text
customer
internal
```

---

# Commentable Ticket States

Comments may only be added while the ticket is:

```text
open
in_progress
waiting_for_customer
reopened
```

Resolved and closed tickets cannot directly receive comments.

---

# Comment Authorization

Supported authenticated roles are:

```text
customer
support_agent
admin
```

Customers have additional restrictions:

```text
customer
   │
   ├── may comment only on own ticket
   │
   └── may not create internal comments
```

---

# Comment Validation

Content:

```text
required
non-blank
maximum 20,000 characters
```

Metadata follows the same bounded JSON-oriented validation model used by ticket creation:

```text
maximum keys: 100
maximum serialized length: 20,000
```

---

# Concurrency Protection

Before validating or inserting a comment, the ticket is loaded using:

```python
get_by_id_for_update(...)
```

This locks the ticket row.

## The purpose is to prevent a concurrent ticket closure from racing with comment creation.

# Author Validation

The service verifies:

```text
author exists
     ↓
author active
     ↓
persisted role == authenticated role
```

For customers it additionally verifies:

```text
principal.user_id == ticket.customer_id
```

---

# Comment Persistence

The comment is represented by:

```python
TicketCommentModel
```

and persisted through:

```text
TicketCommentRepository
```

After flush, both:

```text
comment.id
comment.created_at
```

must be populated.

Otherwise:

```text
TicketCommentPersistenceContractError
```

is raised.

---

# Comment Audit

Every comment generates:

```text
ticket.comment_added
```

with:

```text
action = comment_added
```

The audit records:

* ticket;
* comment ID;
* visibility;
* author role;
* actor;
* trace ID;
* conversation;
* comment length.

---

# `AddTicketCommentResult`

The result contains:

```text
comment_id
ticket_id
author_id
author_role
visibility
content
created_at
```

---

# 4. `query_tickets.py`

`query_tickets.py` contains the read side of the ticket application layer.

It exposes two primary application services:

```python
GetTicket
ListTickets
```

and corresponding query DTOs:

```python
GetTicketQuery
ListTicketsQuery
```

---

# Ticket Read Models

The query layer intentionally returns detached representations rather than database models.

It defines:

```text
TicketCommentView
TicketView
TicketDetail
TicketPage
```

This prevents callers from directly depending on SQLAlchemy persistence entities.

---

# `TicketCommentView`

Represents a comment visible to the requester:

```text
comment_id
ticket_id
author_id
author_role
visibility
content
metadata
created_at
```

Metadata is wrapped in an immutable mapping.

---

# `TicketView`

Represents the ticket itself.

It includes:

```text
ticket_id
ticket_number
ticket_reference
conversation_id
customer_id
source_message_id
escalation_id
assigned_agent_id
source
subject
description
category
priority
status
resolution_summary
metadata
row_version
created_at
updated_at
assigned_at
resolved_at
closed_at
```

---

# Metadata Visibility

A key security rule is that customer-facing queries do **not** expose administrative metadata.

`TicketView` explicitly documents that:

```text
metadata is empty for customer-facing queries
```

because administrative metadata may contain internal routing information.

The same principle applies to comments.

---

# `GetTicket`

`GetTicket` retrieves:

```text
ticket
+
requester-visible comment history
```

The flow is:

```text
validate query
    ↓
validate requester
    ↓
load ticket
    ↓
authorize access
    ↓
determine metadata visibility
    ↓
load comments
    ↓
map to detached views
    ↓
return TicketDetail
```

---

# Ticket Access Rules

Support agents and administrators may access tickets operationally.

Customers may access only tickets where:

```text
ticket.customer_id == principal.user_id
```

If a customer attempts to access another customer's ticket, the service raises:

```text
TicketDoesNotExistError
```

rather than revealing that the ticket exists.

This provides an existence-concealment boundary.

---

# Comment Visibility in Queries

For:

```text
support_agent
admin
```

the query includes internal comments.

For customers:

```text
internal comments are excluded
```

---

# `ListTickets`

`ListTickets` provides two conceptual views:

```text
Customer ticket list
        OR
Support operations queue
```

---

# Customer Listing

Customers are always restricted to:

```python
principal.user_id
```

They cannot use:

```text
assigned_agent_id
unassigned_only
active_only
priority
category
```

## because these represent operational/internal queue concerns.

# Staff Queue

Support agents and administrators can query:

```text
active queue
```

using:

```text
priority
category
assigned_agent_id
unassigned_only
```

or recent/history results using:

```text
status
priority
category
assigned_agent_id
unassigned_only
```

---

# Pagination

Ticket listing uses:

```text
limit
offset
```

with:

```text
limit > 0
limit <= 200
offset >= 0
```

The implementation fetches:

```text
limit + 1
```

records to determine whether more records exist.

```text
fetch limit + 1
       ↓
has_more = len(records) > limit
       ↓
return first limit
```

---

# `TicketPage`

The result contains:

```text
items
limit
offset
has_more
```

and exposes:

```python
count
```

as the number of returned items.

---

# 5. `update_ticket.py`

`update_ticket.py` contains the controlled ticket mutation workflow.

Its main service is:

```python
UpdateTicket
```

and its command is:

```python
UpdateTicketCommand
```

The service handles:

* status transitions;
* priority changes;
* category changes;
* assignment;
* unassignment;
* resolution;
* reopening;
* customer-facing notifications;
* audit events;
* optimistic concurrency.

---

# Update Authorization

Only:

```text
support_agent
admin
```

may update tickets.
Customers cannot mutate ticket state through this service.

---

# Optimistic Concurrency

Every update requires:

```text
expected_row_version
```

and it must be a positive integer.

The service loads the ticket with a row lock and compares:

```text
ticket.row_version
        vs
command.expected_row_version
```

A mismatch produces:

```text
TicketConcurrencyError
```

The service also translates SQLAlchemy `StaleDataError` into the same application-level concurrency error.

This provides two layers:

```text
row lock
   +
row version
```

The row lock protects lifecycle validation during the transaction, while the version prevents a stale client from overwriting state it did not retrieve.

---

# Allowed Ticket Statuses

The lifecycle statuses are:

```text
open
in_progress
waiting_for_customer
resolved
closed
reopened
```

---

# Status Transition Graph

The allowed transitions are:

```text
open
 ├──► in_progress
 ├──► waiting_for_customer
 └──► resolved

in_progress
 ├──► waiting_for_customer
 └──► resolved

waiting_for_customer
 ├──► in_progress
 └──► resolved

resolved
 ├──► closed
 └──► reopened

closed
 └──► reopened

reopened
 ├──► in_progress
 ├──► waiting_for_customer
 └──► resolved
```

These transitions are explicitly encoded in `ALLOWED_TICKET_TRANSITIONS`.

Any unsupported transition raises:

```text
InvalidTicketTransitionError
```

---

# Resolution Semantics

Transitioning to:

```text
resolved
```

requires:

```text
resolution_summary
```

with a maximum length of:

```text
5,000 characters
```

The transition sets:

```text
status = resolved
resolution_summary = supplied value
resolved_at = current timestamp
closed_at = None
```

---

# Closing Tickets

A ticket may only be closed from:

```text
resolved
```

and it must retain:

```text
resolved_at
resolution_summary
```

Closing sets:

```text
status = closed
closed_at = current timestamp
```

---

# Reopening

Reopening a ticket:

```text
status = reopened
resolution_summary = None
resolved_at = None
closed_at = None
```

A closed ticket cannot be modified unless the same command reopens it.

Reopening may, however, be combined atomically with:

```text
assignment
priority
category
```

updates.

---

# Assignment

A support agent can be assigned through:

```text
assigned_agent_id
```

or removed through:

```text
unassign=True
```

These two options cannot be supplied simultaneously.

---

# Agent Validation

Before assignment, the target user must:

```text
exist
  ↓
be active
  ↓
have role support_agent or admin
```

Otherwise:

```text
TicketAgentDoesNotExistError
TicketAgentNotAssignableError
```

may be raised.

---

# Customer Message

A customer-facing message can be supplied only when transitioning to:

```text
waiting_for_customer
```

It is limited to:

```text
2,000 characters
```

The message becomes part of the customer-facing notification.

---

# No-Op Protection

At least one mutation must be requested.

The command rejects an update where:

```text
target_status = None
priority = None
category = None
assigned_agent_id = None
unassign = False
```

This prevents accidental "update" calls that change nothing.

---

# Atomic Update Workflow

The update service follows:

```text
UpdateTicketCommand
        │
        ▼
validate command
        │
        ▼
open Unit of Work
        │
        ▼
load ticket FOR UPDATE
        │
        ▼
check row version
        │
        ▼
validate closed-ticket rules
        │
        ▼
capture before state
        │
        ▼
apply mutations
        │
        ▼
flush
        │
        ├──────────────► notification if status changed
        │
        ├──────────────► audit event
        │
        ▼
construct result
        │
        ▼
commit
        │
        ▼
return
```

---

# Customer Notifications

Status changes generate customer-facing conversation notifications.

Mappings include:

| Ticket status          | Notification kind             |
| ---------------------- | ----------------------------- |
| `in_progress`          | `ticket_in_progress`          |
| `waiting_for_customer` | `ticket_waiting_for_customer` |
| `resolved`             | `ticket_resolved`             |
| `closed`               | `ticket_closed`               |
| `reopened`             | `ticket_reopened`             |

Notification content is generated according to the new status.

Examples include:

```text
in_progress
→ support team is reviewing the ticket

waiting_for_customer
→ customer is asked for information

resolved
→ resolution summary is communicated

closed
→ closure and resolution are communicated

reopened
→ ticket has returned to the support queue
```

---

# Ticket Audit Trail

Ticket mutation operations integrate with the audit application layer.

Creation records:

```text
ticket.created
```

Comment creation records:

```text
ticket.comment_added
```

Updates record:

```text
ticket.updated
```

The update audit contains both:

```text
before_state
after_state
```

allowing ticket lifecycle changes to be reconstructed.

---

# Shared Unit of Work Model

The ticket services consistently use:

```python
SqlAlchemyUnitOfWork
```

through:

```python
UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
```

This keeps transaction ownership inside the application service.

The general pattern is:

```text
Service
  │
  ▼
uow_factory()
  │
  ▼
Unit of Work
  │
  ├── repositories
  ├── flush
  └── commit
```

For composed workflows, services can reuse an existing Unit of Work instead of creating nested transactions.

The most important example is:

```text
CreateTicketFromEscalation
          │
          ▼
CreateTicket.execute_in_uow()
```

---

# Authorization Model

The ticket application layer consistently uses:

```python
AuthenticatedPrincipal
```

and:

```python
AuthRole
```

The principal roles relevant to ticket operations are:

```text
customer
support_agent
admin
```

The application services do not simply trust the caller's role.

They also validate persisted user state.

For example, query operations verify:

```text
requester exists
requester active
persisted role == authenticated role
```

Comment creation performs equivalent author validation.

This creates a second identity-consistency boundary between authentication and persisted application state.

---

# Customer vs Staff Boundary

A central architectural rule is the separation between customer-facing and internal support operations.

## Customers

Customers can:

```text
create their own tickets
view their own tickets
add comments to their own tickets
```

They cannot:

```text
view another customer's tickets
filter operational queues
use internal priority/category filters
view internal comments
create internal comments
update ticket lifecycle state
assign agents
```

## These restrictions are enforced at the application layer.

## Support Agents / Administrators

Staff users can:

```text
create tickets for customers
convert escalations
query operational queues
view internal metadata
view internal comments
update ticket state
assign support agents
resolve / close / reopen tickets
```

The exact permissions remain operation-specific rather than being implemented as one broad "staff" permission.

---

# Data Exposure Boundary

The query layer deliberately maps database models to detached view models.

This prevents callers from accidentally modifying persistence objects.

The mapping also provides a security boundary:

```text
Database TicketModel
        │
        ▼
include_metadata?
        │
   ┌────┴────┐
   │         │
customer   staff
   │         │
   ▼         ▼
{}       full metadata
```

The same approach is used for comments.

---

# Immutable Application DTOs

The command, query, and result objects use:

```python
@dataclass(frozen=True, slots=True)
```

throughout the package.

Examples include:

```text
CreateTicketCommand
CreateTicketResult

AddTicketCommentCommand
AddTicketCommentResult

GetTicketQuery
ListTicketsQuery

TicketView
TicketCommentView
TicketDetail
TicketPage

UpdateTicketCommand
UpdateTicketResult

CreateTicketFromEscalationCommand
```

## This gives application boundaries explicit, immutable data contracts.

# Ticket Lifecycle

The combined services implement this lifecycle:

```text
                    ┌─────────────┐
                    │     OPEN    │
                    └──────┬──────┘
                           │
              ┌────────────┼─────────────┐
              │            │             │
              ▼            ▼             ▼
        IN_PROGRESS   WAITING_FOR    RESOLVED
              │        CUSTOMER          │
              │            │             │
              └──────┬─────┘             ▼
                     │                  CLOSED
                     ▼                     │
                 RESOLVED                  │
                     │                     │
                     └──────────┬──────────┘
                                ▼
                            REOPENED
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              IN_PROGRESS  WAITING_FOR   RESOLVED
                           CUSTOMER
```

The transition rules are enforced centrally by `UpdateTicket`.

---

# Concurrency Model

Ticket operations use two complementary concurrency mechanisms.

## Pessimistic row locking

Used when the operation must validate current state and mutate it atomically:

```text
AddTicketComment
        ↓
get_by_id_for_update()

UpdateTicket
        ↓
get_by_id_for_update()
```

---

## Optimistic row versioning

`UpdateTicket` additionally requires:

```text
expected_row_version
```

and compares it against the persisted:

```text
row_version
```

This protects clients from updating stale representations.

Together:

```text
row lock
+
row version
=
safe concurrent mutation boundary
```

---

# Error Organization

Each service defines its own application-level error hierarchy.

Examples:

```text
CreateTicketError
├── TicketCreationAccessDeniedError
├── TicketConversationDoesNotExistError
├── TicketCustomerDoesNotExistError
├── TicketCustomerNotActiveError
├── TicketConversationOwnershipError
├── TicketSourceMessageDoesNotExistError
├── TicketSourceMessageMismatchError
├── TicketEscalationDoesNotExistError
├── TicketEscalationMismatchError
├── TicketEscalationNotActiveError
├── TicketIdempotencyConflictError
└── TicketPersistenceContractError
```

Comment errors follow a similar structure:

```text
AddTicketCommentError
├── CommentTicketDoesNotExistError
├── CommentAuthorDoesNotExistError
├── CommentAuthorNotActiveError
├── CommentAuthorRoleMismatchError
├── TicketCommentOwnershipError
├── CustomerInternalCommentError
├── TicketNotCommentableError
└── TicketCommentPersistenceContractError
```

Query errors:

```text
TicketQueryError
├── TicketDoesNotExistError
├── TicketRequesterDoesNotExistError
├── TicketRequesterNotActiveError
├── TicketRequesterRoleMismatchError
├── TicketAccessDeniedError
└── TicketQueryContractError
```

Update errors:

```text
UpdateTicketError
├── TicketDoesNotExistError
├── TicketUpdateAccessDeniedError
├── InvalidTicketTransitionError
├── TicketAgentDoesNotExistError
├── TicketAgentNotAssignableError
├── TicketConcurrencyError
├── ClosedTicketMutationError
└── TicketPersistenceContractError
```

These application-specific exceptions prevent database or ORM exceptions from becoming the primary API contract.

---

# Audit Integration

Ticket mutations integrate with the audit layer.

The relationship is:

```text
Ticket Application Service
          │
          ▼
      AuditRecorder
          │
          ▼
    AuditEventRepository
```

Creation records the initial ticket state, comments record comment creation, and updates record before/after ticket state.
This means the ticket layer is not responsible for implementing audit persistence itself; it supplies the appropriate application-level audit event.

---

# Notification Integration

Customer-visible ticket lifecycle changes integrate with:

```text
ConversationNotificationWriter
```

This is used by:

```text
CreateTicketFromEscalation
UpdateTicket
```

The notifications are executed inside the same Unit of Work:

```text
ticket mutation
      │
      ├── notification
      │
      ├── audit
      │
      └── commit
```

This keeps the ticket state change and its associated application side effects inside the same transaction boundary.

---

# Persistence Contract Validation

The services validate that their required Unit of Work dependencies exist before performing persistence operations.

Typical requirements include:

```text
session
users
conversations
messages
tickets
escalations
ticket_comments
audit_events
```

depending on the operation.

For example, ticket creation requires the appropriate user, conversation, message, escalation, ticket, and audit repositories.

The application services therefore fail explicitly when their persistence wiring is incomplete rather than producing obscure attribute errors later.

---

# Result Objects

All mutation services return detached result DTOs.

```text
CreateTicket
        ↓
CreateTicketResult

AddTicketComment
        ↓
AddTicketCommentResult

UpdateTicket
        ↓
UpdateTicketResult

GetTicket
        ↓
TicketDetail

ListTickets
        ↓
TicketPage
```

This creates a clean boundary:

```text
Database Models
      ≠
Application Results
```

---

# Typical Workflows

## Customer creates a ticket

```text
AuthenticatedPrincipal(customer)
        │
        ▼
CreateTicketCommand
        │
        ▼
CreateTicket
        │
        ├── validate customer
        ├── validate conversation ownership
        ├── create ticket
        └── audit
        │
        ▼
CreateTicketResult
```

---

## Customer adds a comment

```text
AuthenticatedPrincipal(customer)
        │
        ▼
AddTicketCommentCommand
        │
        ▼
lock ticket
        │
        ▼
verify ownership
        │
        ▼
create comment
        │
        ▼
audit
        │
        ▼
commit
```

---

## Agent updates a ticket

```text
Support Agent
     │
     ▼
UpdateTicketCommand
     │
     ▼
lock ticket
     │
     ▼
check row_version
     │
     ▼
validate transition
     │
     ▼
apply mutation
     │
     ├── notification
     └── audit
     │
     ▼
commit
```

---

## Escalation becomes a ticket

```text
Escalation
    │
    ▼
CreateTicketFromEscalation
    │
    ├── authorize staff
    ├── load escalation
    ├── load conversation
    │
    ▼
CreateTicket.execute_in_uow()
    │
    ├── idempotency
    ├── ticket creation
    └── audit
    │
    ▼
ticket_created notification
    │
    ▼
commit
```

---

## Customer queries tickets

```text
Customer
   │
   ▼
ListTicketsQuery
   │
   ▼
validate requester
   │
   ▼
list_for_customer()
   │
   ▼
strip internal metadata
   │
   ▼
TicketPage
```

---

## Staff queries operational queue

```text
Support Agent / Admin
        │
        ▼
ListTicketsQuery
        │
        ├── active_only
        ├── priority
        ├── category
        ├── assigned_agent_id
        └── unassigned_only
        │
        ▼
operations queue
        │
        ▼
TicketPage
```

---

# Design Principles

## 1. Application Services Own Use Cases

The files do not expose raw repository operations to callers.

Instead:

```text
Caller
  ↓
Command / Query
  ↓
Application Service
  ↓
Repository
```

This centralizes business/application invariants.

---

## 2. Commands Are Immutable

Mutation requests use frozen dataclasses.

This prevents accidental modification after validation.

---

## 3. Authorization Is Explicit

Authorization decisions are made within the application services instead of assuming that an authenticated principal automatically has permission for every ticket operation.

---

## 4. Customer Data Is Isolated

Customer access is restricted by ownership.

Internal comments and administrative metadata are excluded from customer-facing reads.

---

## 5. Ticket State Transitions Are Explicit

The update service does not permit arbitrary status changes.

Every transition must exist in the explicit transition graph.

---

## 6. Concurrency Is First-Class

Ticket updates account for concurrent modifications through:

```text
row locks
+
row version
+
StaleDataError translation
```

---

## 7. Side Effects Share the Transaction

Ticket mutations can generate:

```text
audit events
notifications
```

inside the same Unit of Work.

---

## 8. Escalation Logic Reuses Ticket Creation

`create_ticket_from_escalation.py` delegates the actual ticket creation to:

```python
CreateTicket.execute_in_uow()
```

instead of duplicating ticket persistence rules.

---

# Dependency Overview

```text
                         packages/application/tickets
                                      │
              ┌───────────────────────┼────────────────────────┐
              │                       │                        │
              ▼                       ▼                        ▼
       Authentication             Audit                  Notifications
              │                       │                        │
              ▼                       ▼                        ▼
    AuthenticatedPrincipal      AuditRecorder       ConversationNotificationWriter
              │                       │                        │
              └───────────────────────┼────────────────────────┘
                                      │
                                      ▼
                              SqlAlchemyUnitOfWork
                                      │
                ┌─────────────────────┼─────────────────────┐
                │                     │                     │
                ▼                     ▼                     ▼
             Tickets             Comments              Escalations
                │                     │                     │
                └─────────────────────┼─────────────────────┘
                                      │
                                      ▼
                                  Database
```

---

# File Interaction Map

```text
create_ticket.py
      │
      ├──────────────► AuditRecorder
      │
      └──────────────► used by
                           │
                           ▼
              create_ticket_from_escalation.py


add_ticket_comment.py
      │
      ├──────────────► TicketRepository
      ├──────────────► TicketCommentRepository
      └──────────────► AuditRecorder


query_tickets.py
      │
      ├──────────────► TicketRepository
      └──────────────► TicketCommentRepository


update_ticket.py
      │
      ├──────────────► TicketRepository
      ├──────────────► AuditRecorder
      └──────────────► ConversationNotificationWriter


create_ticket_from_escalation.py
      │
      ├──────────────► EscalationRepository
      ├──────────────► ConversationRepository
      ├──────────────► CreateTicket
      └──────────────► ConversationNotificationWriter
```

---

# Testing Strategy

Tests for this package should cover the application contracts rather than merely checking that repository methods were called.

## Ticket Creation

Test:

* customer self-creation;
* customer attempting to create for another user;
* staff creation;
* internal system creation;
* internal escalation creation;
* invalid source;
* invalid category;
* invalid priority;
* blank subject;
* oversized subject;
* oversized description;
* invalid customer;
* inactive customer;
* conversation ownership;
* invalid source message;
* invalid escalation;
* inactive escalation;
* escalation idempotency;
* idempotency conflict;
* audit creation;
* missing repository dependencies.

---

## Escalation Conversion

Test:

* customer denied;
* support agent allowed;
* admin allowed;
* escalation missing;
* conversation missing;
* correct customer derivation;
* correct escalation provenance;
* ticket reuse;
* notification only when a new ticket is created;
* atomic Unit of Work behavior.

---

## Comments

Test:

* customer comment on own ticket;
* customer access to another ticket denied;
* customer internal comment denied;
* staff internal comment;
* inactive author;
* role mismatch;
* nonexistent ticket;
* resolved ticket;
* closed ticket;
* row-lock behavior;
* comment audit;
* generated ID;
* generated timestamp.

---

## Queries

Test:

* customer own-ticket retrieval;
* customer foreign-ticket concealment;
* staff ticket retrieval;
* internal comment visibility;
* customer comment visibility;
* metadata filtering;
* customer list restrictions;
* staff queue filters;
* pagination;
* `has_more`;
* invalid limits;
* invalid offsets;
* requester identity mismatch.

---

## Updates

Test:

* unauthorized customer update;
* stale row version;
* invalid transition;
* closed-ticket mutation;
* valid reopening;
* assignment;
* unassignment;
* invalid agent;
* inactive agent;
* invalid priority/category;
* resolution without summary;
* invalid customer message usage;
* waiting-for-customer transition;
* notification creation;
* audit before/after state;
* concurrent `StaleDataError`.

---

# Summary

`packages/application/tickets/` is the application-layer implementation of the support-ticket lifecycle.

Its five files divide responsibility cleanly:

```text
create_ticket.py
    │
    └── ticket creation + validation + idempotency + audit

create_ticket_from_escalation.py
    │
    └── escalation → ticket workflow

add_ticket_comment.py
    │
    └── authenticated append-only comments + audit

query_tickets.py
    │
    └── customer reads + staff queues + visibility controls

update_ticket.py
    │
    └── lifecycle mutations + assignment + concurrency
        + notifications + audit
```

The resulting architecture is:

```text
                    ┌───────────────────────┐
                    │   Ticket Application  │
                    │        Layer          │
                    └───────────┬───────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
          ▼                     ▼                     ▼
       Commands              Queries              Results
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                │
                                ▼
                         Authorization
                                │
                                ▼
                       Ticket invariants
                                │
                                ▼
                         Unit of Work
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
        Persistence           Audit          Notifications
             │
             ▼
          Database
```

The package therefore provides a cohesive boundary for **ticket creation, querying, commenting, lifecycle management, escalation conversion, authorization, concurrency control, auditing, and customer-facing ticket notifications**, while keeping persistence and infrastructure concerns behind their respective abstractions.
