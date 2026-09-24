# Authentication Application Layer

## Overview

The `auth` package implements the **application-layer authentication and session-management subsystem** of the AI customer-support agent.

```text
AI-customer-support-agent/
└── packages/
    └── application/
        └── auth/
            ├── authenticate_access_token.py
            ├── exceptions.py
            ├── get_current_user.py
            ├── login_user.py
            ├── logout_user.py
            ├── models.py
            ├── password_hasher.py
            ├── refresh_session.py
            ├── register_user.py
            └── token_service.py
```

The package coordinates the complete local-authentication lifecycle:

```text
                    Authentication Layer
                            │
       ┌────────────────────┼────────────────────┐
       │                    │                    │
       ▼                    ▼                    ▼
   Registration          Login              Existing Session
       │                    │                    │
       ▼                    ▼                    ▼
 Create User          Verify Password      Authenticate JWT
 Create Credential    Create Session       Validate DB State
 Create Session       Issue Tokens         Build Principal
       │                    │                    │
       └──────────────┬─────┴────────────────────┘
                      │
                      ▼
                Session Lifecycle
                      │
              ┌───────┴────────┐
              ▼                ▼
           Refresh           Logout
              │                │
              ▼                ▼
       Rotate Session      Revoke Session
```

The package deliberately separates:

* authentication contracts;
* password hashing;
* token cryptography;
* authentication use cases;
* authentication errors.

---

# Package Responsibilities

The authentication layer is responsible for:

* registering customers;
* validating registration passwords;
* hashing and verifying passwords;
* issuing JWT access tokens;
* generating opaque refresh tokens;
* hashing refresh tokens for persistence;
* authenticating access tokens against current database state;
* logging users in;
* enforcing failed-login lockout;
* rotating refresh sessions;
* detecting refresh-token reuse;
* logging users out;
* retrieving the current authenticated user's safe profile;
* maintaining authentication-related audit events;
* exposing safe public authentication errors.

The package does **not** treat a valid JWT signature as sufficient proof of an active session. The persisted authentication state is checked as well.

---

# Package Structure

| File                           | Responsibility                                                            |
| ------------------------------ | ------------------------------------------------------------------------- |
| `models.py`                    | Shared authentication contracts, enums, commands, results, and validation |
| `password_hasher.py`           | Argon2id password hashing, verification, and rehash detection             |
| `token_service.py`             | JWT access tokens and opaque refresh-token primitives                     |
| `register_user.py`             | Customer registration and initial session creation                        |
| `login_user.py`                | Password authentication and session creation                              |
| `refresh_session.py`           | Single-use refresh-token rotation and reuse detection                     |
| `logout_user.py`               | Authenticated-session revocation                                          |
| `authenticate_access_token.py` | JWT + persisted-session authentication                                    |
| `get_current_user.py`          | Safe retrieval of the authenticated user's profile                        |
| `exceptions.py`                | Typed authentication/application failure hierarchy                        |

---

# Architectural Position

The package sits between API/request handling and persistence/security infrastructure.

```text
API / HTTP Layer
       │
       ▼
Application Authentication Use Cases
       │
       ├── RegisterUser
       ├── LoginUser
       ├── RefreshSession
       ├── LogoutUser
       ├── AuthenticateAccessToken
       └── GetCurrentUser
       │
       ├──────────────┐
       ▼              ▼
TokenService     PasswordHasher
       │              │
       └───────┬──────┘
               ▼
       SqlAlchemyUnitOfWork
               │
       ┌───────┼────────┐
       ▼       ▼        ▼
     Users   Auth     Audit
```

The application services depend on abstractions and infrastructure adapters rather than embedding cryptographic or database logic throughout the use cases.

---

# Authentication State Model

The authentication system distinguishes three related concepts:

```text
User
 │
 ├── Credential
 │     ├── password_hash
 │     ├── failed_login_attempts
 │     └── locked_until
 │
 └── Auth Sessions
       ├── refresh_token_hash
       ├── family_id
       ├── expires_at
       ├── revoked_at
       └── replaced_by_session_id
```

Access tokens reference the user and session through JWT claims, while the session database record remains the authoritative state for revocation and expiration.

---

# Authentication Roles

