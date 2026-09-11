# AI-customer-support-agent\packages\application\auth\get_current_user.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from packages.application.auth.exceptions import CurrentUserUnavailableError, CurrentUserStateConflictError, GetCurrentUserPersistenceError
from packages.application.auth.models import AuthenticatedPrincipal, AuthenticatedUser, AuthRole, AuthUserStatus
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

@dataclass(frozen=True, slots=True)
class GetCurrentUserCommand:
    principal: AuthenticatedPrincipal

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

class GetCurrentUser:
    """
    Return the safe profile of the authenticated user.

    This service never returns:

    - password hashes;
    - refresh-token hashes;
    - session-family identifiers;
    - failed-login counters;
    - lockout details.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        if uow_factory is None or not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def execute(self, command: GetCurrentUserCommand) -> AuthenticatedUser:
        if not isinstance(command, GetCurrentUserCommand):
            raise TypeError("command must be a GetCurrentUserCommand")

        principal = command.principal
        with self._uow_factory() as uow:
            self._require_repositories(uow)
            user = uow.users.get_by_id(principal.user_id)
            if user is None:
                raise CurrentUserUnavailableError("Authenticated user is unavailable.")

            credential = uow.auth.get_credential_by_user_id(principal.user_id)

            if credential is None:
                raise CurrentUserUnavailableError("Authenticated user credentials are unavailable.")

            if user.status != AuthUserStatus.ACTIVE.value:
                raise CurrentUserUnavailableError("Authenticated user is unavailable.")

            if user.role != principal.role.value:
                raise CurrentUserStateConflictError("Authenticated role no longer matches the current user role.")

            try:
                role = AuthRole(user.role)
                status = AuthUserStatus(user.status)
                
            except ValueError as exc:
                raise CurrentUserStateConflictError("User contains unsupported identity state.") from exc

            return AuthenticatedUser(
                user_id=user.id, email=credential.email_normalized, display_name=user.display_name, role=role, status=status, created_at=user.created_at
            )

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> None:
        if uow.users is None:
            raise GetCurrentUserPersistenceError("User repository is unavailable.")

        if uow.auth is None:
            raise GetCurrentUserPersistenceError("Authentication repository is unavailable.")