# AI-customer-support-agent\packages\application\users\update_user_access.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole, AuthUserStatus
from packages.database.models.support.user import UserModel
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
Clock = Callable[[], datetime]

ASSIGNABLE_ROLES: Final[frozenset[AuthRole]] = frozenset({AuthRole.CUSTOMER, AuthRole.SUPPORT_AGENT, AuthRole.ADMIN,})
MANAGEABLE_STATUSES: Final[frozenset[AuthUserStatus]] = frozenset({AuthUserStatus.ACTIVE, AuthUserStatus.DISABLED,})
MAX_REASON_LENGTH: Final[int] = 1_000

class UpdateUserAccessError(RuntimeError):
    """Base error for administrative access changes."""

class UserAccessDeniedError(UpdateUserAccessError):
    """Raised when the actor cannot manage user access."""

class AccessManagerDoesNotExistError(UpdateUserAccessError):
    """Raised when the authenticated administrator is missing."""

class AccessManagerNotActiveError(UpdateUserAccessError):
    """Raised when the administrator is inactive."""

class AccessManagerRoleMismatchError(UpdateUserAccessError):
    """Raised when token and persisted roles differ."""

class ManagedUserDoesNotExistError(UpdateUserAccessError):
    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id
        super().__init__(f"Managed user does not exist: {user_id}")

class ProtectedSystemUserError(UpdateUserAccessError):
    """Raised when attempting to modify a system identity."""

class DeletedUserAccessMutationError(UpdateUserAccessError):
    """Raised when attempting to reactivate a deleted user."""

class FinalActiveAdministratorError(UpdateUserAccessError):
    """Raised when a mutation would remove the final active admin."""

class AdministratorSelfMutationError(UpdateUserAccessError):
    """Raised for self-demotion or self-disable operations."""

class UserAccessPersistenceContractError(UpdateUserAccessError):
    """Raised when required persistence components are unavailable."""

@dataclass(frozen=True, slots=True)
class UpdateUserAccessCommand:
    target_user_id: uuid.UUID
    principal: AuthenticatedPrincipal
    trace_id: uuid.UUID
    role: AuthRole | None = None
    status: AuthUserStatus | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.target_user_id, uuid.UUID):
            raise TypeError("target_user_id must be a UUID")

        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID")

        if self.principal.role is not AuthRole.ADMIN:
            raise UserAccessDeniedError("Only administrators may manage user access")

        if self.role is not None:
            if not isinstance(self.role, AuthRole):
                raise TypeError("role must be an AuthRole or None")

            if self.role not in ASSIGNABLE_ROLES:
                raise ValueError("role cannot be assigned through user access management")

        if self.status is not None:
            if not isinstance(self.status, AuthUserStatus):
                raise TypeError("status must be an AuthUserStatus or None")

            if self.status not in MANAGEABLE_STATUSES:
                raise ValueError("status cannot be assigned through user access management")

        if self.role is None and self.status is None:
            raise ValueError("at least one of role or status must be provided")

        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string")

        normalized_reason = " ".join(self.reason.split())

        if not normalized_reason:
            raise ValueError("reason cannot be blank")

        if len(normalized_reason) > MAX_REASON_LENGTH:
            raise ValueError(f"reason cannot exceed {MAX_REASON_LENGTH} characters")

        object.__setattr__(self, "reason", normalized_reason)

@dataclass(frozen=True, slots=True)
class UpdateUserAccessResult:
    user_id: uuid.UUID
    email: str | None
    display_name: str | None
    role: AuthRole
    status: AuthUserStatus
    updated_at: datetime
    changed: bool
    revoked_session_count: int