`models.py` defines four roles:

```text
customer
support_agent
admin
system
```

The corresponding user states are:

```text
active
disabled
deleted
```

Interactive access-token authentication permits:

```text
customer
support_agent
admin
```

but excludes the `system` role from interactive authentication.

---

# `models.py`

## Purpose

`models.py` contains the shared application contracts used by the authentication use cases.

It deliberately uses immutable:

```python
@dataclass(frozen=True, slots=True)
```

models.

The file defines:

* `AuthRole`;
* `AuthUserStatus`;
* `AuthenticatedPrincipal`;
* `AuthenticatedUser`;
* `AuthTokenPair`;
* `AuthenticationResult`;
* `RegisterCommand`;
* `LoginCommand`;
* `RefreshSessionCommand`;
* `LogoutCommand`;
* validation helpers.

---

# `AuthenticatedPrincipal`

`AuthenticatedPrincipal` represents a **trusted identity produced by access-token authentication**.

It contains:

```text
user_id
session_id
role
```

The design explicitly treats this as trusted authentication state.

Route handlers should consume this principal rather than reconstructing identity from:

* request bodies;
* query parameters;
* other caller-controlled fields.

---

# `AuthenticatedUser`

`AuthenticatedUser` is the safe application representation of a user's public authentication profile.

It contains:

```text
user_id
email
display_name
role
status
created_at
```

It does not contain:

* password hashes;
* refresh-token hashes;
* session identifiers;
* lockout state;
* failed-login counters.

---

# `AuthTokenPair`

An authentication response contains:

```text
access_token
refresh_token
access_token_expires_at
refresh_token_expires_at
token_type
```

The default token type is:

```text
Bearer
```

The model requires the refresh token to expire after the access token.

---

# `AuthenticationResult`

`AuthenticationResult` combines:

```text
AuthenticatedUser
+
AuthTokenPair
```

This is the common successful result returned by:

* registration;
* login;
* refresh.

---

# Authentication Commands

The application layer uses explicit command objects.

## `RegisterCommand`

Contains:

```text
email
password
display_name
client_ip
user_agent
trace_id
```

## `LoginCommand`

Contains:

```text
email
password
client_ip
user_agent
trace_id
```

## `RefreshSessionCommand`

Contains:

```text
refresh_token
client_ip
user_agent
trace_id
```

## `LogoutCommand`

Contains:

```text
AuthenticatedPrincipal
trace_id
```

Passwords and refresh tokens are marked `repr=False`, preventing accidental exposure through normal dataclass representations.

---

# Input Normalization

Email addresses are:

1. required to be strings;
2. stripped;
3. lowercased;
4. limited to 320 characters;
5. required to contain exactly one `@`;
6. required to contain a non-empty local part and domain;
7. required to contain a dot in the domain.

---

# Password Input Validation

Command-level password validation requires:

* a string;
* non-empty content;
* no more than 1,024 UTF-8 encoded bytes.

This validation is intentionally separate from the stronger registration password policy implemented by `register_user.py`.

---

# Request Metadata Validation

Optional:

```text
client_ip
user_agent
trace_id
```

are validated at the command boundary.

The limits are:

```text
client_ip   <= 255 characters
user_agent  <= 2048 characters
trace_id    must be UUID
```

---

# `password_hasher.py`

## Purpose

This module isolates password hashing from authentication workflows.

The application depends on:

```python
PasswordHasherContract
```

rather than directly depending on the Argon2 implementation.

The contract provides:

```text
hash_password()
verify_password()
needs_rehash()
```

---

# Argon2id Configuration

`Argon2PasswordHasherConfig` defaults to:

```text
time_cost    = 2
memory_cost  = 19,456 KiB
parallelism  = 1
hash_length  = 32 bytes
salt_length  = 16 bytes
```

All numeric parameters must be positive.

---

# Argon2 Adapter

`Argon2PasswordHasher` constructs an Argon2id hasher using:

```python
Type.ID
```

and the configured parameters.

This keeps the application use cases independent from `argon2-cffi`.

---

# Password Hashing

`hash_password()`:

1. validates the password type and size;
2. passes it to Argon2id;
3. converts Argon2 hashing failures into `PasswordHashingError`.

