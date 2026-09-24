# Observability Application Layer

## Overview

The `packages/application/observability/` package provides the application-layer boundary for **durably recording completed HTTP API requests**.

Currently, this folder contains a single implementation:

```text
AI-customer-support-agent/
└── packages/
    └── application/
        └── observability/
            ├── record_api_request.py
            └── README.md
```

The package is responsible for taking **sanitized HTTP request telemetry**, validating it, converting it into the database persistence model, and committing it through the application's Unit of Work and repository abstractions.

The central flow is:

```text
HTTP / Middleware
       │
       │ sanitized telemetry
       ▼
RecordAPIRequestCommand
       │
       │ validation + normalization
       ▼
RecordAPIRequest
       │
       │ Unit of Work
       ▼
APIRequestRepository
       │
       ▼
APIRequestModel
       │
       ▼
   Database
```

The service is designed specifically for **durable observability/audit telemetry**, not for handling the HTTP request itself.

---

# Responsibilities

The folder currently has one file:

| File                    | Responsibility                                                                           |
| ----------------------- | ---------------------------------------------------------------------------------------- |
| `record_api_request.py` | Validates sanitized API-request telemetry and persists one completed HTTP-request record |

The file defines:

```text
record_api_request.py
│
├── UnitOfWorkFactory
├── HTTP / actor / size limits
│
├── RecordAPIRequestError
├── APIRequestPersistenceContractError
│
├── RecordAPIRequestCommand
├── RecordAPIRequestResult
│
└── RecordAPIRequest
```

## The command represents sanitized telemetry, while the service performs the actual persistence operation.

# Architectural Position

`observability` belongs to the **application layer**.

Its dependencies point downward into the persistence layer:

```text
packages/application/observability
              │
              ├── APIRequestModel
              │
              ├── APIRequestRepository
              │
              └── SqlAlchemyUnitOfWork
                       │
                       ▼
                  Database Layer
```

The service therefore coordinates existing persistence abstractions rather than directly managing SQLAlchemy sessions or database statements.

The three persistence components imported by the module are:

```python
APIRequestModel
APIRequestRepository
SqlAlchemyUnitOfWork
```

---

# Core Design Principle

The most important design rule in this module is:

> **Only sanitized request telemetry should cross the application persistence boundary.**

`RecordAPIRequestCommand` explicitly documents that raw request bodies, response bodies, cookies, authorization headers, API keys, and arbitrary headers must never be included.

The intended boundary is therefore:

```text
Raw HTTP Request
       │
       │ middleware sanitization
       ▼
Safe telemetry fields
       │
       ▼
RecordAPIRequestCommand
       │
       ▼
Durable persistence
```

This prevents sensitive HTTP-level data from accidentally becoming part of the durable API-request telemetry record.

---

# `UnitOfWorkFactory`

The module defines:

```python
UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
```

This abstraction allows `RecordAPIRequest` to receive a factory rather than a pre-created Unit of Work.

Conceptually:

```text
RecordAPIRequest
       │
       │ calls factory
       ▼
SqlAlchemyUnitOfWork
       │
       ├── session
       └── api_requests repository
```

This keeps Unit of Work creation outside the service and makes the service easier to wire into the application's dependency-management infrastructure.

---

# Validation Constants

The module defines explicit limits for request telemetry.

## HTTP Methods

Supported methods are:

```text
GET
POST
PUT
PATCH
DELETE
OPTIONS
HEAD
```

represented by:

```python
VALID_HTTP_METHODS
```

---

## Actor Roles

Supported actor roles are:

```text
customer
support_agent
admin
system
```

represented by:

```python
VALID_ACTOR_ROLES
```

---

## Field Length Limits

The module defines the following limits:

| Field               |           Maximum |
| ------------------- | ----------------: |
| `route_template`    |    500 characters |
| `request_path`      |  2,000 characters |
| `error_code`        |    100 characters |
| `exception_type`    |    255 characters |
| `client_ip`         |     45 characters |
| `user_agent`        |  1,024 characters |
| metadata keys       |               100 |
| serialized metadata | 20,000 characters |

