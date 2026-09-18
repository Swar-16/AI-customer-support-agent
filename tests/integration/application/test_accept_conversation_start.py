# AI-customer-support-agent\tests\integration\application\test_accept_conversation_start.py
from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker
from uuid6 import uuid7

from packages.application.auth.models import (
    AuthenticatedPrincipal,
    AuthRole,
)
from packages.application.conversations.accept_conversation_start import (
    AcceptConversationStart,
    AcceptConversationStartCommand,
)
from packages.application.conversations.start_conversation_errors import (
    ConversationStartIdempotencyConflictError,
)
from packages.database.models.audit.audit_event import (
    AuditEventModel,
)
from packages.database.models.support.conversation import (
    ConversationModel,
)
from packages.database.models.support.conversation_start_request import (
    ConversationStartRequestModel,
)
from packages.database.models.support.message import MessageModel
from packages.database.models.support.user import UserModel
from packages.database.unit_of_work.sqlalchemy_uow import (
    SqlAlchemyUnitOfWork,
)


@pytest.fixture
def customers(
    test_session_factory: sessionmaker[Session],
) -> Generator[tuple[UserModel, UserModel], None, None]:
    with test_session_factory() as session:
        first = UserModel(
            external_id=f"start-test-{uuid7()}",
            email=None,
            display_name="First Start Test Customer",
            role="customer",
            status="active",
        )
        second = UserModel(
            external_id=f"start-test-{uuid7()}",
            email=None,
            display_name="Second Start Test Customer",
            role="customer",
            status="active",
        )

        session.add_all([first, second])
        session.commit()

        first_id = first.id
        second_id = second.id

    yield first, second

    with test_session_factory() as session:
        conversation_ids = tuple(
            session.scalars(
                select(ConversationModel.id).where(
                    ConversationModel.user_id.in_(
                        (first_id, second_id)
                    )
                )
            )
        )

        if conversation_ids:
            session.execute(
                delete(AuditEventModel).where(
                    AuditEventModel.conversation_id.in_(
                        conversation_ids
                    )
                )
            )

            session.execute(
                delete(
                    ConversationStartRequestModel
                ).where(
                    ConversationStartRequestModel.conversation_id.in_(
                        conversation_ids
                    )
                )
            )

            session.execute(
                delete(MessageModel).where(
                    MessageModel.conversation_id.in_(
                        conversation_ids
                    )
                )
            )

            session.execute(
                delete(ConversationModel).where(
                    ConversationModel.id.in_(
                        conversation_ids
                    )
                )
            )

        session.execute(
            delete(UserModel).where(
                UserModel.id.in_(
                    (first_id, second_id)
                )
            )
        )

        session.commit()


@pytest.fixture
def service(
    test_session_factory: sessionmaker[Session],
) -> AcceptConversationStart:
    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            session_factory=test_session_factory
        )

    return AcceptConversationStart(
        uow_factory=uow_factory
    )


def _principal(
    customer: UserModel,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=customer.id,
        session_id=uuid7(),
        role=AuthRole.CUSTOMER,
    )


def _command(
    customer: UserModel,
    *,
    idempotency_key: str,
    message: str = "What is your return policy?",
) -> AcceptConversationStartCommand:
    return AcceptConversationStartCommand(
        principal=_principal(customer),
        idempotency_key=idempotency_key,
        customer_message=message,
        trace_id=uuid7(),
        channel="web",
        title=None,
    )


def test_atomically_creates_conversation_first_message_and_request(
    service: AcceptConversationStart,
    test_session_factory: sessionmaker[Session],
    customers: tuple[UserModel, UserModel],
) -> None:
    customer, _ = customers

    result = service.execute(
        _command(
            customer,
            idempotency_key=str(uuid7()),
        )
    )

    assert result.created is True
    assert result.status == "accepted"

    with test_session_factory() as session:
        conversation = session.get(
            ConversationModel,
            result.conversation_id,
        )
        message = session.get(
            MessageModel,
            result.customer_message_id,
        )
        start_request = session.get(
            ConversationStartRequestModel,
            result.request_id,
        )

    assert conversation is not None
    assert conversation.user_id == customer.id
    assert conversation.status == "open"
    assert conversation.next_message_sequence == 2

    assert message is not None
    assert message.conversation_id == conversation.id
    assert message.role == "customer"
    assert message.sequence_number == 1
    assert message.content == "What is your return policy?"

    assert start_request is not None
    assert start_request.customer_id == customer.id
    assert start_request.conversation_id == conversation.id
    assert start_request.customer_message_id == message.id
    assert start_request.status == "accepted"
    assert start_request.attempt_count == 0

    # Raw idempotency keys must never be persisted.
    assert start_request.idempotency_key_hash != (
        str(result.request_id)
    )
    assert len(start_request.idempotency_key_hash) == 64


def test_identical_retry_replays_existing_acceptance(
    service: AcceptConversationStart,
    test_session_factory: sessionmaker[Session],
    customers: tuple[UserModel, UserModel],
) -> None:
    customer, _ = customers
    key = str(uuid7())

    first = service.execute(
        _command(
            customer,
            idempotency_key=key,
        )
    )
    second = service.execute(
        _command(
            customer,
            idempotency_key=key,
        )
    )

    assert first.created is True
    assert second.created is False

    assert second.request_id == first.request_id
    assert (
        second.conversation_id
        == first.conversation_id
    )
    assert (
        second.customer_message_id
        == first.customer_message_id
    )

    with test_session_factory() as session:
        conversation_count = session.scalar(
            select(func.count(ConversationModel.id))
            .where(
                ConversationModel.user_id
                == customer.id
            )
        )
        message_count = session.scalar(
            select(func.count(MessageModel.id))
            .where(
                MessageModel.conversation_id
                == first.conversation_id
            )
        )
        request_count = session.scalar(
            select(
                func.count(
                    ConversationStartRequestModel.id
                )
            )
            .where(
                ConversationStartRequestModel.customer_id
                == customer.id
            )
        )

    assert conversation_count == 1
    assert message_count == 1
    assert request_count == 1


def test_same_key_with_different_input_is_rejected(
    service: AcceptConversationStart,
    test_session_factory: sessionmaker[Session],
    customers: tuple[UserModel, UserModel],
) -> None:
    customer, _ = customers
    key = str(uuid7())

    original = service.execute(
        _command(
            customer,
            idempotency_key=key,
            message="What is your return policy?",
        )
    )

    with pytest.raises(
        ConversationStartIdempotencyConflictError
    ):
        service.execute(
            _command(
                customer,
                idempotency_key=key,
                message="How can I reset my password?",
            )
        )

    with test_session_factory() as session:
        messages = tuple(
            session.scalars(
                select(MessageModel).where(
                    MessageModel.conversation_id
                    == original.conversation_id
                )
            )
        )

    assert len(messages) == 1
    assert messages[0].content == (
        "What is your return policy?"
    )


def test_idempotency_key_is_scoped_to_customer(
    service: AcceptConversationStart,
    customers: tuple[UserModel, UserModel],
) -> None:
    first_customer, second_customer = customers
    shared_key = str(uuid7())

    first = service.execute(
        _command(
            first_customer,
            idempotency_key=shared_key,
        )
    )
    second = service.execute(
        _command(
            second_customer,
            idempotency_key=shared_key,
        )
    )

    assert first.created is True
    assert second.created is True

    assert first.request_id != second.request_id
    assert (
        first.conversation_id
        != second.conversation_id
    )
    assert (
        first.customer_message_id
        != second.customer_message_id
    )