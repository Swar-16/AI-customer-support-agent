# AI-customer-support-agent\packages\application\auth\register_user.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from packages.application.auth.exceptions import RegistrationConflictError, RegistrationPasswordPolicyError, RegistrationPersistenceError
from packages.application.auth.exceptions import RegistrationConfigurationError, RegistrationPasswordHashingError
from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedUser, AuthenticationResult, AuthRole, AuthTokenPair, AuthUserStatus, RegisterCommand
from packages.application.auth.password_hasher import PasswordHasherContract, PasswordHashingError
from packages.application.auth.token_service import TokenService
from packages.database.models.support.auth_session import AuthSessionModel
from packages.database.models.support.user import UserModel
from packages.database.models.support.user_credential import UserCredentialModel
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
Clock = Callable[[], datetime]

class RegisterUser:
    """
    Register a customer and establish the first authenticated session.

    The following records are committed atomically:

        user
        + credential
        + refresh-token session
        + immutable audit event

    The raw refresh token and plaintext password are never persisted.
    """
    _MINIMUM_PASSWORD_CHARACTERS = 10
    _MAXIMUM_PASSWORD_BYTES = 1_024
    _COMMON_PASSWORDS = frozenset({
        "1234567890", "123456789", "qwerty123", "qwerty12345", "password", "password1", "password123", "admin123", "letmein123", "welcome123",
    })

    def __init__(self, *, uow_factory: UnitOfWorkFactory, password_hasher: PasswordHasherContract, token_service: TokenService,
                 refresh_token_ttl: timedelta, clock: Clock | None = None) -> None:
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

        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")

        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._token_service = token_service
        self._refresh_token_ttl = refresh_token_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def execute(self, command: RegisterCommand) -> AuthenticationResult:
        if not isinstance(command, RegisterCommand):
            raise TypeError("command must be a RegisterCommand")

        self._validate_password(password=command.password, email=command.email, display_name=command.display_name)
        occurred_at = self._utc_now()

        try:
            password_hash = self._password_hasher.hash_password(command.password)
            
        except PasswordHashingError as exc:
            raise RegistrationPasswordHashingError("Password hashing failed.") from exc

        user_id = uuid7()
        auth_session_id = uuid7()
        token_family_id = uuid7()
        refresh_material = self._token_service.generate_refresh_token()
        refresh_expires_at = occurred_at + self._refresh_token_ttl
        access_token = self._token_service.issue_access_token(
            user_id=user_id,
            session_id=auth_session_id,
            role=AuthRole.CUSTOMER.value,
            now=occurred_at,
        )

        if refresh_expires_at <= access_token.expires_at:
            raise RegistrationConfigurationError("Refresh-token lifetime must exceed access-token lifetime.")

        user = UserModel(
            id=user_id,
            email=command.email,
            display_name=command.display_name,
            role=AuthRole.CUSTOMER.value,
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

        auth_session = AuthSessionModel(
            id=auth_session_id,
            user_id=user_id,
            family_id=token_family_id,
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

        try:
            with self._uow_factory() as uow:
                self._require_repositories(uow)
                existing_credential = uow.auth.get_credential_by_email(command.email)
                if existing_credential is not None:
                    raise RegistrationConflictError("An account already exists for this email.")

                uow.users.add(user)
                uow.flush()
                # Persist the FK parent first. This is only a flush—not a commit—so the complete registration remains one atomic transaction.
                uow.auth.add_credential(credential)
                uow.auth.add_session(auth_session)
                uow.flush()
                AuditRecorder(repository=uow.audit_events).record(
                    RecordAuditEventCommand(
                        event_type="auth.user_registered",
                        entity_type="user",
                        entity_id=user_id,
                        action="registered",
                        actor=AuditActor(actor_type=AuditActorType.CUSTOMER, actor_id=user_id),
                        trace_id=command.trace_id,
                        before_state=None,
                        after_state={
                            "role": AuthRole.CUSTOMER.value,
                            "status": AuthUserStatus.ACTIVE.value,
                            "credentials_configured": True,
                        },
                        metadata={
                            "auth_session_id": str(auth_session_id),
                            "token_family_id": str(token_family_id),
                            "registration_method": "local_password",
                        },
                        occurred_at=occurred_at,
                    )
                )

                uow.commit()

        except RegistrationConflictError:
            raise
        
        except IntegrityError as exc:
            if self._is_email_conflict(exc):
                raise RegistrationConflictError("An account already exists for this email.") from exc

            raise RegistrationPersistenceError("Registration could not be persisted.") from exc

        authenticated_user = AuthenticatedUser(
            user_id=user_id,
            email=command.email,
            display_name=command.display_name,
            role=AuthRole.CUSTOMER,
            status=AuthUserStatus.ACTIVE,
            created_at=occurred_at,
        )

        tokens = AuthTokenPair(
            access_token=access_token.token,
            refresh_token=refresh_material.raw_token,
            access_token_expires_at=access_token.expires_at,
            refresh_token_expires_at=refresh_expires_at,
        )

        return AuthenticationResult(user=authenticated_user, tokens=tokens)

    def _validate_password(self, *, password: str, email: str, display_name: str | None) -> None:
        if len(password) < self._MINIMUM_PASSWORD_CHARACTERS:
            raise RegistrationPasswordPolicyError(f"Password must contain at least {self._MINIMUM_PASSWORD_CHARACTERS} characters.")

        if len(password.encode("utf-8")) > self._MAXIMUM_PASSWORD_BYTES:
            raise RegistrationPasswordPolicyError("Password is too long.")

        if "\x00" in password:
            raise RegistrationPasswordPolicyError("Password contains an unsupported character.")

        casefolded_password = password.casefold()
        if casefolded_password in self._COMMON_PASSWORDS:
            raise RegistrationPasswordPolicyError("Password is too common.")

        email_local_part = email.split("@", maxsplit=1)[0]
        if len(email_local_part) >= 4 and email_local_part.casefold() in casefolded_password:
            raise RegistrationPasswordPolicyError("Password must not contain the email username.")

        if display_name is not None:
            compact_name = "".join(character for character in display_name.casefold() if character.isalnum())
            compact_password = "".join(character for character in casefolded_password if character.isalnum())
            if len(compact_name) >= 4 and compact_name in compact_password:
                raise RegistrationPasswordPolicyError("Password must not contain the display name.")

    def _utc_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise RegistrationConfigurationError("Authentication clock must return a datetime.")

        if value.tzinfo is None:
            raise RegistrationConfigurationError("Authentication clock must return a timezone-aware datetime.")

        return value.astimezone(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> None:
        if uow.users is None:
            raise RegistrationPersistenceError("User repository is unavailable.")

        if uow.auth is None:
            raise RegistrationPersistenceError("Authentication repository is unavailable.")

        if uow.audit_events is None:
            raise RegistrationPersistenceError("Audit-event repository is unavailable.")

    @staticmethod
    def _is_email_conflict(exc: IntegrityError) -> bool:
        """
        Identify the expected PostgreSQL unique-email violation without translating unrelated database failures into false conflicts.
        """
        original = getattr(exc, "orig", None)
        diagnostics = getattr(original, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        
        return constraint_name in {"uq_user_credentials_email_normalized", "uq_user_credentials_email",}