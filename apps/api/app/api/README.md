# API Infrastructure

## Overview

The `apps/api/app/api/` package contains the **shared HTTP infrastructure and cross-cutting API behavior** for the AI customer-support agent.

Unlike `v1/`, which contains concrete feature endpoints, this layer provides the mechanisms that those endpoints depend on:

- FastAPI dependency injection;
- application-service access;
- authentication and authorization dependencies;
- request correlation and trace IDs;
- browser authentication transport;
- refresh-token cookie handling;
- centralized exception translation;
- canonical API error responses;
- OpenAPI transport-contract enforcement.

```text
                         FastAPI Application
                                │
                                ▼
                    ┌───────────────────────┐
                    │      app/api/          │
                    │                       │
                    │  dependencies.py      │
                    │  browser_auth.py      │
                    │  errors.py            │
                    │  openapi_contract.py  │
                    └───────────┬───────────┘
                                │
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                  ▼
           /v1 routes       HTTP errors       OpenAPI schema
              │
              ▼
       Application Services
```

The `v1/` package sits underneath this infrastructure and contains the actual versioned API routes. Its detailed architecture is documented separately.

---

# Directory Structure

```text
apps/api/app/api/
│
├── browser_auth.py
├── dependencies.py
├── errors.py
├── openapi_contract.py
│
└── v1/
    ├── router.py
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
        └── ...
```

The architectural split is:

```text
api/
│
├── Cross-cutting HTTP infrastructure
│   ├── dependencies.py
│   ├── browser_auth.py
│   ├── errors.py
│   └── openapi_contract.py
│
└── Versioned API surface
    └── v1/
```

This prevents authentication, error handling, tracing, and transport policies from being duplicated across individual endpoint modules.

---

# Responsibilities

| File | Responsibility |
|---|---|
| `dependencies.py` | FastAPI dependency injection, authentication, authorization, trace IDs and request metadata |
| `browser_auth.py` | Browser authentication transport and refresh-token cookie security |
| `errors.py` | Central application/HTTP exception → stable API error translation |
| `openapi_contract.py` | Enforces documented transport/security behavior in generated OpenAPI |
| `v1/` | Concrete versioned HTTP endpoints |

Together these files form the **API infrastructure boundary** between HTTP clients and the application layer.

---

# Architectural Position

The overall request path is:

```text
HTTP Client
    │
    ▼
FastAPI
    │
    ├── Middleware
    │
    ├── API Dependencies
    │      │
    │      ├── Settings
    │      ├── Services
    │      ├── Trace ID
    │      ├── Authentication
    │      └── Authorization
    │
    ▼
v1 Router
    │
    ▼
Endpoint
    │
    ▼
Application Command / Query
    │
    ▼
Application Services
    │
    ├── Domain
    ├── Repositories
    ├── AI
    └── Knowledge
    │
    ▼
Application Result
    │
    ▼
HTTP Response
```

Errors can enter the flow from almost any stage:

```text
Application Exception
        │
        ▼
apps/api/app/api/errors.py
        │
        ▼
Canonical APIErrorResponse
        │
        ▼
HTTP Client
```

---

# `dependencies.py`

## Purpose

`dependencies.py` contains the reusable FastAPI dependency functions used throughout the API.

It is the main **request-context assembly layer**.

It provides access to:

- application services;
- application settings;
- browser-auth settings;
- trace/correlation IDs;
- client IP;
- user agent;
- authenticated principals;
- role-restricted principals.

The dependency module obtains the process-scoped `ApplicationServices` container from `request.app.state`, ensuring endpoint handlers use the application services initialized during FastAPI lifespan startup.

---

## Application Services Dependency

```text
FastAPI Request
      │
      ▼
request.app.state.application_services
      │
      ▼
ApplicationServices
      │
      ├── Auth
      ├── Conversations
      ├── Tickets
      ├── Feedback
      ├── Knowledge
      └── Dashboard
```

The dependency validates that the object exists and is actually an `ApplicationServices` instance before returning it.

This keeps endpoint modules independent of application-service construction.

---

## Settings Dependency

API settings are similarly resolved from application state.

```text
request.app.state.settings
        │
        ▼
Settings
```

