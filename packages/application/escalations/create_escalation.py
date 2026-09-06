# AI-customer-support-agent\packages\application\escalations\create_escalation.py
from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Mapping

from packages.database.models.support.escalation import EscalationModel
from packages.database.repositories.support.escalation_repository import EscalationRepository

VALID_ESCALATION_SOURCES: Final[frozenset[str]] = frozenset({"decision", "guardrail", "system", "manual",})
VALID_ESCALATION_PRIORITIES: Final[frozenset[str]] = frozenset({"low", "normal", "high", "urgent",})
MAX_REASON_CODE_LENGTH: Final[int] = 100
MAX_REASON_SUMMARY_LENGTH: Final[int] = 2_000
MAX_HANDOFF_SUMMARY_LENGTH: Final[int] = 5_000
MAX_METADATA_KEYS: Final[int] = 100
MAX_METADATA_SERIALIZED_LENGTH: Final[int] = 20_000


class CreateEscalationError(RuntimeError):
    """Base application-layer error for escalation creation."""

class CreateEscalationContractError(CreateEscalationError):
    """Raised when escalation persistence violates an internal contract."""

class EscalationIdempotencyConflictError(CreateEscalationError):
    """Raised when an AI run already has an active escalation whose provenance conflicts with the requested escalation."""

@dataclass(frozen=True, slots=True)
class CreateEscalationCommand:
    """
    Application command for creating a persistent escalation.

    This command describes an escalation that has already been requested by orchestration or another trusted 
    application workflow. It does not decide whether escalation is necessary.
    """
    conversation_id: uuid.UUID
    source: str
    reason_code: str
    ai_run_id: uuid.UUID | None = None
    trigger_message_id: uuid.UUID | None = None
    reason_summary: str | None = None
    priority: str = "normal"
    handoff_summary: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_uuid(self.conversation_id, field_name="conversation_id")
        if self.ai_run_id is not None:
            self._validate_uuid(self.ai_run_id, field_name="ai_run_id")

        if self.trigger_message_id is not None:
            self._validate_uuid(self.trigger_message_id, field_name="trigger_message_id")

        normalized_source = self._normalize_required_text(self.source, field_name="source", max_length=32).lower()
        if normalized_source not in VALID_ESCALATION_SOURCES:
            expected = ", ".join(sorted(VALID_ESCALATION_SOURCES))
            raise ValueError(f"source must be one of: {expected}")

        normalized_reason_code = self._normalize_required_text(self.reason_code, field_name="reason_code", max_length=MAX_REASON_CODE_LENGTH).upper()
        normalized_priority = self._normalize_required_text(self.priority, field_name="priority", max_length=16).lower()
        if normalized_priority not in VALID_ESCALATION_PRIORITIES:
            expected = ", ".join(sorted(VALID_ESCALATION_PRIORITIES))
            raise ValueError(f"priority must be one of: {expected}")

        normalized_reason_summary = self._normalize_optional_text(self.reason_summary, field_name="reason_summary", max_length=MAX_REASON_SUMMARY_LENGTH)
        normalized_handoff_summary = self._normalize_optional_text(self.handoff_summary, field_name="handoff_summary", max_length=MAX_HANDOFF_SUMMARY_LENGTH)
        normalized_metadata = self._normalize_metadata(self.metadata)
        object.__setattr__(self, "source", normalized_source)
        object.__setattr__(self, "reason_code", normalized_reason_code)
        object.__setattr__(self, "priority", normalized_priority)
        object.__setattr__(self, "reason_summary", normalized_reason_summary)
        object.__setattr__(self, "handoff_summary", normalized_handoff_summary)
        object.__setattr__(self, "metadata", MappingProxyType(normalized_metadata))

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str, max_length: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        if len(normalized) > max_length:
            raise ValueError(f"{field_name} exceeds {max_length} characters")

        return normalized

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str, max_length: int) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = " ".join(value.split())
        if not normalized:
            return None

        if len(normalized) > max_length:
            raise ValueError(f"{field_name} exceeds {max_length} characters")

        return normalized

    @staticmethod
    def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping")

        if len(metadata) > MAX_METADATA_KEYS:
            raise ValueError("metadata contains too many keys")

        normalized: dict[str, Any] = {}
        for key, value in metadata.items():
            if not isinstance(key, str):
                raise TypeError("metadata keys must be strings")

            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError("metadata keys cannot be blank")

            if normalized_key in normalized:
                raise ValueError("metadata contains duplicate keys after normalization")

            normalized[normalized_key] = value

        try:
            serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
            
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must contain only JSON-serializable values") from exc

        if len(serialized) > MAX_METADATA_SERIALIZED_LENGTH:
            raise ValueError(f"serialized metadata exceeds {MAX_METADATA_SERIALIZED_LENGTH} characters")

        return normalized

