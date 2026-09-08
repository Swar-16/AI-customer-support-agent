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

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork,]
Clock = Callable[[], datetime]
VALID_ESCALATION_STATUSES: Final[frozenset[str]] = frozenset({"open", "in_review", "resolved", "dismissed",})
TERMINAL_ESCALATION_STATUSES: Final[frozenset[str]] = frozenset({"resolved", "dismissed",})
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
    Request to move one escalation to another lifecycle state.

    The actor information will later be persisted through the audit-event subsystem. It receiving no actor fields here
    avoids accepting that an unauthenticated caller has already been authorized.
    """
    escalation_id: uuid.UUID
    target_status: str

    def __post_init__(self) -> None:
        if not isinstance(self.escalation_id, uuid.UUID):
            raise TypeError("escalation_id must be a UUID")

        if not isinstance(self.target_status, str):
            raise TypeError("target_status must be a string")

        normalized_target = self.target_status.strip().lower()
        if not normalized_target:
            raise ValueError("target_status cannot be blank")

        if normalized_target not in VALID_ESCALATION_STATUSES:
            expected = ", ".join(sorted(VALID_ESCALATION_STATUSES))
            raise ValueError(f"target_status must be one of: {expected}")

        object.__setattr__(self, "target_status", normalized_target)

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

class UpdateEscalation:
    """
    Update an escalation lifecycle using a row lock.

    Unlike CreateEscalation, this service owns its Unit of Work because it represents a standalone agent/admin
    action initiated after the original customer-message transaction has completed.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock | None = None) -> None:
        if uow_factory is None:
            raise TypeError("uow_factory cannot be None")

        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable or None")

        self._uow_factory = uow_factory
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
                result = self._to_result(escalation=escalation, previous_status=previous_status, changed=False)

                # Explicit commit keeps Unit of Work semantics consistent. No SQL UPDATE is emitted when nothing changed.
                uow.commit()
                return result

            self._validate_transition(escalation_id=escalation.id, current_status=previous_status, target_status=command.target_status)
            occurred_at = self._clock()
            self._validate_clock_value(occurred_at)
            before_state = self._audit_state(escalation)
            self._apply_transition(escalation=escalation, target_status=command.target_status, occurred_at=occurred_at)
            # SQLAlchemy tracks this loaded ORM object automatically. No repository.save() method is necessary.
            uow.flush()
            AuditRecorder(repository=audit_repository).record(
                RecordAuditEventCommand(
                    event_type="escalation.updated",
                    entity_type="escalation",
                    entity_id=escalation.id,
                    action="updated",
                    actor=AuditActor(actor_type=AuditActorType.SYSTEM),
                    conversation_id=escalation.conversation_id,
                    ai_run_id=escalation.ai_run_id,
                    before_state=before_state,
                    after_state=self._audit_state(escalation),
                    metadata={
                        "previous_status": previous_status,
                        "target_status": command.target_status,
                    },
                    occurred_at=occurred_at,
                )
            )

            result = self._to_result(escalation=escalation, previous_status=previous_status, changed=True)
            uow.commit()
            return result

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
    def _to_result(*, escalation: EscalationModel, previous_status: str, changed: bool) -> UpdateEscalationResult:
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