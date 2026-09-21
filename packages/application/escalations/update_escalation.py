# AI-customer-support-agent\packages\application\escalations\update_escalation.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from packages.database.models.support.escalation import EscalationModel
from packages.database.repositories.support.escalation_repository import EscalationRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.application.conversations.conversation_notification import AppendConversationNotificationCommand, ConversationNotificationWriter

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork,]
Clock = Callable[[], datetime]
VALID_ESCALATION_STATUSES: Final[frozenset[str]] = frozenset({"open", "in_review", "resolved", "dismissed",})
TERMINAL_ESCALATION_STATUSES: Final[frozenset[str]] = frozenset({"resolved", "dismissed",})
MAX_CUSTOMER_MESSAGE_LENGTH: Final[int] = 2_000
_ESCALATION_IN_REVIEW_NOTICE: Final[str] = (
    "A support specialist is now reviewing your request. "
    "You can continue adding relevant details while the review "
    "is in progress."
)
_ESCALATION_RESOLVED_PREFIX: Final[str] = "Your support escalation has been resolved."
_ESCALATION_DISMISSED_PREFIX: Final[str] = "Your support escalation has been closed without further action."
ALLOWED_ESCALATION_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "open": frozenset({"in_review", "resolved", "dismissed",}),
    "in_review": frozenset({"resolved", "dismissed",}),
    "resolved": frozenset(),
    "dismissed": frozenset(),
}

class UpdateEscalationError(RuntimeError):
    """Base application error for escalation lifecycle updates."""

class EscalationDoesNotExistError(UpdateEscalationError):
    """Raised when the requested escalation does not exist."""
    def __init__(self, escalation_id: uuid.UUID) -> None:
        self.escalation_id = escalation_id
        super().__init__(f"Escalation does not exist: {escalation_id}")

class InvalidEscalationTransitionError(UpdateEscalationError):
    """Raised when the requested lifecycle transition is not allowed."""
    def __init__(self, *, escalation_id: uuid.UUID, current_status: str, target_status: str) -> None:
        self.escalation_id = escalation_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(f"Invalid escalation transition for {escalation_id}: {current_status!r} -> {target_status!r}")

class EscalationPersistenceContractError(UpdateEscalationError):
    """Raised when Unit of Work wiring is incomplete."""

@dataclass(frozen=True, slots=True)
class UpdateEscalationCommand:
    """
    Move an escalation through its controlled lifecycle.

    `customer_message` is customer-visible text written by a trusted support agent or administrator.
    It is required for terminal transitions so customers are not left without an explanation.

    The field must never contain internal notes, provider errors, hidden prompts, unrestricted metadata, or handoff-only details.
    """
    escalation_id: uuid.UUID
    target_status: str
    principal: AuthenticatedPrincipal
    trace_id: uuid.UUID | None = None
    customer_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.escalation_id, uuid.UUID):
            raise TypeError("escalation_id must be a UUID")

        if not isinstance(self.target_status, str):
            raise TypeError("target_status must be a string")

        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if self.principal.role not in {AuthRole.SUPPORT_AGENT, AuthRole.ADMIN,}:
            raise ValueError("Only support agents and administrators may update escalations.")

        if self.trace_id is not None and not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID or None")

        normalized_target = self.target_status.strip().lower()

        if not normalized_target:
            raise ValueError("target_status cannot be blank")

        if normalized_target not in VALID_ESCALATION_STATUSES:
            expected = ", ".join(sorted(VALID_ESCALATION_STATUSES))
            raise ValueError(f"target_status must be one of: {expected}")

        normalized_customer_message = self._normalize_customer_message(self.customer_message)
        if normalized_target in TERMINAL_ESCALATION_STATUSES and normalized_customer_message is None:
            raise ValueError("customer_message is required when resolving or dismissing an escalation")

        if normalized_target not in TERMINAL_ESCALATION_STATUSES and normalized_customer_message is not None:
            raise ValueError("customer_message may only be supplied when resolving or dismissing an escalation")

        object.__setattr__(self, "target_status", normalized_target)
        object.__setattr__(self, "customer_message", normalized_customer_message)

    @staticmethod
    def _normalize_customer_message(value: str | None) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError("customer_message must be a string or None")

        normalized = " ".join(value.split())
        if not normalized:
            return None

        if len(normalized) > MAX_CUSTOMER_MESSAGE_LENGTH:
            raise ValueError(f"customer_message exceeds {MAX_CUSTOMER_MESSAGE_LENGTH} characters")

        return normalized

