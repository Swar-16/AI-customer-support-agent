# User Administration Application Services

## Overview

The `packages/application/users/` package contains application-layer use cases for **administrative user provisioning and access management**.

The folder currently contains two application services:

```text
packages/application/users/
├── provision_initial_admin.py
├── update_user_access.py
└── README.md
```

The services cover two distinct administrative workflows:

| File                         | Responsibility                                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------------------------------ |
| `provision_initial_admin.py` | Safely bootstrap the first active administrator account                                                |
| `update_user_access.py`      | Administratively change an existing user's role/status and revoke their active authentication sessions |

Together, these services establish and maintain the administrative access boundary of the application.

---

# Architecture

The two services follow the application-layer pattern used throughout the project:

```text
Authenticated / Internal Caller
              │
              ▼
       Immutable Command
              │
              ▼
       Application Service
              │
              ├── Authorization
              ├── Validation
              ├── Concurrency Protection
              ├── Persistence
              ├── Session Revocation
              └── Audit
              │
              ▼
        Unit of Work
              │
              ▼
      Commit / Result DTO
```

Both services use:

```python
SqlAlchemyUnitOfWork
```

through a callable `UnitOfWorkFactory`.

They also use UTC-aware timestamps through an injectable clock, making the services deterministic and easier to test.

---

# 1. `provision_initial_admin.py`

## Purpose

`provision_initial_admin.py` implements the controlled bootstrap process for creating the application's **first administrator**.

Its main application service is:

```python
ProvisionInitialAdmin
```

and its command/result contracts are:

```python
ProvisionInitialAdminCommand
ProvisionInitialAdminResult
```

The service is explicitly designed for administrative bootstrap rather than public user registration.

Its purpose is to:

1. validate the administrator's registration password;
2. normalize and validate input;
3. prevent concurrent bootstrap processes;
4. ensure an administrator does not already exist;
5. hash the password;
6. create the user;
7. create the authentication credential;
8. record an immutable audit event;
9. commit all changes atomically.

The implementation explicitly describes the user, credential, and audit event as being committed in one transaction, with a PostgreSQL advisory lock protecting concurrent bootstrap processes.

---

## Command

```python
@dataclass(frozen=True, slots=True)
class ProvisionInitialAdminCommand:
```

The command contains:

```text
email
password
display_name
trace_id
```

The password is excluded from the dataclass representation:

```python
password: str = field(repr=False)
```

This avoids exposing the raw password through normal object representations.

---

## Input Normalization

The email is normalized using the application's shared:

```python
normalize_email()
```

function.

The normalized value replaces the original command value.

The password must:

* be a string;
* be non-empty.

The display name, when supplied:

* must be a string;
* has surrounding/repeated whitespace normalized;
* cannot exceed 255 characters;
* becomes `None` when normalization produces an empty value.

The trace ID, when supplied, must be a UUID.

---

# Password Policy

The bootstrap operation does not implement its own password policy.

Instead it delegates to:

```python
validate_registration_password(...)
```

from the authentication registration application layer.

This keeps password requirements consistent with normal registration.

If registration validation fails, the authentication-layer error is translated into:

```text
InitialAdminPasswordPolicyError
```

---

# Password Hashing

The service receives a:

```python
PasswordHasherContract
```

dependency.

It hashes the password before constructing the credential model.

If password hashing fails with:

```text
PasswordHashingError
```

the application service converts it into:

```text
InitialAdminPasswordHashingError
```

The application service therefore never persists the raw administrator password.

---

# Bootstrap Concurrency Protection

One of the most important characteristics of this service is that initial administrator provisioning is protected against concurrent execution.

Inside the Unit of Work it acquires:

```python
uow.users.acquire_initial_admin_lock()
```

before checking whether an administrator already exists.

The intended flow is:

```text
Bootstrap Process A             Bootstrap Process B
        │                               │
        ▼                               ▼
 acquire initial-admin lock      acquire initial-admin lock
        │                               │
        ▼                               │
 check administrators                   │
        │                               │
        ▼                               │
 create administrator                   │
        │                               │
        ▼                               │
      commit                            │
                                        ▼
                                  continue after lock
                                        │
                                        ▼
                                  observe admin exists
```

