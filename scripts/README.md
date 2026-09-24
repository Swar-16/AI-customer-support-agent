# Scripts

## Overview

The `scripts/` directory contains **operational, development, bootstrap, verification, and contract-generation utilities** for the AI customer-support system.

These scripts are intentionally kept outside the main `packages/` architecture. They are entry points for tasks such as:

- bootstrapping knowledge;
- backfilling embeddings;
- provisioning the initial administrator;
- registering a customer;
- generating/verifying the OpenAPI contract;
- inspecting embedding/retrieval/cache behavior.

They generally **compose existing application services and infrastructure** rather than reimplementing domain logic.

```text
AI-customer-support-agent/
│
├── packages/
│   ├── application/
│   ├── ai/
│   ├── knowledge/
│   ├── database/
│   └── config/
│
├── contracts/
│   └── openapi.json
│   └── database_schema.json
│
├── knowledge_data/
│
└── scripts/
    ├── create_admin.py
    ├── register_customer.py
    ├── seed_knowledge.py
    ├── embed_knowledge.py
    ├── export_openapi.py
    ├── create_openapi_json.py
    └── verify_embedding_cache.sql
```

---

# Script Categories

The scripts can be grouped into five operational areas:

```text
scripts/
│
├── Environment / Bootstrap
│   ├── create_admin.py
│   ├── register_customer.py
│   └── seed_knowledge.py
│
├── Knowledge Operations
│   └── embed_knowledge.py
│
├── API Contract
│   ├── export_openapi.py
│   └── create_openapi_json.py
│
└── Diagnostics / Verification
    └── verify_embedding_cache.sql
```

---

# 1. Knowledge Bootstrap

## `seed_knowledge.py`

`seed_knowledge.py` bootstraps repository knowledge into the database.

It discovers knowledge files from:

```text
knowledge_data/
├── faqs/
└── policies/
```

and maps them to the appropriate knowledge content types.

The script composes the existing knowledge application services rather than directly manipulating the database schema:

```text
Knowledge Files
      │
      ▼
seed_knowledge.py
      │
      ├── Discover files
      ├── Normalize content
      ├── Calculate content hash
      ├── Create/update documents
      ├── Create versions
      ├── Process versions
      └── Publish versions
             │
             ▼
      Knowledge Application
             │
             ▼
          Database
```

The script uses deterministic UUID derivation for source files. Its namespace must remain stable after real environments have been seeded, otherwise the same source file could receive a different logical document identity.

### Idempotent Bootstrap

The script tracks outcomes such as:

```text
discovered
created_documents
created_versions
processed_versions
published_versions
skipped
failed
```



This makes it suitable for repository-level knowledge initialization and repeatable bootstrap operations.

---

# 2. Knowledge Embedding Backfill

## `embed_knowledge.py`

`embed_knowledge.py` performs embedding backfills for published knowledge versions.

It composes:

```text
Knowledge Embedding Factory
          │
          ▼
   Embedding Provider
          │
          ▼
 EmbedKnowledgeVersion
          │
          ▼
    Knowledge UoW
          │
          ▼
       Database
```

The script creates the embedding service using the configured provider and embedding batch size.

### Target Selection

It supports two modes:

```text
--version-id <UUID>
        │
        └── Embed one specific version

(no --version-id)
        │
        └── Discover all eligible published versions
```

Eligible versions are resolved through the knowledge Unit of Work rather than by duplicating repository logic.

### Safety

The script explicitly refuses to operate against a database other than:

```text
support_ai
```



### Independent Processing

Versions are processed independently. A failure for one version is recorded while processing continues for other versions.

The final summary reports:

```text
Versions discovered
Successful
Failed
Chunks processed
Already existing
New embeddings
```



---

# 3. Administrator Provisioning

## `create_admin.py`

`create_admin.py` provisions the initial administrator account for the development environment.

The script intentionally restricts itself to:

```text
development
     +
support_ai database
```

and refuses to continue if those conditions are not satisfied.

It additionally requires explicit confirmation:

```text
Type support_ai to confirm provisioning:
```

before performing the operation.

The actual provisioning is delegated to the application service:

```text
create_admin.py
      │
      ▼
ProvisionInitialAdmin
      │
      ├── Password policy
      ├── Argon2 hashing
      ├── Admin invariants
      └── Persistence
```

The script therefore acts as a **safe command-line entry point**, not as a second implementation of administrator provisioning.

---

# 4. Customer Registration Utility

## `register_customer.py`

`register_customer.py` is a small development utility for exercising the customer registration API.

It communicates with:

```text
http://localhost:8000
```

and uses the configured frontend origin:

```text
http://localhost:5173
```



The workflow is:

```text
Prompt for credentials
        │
        ▼
POST /v1/auth/register
        │
        ▼
Registration response
        │
        ▼
Extract access token
        │
        ▼
POST /v1/auth/logout
        │
        ▼
Clear temporary cookies
```



The script also translates common registration failures into developer-friendly messages, including:

- password-policy rejection;
- origin rejection;
- existing email;
- request validation failure.

This is primarily a **local API smoke/development utility**, not part of the authentication implementation itself.

---

# 5. OpenAPI Contract Generation

## `export_openapi.py`

`export_openapi.py` generates the committed OpenAPI contract:

```text
     apps/api
        │
        ▼
  create_api_app()
        │
        ▼
application.openapi()
        │
        ▼
contracts/openapi.json
```



The generated contract is serialized deterministically:

```text
UTF-8
pretty printed
sorted keys
no NaN values
```



### Normal Export

```bash
python scripts/export_openapi.py
```

This updates:

```text
contracts/openapi.json
```

### Drift Check

The same script supports:

```bash
python scripts/export_openapi.py --check
```

The check compares the currently generated API contract with the committed snapshot and fails when they differ.

Conceptually:

```text
Current API
    │
    ▼
Generated OpenAPI
    │
    ├── matches ──► OK
    │
    └── differs ──► Drift detected
```

This makes the committed OpenAPI document a verifiable API contract rather than an unchecked generated artifact.

---

# 6. `create_openapi_json.py`

`create_openapi_json.py` is a smaller OpenAPI generation utility.

It:

1. creates the API application;
2. obtains `app.openapi()`;
3. serializes the result;
4. writes it to:

```text
contracts/openapi.json
```



Compared with `export_openapi.py`, it is a minimal generation path without the explicit `--check` drift-validation workflow.

For normal contract maintenance, `export_openapi.py` provides the more complete export/check workflow.

---

# 7. Embedding Cache Verification

## `verify_embedding_cache.sql`

This SQL script is a **diagnostic/verification tool** for query-embedding caching.

It inspects recent:

```text
ai.embedding_calls
ai.retrieval_runs
```

and reports:

```text
Recent query embedding calls
Recent retrieval runs
Cache verification summary
```



### Cache Summary

For successful activity in the previous 30 minutes, it calculates:

```text
retrieval_runs
external_embedding_calls
probable_cache_hits
avg_cache_miss_vector_ms
avg_cache_hit_vector_ms
```



A retrieval with:

```text
embedding_call_id IS NULL
```

is treated as a **probable cache hit** by this diagnostic query.

This aligns with the runtime architecture:

```text
User Query
    │
    ▼
Retrieval
    │
    ▼
QueryEmbeddingCache
   │       │
 HIT      MISS
   │       │
   │       ▼
   │   Embedding Provider
   │       │
   └───┬───┘
       ▼
Query Vector
```

The query cache is process-local, bounded, TTL-based, and LRU-evicted rather than a distributed cache.

### Running the Verification

The SQL file itself documents the intended PostgreSQL invocation:

```powershell
$env:PGPASSWORD = "<your-actual-database-password>"

psql -h localhost -p 5432 `
  -U support_ai_admin `
  -d support_ai `
  -X `
  -v ON_ERROR_STOP=1 `
  -f scripts/verify_embedding_cache.sql