Invalid or missing application initialization results in a runtime configuration failure rather than silently constructing a new settings object inside the request path.

---

# Trace / Correlation IDs

The API uses:

```text
X-Trace-ID
```

as the request correlation header.

The resolution rules are:

```text
                    Request
                       │
              X-Trace-ID present?
                 /           \
               yes            no
                │              │
                ▼              ▼
         Validate UUID       UUIDv7
                │              │
                └──────┬───────┘
                       ▼
              request.state.trace_id
                       │
                       ▼
              Application Command
```

A caller-supplied valid UUID is reused.

If no header is provided, a UUIDv7 is generated.

A malformed or empty header produces HTTP `400`.

This trace ID subsequently becomes part of the application's audit, observability and error-correlation path.

---

# Request Metadata

The dependency layer also captures request metadata.

## Client IP

`get_client_ip()` returns the directly connected client address.

It deliberately does **not** trust `X-Forwarded-For` automatically. Proxy-header trust must instead be established through a known deployment configuration.

This avoids treating arbitrary client-controlled forwarding headers as trustworthy identity information.

## User Agent

The `User-Agent` header is normalized and bounded to 2048 characters before entering downstream processing/persistence.

---

# Bearer Authentication

The dependency layer defines the HTTP Bearer authentication scheme:

```text
Authorization: Bearer <access-token>
```

using FastAPI's `HTTPBearer`.

Authentication is not implemented by decoding a JWT directly inside the dependency.

Instead:

```text
Bearer Token
     │
     ▼
get_current_principal()
     │
     ▼
AuthenticateAccessTokenCommand
     │
     ▼
Application Authentication Service
     │
     ▼
AuthenticatedPrincipal
```

The application authentication service validates the access token and its session against current PostgreSQL state.

This is an important architectural boundary:

> `dependencies.py` extracts HTTP credentials; the application authentication service owns authoritative access-token/session validation.

---

# Authentication Context

After successful authentication, the trusted principal is stored on the request:

```text
request.state.authenticated_principal
request.state.actor_user_id
request.state.actor_role
```



This allows later middleware/dependencies and observability code to reuse the authenticated context without re-authenticating the same request.

---

# Role-Based Authorization

`require_roles()` creates reusable authorization dependencies.

```text
Current Principal
       │
       ▼
require_roles(...)
       │
       ├── allowed role?
       │       │
       │      yes
       │       ▼
       │    continue
       │
       └── no
            │
            ▼
           403
```

The dependency explicitly distinguishes:

```text
No/invalid authentication → 401

Authenticated but wrong role → 403
```



Predefined dependencies include:

```text
CustomerPrincipalDependency

SupportAgentPrincipalDependency
    support_agent OR admin

AdminPrincipalDependency
    admin only
```



This allows route declarations to remain concise:

```python
def endpoint(
    principal: AdminPrincipalDependency,
):
    ...
```

while keeping authorization behavior centralized.

---

# Browser Authentication

## `browser_auth.py`

`browser_auth.py` handles the browser-specific transport side of authentication.

The application authentication layer deals with refresh-token semantics; this module handles **how refresh material is transported through the browser**.

The refresh cookie is:

```text
support_ai_refresh
```

with the scope:

```text
/v1/auth
```



---

# Refresh Cookie Security

The refresh token is stored as an HTTP-only cookie.

```text
Browser
   │
   │ Cookie
   ▼
support_ai_refresh
   │
   ├── HttpOnly
   ├── SameSite=Lax
   ├── Secure according to environment
   ├── Path=/v1/auth
   └── Explicit expiry
```

The cookie is set with:

- `httponly=True`;
- `samesite="lax"`;
- environment-controlled `secure`;
- `/v1/auth` path;
- UTC-normalized expiry.

Frontend JavaScript therefore does not need to read or construct refresh tokens.

---

# Refresh Cookie Validation

Incoming refresh material is read only from:

```text
support_ai_refresh
```

The helper rejects:

- missing tokens;
- empty values;
- values exceeding the configured maximum length;
- values with surrounding whitespace.



When issuing a cookie, the value is additionally restricted to URL-safe alphanumeric characters plus `-` and `_`.

