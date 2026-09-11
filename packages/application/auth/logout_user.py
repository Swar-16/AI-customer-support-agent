# AI-customer-support-agent\packages\application\auth\logout_user.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthRole, LogoutCommand
from packages.application.auth.exceptions import LogoutSessionOwnershipError, LogoutPersistenceError, LogoutConfigurationError
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
Clock = Callable[[], datetime]

@dataclass(frozen=True, slots=True)
class LogoutResult:
    user_id: uuid.UUID
    session_id: uuid.UUID
    revoked: bool
    already_inactive: bool
    revoked_at: datetime | None

class LogoutUser:
    """
    Revoke the authenticated principal's current refresh-token session.

    Logout is idempotent:

    - active session: revoke, audit, and commit;
    - already-revoked session: return success without another event;
    - missing session: return success without revealing session existence.

    Access tokens are short-lived JWTs and cannot be physically deleted. Authorization dependencies must 
    therefore verify that the referenced persisted session remains active.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock | None = None) -> None:
        if uow_factory is None or not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")

        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def execute(self, command: LogoutCommand) -> LogoutResult:
        if not isinstance(command, LogoutCommand):
            raise TypeError("command must be a LogoutCommand")

        principal = command.principal
        occurred_at = self._utc_now()
        with self._uow_factory() as uow:
            self._require_repositories(uow)
            auth_session = uow.auth.get_session_by_id(principal.session_id, for_update=True)
            # A missing session is treated as already inactive. This keeps
            # logout idempotent and avoids exposing session existence.
            if auth_session is None:
                return LogoutResult(
                    user_id=principal.user_id, session_id=principal.session_id, revoked=False, already_inactive=True, revoked_at=None
                )

            if auth_session.user_id != principal.user_id:
                raise LogoutSessionOwnershipError("Authentication session does not belong to the authenticated principal.")

            if auth_session.revoked_at is not None:
                return LogoutResult(
                    user_id=principal.user_id, session_id=principal.session_id, revoked=False, already_inactive=True, revoked_at=auth_session.revoked_at
                )

            before_state = {
                "active": True,
                "expires_at": auth_session.expires_at.isoformat(),
            }
            auth_session.last_used_at = occurred_at
            auth_session.revoked_at = occurred_at
            auth_session.revocation_reason = "user_logout"
            uow.flush()
            AuditRecorder(repository=uow.audit_events).record(
                RecordAuditEventCommand(
                    event_type="auth.session_revoked",
                    entity_type="auth_session",
                    entity_id=auth_session.id,
                    action="session_revoked",
                    actor=AuditActor(actor_type=self._audit_actor_type(principal.role), actor_id=principal.user_id),
                    trace_id=command.trace_id,
                    before_state=before_state,
                    after_state={
                        "active": False,
                        "revoked_at": occurred_at.isoformat(),
                    },
                    reason="user_logout",
                    metadata={
                        "user_id": str(principal.user_id),
                        "token_family_id": str(auth_session.family_id),
                    },
                    occurred_at=occurred_at,
                )
            )

            uow.commit()

            return LogoutResult(
                user_id=principal.user_id, session_id=principal.session_id, revoked=True, already_inactive=False, revoked_at=occurred_at
            )

    def _utc_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise LogoutConfigurationError("Authentication clock must return a datetime.")

        if value.tzinfo is None:
            raise LogoutConfigurationError("Authentication clock must return a timezone-aware datetime.")

        return value.astimezone(timezone.utc)

    @staticmethod
    def _audit_actor_type(role: AuthRole) -> AuditActorType:
        mapping = {
            AuthRole.CUSTOMER: AuditActorType.CUSTOMER,
            AuthRole.SUPPORT_AGENT: AuditActorType.AGENT,
            AuthRole.ADMIN: AuditActorType.ADMIN,
        }

        try:
            return mapping[role]
        
        except KeyError as exc:
            raise LogoutConfigurationError(f"Role cannot perform interactive logout: {role.value!r}") from exc

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> None:
        if uow.auth is None:
            raise LogoutPersistenceError("Authentication repository is unavailable.")

        if uow.audit_events is None:
            raise LogoutPersistenceError("Audit-event repository is unavailable.")