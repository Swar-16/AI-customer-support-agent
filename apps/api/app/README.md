# API Application Layer

## Overview

The `apps/api/app/` package is the **composition and runtime boundary of the HTTP API** for the AI Customer Support Agent.

It brings together:

- API routing;
- application bootstrap;
- HTTP middleware;
- exception handling;
- OpenAPI transport contracts;
- application lifecycle management.

The package does not contain the core business logic itself. Instead, it connects the HTTP/API boundary with the application services provided by `packages/application`.

```text
                    API Client
                        │
                        ▼
              ┌──────────────────┐
              │  apps/api/app/   │
              │                  │
              │  FastAPI App     │
              └────────┬─────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       Middleware    Routing     Exceptions
          │            │            │
          └────────────┼────────────┘
                       ▼
              Application Services
                       │
                       ▼
              packages/application
```

---

# Directory Structure

At this level, the API application is organized into focused infrastructure boundaries:

```text
apps/api/app/
│
├── api/
│   ├── errors.py
│   ├── openapi_contract.py
│   ├── dependencies.py
│   └── v1/
│       └── ...
│
├── bootstrap/
│   └── application.py
│
├── middleware/
│   ├── browser_security.py
│   └── request_observability.py
│
└── main.py
```

Each area has a deliberately different responsibility.

| Area | Responsibility |
|---|---|
| `main.py` | Creates and owns the FastAPI application |
| `api/` | HTTP contracts, dependencies, errors and versioned routes |
| `bootstrap/` | Constructs long-lived application services |
| `middleware/` | Cross-cutting HTTP security and observability |

The detailed behavior of each lower-level package belongs in its respective README.

---

# `main.py`

`main.py` is the **API composition root**.

It creates the FastAPI application and connects the major API subsystems:

```text
main.py
   │
   ├── Runtime configuration
   ├── Application services
   ├── Middleware
   ├── API routers
   ├── Exception handlers
   └── OpenAPI transport contract
```

The application metadata currently identifies the service as:

```text
AI Customer Support API
version: 1.0.0
```

with the standard OpenAPI, Swagger and ReDoc endpoints configured.

---

# Application Factory

The public application factory is:

```python
create_api_app()
```

It creates a `BrowserReadyFastAPI` instance and then registers the API's major components.

```text
create_api_app()
      │
      ├── Create FastAPI application
      │
      ├── Register routers
      │
      ├── Register middleware
      │
      └── Register exception handlers
              │
              ▼
         FastAPI application
```

The factory approach keeps application construction explicit and makes isolated application instances possible for testing.

---

# Application Startup

The FastAPI lifespan handler manages process startup and shutdown.

During startup it:

1. resolves runtime settings;
2. constructs/loads application services;
3. fails fast if composition fails;
4. exposes both through `app.state`.



```text
API startup
    │
    ▼
get_runtime_settings()
    │
    ▼
Settings
    │
    ▼
get_application_services()
    │
    ▼
ApplicationServices
    │
    ▼
app.state
```

The application therefore has one clear process-level composition boundary.

---

# Application Shutdown

Shutdown currently performs lightweight cleanup.

The references stored in:

```text
app.state.application_services
app.state.settings
```

are removed.

The bootstrap cache itself is intentionally not cleared during ordinary shutdown because ownership of that cache remains with the bootstrap layer.

Request-scoped database sessions are not managed here; they belong to the request lifecycle.

---

# API Routing

The API routing tree is registered through:

```text
api/v1/router.py
```

and included by `main.py`.

The hierarchy is therefore:

```text
FastAPI Application
       │
       ▼
   v1 Router
       │
       ├── Authentication
       ├── Users
       ├── Conversations
       ├── Tickets
       ├── Knowledge
       ├── Feedback
       ├── Escalations
       └── other API resources
```

Version-specific route ownership remains inside `api/v1/`, keeping `main.py` independent of individual endpoints.

---

# Middleware

Process-wide HTTP middleware is registered centrally from `main.py`.

Currently the application includes:

```text
RequestObservabilityMiddleware
```

while `BrowserSecurityMiddleware` is integrated through the custom FastAPI subclass.

Conceptually:

```text
HTTP Request
     │
     ▼
Browser Security
     │
     ▼
Request Observability
     │
     ▼
FastAPI Routing
     │
     ▼
Application Services
```

