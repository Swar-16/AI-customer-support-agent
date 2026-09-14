# AI-customer-support-agent\packages\application\auth\refresh_session.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from packages.application.auth.exceptions import RefreshSessionError, InvalidRefreshTokenError, RefreshSessionPersistenceError, RefreshSessionConfigurationError
from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedUser, AuthenticationResult, AuthRole, AuthTokenPair, AuthUserStatus, RefreshSessionCommand
from packages.application.auth.token_service import TokenService
from packages.database.models.support.auth_session import AuthSessionModel
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
Clock = Callable[[], datetime]

class RefreshSession:
    """
    Rotate a single-use opaque refresh token.

    Successful rotation:

        current session revoked + replacement session inserted + immutable audit event
                                                ↓
                                            one commit

    Reuse detection:

        already-revoked token presented + every active session in its family revoked
                        + immutable security audit event
                                        ↓
                                    one commit
    """
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

    def execute(self, command: RefreshSessionCommand) -> AuthenticationResult:
        if not isinstance(command, RefreshSessionCommand):
            raise TypeError("command must be a RefreshSessionCommand")

        occurred_at = self._utc_now()
        supplied_token_hash = self._token_service.hash_refresh_token(command.refresh_token)
        result: AuthenticationResult | None = None
        rejected = False

        try:
            with self._uow_factory() as uow:
                self._require_repositories(uow)
                current_session = uow.auth.get_session_by_token_hash(supplied_token_hash, for_update=True)
                if current_session is None:
                    self._record_unknown_token_failure(uow=uow, command=command, occurred_at=occurred_at)
                    uow.commit()
                    rejected = True

                elif current_session.revoked_at is not None:
                    # A previously consumed token has been presented again.
                    # # Revoke every still-active descendant in the family.
                    revoked_count = uow.auth.revoke_active_family(
                        family_id=current_session.family_id,
                        revoked_at=occurred_at,
                        reason="refresh_token_reuse",
                    )
                    self._record_reuse_detected(
                        uow=uow,
                        command=command,
                        auth_session=current_session,
                        occurred_at=occurred_at,
                        revoked_count=revoked_count,
                    )
                    uow.commit()
                    rejected = True

                elif current_session.expires_at <= occurred_at:
                    current_session.revoked_at = occurred_at
                    current_session.revocation_reason = ("refresh_token_expired")
                    current_session.last_used_at = occurred_at
                    self._record_rejected_session(
                        uow=uow,
                        command=command,
                        auth_session=current_session,
                        occurred_at=occurred_at,
                        reason="refresh_token_expired",
                    )
                    uow.flush()
                    uow.commit()
                    rejected = True

                else:
                    user = uow.users.get_by_id(current_session.user_id)
                    credential = uow.auth.get_credential_by_user_id(current_session.user_id)
                    if user is None or credential is None or user.status != AuthUserStatus.ACTIVE.value or user.role == AuthRole.SYSTEM.value:
                        revoked_count = uow.auth.revoke_active_family(
                            family_id=current_session.family_id,
                            revoked_at=occurred_at,
                            reason="account_unavailable",
                        )

                        self._record_rejected_session(
                            uow=uow,
                            command=command,
                            auth_session=current_session,
                            occurred_at=occurred_at,
                            reason="account_unavailable",
                            extra_metadata={"family_sessions_revoked": revoked_count,},
                        )
                        uow.commit()
                        rejected = True

                    else:
                        result = self._rotate_session(
                            uow=uow,
                            command=command,
                            current_session=current_session,
                            user=user,
                            email=credential.email_normalized,
                            occurred_at=occurred_at,
                        )
                        uow.commit()

        except RefreshSessionError:
            raise
        
        except IntegrityError as exc:
            raise RefreshSessionPersistenceError("Refresh-session rotation could not be persisted.") from exc

        if rejected:
            raise InvalidRefreshTokenError()

        if result is None:
            raise RefreshSessionPersistenceError("Refresh completed without a result.")

        return result

    def _rotate_session(self, *, uow: SqlAlchemyUnitOfWork, command: RefreshSessionCommand, current_session: AuthSessionModel,
                        user, email: str, occurred_at: datetime) -> AuthenticationResult:
        replacement_session_id = uuid7()
        refresh_material = self._token_service.generate_refresh_token()
        issued_access_token = self._token_service.issue_access_token(
            user_id=user.id,
            session_id=replacement_session_id,
            role=user.role,
            now=occurred_at,
        )

        # Rotation preserves the original login session's refresh expiry. Repeated refreshes therefore cannot extend a session forever.
        refresh_expires_at = current_session.expires_at
        if refresh_expires_at <= issued_access_token.expires_at:
            current_session.revoked_at = occurred_at
            current_session.revocation_reason = ("insufficient_session_lifetime")
            current_session.last_used_at = occurred_at
            self._record_rejected_session(
                uow=uow,
                command=command,
                auth_session=current_session,
                occurred_at=occurred_at,
                reason="insufficient_session_lifetime",
            )
            uow.flush()
            uow.commit()
            raise InvalidRefreshTokenError()

        replacement_session = AuthSessionModel(
            id=replacement_session_id,
            user_id=current_session.user_id,
            family_id=current_session.family_id,
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

        # Insert the replacement first so the self-referencing foreign key can safely point to an existing row.
        uow.auth.add_session(replacement_session)
        uow.flush()

        current_session.last_used_at = occurred_at
        current_session.revoked_at = occurred_at
        current_session.revocation_reason = "refresh_token_rotated"
        current_session.replaced_by_session_id = replacement_session_id
        uow.flush()

        AuditRecorder(repository=uow.audit_events).record(
            RecordAuditEventCommand(
                event_type="auth.session_refreshed",
                entity_type="auth_session",
                entity_id=replacement_session_id,
                action="session_refreshed",
                actor=AuditActor(actor_type=self._audit_actor_type(user.role), actor_id=user.id),
                trace_id=command.trace_id,
                before_state={
                    "previous_session_id": str(current_session.id),
                    "previous_session_active": True,
                },
                after_state={
                    "previous_session_active": False,
                    "replacement_session_active": True,
                },
                metadata={
                    "user_id": str(user.id),
                    "token_family_id": str(current_session.family_id),
                },
                occurred_at=occurred_at,
            )
        )

        return AuthenticationResult(
            user=AuthenticatedUser(
                user_id=user.id,
                email=email,
                display_name=user.display_name,
                role=AuthRole(user.role),
                status=AuthUserStatus(user.status),
                created_at=user.created_at,
            ),
            tokens=AuthTokenPair(
                access_token=issued_access_token.token,
                refresh_token=refresh_material.raw_token,
                access_token_expires_at=issued_access_token.expires_at,
                refresh_token_expires_at=refresh_expires_at,
            ),
        )

    def _record_unknown_token_failure(self, *, uow: SqlAlchemyUnitOfWork, command: RefreshSessionCommand, occurred_at: datetime) -> None:
        # Never persist the raw token or its reusable database lookup hash.
        AuditRecorder(repository=uow.audit_events).record(
            RecordAuditEventCommand(
                event_type="auth.refresh_failed",
                entity_type="auth_attempt",
                entity_id=uuid7(),
                action="refresh_failed",
                actor=AuditActor(actor_type=AuditActorType.CUSTOMER),
                trace_id=command.trace_id,
                reason="invalid_refresh_token",
                metadata={"known_session": False,},
                occurred_at=occurred_at,
            )
        )

    def _record_reuse_detected(self, *, uow: SqlAlchemyUnitOfWork, command: RefreshSessionCommand, auth_session: AuthSessionModel,
                               occurred_at: datetime, revoked_count: int
    ) -> None:
        AuditRecorder(repository=uow.audit_events).record(
            RecordAuditEventCommand(
                event_type="auth.refresh_reuse_detected",
                entity_type="auth_session",
                entity_id=auth_session.id,
                action="refresh_reuse_detected",
                actor=AuditActor(actor_type=AuditActorType.CUSTOMER, actor_id=auth_session.user_id),
                trace_id=command.trace_id,
                before_state={"session_revoked": True,},
                after_state={"token_family_revoked": True,},
                reason="refresh_token_reuse",
                metadata={
                    "user_id": str(auth_session.user_id),
                    "token_family_id": str(auth_session.family_id),
                    "family_sessions_revoked": revoked_count,
                },
                occurred_at=occurred_at,
            )
        )

    def _record_rejected_session(self, *, uow: SqlAlchemyUnitOfWork, command: RefreshSessionCommand, auth_session: AuthSessionModel,
                                 occurred_at: datetime, reason: str, extra_metadata: dict[str, object] | None = None
    ) -> None:
        metadata: dict[str, object] = {
            "user_id": str(auth_session.user_id),
            "token_family_id": str(auth_session.family_id),
            "known_session": True,
        }

        if extra_metadata:
            metadata.update(extra_metadata)

        AuditRecorder(repository=uow.audit_events).record(
            RecordAuditEventCommand(
                event_type="auth.refresh_failed",
                entity_type="auth_session",
                entity_id=auth_session.id,
                action="refresh_failed",
                actor=AuditActor(actor_type=AuditActorType.CUSTOMER, actor_id=auth_session.user_id),
                trace_id=command.trace_id,
                reason=reason,
                metadata=metadata,
                occurred_at=occurred_at,
            )
        )

    def _utc_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise RefreshSessionConfigurationError("Authentication clock must return a datetime.")

        if value.tzinfo is None:
            raise RefreshSessionConfigurationError("Authentication clock must return a timezone-aware datetime.")

        return value.astimezone(timezone.utc)

    @staticmethod
    def _audit_actor_type(role: str) -> AuditActorType:
        mapping = {
            AuthRole.CUSTOMER.value: AuditActorType.CUSTOMER,
            AuthRole.SUPPORT_AGENT.value: AuditActorType.AGENT,
            AuthRole.ADMIN.value: AuditActorType.ADMIN,
        }

        try:
            return mapping[role]
        
        except KeyError as exc:
            raise RefreshSessionConfigurationError(f"Role cannot refresh a session: {role!r}") from exc

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> None:
        if uow.users is None:
            raise RefreshSessionPersistenceError("User repository is unavailable.")

        if uow.auth is None:
            raise RefreshSessionPersistenceError("Authentication repository is unavailable.")

        if uow.audit_events is None:
            raise RefreshSessionPersistenceError("Audit-event repository is unavailable.")