@dataclass(frozen=True, slots=True)
class UpdateEscalationResult:
    """Detached result returned after transaction commit."""

    escalation_id: uuid.UUID
    conversation_id: uuid.UUID
    ai_run_id: uuid.UUID | None
    previous_status: str
    current_status: str
    resolved_at: datetime | None
    updated_at: datetime
    changed: bool
    notification_message_id: uuid.UUID | None

class UpdateEscalation:
    """
    Update an escalation lifecycle using a row lock.

    Unlike CreateEscalation, this service owns its Unit of Work because it represents a standalone agent/admin
    action initiated after the original customer-message transaction has completed.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, notification_writer: ConversationNotificationWriter, clock: Clock | None = None) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if not isinstance(notification_writer, ConversationNotificationWriter):
            raise TypeError("notification_writer must be a ConversationNotificationWriter")

        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable or None")

        self._uow_factory = uow_factory
        self._notification_writer = notification_writer
        self._clock = clock if clock is not None else self._utc_now

    def execute(self, command: UpdateEscalationCommand) -> UpdateEscalationResult:
        if not isinstance(command, UpdateEscalationCommand):
            raise TypeError("command must be an UpdateEscalationCommand")

        with self._uow_factory() as uow:
            repository, audit_repository = self._require_repositories(uow)
            escalation = repository.get_by_id_for_update(command.escalation_id)
            if escalation is None:
                raise EscalationDoesNotExistError(command.escalation_id)

            previous_status = escalation.status
            if previous_status == command.target_status:
                result = self._to_result(escalation=escalation, previous_status=previous_status, changed=False, notification_message_id=None)

                # An idempotent replay does not append another notice.
                uow.commit()
                return result

            self._validate_transition(escalation_id=escalation.id, current_status=previous_status, target_status=command.target_status)
            before_state = self._audit_state(escalation)
            occurred_at = self._clock()
            self._validate_clock_value(occurred_at)
            self._apply_transition(escalation=escalation, target_status=command.target_status, occurred_at=occurred_at)

            uow.flush()

            notification = self._notification_writer.execute_in_uow(
                command=AppendConversationNotificationCommand(
                    conversation_id=escalation.conversation_id,
                    notification_kind=self._notification_kind(command.target_status),
                    content=self._notification_content(target_status=command.target_status, customer_message=command.customer_message),
                    metadata={
                        "escalation_id": str(escalation.id),
                        "escalation_status": command.target_status,
                    },
                ),
                uow=uow,
            )

            AuditRecorder(repository=audit_repository).record(
                RecordAuditEventCommand(
                    event_type="escalation.updated",
                    entity_type="escalation",
                    entity_id=escalation.id,
                    action="updated",
                    actor=AuditActor(actor_type=self._audit_actor_type(command.principal.role), actor_id=command.principal.user_id),
                    trace_id=command.trace_id,
                    conversation_id=escalation.conversation_id,
                    ai_run_id=escalation.ai_run_id,
                    before_state=before_state,
                    after_state=self._audit_state(escalation),
                    metadata={
                        "previous_status": previous_status,
                        "target_status": command.target_status,
                        "customer_message_supplied": command.customer_message is not None,
                        "customer_message_length": len(command.customer_message) if command.customer_message is not None else 0,
                        "notification_message_id": str(notification.message_id),
                    },
                    occurred_at=occurred_at,
                )
            )

            result = self._to_result(
                escalation=escalation,
                previous_status=previous_status,
                changed=True,
                notification_message_id=notification.message_id,
            )

            uow.commit()
            return result

    @staticmethod
    def _notification_kind(target_status: str) -> str:
        mapping = {
            "in_review": "escalation_in_review",
            "resolved": "escalation_resolved",
            "dismissed": "escalation_dismissed",
        }

        notification_kind = mapping.get(target_status)
        if notification_kind is None:
            raise EscalationPersistenceContractError("Escalation target status has no customer notification mapping")

        return notification_kind

    @staticmethod
    def _notification_content(*, target_status: str, customer_message: str | None) -> str:
        if target_status == "in_review":
            return _ESCALATION_IN_REVIEW_NOTICE

        if target_status == "resolved":
            if customer_message is None:
                raise EscalationPersistenceContractError("Resolved escalation has no customer-facing explanation")

            return f"{_ESCALATION_RESOLVED_PREFIX} {customer_message}"

        if target_status == "dismissed":
            if customer_message is None:
                raise EscalationPersistenceContractError("Dismissed escalation has no customer-facing explanation")

            return f"{_ESCALATION_DISMISSED_PREFIX} {customer_message}"

        raise EscalationPersistenceContractError("Escalation target status has no customer notification content")

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> tuple[EscalationRepository, AuditEventRepository,]:
        if uow.session is None:
            raise EscalationPersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.escalations is None:
            raise EscalationPersistenceContractError("EscalationRepository unavailable")

        if uow.audit_events is None:
            raise EscalationPersistenceContractError("AuditEventRepository unavailable")

        return uow.escalations, uow.audit_events
    
    @staticmethod
    def _audit_state(escalation: EscalationModel) -> dict[str, object]:
        return {
            "status": escalation.status,
            "priority": escalation.priority,
            "source": escalation.source,
            "reason_code": escalation.reason_code,
            "resolved_at": escalation.resolved_at.isoformat() if escalation.resolved_at is not None else None,
            "updated_at": escalation.updated_at.isoformat() if escalation.updated_at is not None else None,
        }
        
    @staticmethod
    def _audit_actor_type(role: AuthRole) -> AuditActorType:
        if role is AuthRole.SUPPORT_AGENT:
            return AuditActorType.AGENT

        if role is AuthRole.ADMIN:
            return AuditActorType.ADMIN

        raise ValueError("Only support agents and administrators may update escalations.")

    @staticmethod
    def _validate_transition(*, escalation_id: uuid.UUID, current_status: str, target_status: str) -> None:
        allowed_targets = ALLOWED_ESCALATION_TRANSITIONS.get(current_status)
        if allowed_targets is None or target_status not in allowed_targets:
            raise InvalidEscalationTransitionError(escalation_id=escalation_id, current_status=current_status, target_status=target_status)

    @staticmethod
    def _apply_transition(*, escalation: EscalationModel, target_status: str, occurred_at: datetime) -> None:
        escalation.status = target_status
        escalation.updated_at = occurred_at

        if target_status in TERMINAL_ESCALATION_STATUSES:
            escalation.resolved_at = occurred_at
        else:
            escalation.resolved_at = None

    @staticmethod
    def _to_result(*, escalation: EscalationModel, previous_status: str, changed: bool, notification_message_id: uuid.UUID | None) -> UpdateEscalationResult:
        if escalation.id is None:
            raise EscalationPersistenceContractError("Persisted escalation has no ID")

        return UpdateEscalationResult(
            escalation_id=escalation.id,
            conversation_id=escalation.conversation_id,
            ai_run_id=escalation.ai_run_id,
            previous_status=previous_status,
            current_status=escalation.status,
            resolved_at=escalation.resolved_at,
            updated_at=escalation.updated_at,
            changed=changed,
            notification_message_id=notification_message_id,
        )

    @staticmethod
    def _validate_clock_value(value: datetime) -> None:
        if not isinstance(value, datetime):
            raise TypeError("clock must return a datetime")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)