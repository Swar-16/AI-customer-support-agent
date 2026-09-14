# AI-customer-support-agent\packages\application\auth\models.py
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

class AuthRole(StrEnum):
    CUSTOMER = "customer"
    SUPPORT_AGENT = "support_agent"
    ADMIN = "admin"
    SYSTEM = "system"

class AuthUserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    DELETED = "deleted"

@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """
    Trusted identity extracted from a verified access token.

    Route handlers may accept this object as the authenticated requester.
    They must not reconstruct it from request bodies or query parameters.
    """
    user_id: uuid.UUID
    session_id: uuid.UUID
    role: AuthRole

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, uuid.UUID):
            raise TypeError("user_id must be a UUID")

        if not isinstance(self.session_id, uuid.UUID):
            raise TypeError("session_id must be a UUID")

        if not isinstance(self.role, AuthRole):
            raise TypeError("role must be an AuthRole")

@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    user_id: uuid.UUID
    email: str
    display_name: str | None
    role: AuthRole
    status: AuthUserStatus
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, uuid.UUID):
            raise TypeError("user_id must be a UUID")

        normalized_email = normalize_email(self.email)
        object.__setattr__(self, "email", normalized_email)

        if self.display_name is not None:
            normalized_name = self.display_name.strip()
            object.__setattr__(self, "display_name", normalized_name or None)

        if not isinstance(self.role, AuthRole):
            raise TypeError("role must be an AuthRole")

        if not isinstance(self.status, AuthUserStatus):
            raise TypeError("status must be an AuthUserStatus")

        _require_timezone_aware(self.created_at, field_name="created_at")

@dataclass(frozen=True, slots=True)
class AuthTokenPair:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime
    token_type: str = "Bearer"

    def __post_init__(self) -> None:
        if not self.access_token:
            raise ValueError("access_token cannot be blank")

        if not self.refresh_token:
            raise ValueError("refresh_token cannot be blank")

        if self.token_type != "Bearer":
            raise ValueError("token_type must be 'Bearer'")

        _require_timezone_aware(self.access_token_expires_at, field_name="access_token_expires_at")
        _require_timezone_aware(self.refresh_token_expires_at, field_name="refresh_token_expires_at")

        if self.refresh_token_expires_at <= self.access_token_expires_at:
            raise ValueError("refresh token must expire after access token")

@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    user: AuthenticatedUser
    tokens: AuthTokenPair

@dataclass(frozen=True, slots=True)
class RegisterCommand:
    email: str
    password: str = field(repr=False)
    display_name: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    trace_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "email", normalize_email(self.email))
        _validate_password_input(self.password)

        if self.display_name is not None:
            normalized_name = self.display_name.strip()

            if len(normalized_name) > 255:
                raise ValueError("display_name cannot exceed 255 characters")

            object.__setattr__(self, "display_name", normalized_name or None)

        _validate_request_metadata(client_ip=self.client_ip, user_agent=self.user_agent, trace_id=self.trace_id)

@dataclass(frozen=True, slots=True)
class LoginCommand:
    email: str
    password: str = field(repr=False)
    client_ip: str | None = None
    user_agent: str | None = None
    trace_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "email", normalize_email(self.email))
        _validate_password_input(self.password)
        _validate_request_metadata(client_ip=self.client_ip, user_agent=self.user_agent, trace_id=self.trace_id)

@dataclass(frozen=True, slots=True)
class RefreshSessionCommand:
    refresh_token: str = field(repr=False)
    client_ip: str | None = None
    user_agent: str | None = None
    trace_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.refresh_token, str) or not self.refresh_token.strip():
            raise ValueError("refresh_token cannot be blank")

        object.__setattr__(self, "refresh_token", self.refresh_token.strip())
        _validate_request_metadata(client_ip=self.client_ip, user_agent=self.user_agent, trace_id=self.trace_id)

@dataclass(frozen=True, slots=True)
class LogoutCommand:
    principal: AuthenticatedPrincipal
    trace_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if self.trace_id is not None and not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID")

def normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise TypeError("email must be a string")

    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("email cannot be blank")

    if len(normalized) > 320:
        raise ValueError("email cannot exceed 320 characters")

    if normalized.count("@") != 1:
        raise ValueError("email format is invalid")

    local_part, domain = normalized.split("@", maxsplit=1)
    if not local_part or not domain or "." not in domain:
        raise ValueError("email format is invalid")

    return normalized

def _validate_password_input(password: str) -> None:
    if not isinstance(password, str):
        raise TypeError("password must be a string")

    if not password:
        raise ValueError("password cannot be empty")

    if len(password.encode("utf-8")) > 1_024:
        raise ValueError("password cannot exceed 1024 UTF-8 encoded bytes")

def _validate_request_metadata(*, client_ip: str | None, user_agent: str | None, trace_id: uuid.UUID | None) -> None:
    if client_ip is not None:
        if not isinstance(client_ip, str):
            raise TypeError("client_ip must be a string")

        if len(client_ip) > 255:
            raise ValueError("client_ip cannot exceed 255 characters")

    if user_agent is not None:
        if not isinstance(user_agent, str):
            raise TypeError("user_agent must be a string")

        if len(user_agent) > 2_048:
            raise ValueError("user_agent cannot exceed 2048 characters")

    if trace_id is not None and not isinstance(trace_id, uuid.UUID):
        raise TypeError("trace_id must be a UUID")

def _require_timezone_aware(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")

    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")