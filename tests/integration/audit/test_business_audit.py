# AI-customer-support-agent\tests\integration\audit\test_business_audit.py
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from uuid6 import uuid7

from packages.application.auth.models import (
    AuthenticatedPrincipal,
    AuthRole,
)
from packages.application.tickets.add_ticket_comment import (
    AddTicketComment,
    AddTicketCommentCommand,
)
from packages.application.tickets.create_ticket import (
    CreateTicket,
    CreateTicketCommand,
)
from packages.application.tickets.update_ticket import (
    UpdateTicket,
    UpdateTicketCommand,
)
from packages.database.models.audit.audit_event import (
    AuditEventModel,
)
from packages.database.models.support.conversation import (
    ConversationModel,
)
from packages.database.models.support.ticket import TicketModel
from packages.database.models.support.user import UserModel
from packages.database.repositories.audit.audit_event_repository import (
    AuditEventRepository,
)
from packages.database.unit_of_work.sqlalchemy_uow import (
    SqlAlchemyUnitOfWork,
)


@dataclass(frozen=True, slots=True)
class AuditTestContext:
    customer_id: uuid.UUID
    agent_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_principal: AuthenticatedPrincipal
    agent_principal: AuthenticatedPrincipal


@pytest.fixture()
def audit_context(
    clean_database,
    test_session_factory,
) -> AuditTestContext:
    customer_id = uuid7()
    agent_id = uuid7()
    conversation_id = uuid7()

    with test_session_factory() as session:
        session.add_all(
            [
                UserModel(
                    id=customer_id,
                    external_id="audit-test-customer",
                    role="customer",
                    status="active",
                ),
                UserModel(
                    id=agent_id,
                    external_id="audit-test-agent",
                    role="support_agent",
                    status="active",
                ),
            ]
        )
        session.flush()

        session.add(
            ConversationModel(
                id=conversation_id,
                user_id=customer_id,
            )
        )
        session.commit()

    return AuditTestContext(
        customer_id=customer_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        customer_principal=AuthenticatedPrincipal(user_id=customer_id, session_id=uuid7(), role=AuthRole.CUSTOMER),
        agent_principal=AuthenticatedPrincipal(user_id=agent_id, session_id=uuid7(), role=AuthRole.SUPPORT_AGENT),
    )


@pytest.fixture()
def uow_factory(
    test_session_factory,
) -> Callable[[], SqlAlchemyUnitOfWork]:
    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            session_factory=test_session_factory
        )

    return factory


def _create_ticket(
    *,
    context: AuditTestContext,
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
):
    service = CreateTicket(uow_factory=uow_factory)

    return service.execute(
        CreateTicketCommand(
            conversation_id=context.conversation_id,
            subject="Audit test ticket",
            description=(
                "Verify transactional business auditing."
            ),
            principal=context.customer_principal,
            trace_id=uuid7(),
            category="technical",
            priority="normal",
            metadata={"test": True},
        )
    )


class TestTicketBusinessAudit:
    def test_records_ticket_creation_update_and_comment(
        self,
        audit_context: AuditTestContext,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        test_session_factory,
    ) -> None:
        created = _create_ticket(
            context=audit_context,
            uow_factory=uow_factory,
        )

        with test_session_factory() as session:
            ticket = session.get(
                TicketModel,
                created.ticket_id,
            )

            assert ticket is not None
            initial_row_version = ticket.row_version

        update_service = UpdateTicket(
            uow_factory=uow_factory
        )
        update_service.execute(
            UpdateTicketCommand(
                ticket_id=created.ticket_id,
                expected_row_version=initial_row_version,
                principal=audit_context.agent_principal,
                trace_id=uuid7(),
                priority="high",
            )
        )

        comment_service = AddTicketComment(
            uow_factory=uow_factory
        )
        comment_result = comment_service.execute(
            AddTicketCommentCommand(
                ticket_id=created.ticket_id,
                principal=audit_context.customer_principal,
                trace_id=uuid7(),
                visibility="customer",
                content="Please investigate this issue.",
            )
        )

        with test_session_factory() as session:
            events = tuple(
                session.scalars(
                    select(AuditEventModel)
                    .where(
                        AuditEventModel.entity_type
                        == "ticket",
                        AuditEventModel.entity_id
                        == created.ticket_id,
                    )
                    .order_by(
                        AuditEventModel.occurred_at.asc(),
                        AuditEventModel.id.asc(),
                    )
                )
            )

        assert [
            event.event_type for event in events
        ] == [
            "ticket.created",
            "ticket.updated",
            "ticket.comment_added",
        ]

        creation_event = events[0]
        assert creation_event.actor_type == "customer"
        assert (
            creation_event.actor_id
            == audit_context.customer_id
        )
        assert creation_event.before_state is None
        assert creation_event.after_state["status"] == "open"
        assert (
            creation_event.after_state["priority"]
            == "normal"
        )
        assert creation_event.trace_id is not None

        update_event = events[1]
        assert update_event.before_state["priority"] == "normal"
        assert update_event.after_state["priority"] == "high"
        assert update_event.actor_type == "agent"
        assert update_event.actor_id == audit_context.agent_id
        assert update_event.trace_id is not None

        comment_event = events[2]
        assert (
            comment_event.after_state["comment_id"]
            == str(comment_result.comment_id)
        )
        assert "content" not in comment_event.after_state
        assert (
            comment_event.metadata_["comment_length"]
            == len("Please investigate this issue.")
        )
        assert comment_event.actor_type == "customer"
        assert (
            comment_event.actor_id
            == audit_context.customer_id
        )
        assert comment_event.trace_id is not None

    def test_audit_failure_rolls_back_ticket_creation(
        self,
        audit_context: AuditTestContext,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        test_session_factory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_audit_insert(
            self: AuditEventRepository,
            event: AuditEventModel,
        ) -> None:
            raise RuntimeError(
                "simulated audit persistence failure"
            )

        monkeypatch.setattr(
            AuditEventRepository,
            "add",
            fail_audit_insert,
        )

        service = CreateTicket(
            uow_factory=uow_factory
        )

        with pytest.raises(
            RuntimeError,
            match="simulated audit persistence failure",
        ):
            service.execute(
                CreateTicketCommand(
                    conversation_id=audit_context.conversation_id,
                    subject="Must roll back",
                    description="Ticket must not survive audit failure.",
                    principal=audit_context.customer_principal,
                    trace_id=uuid7(),
                    category="technical",
                    priority="normal",
                )
            )

        with test_session_factory() as session:
            tickets = tuple(
                session.scalars(
                    select(TicketModel).where(
                        TicketModel.conversation_id
                        == audit_context.conversation_id
                    )
                )
            )
            audit_events = tuple(
                session.scalars(
                    select(AuditEventModel)
                )
            )

        assert tickets == ()
        assert audit_events == ()