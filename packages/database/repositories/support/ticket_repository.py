# AI-customer-support-agent\packages\database\repositories\support\ticket_repository.py
from __future__ import annotations
import uuid
from collections.abc import Sequence
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from packages.database.models.support.ticket import TicketModel

ACTIVE_TICKET_STATUSES = frozenset({"open", "in_progress", "waiting_for_customer", "reopened",})
VALID_TICKET_STATUSES = frozenset({"open", "in_progress", "waiting_for_customer", "resolved", "closed", "reopened",})
VALID_TICKET_PRIORITIES = frozenset({"low", "normal", "high", "urgent",})
VALID_TICKET_CATEGORIES = frozenset({"billing", "refund", "order", "account", "technical", "security", "product", "general", "other",})

class TicketRepository:
    """
    Persistence adapter for support tickets.

    Responsibilities:
    - stage tickets for persistence;
    - retrieve tickets by identity and ticket number;
    - retrieve tickets through their business relationships;
    - acquire row locks for lifecycle updates;
    - provide filtered dashboard/agent queues.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, ticket: TicketModel) -> None:
        """
        Stage a ticket in the current transaction.

        The method does not flush or commit.
        """
        self._validate_ticket_instance(ticket)
        self._session.add(ticket)

    def flush(self) -> None:
        """Flush pending ORM state without committing."""
        self._session.flush()

    # Primary lookups
    def get_by_id(self, ticket_id: uuid.UUID) -> TicketModel | None:
        self._validate_uuid(ticket_id, field_name="ticket_id")
        statement = (select(TicketModel)
                     .where(TicketModel.id == ticket_id)
        )

        return self._session.scalar(statement)

    def get_by_id_for_update(self, ticket_id: uuid.UUID) -> TicketModel | None:
        """
        Load a ticket while acquiring a row-level write lock.

        Use this before assignment, priority, category, or lifecycle modifications.
        """
        self._validate_uuid(ticket_id, field_name="ticket_id")
        statement = (select(TicketModel)
                     .where(TicketModel.id == ticket_id)
                     .with_for_update()
        )

        return self._session.scalar(statement)

    def get_by_ticket_number(self, ticket_number: int) -> TicketModel | None:
        """Return a ticket using its human-facing sequence number."""
        self._validate_ticket_number(ticket_number)
        statement = (select(TicketModel)
                     .where(TicketModel.ticket_number == ticket_number)
        )

        return self._session.scalar(statement)

    def get_by_escalation_id(self, escalation_id: uuid.UUID) -> TicketModel | None:
        """
        Return the ticket linked to an escalation.

        The database partial unique index guarantees at most one result.
        """
        self._validate_uuid(escalation_id, field_name="escalation_id")
        statement = (select(TicketModel)
                     .where(TicketModel.escalation_id == escalation_id)
        )

        return self._session.scalar(statement)

    # Relationship queries
    def list_for_conversation(self, conversation_id: uuid.UUID, *, limit: int = 100) -> Sequence[TicketModel]:
        """Return newest-first tickets for one conversation."""
        self._validate_uuid(conversation_id, field_name="conversation_id")
        self._validate_limit(limit)
        statement = (select(TicketModel)
                     .where(TicketModel.conversation_id == conversation_id)
                     .order_by(TicketModel.created_at.desc(),
                               TicketModel.id.desc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_for_customer(self, customer_id: uuid.UUID, *, status: str | None = None, limit: int = 100, offset: int = 0) -> Sequence[TicketModel]:
        """
        Return tickets belonging to one customer.

        Customer ownership authorization remains in the application/API layer. This query only applies the requested persistence filter.
        """
        self._validate_uuid(customer_id, field_name="customer_id")
        self._validate_limit(limit)
        self._validate_offset(offset)
        normalized_status = self._normalize_optional_status(status)
        statement = (select(TicketModel)
                     .where(TicketModel.customer_id == customer_id)
        )

        if normalized_status is not None:
            statement = statement.where(TicketModel.status == normalized_status)

        statement = (statement.order_by(TicketModel.created_at.desc(),
                                        TicketModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Dashboard and agent queue
    def list_recent(self, *, status: str | None = None, priority: str | None = None, category: str | None = None,
                    assigned_agent_id: uuid.UUID | None = None, unassigned_only: bool = False, limit: int = 100, offset: int = 0
    ) -> Sequence[TicketModel]:
        """Return recent tickets using optional exact-match filters."""
        self._validate_limit(limit)
        self._validate_offset(offset)
        self._validate_assignment_filters(assigned_agent_id=assigned_agent_id, unassigned_only=unassigned_only)
        normalized_status = self._normalize_optional_status(status)
        normalized_priority = self._normalize_optional_priority(priority)
        normalized_category = self._normalize_optional_category(category)
        statement = select(TicketModel)
        if normalized_status is not None:
            statement = statement.where(TicketModel.status == normalized_status)

        if normalized_priority is not None:
            statement = statement.where(TicketModel.priority == normalized_priority)

        if normalized_category is not None:
            statement = statement.where(TicketModel.category == normalized_category)

        if assigned_agent_id is not None:
            statement = statement.where(TicketModel.assigned_agent_id == assigned_agent_id)

        if unassigned_only:
            statement = statement.where(TicketModel.assigned_agent_id.is_(None))

        statement = (statement.order_by(TicketModel.created_at.desc(),
                                        TicketModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_active_queue(self, *, priority: str | None = None, category: str | None = None, assigned_agent_id: uuid.UUID | None = None,
                          unassigned_only: bool = False, limit: int = 100, offset: int = 0
    ) -> Sequence[TicketModel]:
        """
        Return the active support queue.

        Ordering:
        1. urgent before high, normal, and low;
        2. reopened before open, in-progress, and waiting;
        3. oldest ticket first within the same priority/status.
        """
        self._validate_limit(limit)
        self._validate_offset(offset)
        self._validate_assignment_filters(assigned_agent_id=assigned_agent_id, unassigned_only=unassigned_only)
        normalized_priority = self._normalize_optional_priority(priority)
        normalized_category = self._normalize_optional_category(category)
        priority_order = case(
            {
                "urgent": 0,
                "high": 1,
                "normal": 2,
                "low": 3,
            },
            value=TicketModel.priority,
            else_=4,
        )

        status_order = case(
            {
                "reopened": 0,
                "open": 1,
                "in_progress": 2,
                "waiting_for_customer": 3,
            },
            value=TicketModel.status,
            else_=4,
        )

        statement = (select(TicketModel)
                     .where(TicketModel.status.in_(ACTIVE_TICKET_STATUSES))
        )

        if normalized_priority is not None:
            statement = statement.where(TicketModel.priority == normalized_priority)

        if normalized_category is not None:
            statement = statement.where(TicketModel.category == normalized_category)

        if assigned_agent_id is not None:
            statement = statement.where(TicketModel.assigned_agent_id == assigned_agent_id)

        if unassigned_only:
            statement = statement.where(TicketModel.assigned_agent_id.is_(None))

        statement = (statement.order_by(priority_order.asc(),
                                        status_order.asc(),
                                        TicketModel.created_at.asc(),
                                        TicketModel.id.asc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Internal validation
    @staticmethod
    def _validate_ticket_instance(ticket: TicketModel) -> None:
        if not isinstance(ticket, TicketModel):
            raise TypeError("ticket must be a TicketModel")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_ticket_number(ticket_number: int) -> None:
        if isinstance(ticket_number, bool) or not isinstance(ticket_number, int):
            raise TypeError("ticket_number must be an integer")

        if ticket_number <= 0:
            raise ValueError("ticket_number must be greater than zero")

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

    @classmethod
    def _validate_assignment_filters(cls, *, assigned_agent_id: uuid.UUID | None, unassigned_only: bool) -> None:
        if not isinstance(unassigned_only, bool):
            raise TypeError("unassigned_only must be a boolean")

        if assigned_agent_id is not None:
            cls._validate_uuid(assigned_agent_id, field_name="assigned_agent_id")

        if assigned_agent_id is not None and unassigned_only:
            raise ValueError("assigned_agent_id and unassigned_only=True cannot be combined")

    @classmethod
    def _normalize_optional_status(cls, value: str | None) -> str | None:
        return cls._normalize_choice(value, field_name="status", valid_values=VALID_TICKET_STATUSES)

    @classmethod
    def _normalize_optional_priority(cls, value: str | None) -> str | None:
        return cls._normalize_choice(value, field_name="priority", valid_values=VALID_TICKET_PRIORITIES)

    @classmethod
    def _normalize_optional_category(cls, value: str | None) -> str | None:
        return cls._normalize_choice(value, field_name="category", valid_values=VALID_TICKET_CATEGORIES)

    @staticmethod
    def _normalize_choice(value: str | None, *, field_name: str, valid_values: frozenset[str]) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip().lower()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        if normalized not in valid_values:
            expected = ", ".join(sorted(valid_values))
            raise ValueError(f"{field_name} must be one of: {expected}")

        return normalized