The input is bounded to 1,024 UTF-8 bytes to avoid excessive resource consumption.

---

# Password Verification

`verify_password()` deliberately returns:

```text
True
False
```

rather than exposing low-level verification exceptions.

Invalid hashes, mismatches, and verification failures all result in `False`.

This gives login logic a simple authentication predicate.

---

# Password Rehashing

`needs_rehash()` checks whether an existing password hash no longer matches the current Argon2 configuration.

Invalid hashes also return:

```text
True
```

so the caller can treat them as requiring replacement.

The login workflow uses this to transparently upgrade hashes after successful authentication.

---

# `token_service.py`

## Purpose

`TokenService` owns token primitives.

The architecture intentionally separates:

```text
Access Token
    JWT

Refresh Token
    opaque random secret
```

The refresh token contains no user information and is not a JWT.

---

# Token Configuration

Defaults:

```text
issuer              = support-ai
audience            = support-ai-api
access_token_ttl    = 15 minutes
clock_skew_seconds  = 30
algorithm           = HS256
```

The secret must contain at least 32 UTF-8 encoded bytes, and only `HS256` is accepted.

---

# Access JWT Claims

Issued JWTs contain:

```text
sub   → user ID
sid   → session ID
role  → authentication role
jti   → token ID
type  → access
iss   → issuer
aud   → audience
iat   → issued-at timestamp
nbf   → not-before timestamp
exp   → expiration timestamp
```

---

# JWT Validation

`decode_access_token()` verifies:

* signature;
* configured algorithm;
* issuer;
* audience;
* required claims;
* expiration;
* token type;
* UUID formatting;
* role validity;
* timestamps.

Expired tokens become:

```text
AccessTokenExpiredError
```

Other malformed/untrusted tokens become:

```text
InvalidAccessTokenError
```

---

# Refresh Tokens

Refresh tokens are generated using:

```python
secrets.token_urlsafe(64)
```

and therefore contain high-entropy random data.

Only the SHA-256 hash should be persisted:

```python
SHA256(refresh_token)
```

The raw token is returned to the client but is never stored in the database.

---

# `register_user.py`

## Purpose

`RegisterUser` creates a customer account and its initial authenticated session.

A successful registration atomically creates:

```text
User
Credential
Refresh Session
Audit Event
```

The plaintext password and raw refresh token are never persisted.

---

# Registration Password Policy

Registration requires at least:

```text
10 characters
```

and no more than:

```text
1,024 UTF-8 bytes
```

It also rejects:

* NUL characters;
* known common passwords;
* passwords containing the email username;
* passwords containing the normalized display name.

---

# Registration Flow

```text
RegisterCommand
      │
      ▼
Validate Registration Password
      │
      ▼
Hash Password
      │
      ▼
Generate UUIDv7 IDs
      │
      ├── user_id
      ├── session_id
      └── token_family_id
      │
      ▼
Generate Refresh Token
      │
      ▼
Issue Access JWT
      │
      ▼
Build User/Credential/Session
      │
      ▼
Check Existing Email
      │
      ▼
Persist User
      │
      ▼
Persist Credential + Session
      │
      ▼
Record Audit Event
      │
      ▼
Commit
      │
      ▼
AuthenticationResult
```

---

# Registration Atomicity

The user is flushed before dependent records are inserted so foreign-key relationships can be established.

The flush is **not** a commit.

The complete registration remains one transaction:

```text
User + Credential + Session + Audit
                  │
                  ▼
                COMMIT
```

---

# Duplicate Email Handling

The application checks for an existing credential by email before insertion.

Database uniqueness constraints remain the final protection.

Expected PostgreSQL email uniqueness violations are translated into:

```text
RegistrationConflictError
```

while unrelated integrity failures become:

```text
RegistrationPersistenceError
```

---

# Registration Audit

Successful registration records:

```text
event_type = auth.user_registered
action     = registered
entity     = user
```

with metadata including:

```text
auth_session_id
token_family_id
registration_method
```

---

# `login_user.py`

## Purpose

`LoginUser` authenticates local-password users and establishes a refresh-token session.

Its security properties include:

* Argon2 verification even for unknown emails;
* generic public authentication failures;
* row-locked failed-attempt updates;
* persisted temporary lockout;
* failure-state reset on success;
* automatic password-hash upgrades;
* non-persistence of raw refresh tokens;
* immutable audit events for attempts.

---

# Login Flow

```text
LoginCommand
      │
      ▼
Find Credential FOR UPDATE
      │
      ├── Unknown
      │     └── Dummy Argon2 Verification
      │
      └── Known
            │
            ├── Locked
            ├── Inactive
            ├── Wrong Password
            └── Correct Password
                     │
                     ▼
              Create Session
                     │
                     ▼
               Issue Tokens
                     │
                     ▼
                Audit Event
```

---

# Timing-Safe Unknown User Handling

If the email is unknown, the service still performs Argon2 verification against a precomputed dummy password hash.

This prevents an obviously faster unknown-account path that could facilitate account enumeration through timing differences.

---

# Account Lockout

Failed password attempts increment:

```text
failed_login_attempts
```

Once the configured threshold is reached:

```text
locked_until = current_time + lockout_duration
```

An expired lock is cleared before starting a new attempt window.

---

# Generic Authentication Failure

Unknown accounts, wrong passwords, disabled accounts, and locked accounts ultimately become:

```text
InvalidCredentialsError
```

with the public message:

```text
Invalid email or password.
```

This prevents the API from revealing whether an account exists or what state it is in.

---

# Successful Login

Successful authentication:

1. resets failed-attempt state;
2. clears lockout;
3. optionally rehashes the password;
4. creates a new session;
5. creates a new token family;
6. generates an opaque refresh token;
7. issues an access JWT;
8. records an audit event.

---

# Login Audit

Successful login records:

```text
auth.login_succeeded
```

with:

```text
entity_type = auth_session
action      = login_succeeded
```

and metadata containing:

```text
user_id
token_family_id
authentication_method
```

Failed attempts produce:

```text
auth.login_failed
```

and use a random attempt UUID when there is no known user ID, avoiding storage of the submitted email or a reversible email fingerprint.

---

# `refresh_session.py`

## Purpose

`RefreshSession` implements **single-use refresh-token rotation**.

The core invariant is:

```text
One refresh token
      │
      ▼
One successful consumption
      │
      ▼
Old session revoked
      │
      ▼
Replacement session created
```

---

# Refresh Flow

```text
Raw Refresh Token
      │
      ▼
SHA-256 Hash
      │
      ▼
Find Session FOR UPDATE
      │
      ├── Unknown
      │      └── Reject
      │
      ├── Already Revoked
      │      └── Reuse Detection
      │
      ├── Expired
      │      └── Reject
      │
      ├── Account Invalid
      │      └── Revoke Family
      │
      └── Valid
             │
             ▼
       Create Replacement
             │
             ▼
       Revoke Current
             │
             ▼
        Audit Event
             │
             ▼
           Commit
```

---

# Refresh Token Reuse Detection

If a previously revoked token is presented again, the system treats this as token reuse.

It then revokes all still-active sessions in the token family:

```text
Reused Token
     │
     ▼
Token Family
     │
     ├── Active session → revoke
     ├── Active session → revoke
     └── Active session → revoke
```

and records:

```text
auth.refresh_reuse_detected
```

---

# Refresh Lifetime Preservation

Refresh rotation deliberately preserves the original session expiration.

It does **not** extend the refresh-session lifetime indefinitely on every rotation.

---

# Replacement Session Ordering

The replacement session is inserted and flushed before the old session's:

```text
replaced_by_session_id
```

is updated.

This is required because the replacement relationship uses a self-referencing foreign key.

---

# Refresh Audit Events

Possible refresh audit events include:

```text
auth.refresh_failed
auth.refresh_reuse_detected
auth.session_refreshed
```

Unknown tokens do not have a known session and therefore receive a random audit-attempt entity ID without persisting the token or lookup hash.

---

# Public Refresh Failure

Unknown, expired, revoked, reused, and account-invalid refresh tokens deliberately collapse into:

```text
InvalidRefreshTokenError
```

with the public message:

```text
The refresh token is invalid or expired.
```

This prevents callers from learning sensitive session-state information.

---

# `logout_user.py`

## Purpose