The browser layer therefore validates the **transport representation**, while the application authentication layer validates the token's actual meaning.

---

# Browser Origin Protection

Browser authentication mutations require exactly one authorized `Origin`.

```text
Browser Mutation
      │
      ▼
Origin header
      │
      ▼
Configured allowlist
      │
      ├── exactly one + allowed → continue
      │
      └── missing/multiple/untrusted → 403
```



This applies to browser authentication operations rather than general API requests.

---

# Authentication Response Caching

Authentication responses receive:

```text
Cache-Control:
no-store, no-cache, must-revalidate, private

Pragma:
no-cache

Expires:
0
```



This prevents credentials, authentication state or refresh-token operations from being accidentally cached by browsers or intermediaries.

---

# Refresh Request Body Protection

The dependency layer rejects legacy refresh request bodies before consuming the refresh cookie.

```text
POST /v1/auth/refresh

Body
  │
  ├── empty → continue
  │
  └── non-empty → 422
```



The refresh operation is therefore cookie-driven rather than accepting refresh material through a request body.

---

# `errors.py`

## Purpose

`errors.py` is the **central exception translation boundary** of the API.

Application/domain exceptions are allowed to propagate out of route handlers and are translated here into stable HTTP responses.

The module explicitly describes itself as the single boundary where internal/application exceptions become public HTTP responses.

The intended flow is:

```text
Application Exception
        │
        ▼
Registered Exception Handler
        │
        ├── HTTP status
        ├── Public error code
        ├── Safe message
        └── Trace ID
        │
        ▼
JSONResponse
```

This prevents individual route handlers from becoming filled with repetitive `try/except` blocks.

---

# Error Taxonomy

The error system groups failures by their **public API meaning**, rather than exposing every internal exception type directly.

Major categories include:

```text
Authentication
    invalid credentials
    invalid refresh token
    unauthenticated
    registration conflict

Conversations
    not found
    access denied
    invalid message
    invalid state
    AI timeout/unavailable/failure
    conversation-start conflicts

Escalations
    not found
    invalid operation
    lifecycle conflict
    customer status unavailable

Tickets
    not found
    related resource missing
    access denied
    invalid operation
    lifecycle conflict
    concurrent update

Feedback
    not found
    related resource missing
    access denied
    invalid operation
    conflict
    concurrent update

Knowledge
    not found
    access denied
    invalid operation
    lifecycle conflict
    upload errors
    processing/embedding failures

Dashboard
    invalid analytics window
    access denied
    temporary analytics unavailability

Users
    not found
    access denied
    access mutation conflict
```

The module defines stable public error-code constants for these categories.

---

# Canonical Error Envelope

All API errors are ultimately normalized into the same structure:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Safe public message.",
    "trace_id": "uuid"
  }
}
```

Validation failures may additionally contain:

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "The request contains invalid data.",
    "trace_id": "uuid",
    "details": [
      {
        "location": ["body", "email"],
        "message": "Invalid email.",
        "type": "value_error"
      }
    ]
  }
}
```

The internal construction helper guarantees that the trace ID appears both in the JSON body and the `X-Trace-ID` response header.

---

# Validation Error Normalization

FastAPI/Pydantic validation failures are converted into the same public error contract.

Instead of exposing FastAPI's native validation response shape, the handler extracts:

```text
location
message
type
```

for each validation failure.

This creates a consistent client-facing error contract across:

- malformed JSON;
- invalid path parameters;
- invalid query parameters;
- invalid request bodies;
- schema validation failures.

---

# HTTPException Normalization

Ordinary FastAPI `HTTPException` instances also pass through the centralized error envelope.

The handler supports structured details:

```python
{
    "code": "...",
    "message": "..."
}
```

and falls back to a generic public message when necessary.

This is particularly useful for dependencies such as trace-ID validation and browser-origin protection.

---

# Sensitive Error Handling

Internal exception details are **not automatically exposed to clients**.

For example, the customer-message validation handler explicitly avoids returning `str(exc)` because application exceptions may eventually contain internal information.

Likewise, the final catch-all handler logs the complete exception internally while returning only:

```text
500
INTERNAL_ERROR
An unexpected internal error occurred.
```



