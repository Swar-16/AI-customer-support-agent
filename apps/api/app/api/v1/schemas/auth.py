# AI-customer-support-agent\apps\api\app\api\v1\schemas\auth.py
from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from packages.application.auth.logout_user import LogoutResult
from packages.application.auth.models import AuthenticatedUser, AuthenticationResult, AuthRole, AuthUserStatus, normalize_email

class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class RegisterRequest(StrictRequestModel):
    email: str = Field(min_length=3, max_length=320, examples=["customer@example.com"])
    password: SecretStr = Field(min_length=1, max_length=1024, examples=["correct-horse-battery-staple"])
    display_name: str | None = Field(default=None, max_length=255, examples=["Alex Morgan"])

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = " ".join(value.split())
        return normalized or None

class LoginRequest(StrictRequestModel):
    email: str = Field(min_length=3, max_length=320, examples=["customer@example.com"])
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)

class RefreshSessionRequest(StrictRequestModel):
    refresh_token: SecretStr = Field(
        min_length=1,
        max_length=512,
        description="Opaque refresh token previously issued by the authentication API.",
    )

class AuthenticatedUserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: uuid.UUID
    email: str
    display_name: str | None
    role: AuthRole
    status: AuthUserStatus
    created_at: datetime

    @classmethod
    def from_application(cls, user: AuthenticatedUser) -> "AuthenticatedUserResponse":
        return cls(
            id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            status=user.status,
            created_at=user.created_at,
        )

class TokenPairResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    access_token: str
    refresh_token: str
    token_type: str
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime

class AuthenticationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user: AuthenticatedUserResponse
    tokens: TokenPairResponse

    @classmethod
    def from_application(cls, result: AuthenticationResult) -> "AuthenticationResponse":
        return cls(
            user=AuthenticatedUserResponse.from_application(result.user),
            tokens=TokenPairResponse(
                access_token=result.tokens.access_token,
                refresh_token=result.tokens.refresh_token,
                token_type=result.tokens.token_type,
                access_token_expires_at=result.tokens.access_token_expires_at,
                refresh_token_expires_at=result.tokens.refresh_token_expires_at,
            ),
        )

class LogoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    logged_out: bool
    session_id: uuid.UUID
    revoked_at: datetime | None

    @classmethod
    def from_application(cls, result: LogoutResult) -> "LogoutResponse":
        return cls(
            # An already inactive or missing session still satisfies the idempotent logout request.
            logged_out=result.revoked or result.already_inactive,
            session_id=result.session_id,
            revoked_at=result.revoked_at,
        )