`LogoutUser` revokes the authenticated principal's current refresh session.

Logout is intentionally **idempotent**.

```text
Active session
    → revoke + audit + commit

Already revoked
    → success, no new audit event

Missing session
    → success, no existence disclosure
```

---

# Logout Flow

```text
AuthenticatedPrincipal
        │
        ▼
Find Session FOR UPDATE
        │
        ├── Missing ──────► Already inactive
        │
        ├── Wrong Owner ─► Ownership Error
        │
        ├── Revoked ─────► Already inactive
        │
        └── Active
              │
              ▼
          Revoke Session
              │
              ▼
          Audit Event
              │
              ▼
            Commit
```

---

# Logout Revocation

An active session is updated with:

```text
last_used_at
revoked_at
revocation_reason = user_logout
```

and an audit event:

```text
auth.session_revoked
```

is recorded.

---

# Access Tokens and Logout

JWTs cannot be physically deleted from clients.

Therefore, logout relies on the persisted session state.

After logout:

```text
JWT
 │
 ├── signature valid
 └── session revoked
          │
          ▼
      Authentication rejected
```

This is why `AuthenticateAccessToken` checks the persisted session.

---

# `authenticate_access_token.py`

## Purpose

`AuthenticateAccessToken` authenticates a bearer access token against **both cryptographic JWT state and current persisted security state**.

A valid signature alone is insufficient because the token could reference:

* a logged-out session;
* an expired session;
* a disabled/deleted user;
* a user whose role changed after token issuance.

---

# Authentication Flow

```text
Access JWT
    │
    ▼
TokenService.decode_access_token()
    │
    ├── Expired ─────────► TOKEN_EXPIRED
    └── Invalid ─────────► TOKEN_INVALID
    │
    ▼
Validate Role
    │
    ▼
Load Session
    │
    ├── Missing
    ├── User mismatch
    ├── Revoked
    └── Expired
    │
    ▼
Load User
    │
    ├── Missing
    ├── Inactive
    └── Role changed
    │
    ▼
AuthenticatedPrincipal
```

---

# Session Validation

The service verifies:

```text
session exists
session.user_id == token.user_id
session is not revoked
session is not expired
```

---

# User Validation

It then verifies:

```text
user exists
user.status == ACTIVE
user.role == token.role
```

This means role changes take effect even for JWTs that have not yet expired.

---

# No Authentication Write Transaction

`AuthenticateAccessToken` does not mutate database state.

The implementation explicitly avoids a write transaction for every authenticated request; request telemetry is handled separately.

This is important for scalability because access-token authentication may occur on every API request.

---

# `get_current_user.py`

## Purpose

`GetCurrentUser` converts an authenticated principal into the user's safe application profile.

```text
AuthenticatedPrincipal
        │
        ▼
Database User + Credential
        │
        ▼
AuthenticatedUser
```

---

# Current User Validation

The service verifies:

1. user exists;
2. credentials exist;
3. user is active;
4. database role matches the trusted principal role.

A mismatch between the trusted principal and current database role becomes:

```text
CurrentUserStateConflictError
```

---

# Sensitive Data Boundary

`GetCurrentUser` deliberately does not return:

* password hashes;
* refresh-token hashes;
* session-family IDs;
* failed-login counters;
* lockout details.

This makes `AuthenticatedUser` a safe application-level profile object.

---

# `exceptions.py`

## Purpose

`exceptions.py` defines the typed error boundary for the entire authentication package.

The hierarchy separates:

```text
Password Hashing
Registration
Token Processing
Refresh Sessions
Login
Logout
Access Authentication
Current User
```

---

# Exception Hierarchy

