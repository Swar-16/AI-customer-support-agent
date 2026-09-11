# AI-customer-support-agent\packages\database\repositories\support\ticket_comment_repository.py
from __future__ import annotations
import uuid
from collections.abc import Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.support.ticket_comment import TicketCommentModel

VALID_COMMENT_VISIBILITIES = frozenset({"customer", "internal",})
VALID_COMMENT_AUTHOR_ROLES = frozenset({"customer", "support_agent", "admin", "system",})


class TicketCommentRepository:
    """
    Persistence adapter for append-only ticket comments.

    Responsibilities:
    - stage new comments for persistence;
    - retrieve comments by identity;
    - retrieve ticket comment history;
    - apply visibility filters required by trusted application services;
    - provide recent-comment queries for operations/debugging.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, comment: TicketCommentModel) -> None:
        """
        Stage a new ticket comment in the current transaction.

        The method does not flush or commit.
        """
        self._validate_comment_instance(comment)
        self._session.add(comment)

    def flush(self) -> None:
        """Flush pending ORM state without committing."""
        self._session.flush()

    # Primary lookup
    def get_by_id(self, comment_id: uuid.UUID) -> TicketCommentModel | None:
        self._validate_uuid(comment_id, field_name="comment_id")
        statement = (select(TicketCommentModel)
                     .where(TicketCommentModel.id == comment_id)
        )

        return self._session.scalar(statement)

    # Ticket history
    def list_for_ticket(self, ticket_id: uuid.UUID, *, include_internal: bool = False, limit: int = 100, offset: int = 0) -> Sequence[TicketCommentModel]:
        """
        Return a ticket's comments in chronological order.

        When include_internal=False, only customer-visible comments are returned. Application services must never
        set include_internal=True for an unauthorized customer request.
        """
        self._validate_uuid(ticket_id, field_name="ticket_id")
        self._validate_boolean(include_internal, field_name="include_internal")
        self._validate_limit(limit)
        self._validate_offset(offset)

        statement = (select(TicketCommentModel)
                     .where(TicketCommentModel.ticket_id == ticket_id)
        )

        if not include_internal:
            statement = statement.where(TicketCommentModel.visibility == "customer")

        statement = (statement.order_by(TicketCommentModel.created_at.asc(),
                                        TicketCommentModel.id.asc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_by_author(self, author_id: uuid.UUID, *, limit: int = 100, offset: int = 0) -> Sequence[TicketCommentModel]:
        """Return newest-first comments written by an actor."""
        self._validate_uuid(author_id, field_name="author_id")
        self._validate_limit(limit)
        self._validate_offset(offset)

        statement = (select(TicketCommentModel)
                     .where(TicketCommentModel.author_id == author_id)
                     .order_by(TicketCommentModel.created_at.desc(),
                               TicketCommentModel.id.desc())
                     .offset(offset)
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Operations query
    def list_recent(self, *, visibility: str | None = None, author_role: str | None = None, limit: int = 100, offset: int = 0) -> Sequence[TicketCommentModel]:
        """
        Return recent ticket comments using optional exact filters.

        This method does not perform authorization. It is intended for trusted support/admin application services.
        """
        self._validate_limit(limit)
        self._validate_offset(offset)
        normalized_visibility = self._normalize_choice(visibility, field_name="visibility", valid_values=VALID_COMMENT_VISIBILITIES)
        normalized_author_role = self._normalize_choice(author_role, field_name="author_role", valid_values=VALID_COMMENT_AUTHOR_ROLES)
        statement = select(TicketCommentModel)

        if normalized_visibility is not None:
            statement = statement.where(TicketCommentModel.visibility == normalized_visibility)

        if normalized_author_role is not None:
            statement = statement.where(TicketCommentModel.author_role == normalized_author_role)

        statement = (statement.order_by(TicketCommentModel.created_at.desc(),
                                        TicketCommentModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Internal validation
    @staticmethod
    def _validate_comment_instance(comment: TicketCommentModel) -> None:
        if not isinstance(comment, TicketCommentModel):
            raise TypeError("comment must be a TicketCommentModel")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_boolean(value: bool, *, field_name: str) -> None:
        if not isinstance(value, bool):
            raise TypeError(f"{field_name} must be a boolean")

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