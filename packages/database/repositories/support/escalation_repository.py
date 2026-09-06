# AI-customer-support-agent\packages\database\repositories\support\escalation_repository.py
from __future__ import annotations
import uuid
from collections.abc import Sequence
from sqlalchemy import select, case
from sqlalchemy.orm import Session

from packages.database.models.support.escalation import EscalationModel


ACTIVE_ESCALATION_STATUSES = frozenset({"open", "in_review",})
VALID_ESCALATION_STATUSES = frozenset({"open", "in_review", "resolved", "dismissed",})
VALID_ESCALATION_PRIORITIES = frozenset({"low", "normal", "high", "urgent",})

class EscalationRepository:
    """
    Persistence adapter for support escalations.

    Responsibilities:
    - stage escalation records for persistence;
    - retrieve escalations by identity and provenance;
    - acquire row locks for lifecycle updates;
    - provide filtered escalation queues;
    - support idempotent escalation creation checks.

    Transaction ownership remains with the surrounding Unit of Work.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, escalation: EscalationModel) -> None:
        """
        Stage a new escalation in the current transaction.

        The method does not flush or commit.
        """
        self._validate_escalation_instance(escalation)
        self._session.add(escalation)

    def flush(self) -> None:
        """
        Flush pending ORM changes without committing.
        """
        self._session.flush()

    # Primary lookups
    def get_by_id(self, escalation_id: uuid.UUID) -> EscalationModel | None:
        """
        Return an escalation by ID.
        """
        self._validate_uuid(escalation_id, field_name="escalation_id")
        statement = (select(EscalationModel)
                     .where(EscalationModel.id == escalation_id)
        )

        return self._session.scalar(statement)

    def get_by_id_for_update(self, escalation_id: uuid.UUID) -> EscalationModel | None:
        """
        Return an escalation while acquiring a row-level write lock.

        The lock remains active for the surrounding transaction and should be used before lifecycle transitions such as:
            open -> in_review
            open -> resolved
            in_review -> resolved
            open -> dismissed
        """
        self._validate_uuid(escalation_id, field_name="escalation_id")
        statement = (select(EscalationModel)
                     .where(EscalationModel.id == escalation_id)
                     .with_for_update()
        )

        return self._session.scalar(statement)

    def get_by_ai_run(self, ai_run_id: uuid.UUID) -> Sequence[EscalationModel]:
        """
        Return all escalations created from one AI run.

        Multiple records are technically supported because different pipeline stages may produce independent escalation evidence.
        Application services should use get_active_for_ai_run() when preventing duplicate active escalations.
        """
        self._validate_uuid(ai_run_id, field_name="ai_run_id")
        statement = (select(EscalationModel)
                     .where(EscalationModel.ai_run_id == ai_run_id)
                     .order_by(EscalationModel.created_at.asc(),
                               EscalationModel.id.asc())
        )

        return tuple(self._session.scalars(statement))

    def get_active_for_ai_run(self, ai_run_id: uuid.UUID) -> EscalationModel | None:
        """
        Return the active escalation associated with an AI run.

        This supports idempotent application behavior when a request is retried or multiple orchestration callbacks report the same escalation outcome.

        If historical data contains multiple active rows, the oldest row is returned as the canonical record.
        A later database constraint may strengthen this invariant once the ticket/escalation relationship is finalized.
        """
        self._validate_uuid(ai_run_id, field_name="ai_run_id")
        statement = (select(EscalationModel)
                     .where(EscalationModel.ai_run_id == ai_run_id,
                            EscalationModel.status.in_(ACTIVE_ESCALATION_STATUSES))
                     .order_by(EscalationModel.created_at.asc(),
                               EscalationModel.id.asc())
                     .limit(1)
        )

        return self._session.scalar(statement)

    def get_by_trigger_message(self, trigger_message_id: uuid.UUID) -> Sequence[EscalationModel]:
        """
        Return escalations caused by a particular message.
        """
        self._validate_uuid(trigger_message_id, field_name="trigger_message_id")
        statement = (select(EscalationModel)
                     .where(EscalationModel.trigger_message_id == trigger_message_id)
                     .order_by(EscalationModel.created_at.asc(),
                               EscalationModel.id.asc())
        )

        return tuple(self._session.scalars(statement))

    # Conversation and queue queries
    def get_by_conversation(self, conversation_id: uuid.UUID, *, limit: int = 100) -> Sequence[EscalationModel]:
        """
        Return the newest escalations for a conversation.
        """
        self._validate_uuid(conversation_id, field_name="conversation_id")
        self._validate_limit(limit)
        statement = (select(EscalationModel)
                     .where(EscalationModel.conversation_id == conversation_id)
                     .order_by(EscalationModel.created_at.desc(),
                               EscalationModel.id.desc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def get_active_for_conversation(self, conversation_id: uuid.UUID, *, limit: int = 100) -> Sequence[EscalationModel]:
        """
        Return active escalations for a conversation.
        """
        self._validate_uuid(conversation_id, field_name="conversation_id")
        self._validate_limit(limit)
        statement = (select(EscalationModel)
                     .where(EscalationModel.conversation_id == conversation_id,
                            EscalationModel.status.in_(ACTIVE_ESCALATION_STATUSES))
                     .order_by(EscalationModel.created_at.asc(),
                               EscalationModel.id.asc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_recent(self, *, status: str | None = None, priority: str | None = None, reason_code: str | None = None, limit: int = 100, offset: int = 0) -> Sequence[EscalationModel]:
        """
        Return a filtered escalation queue ordered newest first.

        This is sufficient for the MVP dashboard. Cursor-based pagination can replace offset pagination when the data volume requires it.
        """
        self._validate_limit(limit)
        self._validate_offset(offset)
        normalized_status = self._normalize_optional_status(status)
        normalized_priority = self._normalize_optional_priority(priority)
        normalized_reason_code = self._normalize_optional_text(reason_code, field_name="reason_code")
        statement = select(EscalationModel)
        if normalized_status is not None:
            statement = statement.where(EscalationModel.status == normalized_status)

        if normalized_priority is not None:
            statement = statement.where(EscalationModel.priority == normalized_priority)

        if normalized_reason_code is not None:
            statement = statement.where(EscalationModel.reason_code == normalized_reason_code)

        statement = (statement.order_by(EscalationModel.created_at.desc(),
                                        EscalationModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_active(self, *, priority: str | None = None, limit: int = 100, offset: int = 0) -> Sequence[EscalationModel]:
        """
        Return the active escalation work queue.

        Urgent and high-priority records appear first. Records with the same priority are ordered oldest first so
        long-waiting escalations are handled before newer ones.
        """
        self._validate_limit(limit)
        self._validate_offset(offset)
        normalized_priority = self._normalize_optional_priority(priority)
        priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3,}
        statement = (select(EscalationModel)
                     .where(EscalationModel.status.in_(ACTIVE_ESCALATION_STATUSES))
        )

        if normalized_priority is not None:
            statement = statement.where(EscalationModel.priority == normalized_priority)

        statement = (statement.order_by(case(priority_order, value=EscalationModel.priority, else_=4,).asc(),
                                        EscalationModel.created_at.asc(),
                                        EscalationModel.id.asc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Internal validation
    @staticmethod
    def _validate_escalation_instance(escalation: EscalationModel) -> None:
        if not isinstance(escalation, EscalationModel):
            raise TypeError("escalation must be an EscalationModel")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if limit > 500:
            raise ValueError("limit must not exceed 500")

    @staticmethod
    def _validate_offset(offset: int) -> None:
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")

        if offset < 0:
            raise ValueError("offset must not be negative")

    @staticmethod
    def _normalize_optional_status(status: str | None) -> str | None:
        normalized = EscalationRepository._normalize_optional_text(status, field_name="status")
        if normalized is not None and normalized not in VALID_ESCALATION_STATUSES:
            expected = ", ".join(sorted(VALID_ESCALATION_STATUSES))
            raise ValueError(f"status must be one of: {expected}")

        return normalized

    @staticmethod
    def _normalize_optional_priority(priority: str | None) -> str | None:
        normalized = EscalationRepository._normalize_optional_text(priority, field_name="priority")
        if normalized is not None and normalized not in VALID_ESCALATION_PRIORITIES:
            expected = ", ".join(sorted(VALID_ESCALATION_PRIORITIES))
            raise ValueError(f"priority must be one of: {expected}")

        return normalized

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip().lower()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        return normalized