These limits protect the persistence boundary from unexpectedly large telemetry values.

---

# Error Hierarchy

The module defines two application-level errors.

```text
RecordAPIRequestError
└── APIRequestPersistenceContractError
```

`RecordAPIRequestError` is the base application error for durable request recording.

`APIRequestPersistenceContractError` represents invalid persistence wiring or invalid state generated during persistence.

---

# `RecordAPIRequestCommand`

`RecordAPIRequestCommand` is the primary input DTO.

It is declared as:

```python
@dataclass(frozen=True, slots=True)
```

and represents:

> Sanitized HTTP request information ready for persistence.

The command contains:

```text
trace_id
method
request_path
status_code
latency_ms
started_at
completed_at
route_template
error_code
exception_type
actor_user_id
actor_role
client_ip
user_agent
request_size_bytes
response_size_bytes
metadata
```

---

# Required Request Fields

The following fields are required:

```text
trace_id
method
request_path
status_code
latency_ms
started_at
completed_at
```

Optional fields include:

```text
route_template
error_code
exception_type
actor_user_id
actor_role
client_ip
user_agent
request_size_bytes
response_size_bytes
metadata
```

---

# `trace_id`

`trace_id` must be an actual:

```python
uuid.UUID
```

instance.

Otherwise a `TypeError` is raised.
The trace ID provides correlation between the request being recorded and other application-level telemetry.

---

# HTTP Method Normalization

`method` must be a string.

It is normalized using:

```text
strip
  ↓
upper-case
```

For example:

```text
" post "
    ↓
"POST"
```

The normalized method must belong to:

```text
GET
POST
PUT
PATCH
DELETE
OPTIONS
HEAD
```

Otherwise a `ValueError` is raised.

---

# Request Path

`request_path` must:

* be a string;
* be stripped;
* not be blank;
* not exceed 2,000 characters.

This prevents empty or excessively large request paths from entering durable telemetry.

---

# HTTP Status Code

`status_code` must:

* be an integer;
* not be a boolean;
* fall between `100` and `599`.

Thus:

```text
100–599
```

is the accepted HTTP status range.

---

# Latency

`latency_ms` must be:

```text
integer
+
non-negative
```

## Boolean values are explicitly rejected even though Python considers `bool` to be an `int` subclass.

# Timestamps

Both:

```text
started_at
completed_at
```

must be timezone-aware `datetime` objects.

A naive datetime is rejected.
Additionally:

```text
completed_at >= started_at
```

must hold.

Otherwise construction fails with:

```text
ValueError:
completed_at cannot be earlier than started_at
```

---

# Optional Error Information

The command supports:

```text
error_code
exception_type
```

Both are normalized as optional text values.

`error_code` receives additional normalization to uppercase.
For example:

```text
" timeout "
      ↓
"TIMEOUT"
```

---

# Success Outcome Sanitization

The command derives an outcome from the HTTP status code.

```text
status < 400
    ↓
success

400 <= status < 500
    ↓
client_error

status >= 500
    ↓
server_error
```

An important rule follows:

```text
success
    ↓
error_code = None
exception_type = None
```

Therefore successful requests cannot retain stale error information.

The public property:

```python
command.outcome
```

always derives the outcome from `status_code`.

---

# Actor Information

The command supports optional actor identity:

```text
actor_user_id
actor_role
```

`actor_user_id` must be a UUID when supplied.

`actor_role` is normalized to lowercase and must belong to:

```text
customer
support_agent
admin
system
```

---

# Actor Consistency Rules

The module enforces a strict relationship between actor ID and role.

## Role without user ID

Invalid:

```text
actor_user_id = None
actor_role = "customer"
```

Raises:

```text
ValueError
```

---

## User ID without role

Also invalid:

```text
actor_user_id = UUID(...)
actor_role = None
```

Raises:

```text
ValueError
```

---

## Valid actor representation

The intended relationship is:

```text
actor_user_id
      +
actor_role
```

or:

```text
neither
```

but not only one of the two.

---

# Client IP

`client_ip` is optional text with a maximum length of:

```text
45 characters
```

It is stripped and converted to `None` when blank.

