# API Middleware

## Overview

The `apps/api/app/middleware/` package contains the **ASGI/Starlette middleware responsible for cross-cutting HTTP concerns** that must apply around the API request lifecycle.

The current middleware layer has two responsibilities:

- browser-facing security and CORS policy;
- request-level observability and API request recording.

```text
                         HTTP Request
                              │
                              ▼
                  ┌───────────────────────┐
                  │   API Middleware      │
                  │                       │
                  │ Browser Security      │
                  │ Request Observability │
                  └───────────┬───────────┘
                              │
                              ▼
                       FastAPI / API v1
                              │
                              ▼
                    Application Services
```

The middleware deliberately stays outside business logic. It observes and controls the HTTP boundary while delegating application behavior to the existing API/application layers.

---

# Directory Structure

```text
apps/api/app/middleware/
│
├── browser_security.py
└── request_observability.py
```

| File | Responsibility |
|---|---|
| `browser_security.py` | CORS policy and browser-specific response cache protection |
| `request_observability.py` | Trace IDs, request metrics, response observation and API request persistence |

---

# Architectural Role

The middleware layer sits between the ASGI server/FastAPI application and the application/API layers:

```text
Client
  │
  ▼
ASGI Server
  │
  ▼
apps/api/app/middleware/
  │
  ├── BrowserSecurityMiddleware
  │
  └── RequestObservabilityMiddleware
  │
  ▼
FastAPI
  │
  ▼
API dependencies / v1 routes
  │
  ▼
Application Services
```

These components should remain **cross-cutting infrastructure**, not feature-specific business logic.

---

# `browser_security.py`

## Purpose

```text
apps/api/app/middleware/browser_security.py
```

`BrowserSecurityMiddleware` applies browser-level HTTP security policy around the FastAPI application.

Its primary responsibilities are:

- configure CORS from application settings;
- allow credentialed browser requests;
- restrict HTTP methods and headers;
- expose trace/retry response headers;
- apply `no-store` caching headers to authentication endpoints.

---

## CORS Configuration

The middleware lazily creates a Starlette `CORSMiddleware`.

Configuration comes from:

```text
Settings.browser_allowed_origins
```

and is configured with:

```text
allow_credentials = true

methods:
    GET
    POST
    PATCH
    OPTIONS

request headers:
    Authorization
    Content-Type
    X-Trace-ID
    Idempotency-Key

exposed response headers:
    X-Trace-ID
    Retry-After

max_age:
    600 seconds
```



Conceptually:

```text
Browser
   │
   │ Origin
   ▼
BrowserSecurityMiddleware
   │
   ▼
Configured browser origins
   │
   ├── allowed → request continues
   └── disallowed → CORS policy blocks browser access
```

The middleware does not hard-code deployment-specific origins; it obtains them from `Settings`.

---

# Credentialed Browser Requests

The CORS configuration explicitly enables:

```text
allow_credentials=True
```

This is required for browser flows involving authentication cookies.

The middleware therefore forms part of the broader browser-authentication architecture:

```text
Browser
   │
   ├── Authorization
   ├── Cookies
   └── Origin
        │
        ▼
BrowserSecurityMiddleware
        │
        ▼
FastAPI
```

Cookie issuance and authentication semantics themselves remain in the API authentication layer rather than this middleware.

---

# Authentication Cache Protection

Authentication endpoints receive explicit response cache prevention.

The middleware identifies:

```text
/v1/auth
/v1/auth/*
```

as authentication paths.

For response-start messages on these paths, it adds:

```http
Cache-Control: no-store, no-cache, must-revalidate, private
Pragma: no-cache
Expires: 0
```



The purpose is to prevent sensitive authentication responses from being cached by browsers or intermediaries.

```text
Authentication Response
        │
        ▼
BrowserSecurityMiddleware
        │
        ├── Cache-Control: no-store
        ├── Pragma: no-cache
        └── Expires: 0
```

---

# Lifespan Safety

Non-HTTP ASGI scopes are passed directly through:

```text
lifespan
websocket
other non-HTTP scope
        │
        ▼
underlying application
```

The middleware intentionally avoids resolving browser settings for these scopes.

This is important because application settings may not be available until FastAPI's startup/lifespan initialization has occurred.

---

# `request_observability.py`

## Purpose

```text
apps/api/app/middleware/request_observability.py
```

`RequestObservabilityMiddleware` records HTTP request execution information using a stable trace identifier.

It observes:

- HTTP method;
- route/path;
- route template;
- route name;
- status code;
- error code;
- exception type;
- actor identity/role;
- client IP;
- user agent;
- request size;
- response size;
- latency;
- start/completion timestamps;
- basic HTTP metadata.

The middleware explicitly avoids persisting sensitive request/response content such as:

- request bodies;
- response bodies;
- cookies;
- authorization headers;
- arbitrary query parameters.

---

# Trace ID Handling

The middleware participates in the API's `X-Trace-ID` correlation mechanism.

```text
Incoming Request
      │
      ▼
X-Trace-ID
      │
      ├── missing → generate UUIDv7
      │
      ├── valid UUID → reuse it
      │
      └── invalid → generate replacement + 400
```

The resulting trace ID is stored in ASGI request state:

```text
scope["state"]["trace_id"]
```



This gives the request a stable identifier that can connect:

```text
HTTP request
    │
    ├── API response
    ├── application execution
    ├── audit/observability
    └── persisted API request record
```

---

# Invalid Trace IDs

A supplied trace ID must be a valid UUID.

Empty values are rejected, and malformed UUID values are rejected as well.

The middleware produces:

```text
HTTP 400
```

with an error envelope containing:

```text
INVALID_TRACE_ID
```

and the generated replacement trace ID.

This means malformed correlation metadata cannot silently propagate through the application.

---

# Response Observation

The middleware wraps the ASGI `send()` function to observe outgoing responses.

For `http.response.start`, it captures:

- status code;
- route template;
- route name;

and ensures the response contains:

```http
X-Trace-ID: <trace-id>
```



Thus the client can correlate its response with server-side logs and persisted observability data.

---

# Response Size and Error Inspection

The middleware counts response body bytes:

```text
response_size_bytes
```

but does not generally retain response bodies.

Only error responses are inspected, and only up to:

```text
64 KiB
```

for extracting a stable API error code.

This is an important privacy/security boundary:

```text
Successful response
    │
    └── size only

Error response
    │
    └── bounded prefix
            │
            ▼
        error.code
```

Authentication responses containing access/refresh tokens therefore do not need to be copied into middleware memory merely for observability.

---

# Error Code Extraction

For error responses, the middleware attempts to parse the standard API error envelope:

```json
{
  "error": {
    "code": "..."
  }
}
```

and extracts the normalized uppercase error code.

If a server-side failure reaches `500` without an explicit API error code, it records:

```text
INTERNAL_ERROR
```



This allows observability records to correlate HTTP failures with the same stable public error taxonomy used by the API.

---

# Route Information

The middleware records both:

```text
route_template
route_name
```

rather than relying exclusively on the concrete request path.

For example:

```text
Concrete path:
/v1/tickets/8f2.../comments

Route template:
/v1/tickets/{ticket_id}/comments
```

Path parameters are replaced with placeholders when a matched endpoint is available. Unmatched paths such as ordinary 404s are not incorrectly treated as route templates.

This makes persisted request statistics useful for endpoint-level analysis.

---

# Actor Context

The middleware can reuse authentication context previously placed into ASGI request state:

```text
actor_user_id
actor_role
```

Only recognized roles are accepted:

```text
customer
support_agent
admin
system
```



This allows API request records to answer questions such as:

```text
Which authenticated actor made this request?
Which role made it?
```

without storing authentication credentials.

---

# Request Metadata

The middleware captures bounded request metadata.

## User Agent

The user agent is normalized and limited to:

```text
2048 characters
```



## Client IP

The directly connected client address is captured and limited to:

```text
45 characters
```



The middleware does not attempt to infer trusted proxy identity from arbitrary forwarding headers.

## Request Size

`Content-Length` is parsed when available.

Invalid, negative or missing values result in:

```text
None
```

rather than an invented size.

---

# API Request Persistence

The middleware delegates persistence to the application layer rather than directly accessing a repository.

```text
RequestObservabilityMiddleware
          │
          ▼
ApplicationServices
          │
          ▼
record_api_request
          │
          ▼
RecordAPIRequestCommand
          │
          ▼
Application / Repository
```

The command contains the observed HTTP metadata, including trace ID, route, status, actor, sizes and timing information.

This preserves the dependency direction:

```text
    Middleware
        │
        ▼
Application Service
        │
        ▼
    Persistence
```

rather than making the HTTP middleware database-aware.

---

# Best-Effort Observability

API request recording is intentionally **best-effort**.

If the recorder is unavailable:

```text
Request completes
      │
      ▼
Recorder unavailable
      │
      ├── warning logged
      └── API response unaffected
```



If persistence itself fails:

```text
Persistence failure
      │
      ├── exception logged
      └── API response unaffected
```



This is critical: observability must not become a dependency that can take down the customer-facing API.

---

# Synchronous Persistence Off the Event Loop

The recorder execution is moved to a worker thread:

```text
await to_thread.run_sync(...)
```



The purpose is to avoid blocking the async request event loop with synchronous persistence work.

```text
Async Request
     │
     ▼
Request Middleware
     │
     ├── API processing
     │
     └── recording
           │
           ▼
       worker thread
           │
           ▼
      synchronous recorder
```