This prevents two simultaneous bootstrap processes from both observing zero administrators and creating separate initial administrators.

---

# Existing Credential Handling

Before checking the global administrator count, the service checks whether the requested email already has credentials:

```python
uow.auth.get_credential_by_email(
    command.email,
    for_update=True
)
```

If credentials exist, the associated user is loaded.

If the existing account is already:

```text
role   = ADMIN
status = ACTIVE
```

the operation is **idempotent**.

Instead of creating another user, it returns the existing administrator with:

```text
changed = False
```

---

# Email Conflict

If the requested email belongs to an account that is not an active administrator, the operation raises:

```text
InitialAdminEmailConflictError
```

This prevents the bootstrap process from silently modifying or taking over an existing account.

An `IntegrityError` occurring during persistence is also translated into the same application-level email conflict error.

---

# Existing Administrator Protection

If there are already active administrators:

```python
uow.users.count_active_admins() > 0
```

the bootstrap operation raises:

```text
InitialAdminAlreadyExistsError
```

Therefore, the service is intended for **initial bootstrap only**, not for ordinary administrator creation.

---

# Administrator User Creation

A new administrator is created with:

```text
role   = ADMIN
status = ACTIVE
```

The user receives a UUIDv7 ID.

The following fields are initialized:

```text
id
external_id
email
display_name
role
status
created_at
updated_at
```

with `external_id` initially set to `None`.

---

# Credential Creation

The corresponding `UserCredentialModel` is created with:

```text
user_id
email_normalized
password_hash
failed_login_attempts = 0
locked_until = None
password_changed_at
created_at
updated_at
```

The credential is therefore initialized in an unlocked state with no failed-login history.

---

# Persistence Order

The service persists the user first:

```text
UserModel
    │
    ▼
uow.users.add()
    │
    ▼
uow.users.flush()
```

Then the credential:

```text
UserCredentialModel
    │
    ▼
uow.auth.add_credential()
    │
    ▼
uow.auth.flush()
```

This ensures both objects exist within the same transaction before the audit event is recorded.

---

# Audit Event

Successful initial administrator creation records:

```text
event_type = auth.initial_admin_provisioned
entity_type = user
action      = initial_admin_provisioned
```

The actor is:

```text
AuditActorType.SYSTEM
```

because this is a bootstrap operation rather than a normal administrator action.

The audit `after_state` records:

```text
role = admin
status = active
credentials_configured = true
```

and metadata records:

```text
provisioning_method = local_cli
bootstrap = true
```

---

# Transaction Boundary

The entire operation is committed through:

```python
uow.commit()
```

only after:

```text
user created
credential created
audit recorded
result constructed
```

Conceptually:

```text
┌──────────────────────────────────────────┐
│          Initial Admin Transaction       │
│                                          │
│    Acquire bootstrap lock                │
│              ↓                           │
│  Validate existing accounts              │
│              ↓                           │
│        Hash password                     │
│              ↓                           │
│         Create user                      │
│              ↓                           │
│      Create credential                   │
│              ↓                           │
│     Record audit event                   │
│              ↓                           │
│            COMMIT                        │
└──────────────────────────────────────────┘
```

If the operation fails, the transaction does not intentionally expose a partially-created administrator.

---

# Result

`ProvisionInitialAdminResult` contains:

```text
user_id
email
display_name
role
status
created_at
changed
```

The `changed` field is important for distinguishing:

```text
changed = True
```

from an idempotent existing-administrator result:

```text
changed = False
```

---

# Clock Handling

The service accepts an injectable:

```python
Clock = Callable[[], datetime]
```

If no clock is supplied, it uses the current UTC time.

The `_utc_now()` method requires the clock to return a timezone-aware `datetime` and converts it to UTC.

This gives tests deterministic timestamp control.

---

# Persistence Contract

Before performing the operation, `_require_repositories()` verifies:

```text
uow.session
uow.users
uow.auth
uow.audit_events
```

are available.

Missing persistence dependencies are converted into:

```text
InitialAdminPersistenceError
```

---

# Error Model

The service defines:

```text
ProvisionInitialAdminError
├── InitialAdminAlreadyExistsError
├── InitialAdminEmailConflictError
├── InitialAdminPasswordPolicyError
├── InitialAdminPasswordHashingError
└── InitialAdminPersistenceError
```

This keeps callers independent from lower-level authentication, hashing, ORM, and database exceptions.

---

# 2. `update_user_access.py`

## Purpose

`update_user_access.py` implements the administrative workflow for changing an existing user's:

```text
role
status
```

and revoking their active authentication sessions.

Its primary service is:

```python
UpdateUserAccess
```

with:

```python
UpdateUserAccessCommand
UpdateUserAccessResult
```

The operation is transactional and locks the target user while a separate administrative transaction lock protects the **final active administrator** invariant.

---

# Supported Roles

The service permits these roles to be assigned:

```text
CUSTOMER
SUPPORT_AGENT
ADMIN
```

defined through:

```python
ASSIGNABLE_ROLES
```

System identities are deliberately excluded from this assignable set.

---

# Supported Statuses

The service permits these statuses:

```text
ACTIVE
DISABLED
```

through:

```python
MANAGEABLE_STATUSES
```

Deleted users are handled separately and cannot be modified through this access-management workflow.

---

# Command

```python
@dataclass(frozen=True, slots=True)
class UpdateUserAccessCommand:
```

contains:

```text
target_user_id
principal
trace_id
role
status
reason
```

At least one of:

```text
role
status
```

must be supplied.

A command containing neither is rejected.

---

# Administrative Authorization

The command itself requires:

```python
principal.role is AuthRole.ADMIN
```

Otherwise:

```text
UserAccessDeniedError
```

is raised.

This creates an early authorization boundary before the actual database operation begins.

---

# Reason

Every access mutation requires a non-blank reason.

The reason is normalized by collapsing whitespace:

```text
"  promoted   after review  "
             ↓
"promoted after review"
```

The maximum length is:

```text
1,000 characters
```

The reason is later stored in the audit event.

---

# Administrative Transaction Flow

The update operation follows:

```text
UpdateUserAccessCommand
          │
          ▼
validate command
          │
          ▼
create Unit of Work
          │
          ▼
acquire admin management lock
          │
          ▼
validate acting administrator
          │
          ▼
lock target user
          │
          ▼
validate target
          │
          ▼
calculate resulting role/status
          │
          ▼
validate administrator invariants
          │
          ▼
update user
          │
          ▼
revoke sessions
          │
          ▼
flush
          │
          ▼
audit
          │
          ▼
commit
          │
          ▼
result
```

---

# Administrative Management Lock

The service calls:

```python
uow.users.acquire_admin_management_lock()
```

before validating and mutating the target.

This lock protects global administrative invariants, especially:

```text
there must remain at least one active administrator
```

It complements the row-level lock on the target user.

---

# Acting Administrator Validation

The administrator performing the operation is loaded using:

```python
uow.users.get_by_id(command.principal.user_id)
```

The persisted account must:

1. exist;
2. be active;
3. have the same role as the authenticated principal;
4. actually have the `ADMIN` role.

This prevents stale or manipulated authentication claims from being treated as sufficient authorization.

---

# Target User Lock

The managed account is loaded using:

```python
uow.users.get_by_id_for_update(command.target_user_id)
```

This locks the target row for the duration of the mutation transaction.

---

# System User Protection

If the target user has:

```text
role = SYSTEM
```

the operation raises:

```text
ProtectedSystemUserError
```

System identities cannot be modified through this access-management workflow.

---

# Deleted User Protection

If the target user's status is:

```text
DELETED
```

the service raises:

```text
DeletedUserAccessMutationError
```

Deleted users cannot be reactivated or otherwise modified through this workflow.

---

# Partial Updates

The command allows either or both of:

```text
role
status
```

to be changed.

If a field is omitted, the existing value is preserved:

```python
target_role = command.role if command.role is not None else AuthRole(target.role)

target_status = command.status if command.status is not None else AuthUserStatus(target.status)
```

This allows operations such as:

```text
role only
status only
role + status
```

---

# No-Op Detection

If the requested role and status already match the persisted values:

```text
role_changed  = False
status_changed = False
```

the service returns immediately with:

```text
changed = False
revoked_session_count = 0
```

This prevents unnecessary database updates and unnecessary session revocation.

---

# Administrator Self-Mutation

Administrators can target their own account only if the resulting state remains:

```text
role   = ADMIN
status = ACTIVE
```

If a self-update would demote or disable the current administrator, the service raises:

```text
AdministratorSelfMutationError
```

Conceptually:

```text
Admin modifies self
       │
       ├── remains ADMIN + ACTIVE
       │        ↓
       │      allowed
       │
       └── demotion / disable
                ↓
             rejected
```

---

# Final Active Administrator Protection

The service explicitly protects against removing the last active administrator.

It calculates:

```text
removes_active_admin
```

when the target is currently:

```text
role   = ADMIN
status = ACTIVE
```

and the requested resulting state is no longer both:

```text
ADMIN + ACTIVE
```

If the active administrator count is one or fewer:

```text
FinalActiveAdministratorError
```

is raised.

This protects against accidentally locking the system out of administrative access.

---

# Role and Status Mutation

After validation, the target user is updated:

```python
target.role = target_role.value
target.status = target_status.value
```

The original role/status pair is captured first:

```python
before_state = {
    "role": target.role,
    "status": target.status,
}
```

This becomes part of the audit record.

---

# Session Revocation

Any access change causes all authentication sessions for the target user to be revoked:

```python
uow.auth.revoke_all_for_user(
    user_id=target.id,
    revoked_at=occurred_at,
    reason="user_access_changed",
)
```

The number of revoked sessions is captured as:

```text
revoked_session_count
```

This is important because changing a user's role or disabling their account should not leave previously issued sessions operating with stale authorization.

The overall operation is therefore:

```text
Change access
     │
     ▼
Revoke existing sessions
     │
     ▼
Commit together
```

---

# Audit Event

Every successful access change records:

```text
event_type = user.access_updated
entity_type = user
action = access_updated
```

The audit actor is:

```text
AuditActorType.ADMIN
```

with:

```text
actor_id = principal.user_id
```

---

# Audit Before / After State

The audit event captures the previous state:

```text
before_state:
    role
    status
```

and resulting state:

```text
after_state:
    role
    status
```

Additional metadata records:

```text
role_changed
status_changed
revoked_session_count
```

The supplied administrative reason is also persisted in the audit event.

---

# Transaction Atomicity

The user mutation, session revocation, and audit record occur inside the same Unit of Work.

Conceptually:

```text
┌───────────────────────────────────────────┐
│       User Access Management Tx           │
│                                           │
│  Acquire admin management lock            │
│             ↓                             │
│     Lock target user                      │
│             ↓                             │
│    Validate invariants                    │
│             ↓                             │
│     Change role/status                    │
│             ↓                             │
│     Revoke all sessions                   │
│             ↓                             │
│     Record audit event                    │
│             ↓                             │
│           COMMIT                          │
└───────────────────────────────────────────┘
```

This ensures access state, authentication session state, and audit history move together.

---

# Result

`UpdateUserAccessResult` contains:

```text
user_id
email
display_name
role
status
updated_at
changed
revoked_session_count
```

This gives callers both the resulting access state and the number of sessions invalidated.

---

# Clock Handling

Like the bootstrap service, `UpdateUserAccess` accepts an injectable clock.

If omitted, it defaults to:

```python
datetime.now(timezone.utc)
```

The service requires a timezone-aware datetime and normalizes it to UTC.

---

# Persistence Contracts

Before executing, `_require_repositories()` verifies:

```text
uow.session
uow.users
uow.auth
uow.audit_events
```

are available.

Missing dependencies result in:

```text
UserAccessPersistenceContractError
```

---

# Error Model

The service defines:

```text
UpdateUserAccessError
├── UserAccessDeniedError
├── AccessManagerDoesNotExistError
├── AccessManagerNotActiveError
├── AccessManagerRoleMismatchError
├── ManagedUserDoesNotExistError
├── ProtectedSystemUserError
├── DeletedUserAccessMutationError
├── FinalActiveAdministratorError
├── AdministratorSelfMutationError
└── UserAccessPersistenceContractError
```

