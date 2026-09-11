# AI-customer-support-agent\packages\application\audit\recorder.py
from __future__ import annotations
import json
from typing import Any

from packages.application.audit.models import AuditActorType, AuditEventView, RecordAuditEventCommand
from packages.database.models.audit.audit_event import AuditEventModel
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository

class AuditRecordingError(RuntimeError):
    """Base error raised while recording a business audit event."""

class InvalidAuditPayloadError(AuditRecordingError):
    """Raised when audit snapshots or metadata cannot be stored safely as JSON."""

class AuditPersistenceContractError(AuditRecordingError):
    """Raised when persistence does not produce required database-generated audit-event fields."""

class AuditRecorder:
    """
    Records immutable business audit events in an existing transaction.

    The recorder deliberately receives an active repository instead of a Unit of Work factory. This guarantees
    that the audit event and corresponding business mutation share the same SQLAlchemy Session and commit boundary.

    This service never commits.
    """
    def __init__(self, *, repository: AuditEventRepository) -> None:
        if not isinstance(repository, AuditEventRepository):
            raise TypeError("repository must be an AuditEventRepository")

        self._repository = repository

    def record(self, command: RecordAuditEventCommand) -> AuditEventView:
        """
        Stage and flush one immutable audit event.

        Flushing here ensures audit persistence errors are raised before the caller commits the surrounding business transaction.
        """
        if not isinstance(command, RecordAuditEventCommand):
            raise TypeError("command must be a RecordAuditEventCommand")

        self._validate_json_payload(command.before_state, field_name="before_state")
        self._validate_json_payload(command.after_state, field_name="after_state")
        self._validate_json_payload(command.metadata, field_name="metadata")
        event = AuditEventModel(
            event_type=command.event_type,
            entity_type=command.entity_type,
            entity_id=command.entity_id,
            action=command.action,
            actor_type=command.actor.actor_type.value,
            actor_id=command.actor.actor_id,
            trace_id=command.trace_id,
            conversation_id=command.conversation_id,
            ai_run_id=command.ai_run_id,
            before_state=dict(command.before_state) if command.before_state is not None else None,
            after_state=dict(command.after_state) if command.after_state is not None else None,
            reason=command.reason,
            metadata_=dict(command.metadata),
            occurred_at=command.occurred_at,
        )

        self._repository.add(event)
        self._repository.flush()
        if event.id is None:
            raise AuditPersistenceContractError("Audit event ID was not generated after flush")

        if event.recorded_at is None:
            raise AuditPersistenceContractError("Audit event recorded_at was not generated after flush")

        return self._to_view(event)

    @staticmethod
    def _validate_json_payload(value: dict[str, Any] | None, *, field_name: str) -> None:
        if value is None:
            return

        try:
            json.dumps(value, allow_nan=False, separators=(",", ":"))

        except (TypeError, ValueError, OverflowError) as exc:
            raise InvalidAuditPayloadError(f"{field_name} must contain JSON-serializable values") from exc

    @staticmethod
    def _to_view(event: AuditEventModel) -> AuditEventView:
        try:
            actor_type = AuditActorType(event.actor_type)

        except ValueError as exc:
            raise AuditPersistenceContractError("Persisted audit event contains an invalid actor_type") from exc

        return AuditEventView(
            id=event.id,
            event_type=event.event_type,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            action=event.action,
            actor_type=actor_type,
            actor_id=event.actor_id,
            trace_id=event.trace_id,
            conversation_id=event.conversation_id,
            ai_run_id=event.ai_run_id,
            before_state=dict(event.before_state) if event.before_state is not None else None,
            after_state=dict(event.after_state) if event.after_state is not None else None,
            reason=event.reason,
            metadata=dict(event.metadata_),
            occurred_at=event.occurred_at,
            recorded_at=event.recorded_at,
        )