---

# Middleware Interaction

The two middleware components address different concerns:

```text
                     HTTP Request
                          │
                          ▼
             ┌────────────────────────┐
             │    Browser Security    │
             │                        │
             │ CORS                   │
             │ Auth cache headers     │
             └────────────┬───────────┘
                          │
                          ▼
             ┌────────────────────────┐
             │ Request Observability  │
             │                        │
             │ Trace ID               │
             │ Timing                 │
             │ Status                 │
             │ Error code             │
             │ Actor context          │
             │ API request recording  │
             └────────────┬───────────┘
                          │
                          ▼
                       FastAPI
                          │
                          ▼
                       API v1
```

The exact middleware registration order is determined by the API application's startup/composition configuration.

---

# Relationship with API Dependencies

`RequestObservabilityMiddleware` shares the canonical trace header definition from:

```text
apps/api/app/api/dependencies.py
```

rather than defining a second trace-header constant.

This is important because both layers must agree on:

```text
X-Trace-ID
```

```text
API Dependencies
       │
       └── TRACE_HEADER_NAME
                  ▲
                  │
                  └── RequestObservabilityMiddleware
```

The middleware also consumes authentication state established by the API authentication dependencies:

```text
dependencies.py
    │
    ├── actor_user_id
    └── actor_role
          │
          ▼
RequestObservabilityMiddleware
```

---

# Relationship with Application Observability

The middleware is the HTTP-facing entry point into the application observability subsystem.

```text
            HTTP Request
                │
                ▼
  RequestObservabilityMiddleware
                │
                ▼
     RecordAPIRequestCommand
                │
                ▼
packages/application/observability/
                │
                ▼
        API request recording
```

The middleware therefore collects transport-level facts, while the application observability layer owns the application-level recording behavior.

---

# Security and Privacy Boundary

The middleware deliberately follows a **metadata-first observability model**.

Persisted/recorded data includes:

```text
Trace ID
HTTP method
Route
Status
Error code
Actor identity
Actor role
Client IP
User agent
Request size
Response size
Latency
Timestamps
Basic HTTP metadata
```

It deliberately avoids persisting:

```text
Request body
Response body
Cookies
Authorization headers
Arbitrary query parameters
```



This is particularly important because API requests may contain:

- passwords;
- access tokens;
- refresh tokens;
- customer messages;
- uploaded knowledge content;
- other potentially sensitive data.

---

# Design Principles

## 1. Middleware Is Cross-Cutting Infrastructure

Feature-specific behavior belongs in API routes/application services, not here.

## 2. Security Policy Is Centralized

CORS and authentication-response cache behavior should not be manually repeated across individual routes.

## 3. Traceability Is End-to-End

The same `X-Trace-ID` participates in request processing, responses and observability records.

## 4. Observability Must Not Break the API

Failure to persist an API request is logged but does not alter the customer's response.

## 5. Avoid Sensitive Payload Capture

Observability records should contain useful metadata without becoming a copy of customer/API traffic.

## 6. Keep the Async Event Loop Responsive

Synchronous observability persistence is moved off the async event loop.

## 7. Delegate Business Persistence

Middleware should create application commands and invoke application services rather than directly manipulating repositories or database sessions.

---

# Typical Request Lifecycle

```text
                    Incoming HTTP Request
                              │
                              ▼
                 BrowserSecurityMiddleware
                              │
                    ┌─────────┴─────────┐
                    │                   │
                 CORS check       Auth cache policy
                    │                   │
                    └─────────┬─────────┘
                              ▼
                RequestObservabilityMiddleware
                              │
                              ├── Resolve trace ID
                              ├── Store trace ID
                              ├── Start timer
                              │
                              ▼
                         FastAPI / v1
                              │
                              ▼
                        API dependencies
                              │
                              ▼
                      Application Service
                              │
                              ▼
                           Response
                              │
                              ▼
                RequestObservabilityMiddleware
                              │
                    ┌─────────┴─────────┐
                    │                   │
               Add X-Trace-ID      Measure result
                    │                   │
                    └─────────┬─────────┘
                              ▼
                      Record API request
                          best effort
                              │
                              ▼
                           Client
```

---

# Summary

`apps/api/app/middleware/` provides the API's **HTTP-level cross-cutting controls**.

```text
browser_security.py
    └── Browser security
        ├── CORS
        ├── credentials
        ├── allowed headers/methods
        └── authentication cache protection

request_observability.py
    └── HTTP observability
        ├── Trace IDs
        ├── response observation
        ├── latency / sizes
        ├── actor context
        ├── error codes
        └── best-effort API request recording
```

Together they enforce the principle:

> **Security and observability should surround the API request lifecycle without becoming part of the application's business logic—and observability failures must never become customer-facing API failures.**