```text
RuntimeError
│
├── PasswordHashingError
│
├── RegistrationError
│   ├── RegistrationConflictError
│   ├── RegistrationPasswordPolicyError
│   ├── RegistrationPersistenceError
│   ├── RegistrationConfigurationError
│   └── RegistrationPasswordHashingError
│
├── RefreshSessionError
│   ├── InvalidRefreshTokenError
│   ├── RefreshSessionPersistenceError
│   └── RefreshSessionConfigurationError
│
├── LoginError
│   ├── InvalidCredentialsError
│   ├── LoginPersistenceError
│   ├── LoginConfigurationError
│   └── LoginPasswordHashingError
│
├── LogoutError
│   ├── LogoutSessionOwnershipError
│   ├── LogoutPersistenceError
│   └── LogoutConfigurationError
│
├── AccessAuthenticationError
│   ├── AccessAuthenticationRejectedError
│   ├── AccessAuthenticationPersistenceError
│   └── AccessAuthenticationConfigurationError
│
└── GetCurrentUserError
    ├── CurrentUserUnavailableError
    ├── CurrentUserStateConflictError
    └── GetCurrentUserPersistenceError
```

Token parsing errors form a separate `ValueError` hierarchy:

```text
AccessTokenError
├── AccessTokenExpiredError
└── InvalidAccessTokenError
```

---

# Safe Public Error Design

A major design principle is to distinguish:

```text
Internal reason
      │
      ▼
Typed internal exception
      │
      ▼
Generic public response
```

For example, access authentication has internal reasons:

```text
TOKEN_INVALID
TOKEN_EXPIRED
SESSION_NOT_FOUND
SESSION_USER_MISMATCH
SESSION_REVOKED
SESSION_EXPIRED
USER_NOT_FOUND
USER_INACTIVE
ROLE_CHANGED
ROLE_NOT_INTERACTIVE
```

But the public exception message remains:

```text
Authentication credentials are invalid or expired.
```

The internal reason is available for structured logging, not for exposing account/session state to the caller.

---

# Generic Login Errors

Similarly, all major authentication failures during login become:

```text
InvalidCredentialsError
```

with:

```text
Invalid email or password.
```

This deliberately combines:

* unknown email;
* wrong password;
* disabled account;
* locked account.

---

# Generic Refresh Errors

Refresh failures similarly collapse into:

```text
InvalidRefreshTokenError
```

for:

* unknown token;
* expired token;
* revoked token;
* reused token;
* unavailable account.

---

# Audit Integration

Authentication is tightly integrated with the application's audit subsystem.

The major flows record immutable audit events:

| Operation           | Audit Event                   |
| ------------------- | ----------------------------- |
| Registration        | `auth.user_registered`        |
| Successful login    | `auth.login_succeeded`        |
| Failed login        | `auth.login_failed`           |
| Successful refresh  | `auth.session_refreshed`      |
| Failed refresh      | `auth.refresh_failed`         |
| Refresh-token reuse | `auth.refresh_reuse_detected` |
| Logout              | `auth.session_revoked`        |

The event is generally recorded inside the same Unit of Work as the authentication state mutation.

This produces an important consistency invariant:

```text
Authentication State Change
          +
Audit Event
          │
          ▼
     Same Transaction
```

---

# Transaction and Unit-of-Work Model

The authentication services use:

```python
SqlAlchemyUnitOfWork
```

through an injected:

```python
UnitOfWorkFactory
```

This keeps database transaction management outside the individual repositories.

The general pattern is:

```text
Use Case
   │
   ▼
Create UoW
   │
   ▼
Validate repositories
   │
   ▼
Read / mutate state
   │
   ▼
Flush where necessary
   │
   ▼
Record audit event
   │
   ▼
Commit
```

Registration, login, refresh, and logout all follow this pattern.

---

# UTC Time Handling

All authentication use cases support injectable clocks.

The clock must:

* return a `datetime`;
* be timezone-aware.

The value is normalized to:

```text UTC
```

This pattern exists in registration, login, refresh, logout, and access authentication.

Injectable clocks also make time-dependent authentication behavior deterministic in tests.

---

# Security Invariants

The authentication layer establishes several important invariants.

## Passwords

```text
Plaintext password
       │
       ▼
Argon2id
       │
       ▼
Password hash
       │
       ▼
Database
```

Plaintext passwords are never persisted.

---

## Refresh Tokens

```text
Raw refresh token
       │
       ├── returned to client
       │
       ▼
SHA-256
       │
       ▼
Stored hash
```

The raw refresh token is never persisted.

---

## Access Tokens

```text
JWT signature valid
        ≠
Session valid
```

A token must correspond to:

* an existing session;
* the correct user;
* a non-revoked session;
* a non-expired session;
* an active user;
* the user's current role.

