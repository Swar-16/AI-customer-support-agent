# API Bootstrap

## Overview

The `bootstrap/` package contains the **process-startup composition layer** for the API.

Its responsibility is deliberately narrow: it resolves the runtime configuration and constructs the long-lived `ApplicationServices` container required by the API process.

```text
API Process Startup
        │
        ▼
apps/api/app/bootstrap/
        │
        ├── Resolve runtime settings
        │
        ├── Construct ApplicationServices
        │
        └── Cache process-wide dependencies
                │
                ▼
        ApplicationServices
                │
                ▼
          API / v1 routes
```

The bootstrap layer does **not** execute application workflows or handle request-scoped resources.

---

# Directory Structure

```text
apps/api/app/bootstrap/
│
├── README.md
└── application.py
```

`application.py` is the startup composition entry point for this package.

---

# `application.py`

## Responsibility

`application.py` owns **process startup composition only**.

Its primary responsibilities are:

1. Resolve the API runtime environment.
2. Load the corresponding `Settings`.
3. Construct the long-lived `ApplicationServices` container.
4. Convert application-composition failures into an API-specific bootstrap error.
5. Cache process-wide settings and services.
6. Provide a controlled mechanism for clearing those caches during tests or controlled reinitialization.

The module deliberately avoids request processing and external work during bootstrap.

---

# Runtime Settings

Runtime configuration is resolved through:

```python
get_runtime_settings()
```

The environment is obtained from:

```text
APP_ENV
```

with:

```text
development
```

as the default when the environment variable is absent.

The environment value is normalized using `strip().lower()` and then passed to the central `get_settings()` configuration mechanism.

Conceptually:

```text
APP_ENV
   │
   ├── present → normalize
   │
   └── absent → development
          │
          ▼
     get_settings()
          │
          ▼
       Settings
```

The resolved settings are cached with `lru_cache(maxsize=1)`, so the API process uses one runtime settings instance for this bootstrap path.

---

# Application Service Construction

The main construction function is:

```text
build_application_services()
```

Its job is to construct the long-lived application service container.

```text
Settings
   │
   ▼
create_application()
   │
   ▼
ApplicationServices
```

The function can receive an explicit `Settings` instance:

```python
build_application_services(settings=...)
```

or resolve the runtime settings automatically when no settings object is supplied.

The supplied value must be a `Settings` instance; otherwise a `TypeError` is raised.

---

# Composition Boundary

The actual construction is delegated to:

```text
packages.application.composition.application_factory
```

through:

```text
create_application(settings=resolved_settings)
```

The bootstrap module therefore does not know how each individual application service is constructed.

```text
apps/api/app/bootstrap/
        │
        │ settings
        ▼
application_factory
        │
        ▼
ApplicationServices
```

This keeps process startup separate from the detailed application composition logic.

---

# Bootstrap Error Handling

Startup/composition failures are translated into:

```text
APIBootstrapError
```

which extends `RuntimeError`.

This exception represents a **process startup/configuration failure**, not a normal request-level API failure.

The flow is:

```text
create_application()
        │
        ├── success
        │      │
        │      ▼
        │ ApplicationServices
        │
        └── failure
               │
               ▼
        APIBootstrapError
```

The original exception is preserved as the cause:

```python
raise APIBootstrapError(
    "Failed to initialize application services"
) from exc
```

This gives the bootstrap layer a stable failure type while retaining the underlying exception for diagnostics.

---

# Process-Wide Application Services

The public process-level accessor is:

```text
get_application_services()
```

It is also cached using:

```text
@lru_cache(maxsize=1)
```

Therefore, within a running API process:

```text
First call
    │
    ▼
build_application_services()
    │
    ▼
ApplicationServices
    │
    ▼
cache

Subsequent calls
    │
    ▼
same ApplicationServices instance
```



This is appropriate because the returned container consists of long-lived dependencies rather than request-specific state.

---

# Long-Lived vs Request-Scoped Objects

One of the most important responsibilities of this bootstrap boundary is maintaining the distinction between **process-scoped dependencies** and **request-scoped resources**.

The process-wide container may retain long-lived components such as:

```text
Base provider
Pipeline factory
Orchestration observer
Application services
```

while request-scoped objects are created later:

```text
SQLAlchemy Session
UnitOfWork
AI run
TelemetryRecorder
InstrumentedLLMProvider
```