```



---

# Operational Relationships

The scripts are not isolated utilities. Most of them are thin entry points into existing application architecture.

```text
                         scripts/
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
 Knowledge             Application          API Contract
 Bootstrap             Services             Generation
        │                   │                   │
        ▼                   ▼                   ▼
   Knowledge           Database /            FastAPI
   Services             UoW / AI             Schema
        │
        ▼
   PostgreSQL
```

For embedding operations:

```text
    embed_knowledge.py
            │
            ▼
Knowledge Embedding Factory
            │
            ▼
    Embedding Provider
            │
            ▼
  Knowledge Application
            │
            ▼
      Knowledge UoW
            │
            ▼
       PostgreSQL
```

For administrator provisioning:

```text
create_admin.py
        │
        ▼
ProvisionInitialAdmin
        │
        ├── Argon2PasswordHasher
        └── SqlAlchemyUnitOfWork
                │
                ▼
            PostgreSQL
```

---

# Safety Characteristics

The scripts contain several deliberate safeguards because they can directly affect application state.

## Environment Validation

Operational scripts verify their expected environment/database where appropriate.

For example, the knowledge embedding backfill refuses a database other than `support_ai`.

The administrator provisioning script additionally requires the development environment and explicit database-name confirmation.

## Existing Application Services

Scripts should prefer:

```text
        Application Service
                │
                ▼
Existing domain/application invariants
                │
                ▼
           Persistence
```

rather than:

```text
Script
  │
  └── Direct SQL / ORM mutation
```

This keeps command-line operations consistent with normal application behavior.

## Credentials

Interactive password input uses `getpass` rather than command-line arguments or ordinary `input()`, preventing passwords from being echoed during administrator/customer setup.

---

# When to Use Which Script

| Script | Use when |
|---|---|
| `seed_knowledge.py` | Bootstrapping repository knowledge into the knowledge system |
| `embed_knowledge.py` | Generating/backfilling embeddings for eligible knowledge versions |
| `create_admin.py` | Provisioning the initial development administrator |
| `register_customer.py` | Manually exercising customer registration locally |
| `export_openapi.py` | Generating or checking the committed API contract |
| `create_openapi_json.py` | Performing the minimal OpenAPI JSON generation |
| `verify_embedding_cache.sql` | Inspecting recent embedding/retrieval activity and probable cache behavior |

---

# What These Scripts Are Not

The `scripts/` directory should not become a second application layer.

Scripts should generally **not own**:

```text
Business rules
Authentication policy
Knowledge lifecycle rules
Embedding provider logic
Retrieval algorithms
Database repository behavior
Transaction policy
API routing
```

Those concerns already belong to the corresponding `packages/` or `apps/` layers.

Instead:

```text
scripts/
    = operational entry points

packages/
    = reusable application/domain/infrastructure logic
```

---

# Adding a New Script

A new script should generally follow this pattern:

```text
1. Parse minimal CLI/input arguments
2. Load validated configuration
3. Resolve application dependencies
4. Call an existing application/domain service
5. Display concise operational results
6. Return meaningful exit codes
```

Avoid copying business logic from the application layer into the script.

For database-mutating scripts, additionally consider:

```text
✓ environment validation
✓ database-target validation
✓ explicit confirmation for destructive/high-impact operations
✓ transaction boundaries
✓ safe credential handling
✓ structured failure reporting
✓ useful exit status
✓ idempotency where practical
```

---

# Overall Mental Model

The simplest way to understand `scripts/` is:

```text
                    SCRIPTS
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
    Bootstrap       Operations      Verification
        │              │              │
        ▼              ▼              ▼
   Seed/Create     Embed/Export     SQL/Check
        │              │              │
        └──────────────┼──────────────┘
                       ▼
                Existing System
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      Application    Knowledge    Database
```

The key architectural principle is:

> **Scripts are thin operational entry points; the actual application behavior remains inside the packages that own it.**

This keeps administrative tasks, bootstrap workflows, maintenance operations, contract generation, and diagnostics convenient to run without duplicating the system's core logic.