@dataclass(frozen=True, slots=True)
class CreateEscalationResult:
    """
    Result returned after staging and flushing an escalation.

    `created=False` means an existing active escalation for the same AI run satisfied the idempotent request.
    """
    escalation_id: uuid.UUID
    conversation_id: uuid.UUID
    ai_run_id: uuid.UUID | None
    status: str
    created: bool

class CreateEscalation:
    """
    Create an escalation using an already-active repository.

    This service does not create a Unit of Work and does not commit. Its caller owns the transaction boundary.
    """
    def __init__(self, *, repository: EscalationRepository) -> None:
        if not isinstance(repository, EscalationRepository):
            raise TypeError("repository must be an EscalationRepository")

        self._repository = repository

    def execute(self, command: CreateEscalationCommand) -> CreateEscalationResult:
        if not isinstance(command, CreateEscalationCommand):
            raise TypeError("command must be a CreateEscalationCommand")

        existing = self._find_existing(command)
        if existing is not None:
            self._validate_existing(existing=existing, command=command)
            
            return self._to_result(escalation=existing, created=False)

        escalation = EscalationModel(
            conversation_id=command.conversation_id,
            ai_run_id=command.ai_run_id,
            trigger_message_id=command.trigger_message_id,
            source=command.source,
            reason_code=command.reason_code,
            reason_summary=command.reason_summary,
            priority=command.priority,
            status="open",
            handoff_summary=command.handoff_summary,
            metadata_=dict(command.metadata),
        )

        self._repository.add(escalation)
        self._repository.flush()
        if escalation.id is None:
            raise CreateEscalationContractError("Escalation ID was not generated after flush")

        return self._to_result(escalation=escalation, created=True)

    def _find_existing(self, command: CreateEscalationCommand) -> EscalationModel | None:
        """
        AI-generated escalation creation is idempotent by AI run.

        Manual/system escalations without an AI run are intentionally not deduplicated here because they may represent separate human actions.
        """
        if command.ai_run_id is None:
            return None

        return self._repository.get_active_for_ai_run(command.ai_run_id)

    @staticmethod
    def _validate_existing(*, existing: EscalationModel, command: CreateEscalationCommand) -> None:
        """Prevent a retry from silently reusing an unrelated escalation."""
        conflicts: list[str] = []
        if existing.conversation_id != command.conversation_id:
            conflicts.append("conversation_id")

        if existing.source != command.source:
            conflicts.append("source")

        if existing.reason_code != command.reason_code:
            conflicts.append("reason_code")

        if command.trigger_message_id is not None and existing.trigger_message_id != command.trigger_message_id:
            conflicts.append("trigger_message_id")

        if conflicts:
            fields = ", ".join(conflicts)
            raise EscalationIdempotencyConflictError(f"Active escalation for AI run {command.ai_run_id} conflicts on: {fields}")

    @staticmethod
    def _to_result(*, escalation: EscalationModel, created: bool) -> CreateEscalationResult:
        if escalation.id is None:
            raise CreateEscalationContractError("Persisted escalation has no ID")

        return CreateEscalationResult(
            escalation_id=escalation.id,
            conversation_id=escalation.conversation_id,
            ai_run_id=escalation.ai_run_id,
            status=escalation.status,
            created=created,
        )