The architectural rule is therefore:

```text
Process lifetime
      │
      └── ApplicationServices
              │
              ├── long-lived dependencies
              │
              └── factories/services
                      
Request lifetime
      │
      ├── Session
      ├── UnitOfWork
      ├── AI run
      ├── Telemetry
      └── instrumented provider
```

The bootstrap layer must not accidentally turn request-specific state into process-global state.

---

# What Bootstrap Does Not Do

`application.py` explicitly does **not**:

- open SQLAlchemy sessions;
- begin transactions;
- process customer messages;
- perform provider health checks;
- make external API calls.

This distinction is intentional.

```text
Bootstrap
   │
   ├── Configuration
   ├── Construction
   └── Dependency lifetime
          │
          ▼
       STOP

Request handling
   │
   ├── Database sessions
   ├── Transactions
   ├── AI processing
   ├── Provider calls
   └── Business workflows
```

Keeping bootstrap side-effect-light makes application startup easier to reason about and test.

---

# Cache Reset

The module exposes:

```text
clear_application_services_cache()
```

This clears both:

```text
get_application_services.cache
get_runtime_settings.cache
```



Its intended uses are:

- automated tests;
- controlled application reinitialization;
- scenarios where a fresh settings/service container is required.

```text
Before test
    │
    ▼
clear_application_services_cache()
    │
    ▼
Fresh Settings
    │
    ▼
Fresh ApplicationServices
```

This avoids leaking cached process-level state between tests.

---

# Lifecycle Model

The bootstrap lifecycle can be summarized as:

```text
                    API Process
                        │
                        ▼
              get_runtime_settings()
                        │
                        ▼
                     Settings
                        │
                        ▼
             build_application_services()
                        │
                        ▼
               create_application()
                        │
                        ▼
              ApplicationServices
                        │
                        ▼
                Cached Process State
                        │
             ┌──────────┴──────────┐
             ▼                     ▼
        API dependencies       API routes
             │                     │
             └──────────┬──────────┘
                        ▼
                 Request handling
```

---

# Relationship with Application Composition

The bootstrap layer sits immediately above the application composition layer:

```text
apps/api/app/bootstrap/
        │
        │ startup configuration
        ▼
packages/application/composition/
        │
        │ construct services
        ▼
ApplicationServices
```

The bootstrap package therefore answers:

> **When and under which runtime configuration should the application service container be created?**

The application composition package answers:

> **What goes into that application service container?**

Keeping these responsibilities separate prevents API startup code from becoming coupled to the details of individual application services.

---

# Relationship with the API Layer

Once constructed, `ApplicationServices` becomes available to the API dependency system.

```text
bootstrap
    │
    ▼
ApplicationServices
    │
    ▼
FastAPI application state
    │
    ▼
api/dependencies.py
    │
    ▼
v1 endpoints
```

This gives the API a single process-wide application composition root while allowing individual requests to create their own scoped resources.

---

# Design Principles

## 1. Bootstrap Only

Startup composition belongs here; business workflows do not.

## 2. Centralized Configuration

Runtime settings are resolved through the application's central settings system rather than being reconstructed independently by API components.

## 3. Process-Wide Long-Lived Services

`ApplicationServices` is created once and reused for the lifetime of the process.

## 4. Request Scope Remains Request Scope

Database sessions, units of work, AI runs and telemetry objects are not stored in the process-wide service container.

## 5. Explicit Startup Failures

Composition failures are represented by `APIBootstrapError` instead of being silently swallowed.

## 6. Minimal Side Effects

Bootstrap construction itself does not perform request processing, database transactions, health checks or external API calls.

## 7. Testable Caching

Caches can be explicitly cleared to support isolated tests and controlled reinitialization.

---

# Mental Model

The simplest way to understand `bootstrap/` is:

```text
                 API Startup
                     │
                     ▼
              Resolve APP_ENV
                     │
                     ▼
                  Settings
                     │
                     ▼
          create_application(...)
                     │
                     ▼
            ApplicationServices
                     │
                     ▼
              Cache once/process
                     │
                     ▼
              API dependencies
                     │
                     ▼
                API requests
```

In short:

> **`apps/api/app/bootstrap/` is the API process composition boundary: it resolves runtime configuration, creates the long-lived `ApplicationServices` container, translates startup failures into a bootstrap-specific error, and keeps request-scoped resources out of process-wide state.**