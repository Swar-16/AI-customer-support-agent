# AI-customer-support-agent\packages\application\users\provision_initial_admin.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.exceptions import RegistrationPasswordPolicyError
from packages.application.auth.models import AuthRole, AuthUserStatus, normalize_email
from packages.application.auth.password_hasher import PasswordHasherContract, PasswordHashingError
from packages.application.auth.register_user import validate_registration_password
from packages.database.models.support.user import UserModel
from packages.database.models.support.user_credential import UserCredentialModel
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
Clock = Callable[[], datetime]

class ProvisionInitialAdminError(RuntimeError):
    """Base error for initial administrator provisioning."""

class InitialAdminAlreadyExistsError(ProvisionInitialAdminError):
    """Raised when initial bootstrap has already been completed."""

class InitialAdminEmailConflictError(ProvisionInitialAdminError):
    """Raised when the requested email belongs to another account."""

class InitialAdminPasswordPolicyError(ProvisionInitialAdminError):
    """Raised when the password violates registration policy."""

class InitialAdminPasswordHashingError(ProvisionInitialAdminError):
    """Raised when Argon2id hashing fails."""

class InitialAdminPersistenceError(ProvisionInitialAdminError):
    """Raised when provisioning cannot be persisted safely."""

@dataclass(frozen=True, slots=True)
class ProvisionInitialAdminCommand:
    email: str
    password: str = field(repr=False)
    display_name: str | None = None
    trace_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        normalized_email = normalize_email(self.email)
        object.__setattr__(self, "email", normalized_email)
        if not isinstance(self.password, str):
            raise TypeError("password must be a string")

        if not self.password:
            raise ValueError("password cannot be empty")

        if self.display_name is not None:
            if not isinstance(self.display_name, str):
                raise TypeError("display_name must be a string or None")

            normalized_name = " ".join(self.display_name.split())
            if len(normalized_name) > 255:
                raise ValueError("display_name cannot exceed 255 characters")

            object.__setattr__(self, "display_name", normalized_name or None)

        if self.trace_id is not None and not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID or None")

@dataclass(frozen=True, slots=True)
class ProvisionInitialAdminResult:
    user_id: uuid.UUID
    email: str
    display_name: str | None
    role: str
    status: str
    created_at: datetime
    changed: bool

class ProvisionInitialAdmin:
    """
    Provision the first administrator without issuing credentials through a public API.

    The user, credential and immutable audit event are committed in one transaction. A PostgreSQL advisory
    lock prevents two bootstrap processes from creating administrators concurrently.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, password_hasher: PasswordHasherContract, clock: Clock | None = None) -> None:
        if uow_factory is None or not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if password_hasher is None:
            raise TypeError("password_hasher cannot be None")

        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")

        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def execute(self, command: ProvisionInitialAdminCommand) -> ProvisionInitialAdminResult:
        if not isinstance(command, ProvisionInitialAdminCommand):
            raise TypeError("command must be a ProvisionInitialAdminCommand")

        try:
            validate_registration_password(password=command.password, email=command.email, display_name=command.display_name)
        except RegistrationPasswordPolicyError as exc:
            raise InitialAdminPasswordPolicyError(str(exc)) from exc

        occurred_at = self._utc_now()
        trace_id = command.trace_id or uuid7()

        try:
            with self._uow_factory() as uow:
                self._require_repositories(uow)
                # Prevent concurrent bootstrap processes from both observing zero administrators.
                uow.users.acquire_initial_admin_lock()
                existing_credential = (uow.auth.get_credential_by_email(command.email, for_update=True))
                if existing_credential is not None:
                    existing_user = uow.users.get_by_id(existing_credential.user_id)
                    if existing_user is None:
                        raise InitialAdminPersistenceError("Credential references a missing user.")

                    if existing_user.role == AuthRole.ADMIN.value and existing_user.status == AuthUserStatus.ACTIVE.value:
                        return self._to_result(existing_user, changed=False)

                    raise InitialAdminEmailConflictError("The requested email already belongs to another account.")

                if uow.users.count_active_admins() > 0:
                    raise InitialAdminAlreadyExistsError("Initial administrator provisioning has already been completed.")

                try:
                    password_hash = self._password_hasher.hash_password(command.password)
                    
                except PasswordHashingError as exc:
                    raise InitialAdminPasswordHashingError("Administrator password hashing failed.") from exc

                user_id = uuid7()
                user = UserModel(
                    id=user_id,
                    external_id=None,
                    email=command.email,
                    display_name=command.display_name,
                    role=AuthRole.ADMIN.value,
                    status=AuthUserStatus.ACTIVE.value,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                )

                credential = UserCredentialModel(
                    user_id=user_id,
                    email_normalized=command.email,
                    password_hash=password_hash,
                    failed_login_attempts=0,
                    locked_until=None,
                    password_changed_at=occurred_at,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                )

                uow.users.add(user)
                uow.users.flush()

                uow.auth.add_credential(credential)
                uow.auth.flush()

                AuditRecorder(repository=uow.audit_events).record(
                    RecordAuditEventCommand(
                        event_type="auth.initial_admin_provisioned",
                        entity_type="user",
                        entity_id=user_id,
                        action="initial_admin_provisioned",
                        actor=AuditActor(actor_type=AuditActorType.SYSTEM),
                        trace_id=trace_id,
                        before_state=None,
                        after_state={
                            "role": AuthRole.ADMIN.value,
                            "status": AuthUserStatus.ACTIVE.value,
                            "credentials_configured": True,
                        },
                        metadata={
                            "provisioning_method": "local_cli",
                            "bootstrap": True,
                        },
                        occurred_at=occurred_at,
                    )
                )

                result = self._to_result(
                    user,
                    changed=True,
                )

                uow.commit()

                return result

        except (
            InitialAdminAlreadyExistsError, InitialAdminEmailConflictError, InitialAdminPasswordHashingError,
            InitialAdminPasswordPolicyError, InitialAdminPersistenceError,):
            raise
        
        except IntegrityError as exc:
            raise InitialAdminEmailConflictError("The requested email already belongs to another account.") from exc
        
        except Exception as exc:
            raise InitialAdminPersistenceError("Initial administrator provisioning failed.") from exc

    def _utc_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise InitialAdminPersistenceError("Provisioning clock must return a datetime.")

        if value.tzinfo is None or value.utcoffset() is None:
            raise InitialAdminPersistenceError("Provisioning clock must return a timezone-aware datetime.")

        return value.astimezone(timezone.utc)

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> None:
        if uow.session is None:
            raise InitialAdminPersistenceError("Active SQLAlchemy Session unavailable.")

        if uow.users is None:
            raise InitialAdminPersistenceError("UserRepository unavailable.")

        if uow.auth is None:
            raise InitialAdminPersistenceError("AuthRepository unavailable.")

        if uow.audit_events is None:
            raise InitialAdminPersistenceError("AuditEventRepository unavailable.")

    @staticmethod
    def _to_result(user: UserModel, *, changed: bool) -> ProvisionInitialAdminResult:
        if user.id is None:
            raise InitialAdminPersistenceError("Persisted administrator has no ID.")

        if user.created_at is None:
            raise InitialAdminPersistenceError("Persisted administrator has no created_at.")

        return ProvisionInitialAdminResult(
            user_id=user.id,
            email=user.email or "",
            display_name=user.display_name,
            role=user.role,
            status=user.status,
            created_at=user.created_at,
            changed=changed,
        )