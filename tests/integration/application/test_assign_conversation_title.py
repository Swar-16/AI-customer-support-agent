# AI-customer-support-agent\tests\integration\application\test_assign_conversation_title.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker
from uuid6 import uuid7

from packages.ai.conversation_title.models import (
    ConversationTitleOutput,
    ConversationTitleSource,
)
from packages.ai.providers.mock import MockLLMProvider
from packages.application.auth.models import (
    AuthenticatedPrincipal,
    AuthRole,
)
from packages.application.conversations.assign_conversation_title import (
    AssignConversationTitle,
    AssignConversationTitleCommand,
    ConversationTitleAccessDeniedError,
    ConversationTitleAssignmentStatus,
    ConversationTitleConversationNotFoundError,
)
from packages.database.models.ai.llm_call import (
    LLMCallModel,
)
from packages.database.models.ai.run import AIRunModel
from packages.database.models.audit.audit_event import (
    AuditEventModel,
)
from packages.database.models.support.conversation import (
    ConversationModel,
)
from packages.database.models.support.message import MessageModel
from packages.database.models.support.user import UserModel
from packages.database.unit_of_work.sqlalchemy_uow import (
    SqlAlchemyUnitOfWork,
)


@dataclass(frozen=True, slots=True)
class TitleTestContext:
    customer_id: uuid.UUID
    other_customer_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_message_id: uuid.UUID
    ai_run_id: uuid.UUID
    trace_id: uuid.UUID
    customer_message: str


@pytest.fixture
def title_context(
    clean_database,
    test_session_factory: sessionmaker[Session],
) -> TitleTestContext:
    customer_id = uuid7()
    other_customer_id = uuid7()
    conversation_id = uuid7()
    customer_message_id = uuid7()
    ai_run_id = uuid7()
    trace_id = uuid7()

    customer_message = "What is your return policy?"
    completed_at = datetime.now(timezone.utc)

    with test_session_factory() as session:
        session.add_all(
            [
                UserModel(
                    id=customer_id,
                    external_id=f"title-customer-{uuid7()}",
                    email=None,
                    display_name="Title Test Customer",
                    role="customer",
                    status="active",
                ),
                UserModel(
                    id=other_customer_id,
                    external_id=(
                        f"title-other-customer-{uuid7()}"
                    ),
                    email=None,
                    display_name="Other Title Customer",
                    role="customer",
                    status="active",
                ),
            ]
        )

        session.flush()

        session.add(
            ConversationModel(
                id=conversation_id,
                user_id=customer_id,
                status="open",
                channel="web",
                title=None,
                next_message_sequence=2,
            )
        )

        session.flush()

        session.add(
            MessageModel(
                id=customer_message_id,
                conversation_id=conversation_id,
                role="customer",
                content=customer_message,
                sequence_number=1,
                metadata_={},
            )
        )

        session.flush()

        session.add(
            AIRunModel(
                id=ai_run_id,
                trace_id=trace_id,
                conversation_id=conversation_id,
                trigger_message_id=customer_message_id,
                response_message_id=None,
                parent_run_id=None,
                pipeline_version="title-test-v1",
                status="completed",
                completed_at=completed_at,
                total_latency_ms=10,
                error_code=None,
                error_message=None,
            )
        )

        session.commit()

    return TitleTestContext(
        customer_id=customer_id,
        other_customer_id=other_customer_id,
        conversation_id=conversation_id,
        customer_message_id=customer_message_id,
        ai_run_id=ai_run_id,
        trace_id=trace_id,
        customer_message=customer_message,
    )


def _principal(
    customer_id: uuid.UUID,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=customer_id,
        session_id=uuid7(),
        role=AuthRole.CUSTOMER,
    )


def _command(
    context: TitleTestContext,
    *,
    customer_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    message: str | None = None,
    intent: str | None = "return_exchange",
) -> AssignConversationTitleCommand:
    return AssignConversationTitleCommand(
        conversation_id=(
            conversation_id
            if conversation_id is not None
            else context.conversation_id
        ),
        ai_run_id=context.ai_run_id,
        first_customer_message=(
            message
            if message is not None
            else context.customer_message
        ),
        principal=_principal(
            customer_id
            if customer_id is not None
            else context.customer_id
        ),
        trace_id=context.trace_id,
        intent=intent,
    )


def _provider_returning(
    title: str,
) -> MockLLMProvider:
    def structured_resolver(
        system_prompt: str,
        user_prompt: str,
        response_model,
    ):
        assert response_model is ConversationTitleOutput

        return {
            "title": title,
        }

    return MockLLMProvider(
        structured_resolver=structured_resolver,
    )


def _uow_factory(
    test_session_factory: sessionmaker[Session],
):
    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            session_factory=test_session_factory
        )

    return factory


