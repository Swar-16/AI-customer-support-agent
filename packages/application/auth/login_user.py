# AI-customer-support-agent\packages\application\auth\login_user.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from packages.application.auth.exceptions import LoginError, InvalidCredentialsError, LoginPersistenceError, LoginConfigurationError, LoginPasswordHashingError
from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedUser, AuthenticationResult, AuthRole, AuthTokenPair, AuthUserStatus, LoginCommand
from packages.application.auth.password_hasher import PasswordHasherContract, PasswordHashingError
from packages.application.auth.token_service import TokenService
from packages.database.models.support.auth_session import AuthSessionModel
from packages.database.models.support.user import UserModel
from packages.database.models.support.user_credential import UserCredentialModel
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
Clock = Callable[[], datetime]

class LoginUser:
    """
    Authenticate a local user and create a refresh-token session.

    Security properties:

    - unknown users still perform Argon2 verification;
    - public failures do not reveal whether an account exists;
    - failed-attempt counters are updated under a row lock;
    - temporary lockout is persisted;
    - successful login resets failure state;
    - outdated password hashes are upgraded after successful verification;
    - raw refresh tokens are never persisted;
    - every attempt creates an immutable audit event.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, password_hasher: PasswordHasherContract, token_service: TokenService, 
                 refresh_token_ttl: timedelta, maximum_failed_attempts: int, lockout_duration: timedelta, clock: Clock | None = None, 
                 dummy_password_hash: str | None = None) -> None:
        if uow_factory is None or not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if password_hasher is None:
            raise TypeError("password_hasher cannot be None")

        if token_service is None:
            raise TypeError("token_service cannot be None")

        if not isinstance(refresh_token_ttl, timedelta):
            raise TypeError("refresh_token_ttl must be a timedelta")

        if refresh_token_ttl <= timedelta(0):
            raise ValueError("refresh_token_ttl must be greater than zero")

        if isinstance(maximum_failed_attempts, bool) or not isinstance(maximum_failed_attempts, int):
            raise TypeError("maximum_failed_attempts must be an integer")

        if maximum_failed_attempts <= 0:
            raise ValueError("maximum_failed_attempts must be greater than zero")

        if not isinstance(lockout_duration, timedelta):
            raise TypeError("lockout_duration must be a timedelta")

        if lockout_duration <= timedelta(0):
            raise ValueError("lockout_duration must be greater than zero")

        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")

        if dummy_password_hash is None:
            try:
                dummy_password_hash = password_hasher.hash_password("Dummy-Authentication-Password-Only-7c91")
                
            except PasswordHashingError as exc:
                raise LoginPasswordHashingError("Could not initialize login protection.") from exc

        if not isinstance(dummy_password_hash, str) or not dummy_password_hash.strip():
            raise ValueError("dummy_password_hash cannot be blank")

        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._token_service = token_service
        self._refresh_token_ttl = refresh_token_ttl
        self._maximum_failed_attempts = maximum_failed_attempts
        self._lockout_duration = lockout_duration
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._dummy_password_hash = dummy_password_hash

    def execute(self, command: LoginCommand) -> AuthenticationResult:
        if not isinstance(command, LoginCommand):
            raise TypeError("command must be a LoginCommand")

        occurred_at = self._utc_now()
        failure_reason: str | None = None
        result: AuthenticationResult | None = None

        try:
            with self._uow_factory() as uow:
                self._require_repositories(uow)
                credential = uow.auth.get_credential_by_email(command.email, for_update=True)
                if credential is None:
                    # Prevent a fast unknown-email path that could otherwise be used for account enumeration through timing.
                    self._password_hasher.verify_password(password=command.password, password_hash=self._dummy_password_hash)
                    self._record_failure(
                        uow=uow, command=command, occurred_at=occurred_at, reason="invalid_credentials",
                        user_id=None, failed_attempts=None, locked_until=None
                    )
                    uow.commit()
                    failure_reason = "invalid_credentials"

                else:
                    user = uow.users.get_by_id(credential.user_id)
                    if user is None:
                        raise LoginPersistenceError("Credential references a missing user.")

                    password_matches = self._password_hasher.verify_password(password=command.password, password_hash=credential.password_hash)
                    account_is_locked = credential.locked_until is not None and credential.locked_until > occurred_at
                    account_is_active = user.status == AuthUserStatus.ACTIVE.value
                    if account_is_locked:
                        self._record_failure(
                            uow=uow, command=command, occurred_at=occurred_at, reason="account_locked", user_id=user.id,
                            failed_attempts=credential.failed_login_attempts, locked_until=credential.locked_until,
                        )
                        uow.commit()
                        failure_reason = "account_locked"

                    elif not account_is_active:
                        self._record_failure(
                            uow=uow, command=command, occurred_at=occurred_at, reason="account_unavailable",
                            user_id=user.id, failed_attempts=credential.failed_login_attempts, locked_until=None,
                        )
                        uow.commit()
                        failure_reason = "account_unavailable"

                    elif not password_matches:
                        failure_reason = self._apply_failed_attempt(credential=credential, occurred_at=occurred_at)
                        self._record_failure(
                            uow=uow, command=command, occurred_at=occurred_at, reason=failure_reason, user_id=user.id,
                            failed_attempts=credential.failed_login_attempts, locked_until=credential.locked_until,
                        )
                        uow.flush()
                        uow.commit()

                    else:
                        result = self._complete_successful_login(uow=uow, command=command, user=user, credential=credential, occurred_at=occurred_at)
                        uow.commit()

        except LoginError:
            raise
        
        except IntegrityError as exc:
            raise LoginPersistenceError("Login session could not be persisted.") from exc

        if failure_reason is not None:
            raise InvalidCredentialsError()

        if result is None:
            raise LoginPersistenceError("Login completed without a result.")

        return result

    def _complete_successful_login(self, *, uow: SqlAlchemyUnitOfWork, command: LoginCommand, user: UserModel,
                                   credential: UserCredentialModel, occurred_at: datetime
    ) -> AuthenticationResult:
        credential.failed_login_attempts = 0
        credential.locked_until = None
        credential.updated_at = occurred_at
        if self._password_hasher.needs_rehash(credential.password_hash):
            try:
                credential.password_hash = self._password_hasher.hash_password(command.password)
                
            except PasswordHashingError as exc:
                raise LoginPasswordHashingError("Password hash upgrade failed.") from exc

            credential.password_changed_at = occurred_at

        session_id = uuid7()
        family_id = uuid7()
        refresh_material = self._token_service.generate_refresh_token()
        refresh_expires_at = occurred_at + self._refresh_token_ttl
        issued_access_token = self._token_service.issue_access_token(
            user_id=user.id,
            session_id=session_id,
            role=user.role,
            now=occurred_at,
        )

        if refresh_expires_at <= issued_access_token.expires_at:
            raise LoginConfigurationError("Refresh-token lifetime must exceed access-token lifetime.")

        auth_session = AuthSessionModel(
            id=session_id,
            user_id=user.id,
            family_id=family_id,
            refresh_token_hash=refresh_material.token_hash,
            replaced_by_session_id=None,
            client_ip=self._normalize_optional_text(command.client_ip),
            user_agent=self._normalize_optional_text(command.user_agent),
            created_at=occurred_at,
            expires_at=refresh_expires_at,
            last_used_at=None,
            revoked_at=None,
            revocation_reason=None,
        )
        uow.auth.add_session(auth_session)
        uow.flush()

        AuditRecorder(repository=uow.audit_events).record(
            RecordAuditEventCommand(
                event_type="auth.login_succeeded",
                entity_type="auth_session",
                entity_id=session_id,
                action="login_succeeded",
                actor=AuditActor(actor_type=self._audit_actor_type(user.role), actor_id=user.id),
                trace_id=command.trace_id,
                before_state=None,
                after_state={
                    "session_created": True,
                    "role": user.role,
                },
                metadata={
                    "user_id": str(user.id),
                    "token_family_id": str(family_id),
                    "authentication_method": "local_password",
                },
                occurred_at=occurred_at,
            )
        )

        authenticated_user = AuthenticatedUser(
            user_id=user.id,
            email=credential.email_normalized,
            display_name=user.display_name,
            role=AuthRole(user.role),
            status=AuthUserStatus(user.status),
            created_at=user.created_at,
        )

        return AuthenticationResult(
            user=authenticated_user,
            tokens=AuthTokenPair(
                access_token=issued_access_token.token,
                refresh_token=refresh_material.raw_token,
                access_token_expires_at=issued_access_token.expires_at,
                refresh_token_expires_at=refresh_expires_at,
            ),
        )

    def _apply_failed_attempt(self, *, credential: UserCredentialModel, occurred_at: datetime) -> str:
        # Remove an expired lock before starting a new attempt window.
        if credential.locked_until is not None and credential.locked_until <= occurred_at:
            credential.failed_login_attempts = 0
            credential.locked_until = None

        credential.failed_login_attempts += 1
        credential.updated_at = occurred_at
        if credential.failed_login_attempts >= self._maximum_failed_attempts:
            credential.locked_until = occurred_at + self._lockout_duration
            return "account_locked"

        return "invalid_credentials"

    def _record_failure(self, *, uow: SqlAlchemyUnitOfWork, command: LoginCommand, occurred_at: datetime, reason: str, 
                        user_id: uuid.UUID | None, failed_attempts: int | None, locked_until: datetime | None,
    ) -> None:
        # Unknown accounts have no real entity ID. A random attempt ID avoids
        # storing the submitted email or a reversible email fingerprint.
        entity_id = user_id or uuid7()
        metadata: dict[str, object] = {
            "reason_code": reason,
            "known_user": user_id is not None,
            "authentication_method": "local_password",
        }

        if failed_attempts is not None:
            metadata["failed_attempts"] = failed_attempts

        if locked_until is not None:
            metadata["locked_until"] = locked_until.isoformat()

        AuditRecorder(repository=uow.audit_events).record(
            RecordAuditEventCommand(
                event_type="auth.login_failed",
                entity_type="user" if user_id is not None else "auth_attempt",
                entity_id=entity_id,
                action="login_failed",
                actor=AuditActor(actor_type=AuditActorType.CUSTOMER, actor_id=user_id),
                trace_id=command.trace_id,
                before_state=None,
                after_state=None,
                reason=reason,
                metadata=metadata,
                occurred_at=occurred_at,
            )
        )

    def _utc_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise LoginConfigurationError("Authentication clock must return a datetime.")

        if value.tzinfo is None:
            raise LoginConfigurationError("Authentication clock must return a timezone-aware datetime.")

        return value.astimezone(timezone.utc)

    @staticmethod
    def _audit_actor_type(role: str) -> AuditActorType:
        mapping = {
            AuthRole.CUSTOMER.value: (AuditActorType.CUSTOMER),
            AuthRole.SUPPORT_AGENT.value: (AuditActorType.AGENT),
            AuthRole.ADMIN.value: AuditActorType.ADMIN,
        }

        try:
            return mapping[role]
        
        except KeyError as exc:
            raise LoginConfigurationError(f"Role cannot perform interactive login: {role!r}") from exc

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> None:
        if uow.users is None:
            raise LoginPersistenceError("User repository is unavailable.")

        if uow.auth is None:
            raise LoginPersistenceError("Authentication repository is unavailable.")

        if uow.audit_events is None:
            raise LoginPersistenceError("Audit-event repository is unavailable.")