This establishes an important security boundary:

```text
Internal exception
       │
       ├── Full details → internal logs
       │
       └── Sanitized result → API client
```

---

# Trace ID Recovery

Exception handlers cannot always assume that normal request dependencies have already executed.

For example:

```text
Malformed request
       │
       ▼
Pydantic validation
       │
       ▼
Exception handler
       │
       └── Trace dependency may never have run
```

`_resolve_trace_id()` therefore:

1. reuses `request.state.trace_id` if valid;
2. otherwise generates a UUIDv7;
3. stores it back into request state.



This guarantees that even early failures receive a correlation ID.

---

# Domain-to-HTTP Translation

The exception registry contains mappings from many application/domain exceptions to public API handlers.

For example:

```text
TicketConcurrencyError
        │
        ▼
ticket_concurrency_handler
        │
        ▼
409 TICKET_CONCURRENT_UPDATE
```

and:

```text
CustomerMessagePipelineTimeoutError
        │
        ▼
customer_message_pipeline_timeout_handler
        │
        ▼
504 AI_PROVIDER_TIMEOUT
```

 

This keeps internal exception naming independent from the public API contract.

---

# AI Failure Translation

AI pipeline failures receive deliberately safe public semantics.

```text
AI timeout
    → 504 AI_PROVIDER_TIMEOUT

AI unavailable
    → 503 AI_SERVICE_UNAVAILABLE

AI pipeline failure
    → 500 AI_PIPELINE_FAILED
```



The API does not expose provider-specific diagnostics to the customer.

---

# Knowledge Upload Errors

Knowledge-management upload failures are translated into meaningful HTTP categories:

```text
Invalid upload
    → 400

Too large
    → 413

Unsupported media type
    → 415
```



This gives clients actionable transport semantics while keeping the deeper knowledge subsystem's exceptions internal.

---

# Concurrency and Lifecycle Errors

The API preserves important state/conflict semantics.

For example:

```text
Ticket concurrent update
    → 409 TICKET_CONCURRENT_UPDATE

Knowledge lifecycle conflict
    → 409 KNOWLEDGE_CONFLICT

Conversation-start idempotency conflict
    → 409 CONVERSATION_START_CONFLICT

Conversation-start lease lost
    → 503 CONVERSATION_START_UNAVAILABLE
```

The last case also provides a bounded retry signal through:

```text
Retry-After: 2
```



This allows clients to distinguish a conflict from temporary inability to confirm processing.

---

# `openapi_contract.py`

## Purpose

`openapi_contract.py` ensures the generated OpenAPI document reflects the **actual transport/security behavior** of the API.

It does not define endpoint business behavior.

Instead, it takes an OpenAPI schema and applies confirmed cross-cutting transport rules.

```text
FastAPI Generated OpenAPI
           │
           ▼
apply_transport_contract()
           │
           ├── Error responses
           ├── Security schemes
           ├── Trace headers
           ├── Auth cache headers
           ├── Browser Origin requirements
           ├── Refresh-cookie behavior
           └── Analytics retry behavior
           │
           ▼
Contract-accurate OpenAPI
```



---

# Canonical API Error Schema

The OpenAPI contract requires:

```text
APIErrorResponse
```

to exist.

If it does not, contract generation fails:

```text
RuntimeError:
The canonical API error schema is missing.
```



This ensures that documented API errors remain aligned with the runtime error infrastructure.

---

# OpenAPI Error Responses

The transport contract automatically adds common error responses where appropriate:

```text
400
500
401 for Bearer-authenticated operations
```

and normalizes generic error responses to reference the canonical API error schema.

Explicit domain-specific response schemas are preserved when they are intentionally defined.

This is important because OpenAPI should document the same public error model clients actually receive.

---

# Trace Header Documentation

The OpenAPI contract documents:

```text
X-Trace-ID
```

as a UUID response header for API errors/responses where appropriate.

This makes correlation behavior visible to API consumers instead of leaving it as an undocumented implementation detail.

---

# Authentication Cache Policy

Authentication endpoints receive explicit OpenAPI documentation for:

```text
Cache-Control
Pragma
Expires
```

with non-caching semantics.