class TestAssignConversationTitle:
    def test_persists_provider_title_audit_and_telemetry(
        self,
        title_context: TitleTestContext,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        provider = _provider_returning(
            "Return policy question"
        )

        service = AssignConversationTitle(
            uow_factory=_uow_factory(
                test_session_factory
            ),
            base_provider=provider,
        )

        result = service.execute(
            _command(title_context)
        )

        assert result.status is (
            ConversationTitleAssignmentStatus.ASSIGNED
        )
        assert result.title == "Return policy question"
        assert result.source is (
            ConversationTitleSource.PROVIDER
        )
        assert provider.call_count == 1

        with test_session_factory() as session:
            conversation = session.get(
                ConversationModel,
                title_context.conversation_id,
            )

            llm_calls = tuple(
                session.scalars(
                    select(LLMCallModel).where(
                        LLMCallModel.ai_run_id
                        == title_context.ai_run_id,
                        LLMCallModel.purpose
                        == "conversation_title",
                    )
                )
            )

            audit_events = tuple(
                session.scalars(
                    select(AuditEventModel).where(
                        AuditEventModel.entity_type
                        == "conversation",
                        AuditEventModel.entity_id
                        == title_context.conversation_id,
                        AuditEventModel.event_type
                        == "conversation.title_assigned",
                    )
                )
            )

        assert conversation is not None
        assert conversation.title == (
            "Return policy question"
        )

        assert len(llm_calls) == 1
        assert llm_calls[0].status == "success"
        assert llm_calls[0].purpose == (
            "conversation_title"
        )

        assert len(audit_events) == 1
        event = audit_events[0]

        assert event.action == "title_assigned"
        assert event.before_state == {
            "title_present": False,
        }
        assert event.after_state == {
            "title_present": True,
            "title_source": "provider",
        }
        assert event.metadata_["ai_run_id"] == str(
            title_context.ai_run_id
        )
        assert event.metadata_[
            "generated_title_length"
        ] == len("Return policy question")

        serialized_audit = str(
            {
                "before": event.before_state,
                "after": event.after_state,
                "metadata": event.metadata_,
            }
        )

        assert (
            title_context.customer_message
            not in serialized_audit
        )

    def test_provider_failure_persists_safe_fallback(
        self,
        title_context: TitleTestContext,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        provider = _provider_returning(
            "Unused provider title"
        )
        provider.queue_failure()

        service = AssignConversationTitle(
            uow_factory=_uow_factory(
                test_session_factory
            ),
            base_provider=provider,
        )

        result = service.execute(
            _command(title_context)
        )

        assert result.status is (
            ConversationTitleAssignmentStatus.ASSIGNED
        )
        assert result.title == (
            "Return and exchange help"
        )
        assert result.source is (
            ConversationTitleSource.FALLBACK
        )

        with test_session_factory() as session:
            conversation = session.get(
                ConversationModel,
                title_context.conversation_id,
            )

            llm_call = session.scalar(
                select(LLMCallModel).where(
                    LLMCallModel.ai_run_id
                    == title_context.ai_run_id,
                    LLMCallModel.purpose
                    == "conversation_title",
                )
            )

        assert conversation is not None
        assert conversation.title == (
            "Return and exchange help"
        )

        assert llm_call is not None
        assert llm_call.status == "failed"

        # The normalized telemetry error must not contain customer text.
        assert title_context.customer_message not in (
            llm_call.error_message or ""
        )

    def test_existing_explicit_title_skips_provider(
        self,
        title_context: TitleTestContext,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        with test_session_factory() as session:
            session.execute(
                update(ConversationModel)
                .where(
                    ConversationModel.id
                    == title_context.conversation_id
                )
                .values(title="Customer supplied title")
            )
            session.commit()

        provider = _provider_returning(
            "Generated title must not be used"
        )

        service = AssignConversationTitle(
            uow_factory=_uow_factory(
                test_session_factory
            ),
            base_provider=provider,
        )

        result = service.execute(
            _command(title_context)
        )

        assert result.status is (
            ConversationTitleAssignmentStatus
            .ALREADY_TITLED
        )
        assert result.title == "Customer supplied title"
        assert result.source is None
        assert provider.call_count == 0

        with test_session_factory() as session:
            title_calls = tuple(
                session.scalars(
                    select(LLMCallModel).where(
                        LLMCallModel.ai_run_id
                        == title_context.ai_run_id,
                        LLMCallModel.purpose
                        == "conversation_title",
                    )
                )
            )

        assert title_calls == ()

    def test_rejects_another_customer_before_provider_call(
        self,
        title_context: TitleTestContext,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        provider = _provider_returning(
            "Should not be generated"
        )

        service = AssignConversationTitle(
            uow_factory=_uow_factory(
                test_session_factory
            ),
            base_provider=provider,
        )

        with pytest.raises(
            ConversationTitleAccessDeniedError
        ):
            service.execute(
                _command(
                    title_context,
                    customer_id=(
                        title_context.other_customer_id
                    ),
                )
            )

        assert provider.call_count == 0

    def test_rejects_missing_conversation_before_provider_call(
        self,
        title_context: TitleTestContext,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        provider = _provider_returning(
            "Should not be generated"
        )

        service = AssignConversationTitle(
            uow_factory=_uow_factory(
                test_session_factory
            ),
            base_provider=provider,
        )

        with pytest.raises(
            ConversationTitleConversationNotFoundError
        ):
            service.execute(
                _command(
                    title_context,
                    conversation_id=uuid7(),
                )
            )

        assert provider.call_count == 0

    def test_late_generation_does_not_overwrite_new_title(
        self,
        title_context: TitleTestContext,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        def racing_resolver(
            system_prompt: str,
            user_prompt: str,
            response_model,
        ):
            # Simulate another operation assigning a title while the external
            # provider request is in progress. No title-service UoW should be
            # open at this point.
            with test_session_factory() as session:
                session.execute(
                    update(ConversationModel)
                    .where(
                        ConversationModel.id
                        == title_context.conversation_id
                    )
                    .values(
                        title="Concurrent explicit title"
                    )
                )
                session.commit()

            return {
                "title": "Late generated title",
            }

        provider = MockLLMProvider(
            structured_resolver=racing_resolver,
        )

        service = AssignConversationTitle(
            uow_factory=_uow_factory(
                test_session_factory
            ),
            base_provider=provider,
        )

        result = service.execute(
            _command(title_context)
        )

        assert result.status is (
            ConversationTitleAssignmentStatus.LOST_RACE
        )
        assert result.title == "Concurrent explicit title"
        assert result.source is None

        with test_session_factory() as session:
            conversation = session.get(
                ConversationModel,
                title_context.conversation_id,
            )

            title_audit_events = tuple(
                session.scalars(
                    select(AuditEventModel).where(
                        AuditEventModel.entity_id
                        == title_context.conversation_id,
                        AuditEventModel.event_type
                        == "conversation.title_assigned",
                    )
                )
            )

        assert conversation is not None
        assert conversation.title == (
            "Concurrent explicit title"
        )

        # This service lost the compare-and-set race, so it must not claim
        # that it assigned the winning title.
        assert title_audit_events == ()

    def test_disabled_service_performs_no_io(
        self,
        title_context: TitleTestContext,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        provider = _provider_returning(
            "Should not be generated"
        )

        service = AssignConversationTitle(
            uow_factory=_uow_factory(
                test_session_factory
            ),
            base_provider=provider,
            enabled=False,
        )

        result = service.execute(
            _command(title_context)
        )

        assert result.status is (
            ConversationTitleAssignmentStatus.DISABLED
        )
        assert result.title is None
        assert result.source is None
        assert provider.call_count == 0

        with test_session_factory() as session:
            conversation = session.get(
                ConversationModel,
                title_context.conversation_id,
            )

            title_calls = tuple(
                session.scalars(
                    select(LLMCallModel).where(
                        LLMCallModel.ai_run_id
                        == title_context.ai_run_id,
                        LLMCallModel.purpose
                        == "conversation_title",
                    )
                )
            )

        assert conversation is not None
        assert conversation.title is None
        assert title_calls == ()

class _UoWTracker:
    def __init__(self) -> None:
        self.active_count = 0
        self.maximum_active_count = 0


class _TrackingUnitOfWork:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        tracker: _UoWTracker,
    ) -> None:
        self._inner = SqlAlchemyUnitOfWork(
            session_factory=session_factory
        )
        self._tracker = tracker
        self._entered = False

    def __enter__(self):
        entered = self._inner.__enter__()

        self._tracker.active_count += 1
        self._tracker.maximum_active_count = max(
            self._tracker.maximum_active_count,
            self._tracker.active_count,
        )
        self._entered = True

        return entered

    def __exit__(
        self,
        exception_type,
        exception,
        traceback,
    ):
        try:
            return self._inner.__exit__(
                exception_type,
                exception,
                traceback,
            )
        finally:
            if self._entered:
                self._tracker.active_count -= 1
                self._entered = False


def test_provider_executes_without_active_database_uow(
    title_context: TitleTestContext,
    test_session_factory: sessionmaker[Session],
) -> None:
    tracker = _UoWTracker()

    def tracked_uow_factory():
        return _TrackingUnitOfWork(
            session_factory=test_session_factory,
            tracker=tracker,
        )

    def structured_resolver(
        system_prompt: str,
        user_prompt: str,
        response_model,
    ):
        assert tracker.active_count == 0, (
            "Conversation-title provider executed while "
            "a database Unit of Work was active."
        )

        return {
            "title": "Return policy question",
        }

    provider = MockLLMProvider(
        structured_resolver=structured_resolver,
    )

    service = AssignConversationTitle(
        uow_factory=tracked_uow_factory,
        base_provider=provider,
    )

    result = service.execute(
        _command(title_context)
    )

    assert result.status is (
        ConversationTitleAssignmentStatus.ASSIGNED
    )
    assert provider.call_count == 1
    assert tracker.maximum_active_count >= 1
    assert tracker.active_count == 0