The implementation does not perform IP-address semantic parsing; it enforces the declared text/length boundary.

---

# User Agent

`user_agent` is optional text with a maximum length of:

```text
1,024 characters
```

Like other optional text values, whitespace is stripped and blank values become `None`.

---

# Request and Response Sizes

Both:

```text
request_size_bytes
response_size_bytes
```

are optional.

When present, each must be:

```text
integer
+
non-negative
```

Boolean values are rejected.

---

# Metadata

Metadata is represented as:

```python
Mapping[str, Any]
```

and defaults to an empty mapping.

Metadata undergoes several safety and consistency checks.

---

## Mapping Requirement

Metadata must be a `Mapping`.

Otherwise:

```text
TypeError
```

is raised.

---

## Maximum Number of Keys

Metadata can contain at most:

```text
100 keys
```

---

## Metadata Keys

Every key must:

* be a string;
* not be blank after trimming.

Keys are normalized by stripping whitespace.

---

## Duplicate Normalized Keys

The implementation detects collisions caused by normalization.

For example:

```text
" request_id "
"request_id"
```

would normalize to the same key.

Such duplicates cause:

```text
ValueError
```

---

## JSON Serialization

Metadata must be JSON serializable.

The implementation serializes it using:

```python
json.dumps(
    normalized,
    sort_keys=True,
    separators=(",", ":"),
)
```

Non-serializable values cause:

```text
ValueError
```

with the message that metadata must contain only JSON-serializable values.

---

## Serialized Metadata Limit

The serialized representation must not exceed:

```text
20,000 characters
```

This provides a second protection layer beyond the 100-key limit.

---

# Metadata Immutability

After validation, metadata is stored as:

```python
MappingProxyType(normalized_metadata)
```

This ensures the command's metadata cannot be mutated through the exposed mapping.

The persistence layer later makes an explicit mutable copy:

```python
dict(command.metadata)
```

when constructing the database model.

---

# Optional Text Truncation

Optional text fields use `_normalize_optional_text()`.

The general behavior is:

```text
None
  ↓
None

non-string
  ↓
TypeError

blank string
  ↓
None

within limit
  ↓
trimmed value

over limit
  ↓
truncate to maximum length
```

This differs from required text fields, where exceeding the maximum length causes a validation error.

The implementation explicitly notes that request telemetry should not fail merely because an external user-agent or path-like value is unexpectedly large.

---

# `RecordAPIRequestResult`

`RecordAPIRequestResult` is the immutable output DTO.

It contains:

```text
request_id
trace_id
status_code
outcome
recorded_at
```

The result provides the caller with the database-generated identity and timestamp alongside the original request correlation information.

---

# `RecordAPIRequest`

`RecordAPIRequest` is the application service responsible for persistence.

Its documented responsibility is:

> Persist one completed HTTP-request record.

The service is intentionally strict about invalid telemetry.

The surrounding middleware is expected to use it through a **best-effort boundary**, while this service itself validates aggressively so invalid telemetry can be detected and logged rather than silently persisted.

---

# Constructor

The service requires:

```python
uow_factory: UnitOfWorkFactory
```

Validation:

```text
None
  ↓
TypeError

non-callable
  ↓
TypeError

callable factory
  ↓
accepted
```

The factory is stored internally as:

```text
_uow_factory
```

---

# `execute()`

The primary service operation is:

```python
execute(command: RecordAPIRequestCommand)
    -> RecordAPIRequestResult
```

The method first verifies that the command is a:

```python
RecordAPIRequestCommand
```

Otherwise it raises `TypeError`.

---

# Persistence Workflow

The complete persistence flow is:

```text
     RecordAPIRequestCommand
               │
               ▼
         uow_factory()
               │
               ▼
       SqlAlchemyUnitOfWork
               │
               ▼
      _require_repository()
               │
               ▼
       APIRequestRepository
               │
               ▼
         APIRequestModel
               │
               ▼
        repository.add()
               │
               ▼
       repository.flush()
               │
               ▼
 validate generated ID/timestamp
               │
               ▼
 construct RecordAPIRequestResult
               │
               ▼
         uow.commit()
               │
               ▼
        return result
```