class UpdateUserAccess:
    """
    Update role/status and revoke authentication sessions atomically.

    The target user is locked for update. A global administrative transaction lock protects the final-active-administrator invariant.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock | None = None) -> None:
        if uow_factory is None or not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")

        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def execute(self, command: UpdateUserAccessCommand) -> UpdateUserAccessResult:
        if not isinstance(command, UpdateUserAccessCommand):
            raise TypeError("command must be an UpdateUserAccessCommand")

        occurred_at = self._utc_now()
        with self._uow_factory() as uow:
            self._require_repositories(uow)
            uow.users.acquire_admin_management_lock()
            manager = uow.users.get_by_id(command.principal.user_id)
            self._validate_manager(manager=manager, principal=command.principal)
            target = uow.users.get_by_id_for_update(command.target_user_id)

            if target is None:
                raise ManagedUserDoesNotExistError(command.target_user_id)

            if target.role == AuthRole.SYSTEM.value:
                raise ProtectedSystemUserError("System identities cannot be modified")

            if target.status == AuthUserStatus.DELETED.value:
                raise DeletedUserAccessMutationError("Deleted users cannot be modified through access management")

            target_role = command.role if command.role is not None else AuthRole(target.role)
            target_status = command.status if command.status is not None else AuthUserStatus(target.status)
            self._validate_self_mutation(target_user_id=target.id, principal=command.principal, target_role=target_role, target_status=target_status)
            role_changed = (target.role != target_role.value)
            status_changed = (target.status != target_status.value)
            if not role_changed and not status_changed:
                return self._to_result(target, changed=False, revoked_session_count=0)

            removes_active_admin = (target.role == AuthRole.ADMIN.value and target.status == AuthUserStatus.ACTIVE.value and 
                                    (target_role is not AuthRole.ADMIN or target_status is not AuthUserStatus.ACTIVE))

            if removes_active_admin and uow.users.count_active_admins() <= 1:
                raise FinalActiveAdministratorError("The final active administrator cannot be disabled or demoted")

            before_state = {"role": target.role, "status": target.status,}
            target.role = target_role.value
            target.status = target_status.value
            revoked_session_count = uow.auth.revoke_all_for_user(user_id=target.id, revoked_at=occurred_at, reason="user_access_changed")
            uow.users.flush()

            AuditRecorder(repository=uow.audit_events).record(
                RecordAuditEventCommand(
                    event_type="user.access_updated",
                    entity_type="user",
                    entity_id=target.id,
                    action="access_updated",
                    actor=AuditActor(actor_type=AuditActorType.ADMIN, actor_id=command.principal.user_id),
                    trace_id=command.trace_id,
                    before_state=before_state,
                    after_state={
                        "role": target.role,
                        "status": target.status,
                    },
                    reason=command.reason,
                    metadata={
                        "role_changed": role_changed,
                        "status_changed": status_changed,
                        "revoked_session_count": revoked_session_count,
                    },
                    occurred_at=occurred_at,
                )
            )

            result = self._to_result(
                target,
                changed=True,
                revoked_session_count=revoked_session_count,
            )

            uow.commit()

            return result

    @staticmethod
    def _validate_manager(*, manager: UserModel | None, principal: AuthenticatedPrincipal) -> None:
        if manager is None:
            raise AccessManagerDoesNotExistError("Authenticated administrator does not exist")

        if manager.status != AuthUserStatus.ACTIVE.value:
            raise AccessManagerNotActiveError("Authenticated administrator is not active")

        if manager.role != principal.role.value:
            raise AccessManagerRoleMismatchError("Authenticated role does not match persisted role")

        if manager.role != AuthRole.ADMIN.value:
            raise UserAccessDeniedError("Only administrators may manage user access")

    @staticmethod
    def _validate_self_mutation(*, target_user_id: uuid.UUID, principal: AuthenticatedPrincipal, target_role: AuthRole, target_status: AuthUserStatus) -> None:
        if target_user_id != principal.user_id:
            return

        if target_role is not AuthRole.ADMIN or target_status is not AuthUserStatus.ACTIVE:
            raise AdministratorSelfMutationError("Administrators cannot disable or demote their own account")

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> None:
        if uow.session is None:
            raise UserAccessPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.users is None:
            raise UserAccessPersistenceContractError("UserRepository unavailable")

        if uow.auth is None:
            raise UserAccessPersistenceContractError("AuthRepository unavailable")

        if uow.audit_events is None:
            raise UserAccessPersistenceContractError("AuditEventRepository unavailable")

    def _utc_now(self) -> datetime:
        value = self._clock()

        if not isinstance(value, datetime):
            raise UserAccessPersistenceContractError("Clock must return a datetime")

        if value.tzinfo is None:
            raise UserAccessPersistenceContractError("Clock must return a timezone-aware datetime")

        return value.astimezone(timezone.utc)

    @staticmethod
    def _to_result(user: UserModel, *, changed: bool, revoked_session_count: int) -> UpdateUserAccessResult:
        if user.id is None:
            raise UserAccessPersistenceContractError("Persisted user has no ID")

        if user.updated_at is None:
            raise UserAccessPersistenceContractError("Persisted user has no updated_at")

        return UpdateUserAccessResult(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=AuthRole(user.role),
            status=AuthUserStatus(user.status),
            updated_at=user.updated_at,
            changed=changed,
            revoked_session_count=revoked_session_count,
        )