---

## Refresh Token Rotation

```text
Old token
   │
   ▼
Consumed
   │
   ▼
Revoked
   │
   ▼
Replacement token
```

Reusing the old token triggers family-wide revocation.

---

## Login Enumeration Resistance

Unknown accounts perform dummy password verification and return the same public authentication failure as known-account failures.

---

## Role Consistency

Authentication validates role at multiple boundaries:

```text
JWT role
   │
   ▼
Current database user role
   │
   ▼
AuthenticatedPrincipal
```

A role change invalidates the old authentication state even if the JWT itself remains cryptographically valid.

---

# End-to-End Authentication Lifecycle

## Registration

```text
Customer
   │
   ▼
RegisterUser
   │
   ├── Validate password
   ├── Hash password
   ├── Create user
   ├── Create credential
   ├── Create session
   ├── Issue access JWT
   ├── Generate refresh token
   └── Audit
   │
   ▼
AuthenticationResult
```

---

## Login

```text
Credentials
   │
   ▼
LoginUser
   │
   ├── Lookup credential
   ├── Verify password
   ├── Enforce lockout
   ├── Upgrade hash if necessary
   ├── Create session
   ├── Issue tokens
   └── Audit
   │
   ▼
AuthenticationResult
```

---

## Access Authentication

```text
Bearer JWT
   │
   ▼
AuthenticateAccessToken
   │
   ├── Verify JWT
   ├── Validate role
   ├── Validate session
   ├── Validate user
   └── Validate current role
   │
   ▼
AuthenticatedPrincipal
```

---

## Current User

```text
AuthenticatedPrincipal
        │
        ▼
GetCurrentUser
        │
        ├── Load user
        ├── Load credential
        ├── Verify active status
        └── Verify role consistency
        │
        ▼
AuthenticatedUser
```

---

## Refresh

```text
Refresh Token
      │
      ▼
RefreshSession
      │
      ├── Hash token
      ├── Find session
      ├── Detect reuse
      ├── Validate expiration
      ├── Validate account
      ├── Revoke old session
      ├── Create replacement
      └── Audit
      │
      ▼
AuthenticationResult
```

---

## Logout

```text
AuthenticatedPrincipal
        │
        ▼
LogoutUser
        │
        ├── Find session
        ├── Verify ownership
        ├── Revoke session
        └── Audit
        │
        ▼
LogoutResult
```

---

# Complete Session Lifecycle

```text
                    ┌──────────────┐
                    │ Registration │
                    └──────┬───────┘
                           │
                           ▼
                    Active Session
                           │
             ┌─────────────┼──────────────┐
             │             │              │
             ▼             ▼              ▼
          Refresh        Logout         Expiry
             │             │              │
             ▼             ▼              ▼
      Replacement      Revoked       Rejected
         Session         Session       Session
             │
             ▼
       Old Session
         Revoked
```

Refresh rotation creates a new session while preserving the token-family lifetime.

---

# Separation of Responsibilities

The package deliberately avoids placing all authentication behavior into one service.

```text
models.py
    │
    └── contracts

password_hasher.py
    │
    └── password cryptography

token_service.py
    │
    └── token cryptography

register_user.py
    │
    └── account creation

login_user.py
    │
    └── credential authentication

refresh_session.py
    │
    └── session rotation

logout_user.py
    │
    └── session revocation

authenticate_access_token.py
    │
    └── request authentication

get_current_user.py
    │
    └── authenticated profile lookup

exceptions.py
    │
    └── error contract
```

This makes each authentication concern independently testable and replaceable.

---

# Dependency Direction

The application use cases depend on shared contracts and infrastructure adapters:

```text
                   models.py
                  /    |    \
                 /     |     \
                ▼      ▼      ▼
         Register   Login   Refresh
             │        │       │
             ├────────┴───────┤
             ▼                ▼
      PasswordHasher      TokenService
             │                │
             └────────┬───────┘
                      ▼
              SqlAlchemyUnitOfWork
                      │
              ┌───────┴───────┐
              ▼               ▼
          Auth/User          Audit
```

The higher-level application services coordinate operations; cryptographic primitives remain isolated.

---

# Error Handling Philosophy

