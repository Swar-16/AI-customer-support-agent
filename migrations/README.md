# Database Migrations

## Overview

The `migrations/` directory contains the **Alembic-based database schema migration system** for the AI customer-support agent.

It is responsible for managing the evolution of the PostgreSQL database schema across environments in a controlled, versioned, and reproducible manner.

```text
AI-customer-support-agent/
│
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   │
│   └── version/
│       ├── <revision_1>.py
│       ├── <revision_2>.py
│       ├── <revision_3>.py
│       └── ...
│
└── alembic.ini
```

The migration system separates:

```text
env.py
    → Migration runtime configuration

script.py.mako
    → Template for new revision files

version/
    → Actual schema change history
```

---

# Architecture

The migration flow is:

```text
                    Application Models
                           │
                           ▼
                    packages.database
                           │
                           ▼
                     Base.metadata
                           │
                           ▼
                    Alembic Environment
                         env.py
                           │
                           ▼
                    Migration Revisions
                        version/
                           │
                           ▼
                       PostgreSQL
```

The migration environment imports the application's `Base` and database models so Alembic can use the complete SQLAlchemy metadata when generating or comparing migrations.

---

# Directory Structure

## `env.py`

`env.py` is the **runtime entry point for Alembic migrations**.

It connects Alembic with the application's configuration and SQLAlchemy metadata.

Its main responsibilities are:

- loading Alembic configuration;
- configuring logging;
- loading application settings;
- loading database models;
- selecting the target environment;
- exposing `Base.metadata` to Alembic;
- configuring offline migrations;
- configuring online migrations;
- protecting the test database from accidental migration against the wrong database.

The migration environment imports:

```python
from packages.config.settings import get_settings
from packages.database.base import Base

import packages.database.models
```

and assigns:

```python
target_metadata = Base.metadata
```



This is important because importing the model package ensures the ORM model metadata is populated before Alembic performs migration operations.

---

# Environment Selection

Migrations support explicit environment selection through Alembic's `-x` arguments.

The environment is resolved as:

```text
-x env=<environment>
        │
        ▼
context.get_x_argument()
        │
        ▼
get_settings(environment)
```

If no environment is supplied, the migration environment defaults to:

```text
development
```



Examples:

```bash
alembic -x env=development current
```

```bash
alembic -x env=test current
```

```bash
alembic -x env=test upgrade head
```



This means the migration system uses the application's own configuration system rather than maintaining a completely separate database-configuration mechanism.

---

# Test Database Protection

The migration environment contains an explicit safety check for the test environment.

When:

```text
environment == "test"
```

the configured database must be:

```text
support_ai_test
```

Otherwise migration execution is rejected with a `RuntimeError`.

The same protection is applied during online migration execution.

Conceptually:

```text
                 env=test
                    │
                    ▼
          database_name == ?
                    │
             ┌──────┴──────┐
             │             │
   support_ai_test       anything else
             │             │
             ▼             ▼
          ALLOW          REFUSE
```

This prevents a test migration command from accidentally modifying a non-test database.

---

# Online Migrations

The normal migration path is the **online migration mode**.

`env.py` creates a SQLAlchemy engine using the configured application database URL:

```text
Application Settings
        │
        ▼
settings.database_url
        │
        ▼
SQLAlchemy Engine
        │
        ▼
Database Connection
        │
        ▼
Alembic Migration
```

The migration engine uses:

```text
pool.NullPool
```

for migration execution.

Alembic is then configured with:

- the active database connection;
- application metadata;
- type comparison;
- schema inclusion;
- the migration version table;
- the schema containing that version table.

---

# Migration Version Tracking

Alembic stores the currently applied revision in:

```text
config.alembic_version
```

because `env.py` explicitly configures:

```text
version_table = alembic_version
version_table_schema = config
```



This means the migration system keeps its own version-tracking state inside the database's `config` schema rather than the default PostgreSQL schema.

Conceptually:

```text
PostgreSQL
│
├── support/
├── ai/
├── knowledge/
├── ...
│
└── config/
    └── alembic_version
```

