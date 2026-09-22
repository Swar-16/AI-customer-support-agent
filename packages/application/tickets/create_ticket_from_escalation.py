# AI-customer-support-agent\packages\application\tickets\create_ticket_from_escalation.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.application.tickets.create_ticket import CreateTicket, CreateTicketCommand, CreateTicketResult, TicketConversationDoesNotExistError
from packages.application.tickets.create_ticket import TicketCreationAccessDeniedError, TicketEscalationDoesNotExistError, TicketPersistenceContractError
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.application.conversations.conversation_notification import AppendConversationNotificationCommand, ConversationNotificationWriter

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

@dataclass(frozen=True, slots=True)
class CreateTicketFromEscalationCommand:
    escalation_id: uuid.UUID
    subject: str
    description: str
    category: str
    priority: str
    principal: AuthenticatedPrincipal
    trace_id: uuid.UUID

    def __post_init__(self) -> None:
        if not isinstance(self.escalation_id, uuid.UUID):
            raise TypeError("escalation_id must be a UUID")

        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID")

class CreateTicketFromEscalation:
    """
    Convert an active escalation into one durable support ticket.

    The escalation and conversation are loaded inside the same transaction. Repeated submissions reuse the ticket already linked to the escalation.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, create_ticket: CreateTicket, notification_writer: ConversationNotificationWriter) -> None:
        if uow_factory is None or not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if not isinstance(create_ticket, CreateTicket):
            raise TypeError("create_ticket must be a CreateTicket service")

        if not isinstance(notification_writer, ConversationNotificationWriter):
            raise TypeError("notification_writer must be a ConversationNotificationWriter")

        self._uow_factory = uow_factory
        self._create_ticket = create_ticket
        self._notification_writer = notification_writer

    def execute(self, command: CreateTicketFromEscalationCommand) -> CreateTicketResult:
        if not isinstance(command, CreateTicketFromEscalationCommand):
            raise TypeError("command must be a CreateTicketFromEscalationCommand")

        if command.principal.role not in {AuthRole.SUPPORT_AGENT, AuthRole.ADMIN}:
            raise TicketCreationAccessDeniedError("Only support agents and administrators may convert escalations")

        with self._uow_factory() as uow:
            if uow.escalations is None:
                raise TicketPersistenceContractError("EscalationRepository unavailable")

            if uow.conversations is None:
                raise TicketPersistenceContractError("ConversationRepository unavailable")

            escalation = uow.escalations.get_by_id(command.escalation_id)
            if escalation is None:
                raise TicketEscalationDoesNotExistError(command.escalation_id)

            conversation = uow.conversations.get_by_id(escalation.conversation_id)
            if conversation is None:
                raise TicketConversationDoesNotExistError(escalation.conversation_id)

            result = self._create_ticket.execute_in_uow(
                command=CreateTicketCommand(
                    conversation_id=escalation.conversation_id,
                    customer_id=conversation.user_id,
                    source="escalation",
                    source_message_id=escalation.trigger_message_id,
                    escalation_id=command.escalation_id,
                    subject=command.subject,
                    description=command.description,
                    category=command.category,
                    priority=command.priority,
                    principal=command.principal,
                    trace_id=command.trace_id,
                    metadata={
                        "created_from": "escalation_review",
                    },
                ),
                uow=uow,
            )

            if result.created:
                self._notification_writer.execute_in_uow(
                    command=AppendConversationNotificationCommand(
                        conversation_id=result.conversation_id,
                        notification_kind="ticket_created",
                        content=(
                            f"A support ticket {result.ticket_reference} has been created from your escalation. The support team can "
                            "now track your case. You can view the ticket for updates and customer-visible comments."
                        ),
                        metadata={
                            "ticket_id": str(result.ticket_id),
                            "ticket_reference": result.ticket_reference,
                            "escalation_id": str(command.escalation_id),
                            "ticket_status": result.status,
                        },
                    ),
                    uow=uow,
                )

            uow.commit()
            return result