The package distinguishes three broad classes of failure:

## Expected authentication rejection

Examples:

```text
invalid credentials
invalid refresh token
expired access token
revoked session
inactive user
role mismatch
```

These are represented through safe, intentionally generic public errors.

## Persistence failure

Examples:

```text
missing repository
database integrity failure
session persistence failure
```

These become dedicated persistence exceptions.

## Configuration/programming failure

Examples:

```text
invalid token configuration
invalid clock
unsupported role
invalid dependency
```

These use configuration or type/value errors rather than being disguised as authentication failures.

---

# Security vs Persistence Boundary

The package intentionally keeps cryptographic concerns separate from persistence.

```text
                 Authentication
                       │
          ┌────────────┴────────────┐
          │                         │
          ▼                         ▼
    Cryptographic Layer        Persistence Layer
          │                         │
    PasswordHasher              UnitOfWork
    TokenService                    │
          │                  User/Credential/
          │                  AuthSession/Audit
          └────────────┬────────────┘
                       ▼
                Application Use Case
```

This prevents database repositories from becoming responsible for cryptographic policy and prevents token utilities from becoming aware of database state.

---

# Testing Considerations

The design provides several useful test seams:

### Injectable clock

Every time-dependent use case can receive a deterministic clock.

### Injectable Unit of Work

Authentication workflows can be tested without constructing the production database session directly.

### PasswordHasher contract

Tests can substitute a controlled password-hashing implementation.

### TokenService

Token behavior is isolated from registration/login/session orchestration.

### Explicit command models

Invalid inputs can be tested at construction boundaries.

### Typed exceptions

Expected failure paths can be asserted without matching arbitrary low-level database or cryptographic errors.

---

# Important Invariants for Future Changes

When modifying this package, preserve these invariants:

1. **Never persist plaintext passwords.**
2. **Never persist raw refresh tokens.**
3. **Do not expose password hashes or refresh-token hashes through `AuthenticatedUser`.**
4. **Do not treat JWT signature validity as equivalent to active authentication.**
5. **Keep session revocation authoritative in persisted state.**
6. **Do not reveal account existence through public login errors.**
7. **Do not reveal refresh-token/session state through public refresh errors.**
8. **Preserve refresh-token single-use semantics.**
9. **Preserve token-family reuse detection.**
10. **Keep authentication state changes and their audit events transactionally consistent.**
11. **Keep role consistency between the token, session principal, and current user.**
12. **Keep authentication timestamps timezone-aware and normalized to UTC.**

---

# Summary

The `packages/application/auth/` package is the central application-layer implementation of authentication for the customer-support agent.

Its architecture can be summarized as:

```text
                         AUTH
                          │
        ┌─────────────────┼──────────────────┐
        │                 │                  │
        ▼                 ▼                  ▼
     Identity          Credentials         Tokens
        │                 │                  │
        ▼                 ▼                  ▼
   User Models       Argon2id Hashing    JWT + Refresh
        │                 │                  │
        └─────────────────┼──────────────────┘
                          │
                          ▼
                  Authentication Flows
                          │
        ┌─────────┬───────┼────────┬────────────┐
        ▼         ▼       ▼        ▼            ▼
   Register     Login   Refresh  Logout   Authenticate
        │         │       │        │            │
        └─────────┴───────┴────────┴────────────┘
                          │
                          ▼
                       Audit
                          │
                          ▼
                     Persistence
```

The ten files form one cohesive authentication boundary:

* `models.py` defines the immutable contracts.
* `password_hasher.py` isolates Argon2id.
* `token_service.py` isolates JWT and refresh-token cryptography.
* `register_user.py` creates new authenticated accounts.
* `login_user.py` authenticates credentials and creates sessions.
* `refresh_session.py` rotates sessions and detects token reuse.
* `logout_user.py` revokes sessions idempotently.
* `authenticate_access_token.py` validates both JWTs and current persisted security state.
* `get_current_user.py` exposes a safe authenticated-user profile.
* `exceptions.py` provides the typed and security-conscious error boundary.

Together they implement an authentication model where **cryptographic validity, persisted session state, current user state, role consistency, transactional integrity, and auditability all participate in determining whether a request is authenticated**.