This gives administrative callers explicit application-level failure modes.

---

# Relationship Between the Two Services

The two files address different stages of the administrator lifecycle.

```text
                    USER ADMINISTRATION
                           │
             ┌─────────────┴─────────────┐
             │                           │
             ▼                           ▼
   provision_initial_admin.py    update_user_access.py
             │                           │
             ▼                           ▼
     Bootstrap first admin       Manage existing accounts
             │                           │
             ├── create user             ├── role
             ├── create credential      ├── status
             ├── password hashing       ├── session revocation
             └── audit                  └── audit
```

The intended distinction is:

### `ProvisionInitialAdmin`

Handles the **initial bootstrap state**:

```text
zero active administrators
        │
        ▼
first active administrator
```

### `UpdateUserAccess`

Handles **ongoing administrative access management**:

```text
existing user
     │
     ├── change role
     ├── enable
     ├── disable
     └── preserve admin invariant
```

---

# Security Boundaries

The folder implements several explicit security controls.

## 1. Bootstrap Lock

Initial administrator provisioning uses an initial-admin lock to prevent concurrent bootstrap races.

## 2. Administrative Management Lock

Access updates use an administrative transaction lock to protect global administrator invariants.

## 3. Target Row Locking

The target user is locked before access mutation.

## 4. Persisted Role Verification

The acting administrator's persisted role must match the authenticated principal's role.

## 5. Session Revocation

Access changes revoke all existing authentication sessions for the target user.

## 6. System Identity Protection

System accounts cannot be modified by the normal user-access management operation.

## 7. Final Administrator Protection

The final active administrator cannot be disabled or demoted.

## 8. Self-Demotion Protection

An administrator cannot disable or demote their own account.

---

# Audit Model

Both services use:

```python
AuditRecorder
```

with:

```python
RecordAuditEventCommand
```

The resulting audit trail distinguishes the two workflows:

```text
Initial bootstrap
    │
    └── auth.initial_admin_provisioned

Ongoing access management
    │
    └── user.access_updated
```

This makes administrator bootstrap and later access changes independently observable.

---

# Transaction Comparison

| Concern                | `ProvisionInitialAdmin`      | `UpdateUserAccess`                   |
| ---------------------- | ---------------------------- | ------------------------------------ |
| Primary purpose        | Bootstrap first admin        | Modify existing user access          |
| Caller model           | Internal/system bootstrap    | Authenticated administrator          |
| Role authorization     | Internal bootstrap flow      | Admin required                       |
| User creation          | Yes                          | No                                   |
| Credential creation    | Yes                          | No                                   |
| Password hashing       | Yes                          | No                                   |
| Role mutation          | Initial `ADMIN`              | Yes                                  |
| Status mutation        | Initial `ACTIVE`             | Yes                                  |
| Session revocation     | No                           | Yes                                  |
| Target row lock        | Existing credential lookup   | Yes                                  |
| Global lock            | Initial-admin lock           | Admin-management lock                |
| Audit                  | Yes                          | Yes                                  |
| Final-admin invariant  | Prevents duplicate bootstrap | Prevents removing final active admin |
| Self-mutation rule     | Not applicable               | Yes                                  |
| System-user protection | Not applicable               | Yes                                  |

---

# Common Application-Layer Conventions

Both services use the same architectural conventions.

## Immutable DTOs

Commands and results are:

```python
@dataclass(frozen=True, slots=True)
```

This creates explicit immutable application contracts.

---

## Unit of Work

Persistence occurs through:

```python
SqlAlchemyUnitOfWork
```

rather than directly creating sessions inside the application services.

---

## Repository Contracts

The services validate that the required repositories are present before attempting persistence.

---

## UTC Timestamps

Both services normalize timestamps to UTC and require timezone-aware clock values.

---

## Explicit Application Errors

Infrastructure exceptions are translated into domain/application-specific errors instead of being leaked directly to callers.

---

# End-to-End Administrator Lifecycle

The two services can be viewed as a complete administrator access lifecycle:

```text
                APPLICATION BOOTSTRAP
                       │
                       ▼
          ProvisionInitialAdmin
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
       User       Credential      Audit
          │
          ▼
    ADMIN + ACTIVE
          │
          │
          ▼
   ┌───────────────────────┐
   │ UpdateUserAccess      │
   └───────────┬───────────┘
               │
       ┌───────┼────────┐
       │       │        │
       ▼       ▼        ▼
     Role    Status   Sessions
       │       │        │
       └───────┼────────┘
               ▼
             Audit
```

---

# Typical Workflows

## First Application Startup

```text
No active admin
      │
      ▼
ProvisionInitialAdminCommand
      │
      ▼
validate password
      │
      ▼
acquire bootstrap lock
      │
      ▼
verify no admin exists
      │
      ▼
hash password
      │
      ▼
create UserModel
      │
      ▼
create UserCredentialModel
      │
      ▼
audit
      │
      ▼
commit
```

---

## Repeated Bootstrap Invocation

```text
ProvisionInitialAdminCommand
      │
      ▼
existing requested account?
      │
      ├── active admin
      │      │
      │      ▼
      │   return existing
      │   changed=False
      │
      └── another account
             │
             ▼
          conflict
```

If a different active administrator already exists, bootstrap is rejected.

---

## Administrator Disables a Support Agent

```text
Admin
 │
 ▼
UpdateUserAccessCommand
 │
 │ status = DISABLED
 │ reason = "..."
 ▼
validate admin
 │
 ▼
lock target
 │
 ▼
validate target
 │
 ▼
change status
 │
 ▼
revoke all sessions
 │
 ▼
audit
 │
 ▼
commit
```

---

## Administrator Promotes a Customer

```text
Admin
 │
 ▼
UpdateUserAccessCommand
 │
 │ role = SUPPORT_AGENT
 ▼
validate admin
 │
 ▼
lock target
 │
 ▼
change role
 │
 ▼
revoke existing sessions
 │
 ▼
audit
 │
 ▼
commit
```

---

# Testing Considerations

Tests for this folder should focus heavily on security invariants and transaction behavior.

## `ProvisionInitialAdmin`

Important scenarios include:

* valid initial bootstrap;
* email normalization;
* invalid password;
* empty password;
* oversized display name;
* existing active administrator;
* requested email already belonging to an active admin;
* requested email belonging to another account;
* missing user for existing credential;
* password hashing failure;
* concurrent bootstrap attempts;
* user persistence;
* credential persistence;
* audit event creation;
* UTC clock handling;
* missing repository dependencies;
* idempotent existing administrator result.

---

## `UpdateUserAccess`

Important scenarios include:

* non-admin caller;
* missing acting administrator;
* inactive acting administrator;
* persisted-role/authenticated-role mismatch;
* missing target user;
* system target;
* deleted target;
* role-only update;
* status-only update;
* role + status update;
* no-op update;
* self-demotion;
* self-disable;
* demotion of final active administrator;
* disabling final active administrator;
* valid administrator mutation;
* session revocation;
* audit before/after state;
* audit reason;
* revoked session count;
* repository contract failure;
* timezone-aware clock handling.

---

# Summary

The `packages/application/users/` folder provides the application's administrative user-management boundary.

```text
provision_initial_admin.py
        │
        ├── validates bootstrap request
        ├── enforces one-time initial-admin provisioning
        ├── hashes administrator credentials
        ├── creates user + credential atomically
        ├── protects against concurrent bootstrap
        └── records system audit event


update_user_access.py
        │
        ├── requires authenticated administrator
        ├── validates persisted administrator identity
        ├── protects system identities
        ├── prevents deleted-user mutation
        ├── updates role/status
        ├── prevents administrator self-lockout
        ├── protects final active administrator
        ├── revokes authentication sessions
        └── records administrative audit event
```

The central invariant is that **administrative access changes are treated as security-sensitive application operations rather than ordinary CRUD updates**.

Both services enforce their invariants inside explicit Unit of Work boundaries, protect critical concurrent operations with database locks, and produce audit records for traceability. The result is a controlled lifecycle from **initial administrator bootstrap** through **ongoing administrative access management**.
