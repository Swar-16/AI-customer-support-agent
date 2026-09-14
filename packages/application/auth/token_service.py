# AI-customer-support-agent\packages\application\auth\token_service.py
from __future__ import annotations
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from uuid6 import uuid7

from packages.application.auth.exceptions import AccessTokenExpiredError, InvalidAccessTokenError

@dataclass(frozen=True, slots=True)
class TokenServiceConfig:
    secret_key: str
    issuer: str = "support-ai"
    audience: str = "support-ai-api"
    access_token_ttl: timedelta = timedelta(minutes=15)
    clock_skew_seconds: int = 30
    algorithm: str = "HS256"

    def __post_init__(self) -> None:
        if not isinstance(self.secret_key, str):
            raise TypeError("secret_key must be a string")

        if len(self.secret_key.encode("utf-8")) < 32:
            raise ValueError("secret_key must contain at least 32 UTF-8 encoded bytes")

        if not self.issuer.strip():
            raise ValueError("issuer cannot be blank")

        if not self.audience.strip():
            raise ValueError("audience cannot be blank")

        if self.access_token_ttl <= timedelta(0):
            raise ValueError("access_token_ttl must be greater than zero")

        if self.clock_skew_seconds < 0:
            raise ValueError("clock_skew_seconds cannot be negative")

        if self.algorithm != "HS256":
            raise ValueError("Only HS256 is supported by this token service.")

@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    role: str
    token_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class IssuedAccessToken:
    token: str
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class RefreshTokenMaterial:
    """
    Raw refresh token returned to the client and its persistence-safe hash.

    Only ``token_hash`` may be stored in PostgreSQL.
    """
    raw_token: str
    token_hash: str

class TokenService:
    ACCESS_TOKEN_TYPE = "access"
    _ALLOWED_ROLES = frozenset({"customer", "support_agent", "admin", "system",})

    def __init__(self, config: TokenServiceConfig) -> None:
        if config is None:
            raise TypeError("config cannot be None")

        self._config = config

    def issue_access_token(self, *, user_id: uuid.UUID, session_id: uuid.UUID, role: str, now: datetime | None = None) -> IssuedAccessToken:
        normalized_role = self._validate_role(role)
        issued_at = self._normalize_now(now)
        expires_at = issued_at + self._config.access_token_ttl
        token_id = uuid7()

        payload: dict[str, Any] = {
            "sub": str(user_id),
            "sid": str(session_id),
            "role": normalized_role,
            "jti": str(token_id),
            "type": self.ACCESS_TOKEN_TYPE,
            "iss": self._config.issuer,
            "aud": self._config.audience,
            "iat": issued_at,
            "nbf": issued_at,
            "exp": expires_at,
        }

        encoded = jwt.encode(payload, self._config.secret_key, algorithm=self._config.algorithm)
        return IssuedAccessToken(token=encoded, expires_at=expires_at)

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        if not isinstance(token, str) or not token.strip():
            raise InvalidAccessTokenError("Access token is missing.")

        try:
            payload = jwt.decode(
                token.strip(),
                self._config.secret_key,
                algorithms=[self._config.algorithm],
                issuer=self._config.issuer,
                audience=self._config.audience,
                leeway=self._config.clock_skew_seconds,
                options={
                    "require": ["sub", "sid", "role", "jti", "type", "iss", "aud", "iat", "nbf", "exp",]
                },
            )
        except ExpiredSignatureError as exc:
            raise AccessTokenExpiredError("Access token has expired.") from exc
        except InvalidTokenError as exc:
            raise InvalidAccessTokenError("Access token is invalid.") from exc

        if payload.get("type") != self.ACCESS_TOKEN_TYPE:
            raise InvalidAccessTokenError("Unexpected token type.")

        try:
            user_id = uuid.UUID(str(payload["sub"]))
            session_id = uuid.UUID(str(payload["sid"]))
            token_id = uuid.UUID(str(payload["jti"]))
            role = self._validate_role(str(payload["role"]))
            issued_at = datetime.fromtimestamp(float(payload["iat"]), tz=timezone.utc)
            expires_at = datetime.fromtimestamp(float(payload["exp"]), tz=timezone.utc)
            
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise InvalidAccessTokenError("Access token claims are invalid.") from exc

        return AccessTokenClaims(
            user_id=user_id,
            session_id=session_id,
            role=role,
            token_id=token_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    @staticmethod
    def generate_refresh_token() -> RefreshTokenMaterial:
        """
        Generate a high-entropy opaque refresh token.

        The token is not a JWT and contains no user information.
        """
        raw_token = secrets.token_urlsafe(64)

        return RefreshTokenMaterial(raw_token=raw_token, token_hash=TokenService.hash_refresh_token(raw_token))

    @staticmethod
    def hash_refresh_token(refresh_token: str) -> str:
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            raise ValueError("refresh_token cannot be blank")

        return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()

    @classmethod
    def _validate_role(cls, role: str) -> str:
        if not isinstance(role, str):
            raise TypeError("role must be a string")

        normalized = role.strip().lower()

        if normalized not in cls._ALLOWED_ROLES:
            raise ValueError(f"Unsupported authentication role: {role!r}")

        return normalized

    @staticmethod
    def _normalize_now(value: datetime | None) -> datetime:
        resolved = value or datetime.now(timezone.utc)
        if resolved.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        return resolved.astimezone(timezone.utc)