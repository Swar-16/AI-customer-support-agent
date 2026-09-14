# AI-customer-support-agent\packages\application\auth\authenticate_access_token.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from packages.application.auth.exceptions import AccessAuthenticationRejectedError, AccessAuthenticationReason, AccessTokenError
from packages.application.auth.exceptions import AccessAuthenticationPersistenceError, AccessAuthenticationConfigurationError, AccessTokenExpiredError
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole, AuthUserStatus
from packages.application.auth.token_service import TokenService
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
Clock = Callable[[], datetime]

@dataclass(frozen=True, slots=True)
class AuthenticateAccessTokenCommand:
    access_token: str

    def __post_init__(self) -> None:
        if not isinstance(self.access_token, str):
            raise TypeError("access_token must be a string")

        normalized = self.access_token.strip()
        if not normalized:
            raise ValueError("access_token cannot be blank")

        object.__setattr__(self, "access_token", normalized)

class AuthenticateAccessToken:
    """
    Validate an access JWT against current persisted security state.

    Signature validation alone is insufficient because a correctly signed JWT may refer to:

    - a logged-out session;
    - an expired refresh session;
    - a disabled or deleted user;
    - a user whose role changed after token issuance.

    No database state is mutated here. HTTP request telemetry records usage
    separately, avoiding a write transaction for every authenticated request.
    """
    _INTERACTIVE_ROLES = frozenset({AuthRole.CUSTOMER, AuthRole.SUPPORT_AGENT, AuthRole.ADMIN,})

    def __init__(self, *, uow_factory: UnitOfWorkFactory, token_service: TokenService, clock: Clock | None = None) -> None:
        if uow_factory is None or not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if token_service is None:
            raise TypeError("token_service cannot be None")

        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")

        self._uow_factory = uow_factory
        self._token_service = token_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def execute(self, command: AuthenticateAccessTokenCommand) -> AuthenticatedPrincipal:
        if not isinstance(command, AuthenticateAccessTokenCommand):
            raise TypeError("command must be an AuthenticateAccessTokenCommand")

        try:
            claims = self._token_service.decode_access_token(command.access_token)
            
        except AccessTokenExpiredError as exc:
            raise AccessAuthenticationRejectedError(AccessAuthenticationReason.TOKEN_EXPIRED) from exc
        
        except AccessTokenError as exc:
            raise AccessAuthenticationRejectedError(AccessAuthenticationReason.TOKEN_INVALID) from exc

        try:
            token_role = AuthRole(claims.role)
            
        except ValueError as exc:
            raise AccessAuthenticationRejectedError(AccessAuthenticationReason.TOKEN_INVALID) from exc

        if token_role not in self._INTERACTIVE_ROLES:
            raise AccessAuthenticationRejectedError(AccessAuthenticationReason.ROLE_NOT_INTERACTIVE)

        occurred_at = self._utc_now()
        with self._uow_factory() as uow:
            if uow.auth is None:
                raise AccessAuthenticationPersistenceError("Authentication repository is unavailable.")

            if uow.users is None:
                raise AccessAuthenticationPersistenceError("User repository is unavailable.")

            auth_session = uow.auth.get_session_by_id(claims.session_id)
            if auth_session is None:
                raise AccessAuthenticationRejectedError(AccessAuthenticationReason.SESSION_NOT_FOUND)

            if auth_session.user_id != claims.user_id:
                raise AccessAuthenticationRejectedError(AccessAuthenticationReason.SESSION_USER_MISMATCH)

            if auth_session.revoked_at is not None:
                raise AccessAuthenticationRejectedError(AccessAuthenticationReason.SESSION_REVOKED)

            if auth_session.expires_at <= occurred_at:
                raise AccessAuthenticationRejectedError(AccessAuthenticationReason.SESSION_EXPIRED)

            user = uow.users.get_by_id(claims.user_id)
            if user is None:
                raise AccessAuthenticationRejectedError(AccessAuthenticationReason.USER_NOT_FOUND)

            if user.status != AuthUserStatus.ACTIVE.value:
                raise AccessAuthenticationRejectedError(AccessAuthenticationReason.USER_INACTIVE)

            if user.role != token_role.value:
                raise AccessAuthenticationRejectedError(AccessAuthenticationReason.ROLE_CHANGED)

            return AuthenticatedPrincipal(user_id=user.id, session_id=auth_session.id, role=token_role)

    def _utc_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise AccessAuthenticationConfigurationError("Authentication clock must return a datetime.")

        if value.tzinfo is None:
            raise AccessAuthenticationConfigurationError("Authentication clock must return a timezone-aware datetime.")

        return value.astimezone(timezone.utc)