The `alembic_version` table records which revision(s) have been applied.

---

# Offline Migrations

Alembic also supports **offline mode**.

In offline mode, an SQLAlchemy engine/DBAPI connection is not required. Instead, Alembic is configured using the migration URL and emits SQL statements to the migration output.

Conceptually:

```text
Migration Revisions
       │
       ▼
Offline Alembic
       │
       ▼
Generated SQL
```

This is useful when migration SQL needs to be inspected, captured, or applied through another controlled mechanism.

---

# `script.py.mako`

`script.py.mako` is the **template used when Alembic creates a new migration revision**.

New revision files inherit the standard structure defined by this template:

```text
Revision metadata
        │
        ├── revision
        ├── down_revision
        ├── branch_labels
        └── depends_on
              │
              ▼
         upgrade()
              │
              ▼
        Schema changes
              │
              ▼
        downgrade()
```

The generated revision contains the Alembic `op` interface and SQLAlchemy imports required for schema operations.

Each revision therefore follows the standard structure:

```python
def upgrade() -> None:
    ...

def downgrade() -> None:
    ...
```

This provides both forward migration and rollback logic.

---

# `version/`

```text
migrations/version/
```

The `version/` directory contains the **actual migration history**.

Each Python file represents one Alembic revision.

Conceptually:

```text
version/
│
├── revision_A.py
│       │
│       └── creates initial schema
│
├── revision_B.py
│       │
│       └── adds feature
│
├── revision_C.py
│       │
│       └── changes constraint
│
└── revision_D.py
        │
        └── adds another schema change
```

The revisions form a migration graph:

```text
A
│
▼
B
│
▼
C
│
▼
D
│
▼
HEAD
```

Each revision identifies its parent through:

```python
down_revision = ...
```

while its own identifier is stored in:

```python
revision = ...
```

The exact schema changes belong to the individual files under `version/`; this README intentionally provides only the higher-level migration architecture.

---

# Migration Lifecycle

A typical schema change follows this lifecycle:

```text
1. Modify SQLAlchemy Models
             │
             ▼
2. Generate Migration Revision
             │
             ▼
3. Review Generated Migration
             │
             ▼
4. Test Upgrade
             │
             ▼
5. Test Downgrade
             │
             ▼
6. Apply Migration
             │
             ▼
7. New Alembic HEAD
```

The important distinction is:

> **Changing a SQLAlchemy model does not itself change the PostgreSQL database.**

The migration revision is the durable representation of the schema change.

---

# Model Metadata vs Migration History

The migration system has two related but different concepts:

### SQLAlchemy metadata

Represents the **desired/current ORM schema**:

```text
packages/database/models/
        │
        ▼
Base.metadata
```

### Alembic revision history

Represents the **ordered history of database changes**:

```text
migrations/version/
        │
        ▼
Revision A → B → C → D
```

Together:

```text
Current Models
      │
      ▼
Base.metadata
      │
      │ comparison
      ▼
Database Schema

Migration History
      │
      ▼
Historical path
from old schema → current schema
```

This distinction is important because migrations should remain reproducible even after the application models evolve.

---

# Autogeneration

Because `env.py` exposes:

```python
target_metadata = Base.metadata
```

and online migrations enable:

```text
compare_type=True
```

Alembic can compare SQLAlchemy metadata against the existing database schema when generating migration candidates.

However, generated migrations should be **reviewed manually** before being treated as production-ready.

Autogeneration is a development aid, not a substitute for understanding the actual schema change.

Particular care should be taken with:

- data migrations;
- renamed columns/tables;
- constraints;
- indexes;
- nullable changes;
- server defaults;
- enum changes;
- PostgreSQL-specific objects;
- destructive operations.

---

# Recommended Migration Workflow

## 1. Change the model

Modify the appropriate SQLAlchemy model under:

```text
packages/database/models/
```

## 2. Generate a revision

Use Alembic to generate a new revision.

The exact command depends on the project's Alembic configuration, but conceptually:

```bash
alembic -x env=development revision --autogenerate -m "describe schema change"
```