The middleware layer handles cross-cutting HTTP concerns rather than feature-specific business behavior.

---

# Browser-Aware FastAPI

The application uses:

```text
BrowserReadyFastAPI
```

as a small specialization of FastAPI.

Its purpose is to ensure browser response policy can be applied outside FastAPI's normal error middleware and to provide the browser security middleware with runtime settings.

It also overrides OpenAPI generation so the project's transport contract can be applied:

```text
FastAPI OpenAPI schema
        │
        ▼
apply_transport_contract(...)
        │
        ▼
API OpenAPI schema
```



---

# Exception Handling

API-wide exception mappings are registered during application construction:

```text
_register_exception_handlers()
        │
        ▼
register_api_exception_handlers()
```



This keeps domain/application exceptions separate from their HTTP representation.

```text
Application / Domain Error
          │
          ▼
API Exception Handler
          │
          ▼
HTTP Error Response
```

Individual business services therefore do not need to know about FastAPI response mechanics.

---

# Dependency Direction

The API application sits at the outer edge of the architecture.

```text
                apps/api/app/
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
        Routes   Middleware   API errors
          │
          ▼
    Application Services
          │
          ▼
 packages/application
          │
          ▼
 packages/database / knowledge / providers
```

The API layer should **consume application abstractions**, not reimplement application workflows.

---

# Lifecycle Model

The complete process lifecycle can be viewed as:

```text
                    Process Start
                         │
                         ▼
                  create_api_app()
                         │
             ┌───────────┼───────────┐
             ▼           ▼           ▼
          Routers     Middleware   Errors
             │           │           │
             └───────────┼───────────┘
                         ▼
                    FastAPI App
                         │
                         ▼
                    lifespan()
                         │
                         ▼
                  Runtime Settings
                         │
                         ▼
                Application Services
                         │
                         ▼
                    app.state
                         │
                         ▼
                  Serve Requests
                         │
                         ▼
                  Process Shutdown
                         │
                         ▼
                  State Cleanup
```

---

# Request Lifecycle

A typical request flows through the package like this:

```text
Client
  │
  ▼
ASGI Server
  │
  ▼
Browser Security
  │
  ▼
Request Observability
  │
  ▼
API Dependencies
  │
  ▼
Versioned Router
  │
  ▼
Endpoint
  │
  ▼
Application Service
  │
  ▼
Infrastructure
  │
  ▼
Response
  │
  ▼
Observability
  │
  ▼
Client
```

The API package therefore acts primarily as a **transport adapter and composition boundary**.

---

# State and Lifetime Rules

The application distinguishes between process-level and request-level state.

### Process/application scope

```text
Settings
ApplicationServices
FastAPI application
```

These are initialized during application startup and made available through `app.state`.

### Request scope

```text
Database Session
Unit of Work
AI Run
Request-specific context
```

These must remain request-scoped and should not be placed into the process-wide application container.

This separation is important for concurrency, resource management and test isolation.

---

# Design Principles

## Thin API Layer

The API should translate HTTP concerns into application calls rather than contain business workflows.

## Explicit Composition

All major API components are assembled through `create_api_app()`.

## Centralized Lifecycle

Startup and shutdown behavior is owned by the FastAPI lifespan handler.

## Versioned Routing

API versioning remains under `api/v1/`, keeping the application entry point stable.

## Cross-Cutting Middleware

Security and observability are applied centrally rather than duplicated across endpoints.

## Stable Transport Contracts

OpenAPI and exception handling are centralized so external clients receive consistent HTTP behavior.

## Application/Infrastructure Separation

The API depends on application services rather than directly coordinating database, knowledge, AI or provider internals.

---

# Running Mental Model

The easiest way to understand `apps/api/app/` is:

```text
                 HTTP WORLD
                     │
                     ▼
              ┌─────────────┐
              │   main.py   │
              └──────┬──────┘
                     │
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
   Middleware      Routing      Errors
       │             │             │
       └─────────────┼─────────────┘
                     ▼
             Application Layer
                     │
                     ▼
              Infrastructure
```

In short:

> **`apps/api/app/` is the runtime boundary of the HTTP service. It constructs the FastAPI application, manages its lifecycle, installs cross-cutting middleware and API contracts, exposes versioned routes, and delegates actual application behavior to the underlying application layer.**