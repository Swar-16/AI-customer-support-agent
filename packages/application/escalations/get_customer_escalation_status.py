# AI-customer-support-agent\packages\application\escalations\get_customer_escalation_status.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

class CustomerEscalationStatusError(RuntimeError):
    """Base error for customer escalation-status queries."""

class CustomerConversationNotAccessibleError(CustomerEscalationStatusError):
    """
    Raised when the conversation does not exist or is not owned by the authenticated customer.

    Both cases intentionally map to the same HTTP 404 response.
    """

class CustomerEscalationDoesNotExistError(CustomerEscalationStatusError):
    """Raised when the owned conversation has no escalation."""

class CustomerEscalationStatusContractError(CustomerEscalationStatusError):
    """Raised when Unit of Work wiring is incomplete."""

@dataclass(frozen=True, slots=True)
class GetCustomerEscalationStatusQuery:
    conversation_id: uuid.UUID
    principal: AuthenticatedPrincipal

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, uuid.UUID):
            raise TypeError("conversation_id must be a UUID")

        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if self.principal.role is not AuthRole.CUSTOMER:
            raise ValueError("Customer escalation status requires a customer principal.")

@dataclass(frozen=True, slots=True)
class CustomerEscalationStatusView:
    """
    Customer-safe escalation representation.

    It intentionally excludes:
    - AI-run identifiers;
    - trigger-message identifiers;
    - internal reason codes and summaries;
    - handoff summaries;
    - sources;
    - arbitrary metadata.
    """
    escalation_id: uuid.UUID
    conversation_id: uuid.UUID
    status: str
    priority: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None

class GetCustomerEscalationStatus:
    """Return the newest escalation belonging to an authenticated customer's own conversation."""
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        if uow_factory is None or not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

    def execute(self, query: GetCustomerEscalationStatusQuery) -> CustomerEscalationStatusView:
        if not isinstance(query, GetCustomerEscalationStatusQuery):
            raise TypeError("query must be a GetCustomerEscalationStatusQuery")

        with self._uow_factory() as uow:
            if uow.conversations is None:
                raise CustomerEscalationStatusContractError("Conversation repository is unavailable.")

            if uow.escalations is None:
                raise CustomerEscalationStatusContractError("Escalation repository is unavailable.")

            conversation = uow.conversations.get_by_id(query.conversation_id)

            if conversation is None or conversation.user_id != query.principal.user_id:
                raise CustomerConversationNotAccessibleError("Conversation is unavailable.")

            escalations = uow.escalations.get_by_conversation(query.conversation_id, limit=1)
            if not escalations:
                raise CustomerEscalationDoesNotExistError("The conversation has no escalation.")

            escalation = escalations[0]
            if escalation.id is None:
                raise CustomerEscalationStatusContractError("Persisted escalation has no identifier.")

            return CustomerEscalationStatusView(
                escalation_id=escalation.id,
                conversation_id=escalation.conversation_id,
                status=escalation.status,
                priority=escalation.priority,
                created_at=escalation.created_at,
                updated_at=escalation.updated_at,
                resolved_at=escalation.resolved_at,
            )