This mirrors the runtime behavior implemented by `browser_auth.py`.

Thus:

```text
Runtime
   └── set_sensitive_response_headers()

Documentation
   └── openapi_contract.py
```

remain aligned.

---

# RefreshCookie Security Scheme

The OpenAPI document defines:

```text
RefreshCookie
```

as an API-key-style cookie security scheme.

The cookie is:

```text
support_ai_refresh
```

and is described as HTTP-only browser authentication material.

The refresh endpoint is then explicitly changed to:

```text
security:
  RefreshCookie
```

with no request body.

This prevents the API documentation from incorrectly suggesting that refresh tokens should be passed through JSON.

---

# Browser Mutation Origin Contract

The following authentication operations are treated as browser mutations:

```text
/v1/auth/register
/v1/auth/login
/v1/auth/refresh
/v1/auth/logout
```



OpenAPI explicitly documents an `Origin` header for these operations.

The documented rule is:

```text
Exactly one Origin
        │
        ▼
Configured allowlist
        │
        ├── trusted → allowed
        └── missing/untrusted → 403
```



The frontend does not manually construct this browser header.

---

# Authentication Cookie Lifecycle in OpenAPI

The contract documents the refresh-cookie lifecycle:

```text
Register
    └── Set-Cookie

Login
    └── Set-Cookie

Refresh
    ├── Set-Cookie on success
    └── delete cookie on invalid refresh token

Logout
    └── delete cookie
```



The documentation describes:

- HttpOnly;
- SameSite=Lax;
- `/v1/auth` path;
- environment-sensitive Secure behavior;
- server-controlled expiry;
- JavaScript inaccessibility.

---

# Analytics Retry Contract

Selected dashboard analytics paths receive:

```text
Retry-After: 5
```

when returning a `503` caused by an analytics timeout.

This is a small but important transport-level contract:

```text
Analytics timeout
      │
      ▼
503 Service Unavailable
      │
      └── Retry-After: 5
```

Clients can therefore implement bounded retry behavior without guessing an appropriate delay.

---

# How the Four Infrastructure Files Work Together

The core relationship is:

```text
                    Incoming Request
                           │
                           ▼
                   dependencies.py
                           │
             ┌─────────────┼──────────────┐
             ▼             ▼              ▼
         Trace ID      Authentication   Metadata
             │             │
             │             ▼
             │        Application Auth
             │
             ▼
                       v1 Router
                           │
                           ▼
                   Application Service
                           │
                 ┌─────────┴─────────┐
                 │                   │
              Success              Error
                 │                   │
                 ▼                   ▼
             HTTP Response       errors.py
                                     │
                                     ▼
                              APIErrorResponse
                                     │
                                     ▼
                                  Client
```

At the same time:

```text
Runtime behavior
       │
       ▼
openapi_contract.py
       │
       ▼
Documented OpenAPI behavior
```

and:

```text
Browser auth request
       │
       ▼
browser_auth.py
       │
       ├── Origin
       ├── Refresh cookie
       ├── Cache policy
       └── Cookie lifecycle
```

---

# Cross-Cutting Security Model

The API infrastructure implements several complementary security boundaries.

## Authentication

```text
Bearer access token
        │
        ▼
AuthenticateAccessTokenCommand
        │
        ▼
AuthenticatedPrincipal
```

## Authorization

```text
AuthenticatedPrincipal
        │
        ▼
require_roles(...)
        │
        ▼
Endpoint access
```

## Browser Refresh Security

```text
HTTP-only cookie
        +
Origin allowlist
        +
SameSite policy
        +
Secure policy
```

## Error Sanitization

```text
Internal Exception
        │
        ├── detailed internal logging
        │
        └── sanitized public response
```

## Traceability

```text
X-Trace-ID
    │
    ▼
Request State
    │
    ▼
Application
    │
    ▼
Audit / Logs / API Response
```

---

# Dependency Direction

The intended dependency direction is:

```text
apps/api/app/api/
        │
        ├── depends on ──► packages/application/
        │
        ├── depends on ──► packages/config/
        │
        └── exposes ─────► v1/
```

The application layer should not depend on FastAPI-specific infrastructure.

For example:

```text
GOOD

FastAPI dependency
      │
      ▼
Application Service
      │
      ▼
Domain / Repository


AVOID

Application Service
      │
      └── FastAPI Request / Response
```

The v1 layer follows the same principle: it converts HTTP concerns into application commands/queries and delegates behavior to the application layer.

---

# Error Handling Philosophy

The API infrastructure follows several important rules.

### Internal exceptions remain internal

Application exception names should not automatically become API error messages.

### Public codes are stable

Clients should depend on:

```text
ERROR_CODE
HTTP status
response shape
```

rather than Python exception class names.

### Trace IDs are always available

Even failures occurring before normal dependency execution receive a trace ID.

### Detailed diagnostics belong in logs

The catch-all handler logs the complete exception but exposes only a generic public message.

### Routes should not duplicate exception translation

Known application exceptions should normally propagate to `errors.py`.

---

# Relationship with `v1/`

The hierarchy is:

```text
apps/api/app/api/
│
├── browser_auth.py
├── dependencies.py
├── errors.py
├── openapi_contract.py
│
└── v1/
    │
    ├── router.py
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
```

The distinction is:

```text
api/
    "How should HTTP infrastructure behave?"

api/v1/
    "Which HTTP operations does version 1 expose?"

api/v1/schemas/
    "What exact request/response shapes does v1 expose?"
```

The existing v1 README documents that lower layer in detail; this README therefore focuses on the shared infrastructure above it.

---

# Typical Request Lifecycle

A complete authenticated request can be viewed as:

```text
1. HTTP request
        │
        ▼
2. FastAPI application
        │
        ▼
3. Trace ID resolution
        │
        ├── supplied valid X-Trace-ID
        └── generated UUIDv7
        │
        ▼
4. Authentication dependency
        │
        ▼
5. Access-token/session validation
        │
        ▼
6. Role authorization
        │
        ▼
7. v1 route
        │
        ▼
8. Pydantic request schema
        │
        ▼
9. Application command/query
        │
        ▼
10. Application service
        │
        ▼
11. Result
        │
        ▼
12. Pydantic response schema
        │
        ▼
13. HTTP response
```

If any known exception occurs:

```text
                 Exception
                     │
                     ▼
              errors.py
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
    Public response       Internal logging
          │
          ▼
       Client
```

---

# Design Principles

## Thin API Infrastructure

Shared infrastructure should provide mechanisms, not business workflows.

## Centralized Authentication

Credential extraction happens at the HTTP boundary, while authoritative authentication remains in the application layer.

## Centralized Authorization

Role dependencies should be reusable and consistent across endpoints.

## Stable Error Contracts

Every public error should have a predictable HTTP status, public code, message and trace ID.

## Secure Browser Authentication

Refresh material remains in HTTP-only cookies and is protected with appropriate origin, cache, path and SameSite controls.

## Observable Requests

Every request should have a correlation identifier that can connect HTTP activity with application and infrastructure telemetry.

## Documentation Matches Runtime

OpenAPI must describe the actual transport behavior rather than merely reflecting raw FastAPI defaults.

## No Leakage of Internal State

Application exceptions, provider errors, persistence details and diagnostics should not accidentally become public API responses.

---

# Mental Model

The easiest way to remember this package is:

```text
                       apps/api/app/api/
                               │
          ┌────────────────────┼─────────────────────┐
          │                    │                     │
          ▼                    ▼                     ▼
   dependencies.py       browser_auth.py        errors.py
          │                    │                     │
          │              Browser auth         Exception mapping
          │                    │                     │
          └──────────────┬─────┴─────────────────────┘
                         │
                         ▼
                      v1 API
                         │
                         ▼
                 Application Services
                         │
                         ▼
                    Domain / AI
                         │
                         ▼
                    Persistence

                         ▲
                         │
                 openapi_contract.py
                         │
                         ▼
                API contract/documentation
```

In short:

> **`apps/api/app/api/` is the shared HTTP infrastructure boundary: it assembles request context, authenticates and authorizes callers, secures browser authentication transport, translates internal failures into stable API errors, and keeps the OpenAPI contract aligned with actual runtime behavior.**

The `v1/` package then builds the concrete versioned API on top of these primitives.