---

# Unit of Work Boundary

The service obtains a Unit of Work using:

```python
with self._uow_factory() as uow:
```

This gives the persistence operation a transaction-oriented boundary.

The service does not manually create or close a SQLAlchemy session.

---

# Repository Requirement

The service calls:

```python
_require_repository(uow)
```

before creating the persistence model.

The repository validation requires:

```text
uow.session is not None
uow.api_requests is not None
```

Otherwise:

```text
APIRequestPersistenceContractError
```

is raised.

This ensures persistence is correctly wired before attempting to record telemetry.

---

# Database Model Construction

The command is translated into:

```python
APIRequestModel(...)
```

The mapping includes:

```text
trace_id
method
route_template
request_path
status_code
outcome
error_code
exception_type
actor_user_id
actor_role
client_ip
user_agent
request_size_bytes
response_size_bytes
latency_ms
metadata
started_at
completed_at
```

The command's immutable metadata mapping is converted into a regular dictionary for persistence:

```python
metadata_=dict(command.metadata)
```

---

# Repository Persistence

The model is handed to:

```python
repository.add(request_record)
```

and then:

```python
repository.flush()
```

The flush is significant because the service expects database-generated fields to be populated before constructing the result.

---

# Persistence Contract Validation

After flushing, the service requires:

```text
request_record.id
request_record.recorded_at
```

to have been generated.

If `id` is missing:

```text
APIRequestPersistenceContractError
```

is raised.

If `recorded_at` is missing:

```text
APIRequestPersistenceContractError
```

is raised.

This prevents the service from returning an apparently successful result when the persistence layer failed to populate required generated state.

---

# Result Construction

After successful flush and generated-field validation:

```python
RecordAPIRequestResult(...)
```

is created using:

```text
request_record.id
request_record.trace_id
request_record.status_code
request_record.outcome
request_record.recorded_at
```

Only after the result is constructed does the service commit the Unit of Work.

---

# Transaction Commit

The Unit of Work is committed with:

```python
uow.commit()
```

The result is returned only after the commit call.

Conceptually:

```text
    construct model
         ↓
   repository.add()
         ↓
  repository.flush()
         ↓
validate generated state
         ↓
   construct result
         ↓
       commit
         ↓
       return
```

---

# Observability Failure Strategy

The module explicitly distinguishes between:

### Strict application service

```text
RecordAPIRequest
```

which validates aggressively and raises errors.

### Best-effort caller boundary

```text
HTTP middleware
```

which is expected to invoke the service in a best-effort manner.

This means observability failures can be surfaced and logged without making the telemetry service itself silently swallow invalid state.

---

# Security and Privacy Boundary

The module intentionally stores only a constrained set of HTTP telemetry.

The command documentation explicitly prohibits:

```text
raw request bodies
raw response bodies
cookies
authorization headers
API keys
arbitrary headers
```

Therefore callers should sanitize information **before** constructing `RecordAPIRequestCommand`.

The service should not be treated as a general-purpose HTTP capture mechanism.

---

# End-to-End Example

Conceptually, middleware can transform a completed request into:

```python
RecordAPIRequestCommand(
    trace_id=trace_id,
    method="POST",
    request_path="/api/v1/orders",
    route_template="/api/v1/orders",
    status_code=201,
    latency_ms=84,
    started_at=started_at,
    completed_at=completed_at,
    actor_user_id=user_id,
    actor_role="customer",
    client_ip=client_ip,
    user_agent=user_agent,
    request_size_bytes=request_size,
    response_size_bytes=response_size,
    metadata={
        "service": "customer-support",
        "version": "v1",
    },
)
```

Then:

```python
result = record_api_request.execute(command)
```

The result contains:

```text
request_id
trace_id
status_code
outcome
recorded_at
```

The exact persistence model and repository implementation remain behind the database abstractions.

---

# Lifecycle Summary

The complete lifecycle can be summarized as:

```text
┌─────────────────────────────┐
│ Completed HTTP Request      │
└──────────────┬──────────────┘
               │
               │ sanitize
               ▼
┌─────────────────────────────┐
│ RecordAPIRequestCommand     │
│                             │
│ validate + normalize        │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ RecordAPIRequest            │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ SqlAlchemyUnitOfWork        │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ APIRequestRepository        │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ APIRequestModel             │
└──────────────┬──────────────┘
               │
               ▼
          flush()
               │
               ▼
       generated ID/time
               │
               ▼
          commit()
               │
               ▼
┌─────────────────────────────┐
│ RecordAPIRequestResult      │
└─────────────────────────────┘
```

---

# Important Invariants

The following invariants are enforced by this application boundary:

1. `trace_id` is always a UUID.
2. HTTP methods are normalized to uppercase and must belong to the supported method set.
3. Request paths cannot be blank and cannot exceed the configured limit.
4. HTTP status codes must be between `100` and `599`.
5. Latency and byte sizes cannot be negative.
6. Timestamps must be timezone-aware.
7. `completed_at` cannot precede `started_at`.
8. Actor ID and actor role must either both be present or both be absent.
9. Actor roles are normalized to lowercase and validated against the supported role set.
10. Successful requests cannot retain `error_code` or `exception_type`.
11. Metadata must be a mapping with string keys.
12. Metadata keys are normalized and duplicate normalized keys are rejected.
13. Metadata must be JSON serializable.
14. Metadata is bounded by both key count and serialized size.
15. The command's metadata is immutable after construction.
16. Persistence requires an active SQLAlchemy session and API-request repository.
17. Database-generated request ID and recording timestamp must exist after flush.
18. The service commits only after successful persistence preparation.
19. Raw request/response bodies, credentials, cookies, and arbitrary headers must not enter the command.

---

# Testing Considerations

Tests for this folder should primarily cover **validation, normalization, security boundaries, persistence wiring, and transaction behavior**.

## Command validation

Test:

* invalid UUIDs;
* invalid HTTP methods;
* method normalization;
* blank request paths;
* oversized request paths;
* invalid status codes;
* boolean status codes;
* negative latency;
* naive datetimes;
* `completed_at < started_at`;
* invalid error-code types;
* error-code normalization;
* invalid exception types;
* actor ID/role mismatch;
* invalid actor roles;
* oversized client IP;
* oversized user-agent;
* negative request/response sizes.

## Outcome behavior

Test:

```text
< 400  → success
400–499 → client_error
500–599 → server_error
```

and verify that successful requests clear:

```text
error_code
exception_type
```

---

## Metadata tests

Test:

* non-mapping metadata;
* more than 100 keys;
* non-string keys;
* blank keys;
* duplicate normalized keys;
* non-JSON-serializable values;
* serialized metadata above 20,000 characters;
* metadata immutability.

---

## Persistence tests

Test:

* `None` Unit of Work factory;
* non-callable factory;
* invalid command;
* missing session;
* missing repository;
* correct model mapping;
* repository `add`;
* repository `flush`;
* missing generated request ID;
* missing generated `recorded_at`;
* commit execution;
* returned `RecordAPIRequestResult`.

---

# Design Summary

`packages/application/observability/` provides a narrow and explicit application boundary for durable API-request telemetry.

Its architecture is:

```text
                Sanitized HTTP Telemetry
                           │
                           ▼
                   RecordAPIRequestCommand
                           │
                        validation
                      normalization
                           │
                           ▼
                     RecordAPIRequest
                           │
                      Unit of Work
                           │
                           ▼
                 APIRequestRepository
                           │
                           ▼
                   APIRequestModel
                           │
                           ▼
                       Database
                           │
                           ▼
              RecordAPIRequestResult
```

The implementation deliberately separates:

```text
telemetry input
      ≠
persistence implementation
      ≠
HTTP middleware
```

The command establishes the **sanitized and validated telemetry contract**, while `RecordAPIRequest` handles the **transactional persistence workflow**.

The result contract then exposes only the durable identifiers and outcome information needed by callers.

Overall, this folder serves as the application's **durable API-request observability boundary**, with strong validation and bounded metadata designed to prevent malformed or sensitive HTTP data from being blindly persisted.