## 3. Inspect the revision

Check the generated file under:

```text
migrations/version/
```

Do not blindly trust autogenerated operations.

## 4. Validate `upgrade()`

The upgrade should move the database from the previous revision to the new schema.

## 5. Validate `downgrade()`

Where downgrade support is appropriate, verify that the reverse operation is safe and coherent.

## 6. Apply locally

```bash
alembic -x env=development upgrade head
```

## 7. Verify revision state

```bash
alembic -x env=development current
```

## 8. Test against the test database

```bash
alembic -x env=test upgrade head
```

The migration environment's database-name guard protects the test environment from being accidentally pointed at the wrong database.

---

# Migration Commands

Common operations include:

### Show current revision

```bash
alembic -x env=development current
```

### Show migration history

```bash
alembic -x env=development history
```

### Upgrade to latest revision

```bash
alembic -x env=development upgrade head
```

### Upgrade one revision

```bash
alembic -x env=development upgrade +1
```

### Downgrade one revision

```bash
alembic -x env=development downgrade -1
```

### Generate a new revision

```bash
alembic -x env=development revision --autogenerate -m "describe change"
```

The environment-selection mechanism used by these commands is implemented by `env.py`.

---

# Migration Safety

Database migrations are state-changing operations and should be treated differently from ordinary application code.

Before applying a migration, verify:

```text
✓ Correct environment
✓ Correct database
✓ Expected current Alembic revision
✓ Generated SQL/revision reviewed
✓ Upgrade path tested
✓ Downgrade considered
✓ Data-loss implications understood
✓ Constraints/indexes reviewed
```

For test migrations, the project already enforces an additional database-name safety check.

---

# What Belongs in `migrations/`

The migration directory should contain artifacts concerned with **database schema evolution**:

```text
env.py
    Migration runtime/environment configuration

script.py.mako
    New-revision template

version/
    Immutable schema-change history
```

It should not become a place for:

```text
Application business logic
AI orchestration
Repository implementations
API handlers
Knowledge processing
Runtime application services
```

Those responsibilities belong to the corresponding `packages/` layers.

---

# Relationship with `packages/database/`

The migration system is closely connected to the database package:

```text
packages/database/
        │
        ├── models/
        │      │
        │      ▼
        │   Base.metadata
        │
        └── ...
               │
               ▼
          migrations/env.py
               │
               ▼
       migrations/version/
               │
               ▼
          PostgreSQL
```

The database package defines **how the application represents persistent data**.

The migration package defines **how PostgreSQL evolves to support those representations over time**.

Therefore:

```text
Database Models
    = Current persistence model

Migrations
    = Historical schema evolution
```

Neither replaces the other.

---

# Key Design Principles

## Versioned Schema Evolution

Every structural database change should be represented by a migration revision.

## Reproducibility

A fresh database should be able to reach the current schema by applying the migration history in order.

## Environment Awareness

Migration execution uses the application's environment-specific settings rather than hardcoding a single database configuration.

## Safety

The migration environment explicitly protects the test database from being accidentally substituted with another database.

## Separation of Current State and History

SQLAlchemy models describe the current application schema; Alembic revisions preserve how that schema evolved.

## Review Before Apply

Autogenerated migration output should be treated as a candidate that requires review, particularly for destructive or data-sensitive changes.

---

# Mental Model

The simplest way to understand `migrations/` is:

```text
                   SQLAlchemy Models
                          │
                          ▼
                    Base.metadata
                          │
                          ▼
                    Alembic env.py
                          │
                          ▼
              ┌───────────────────────┐
              │   Migration History   │
              │                       │
              │ A → B → C → D → HEAD  │
              └───────────┬───────────┘
                          │
                          ▼
                     PostgreSQL
```

Or, in one sentence:

> **`migrations/` is the controlled, versioned bridge between the application's SQLAlchemy persistence model and the actual PostgreSQL schema.**

The detailed revision files under `version/` contain the individual schema changes; `env.py` controls how those revisions execute, while `script.py.mako` defines the structure of newly generated revisions.