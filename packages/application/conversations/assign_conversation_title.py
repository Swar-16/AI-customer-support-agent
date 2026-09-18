# AI-customer-support-agent\packages\application\conversations\assign_conversation_title.py
from __future__ import annotations
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from packages.ai.conversation_title.generator import ConversationTitleGenerator
from packages.ai.conversation_title.models import ConversationTitleSource
from packages.ai.providers.base import LLMProvider
from packages.ai.providers.instrumented import InstrumentedLLMProvider, LLMCallContext
from packages.ai.telemetry.llm_call_recorder import LLMCallTelemetryRecorder
from packages.application.audit.models import AuditActor, AuditActorType, RecordAuditEventCommand
from packages.application.audit.recorder import AuditRecorder
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.database.models.support.conversation import ConversationModel
from packages.database.repositories.audit.audit_event_repository import AuditEventRepository
from packages.database.repositories.support.conversation_repository import ConversationRepository
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.ai.conversation_title.prompts import ConversationTitlePromptBuilder

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

class AssignConversationTitleError(RuntimeError):
    """Base error for conversation-title assignment."""

class ConversationTitleAccessDeniedError(AssignConversationTitleError):
    """Raised when the principal does not own the conversation."""

class ConversationTitleConversationNotFoundError(AssignConversationTitleError):
    def __init__(self, conversation_id: uuid.UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation does not exist: {conversation_id}")

class ConversationTitlePersistenceContractError(AssignConversationTitleError):
    """Raised when required persistence components are unavailable."""

class ConversationTitleAssignmentStatus(StrEnum):
    ASSIGNED = "assigned"
    ALREADY_TITLED = "already_titled"
    LOST_RACE = "lost_race"
    DISABLED = "disabled"

@dataclass(frozen=True, slots=True)
class AssignConversationTitleCommand:
    conversation_id: uuid.UUID
    ai_run_id: uuid.UUID
    first_customer_message: str
    principal: AuthenticatedPrincipal
    trace_id: uuid.UUID
    intent: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, uuid.UUID):
            raise TypeError("conversation_id must be a UUID")

        if not isinstance(self.ai_run_id, uuid.UUID):
            raise TypeError("ai_run_id must be a UUID")

        if not isinstance(self.first_customer_message, str):
            raise TypeError("first_customer_message must be a string")

        normalized_message = self.first_customer_message.strip()
        if not normalized_message:
            raise ValueError("first_customer_message cannot be blank")

        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("principal must be an AuthenticatedPrincipal")

        if self.principal.role is not AuthRole.CUSTOMER:
            raise ConversationTitleAccessDeniedError("Only a customer may assign the generated title for a customer conversation")

        if not isinstance(self.trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID")

        if self.intent is not None and not isinstance(self.intent, str):
            raise TypeError("intent must be a string or None")

        normalized_intent = self.intent.strip() if self.intent is not None else None
        object.__setattr__(self, "first_customer_message", normalized_message)
        object.__setattr__(self, "intent", normalized_intent or None)

@dataclass(frozen=True, slots=True)
class AssignConversationTitleResult:
    conversation_id: uuid.UUID
    status: ConversationTitleAssignmentStatus
    title: str | None
    source: ConversationTitleSource | None

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, uuid.UUID):
            raise TypeError("conversation_id must be a UUID")

        if not isinstance(self.status, ConversationTitleAssignmentStatus):
            raise TypeError("status must be a ConversationTitleAssignmentStatus")

        if self.title is not None and not isinstance(self.title, str):
            raise TypeError("title must be a string or None")

        if self.source is not None and not isinstance(self.source, ConversationTitleSource):
            raise TypeError("source must be a ConversationTitleSource or None")

        if self.status is ConversationTitleAssignmentStatus.ASSIGNED and (self.title is None or self.source is None):
            raise ValueError("an assigned title requires title and source")

@dataclass(frozen=True, slots=True)
class _TitleRepositories:
    conversations: ConversationRepository
    audit_events: AuditEventRepository

class AssignConversationTitle:
    """
    Generate and conditionally persist a first-message title.

    Transaction boundaries:

    1. A short read checks ownership and whether a title already exists.
    2. The provider executes with no active Unit of Work.
    3. A short write conditionally sets the title and records its audit event.

    The caller decides whether a title-subsystem error is critical. The StartConversation workflow will deliberately treat
    it as non-critical so accepted messages and customer responses cannot fail because of naming.
    """
    def __init__(self, *, uow_factory: UnitOfWorkFactory, base_provider: LLMProvider, enabled: bool = True, max_input_characters: int = 2_000) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if not isinstance(base_provider, LLMProvider):
            raise TypeError("base_provider must implement LLMProvider")
        
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")

        if isinstance(max_input_characters, bool) or not isinstance(max_input_characters, int):
            raise TypeError("max_input_characters must be an integer")

        if not 128 <= max_input_characters <= 20_000:
            raise ValueError("max_input_characters must be between 128 and 20000")

        self._uow_factory = uow_factory
        self._base_provider = base_provider
        self._enabled = enabled
        self._prompt_builder = ConversationTitlePromptBuilder(max_input_characters=max_input_characters)

    def execute(self, command: AssignConversationTitleCommand) -> AssignConversationTitleResult:
        if not isinstance(command, AssignConversationTitleCommand):
            raise TypeError("command must be an AssignConversationTitleCommand")
        
        if not self._enabled:
            return AssignConversationTitleResult(
                conversation_id=command.conversation_id,
                status=ConversationTitleAssignmentStatus.DISABLED,
                title=None,
                source=None,
            )

        existing_title = self._load_existing_title(conversation_id=command.conversation_id, principal=command.principal)
        if existing_title is not None:
            return AssignConversationTitleResult(
                conversation_id=command.conversation_id,
                status=ConversationTitleAssignmentStatus.ALREADY_TITLED,
                title=existing_title,
                source=None,
            )

        # LLM lifecycle telemetry uses independently committed, short UoWs. No conversation/business transaction remains open here.
        telemetry_recorder = LLMCallTelemetryRecorder(uow_factory=self._uow_factory)
        instrumented_provider = InstrumentedLLMProvider(
            provider=self._base_provider,
            recorder=telemetry_recorder,
            context=LLMCallContext(
                ai_run_id=command.ai_run_id,
                purpose="conversation_title",
                prompt_version_id=None,
                temperature=Decimal("0"),
            ),
        )

        generated = ConversationTitleGenerator(provider=instrumented_provider, prompt_builder=self._prompt_builder).generate(
            customer_message=command.first_customer_message,
            intent=command.intent,
        )

        assigned_at = datetime.now(timezone.utc)

        with self._uow_factory() as uow:
            repositories = self._require_repositories(uow)
            conversation = repositories.conversations.get_by_id(command.conversation_id)
            self._validate_conversation_access(
                conversation=conversation,
                conversation_id=command.conversation_id,
                principal=command.principal,
            )

            assigned = repositories.conversations.set_title_if_absent(
                command.conversation_id,
                title=generated.title,
                updated_at=assigned_at,
            )

            if assigned:
                AuditRecorder(repository=repositories.audit_events).record(
                    RecordAuditEventCommand(
                        event_type="conversation.title_assigned",
                        entity_type="conversation",
                        entity_id=command.conversation_id,
                        action="title_assigned",
                        actor=AuditActor(actor_type=AuditActorType.CUSTOMER, actor_id=command.principal.user_id),
                        trace_id=command.trace_id,
                        conversation_id=command.conversation_id,
                        before_state={"title_present": False,},
                        after_state={
                            "title_present": True,
                            "title_source": generated.source.value,
                        },
                        metadata={
                            "ai_run_id": str(command.ai_run_id),
                            "generated_title_length": len(generated.title),
                        },
                        occurred_at=assigned_at,
                    )
                )

                uow.commit()

                return AssignConversationTitleResult(
                    conversation_id=command.conversation_id,
                    status=ConversationTitleAssignmentStatus.ASSIGNED,
                    title=generated.title,
                    source=generated.source,
                )

            # Another request or explicit-title operation won the race.
            refreshed = repositories.conversations.get_by_id(command.conversation_id)
            self._validate_conversation_access(
                conversation=refreshed,
                conversation_id=command.conversation_id,
                principal=command.principal,
            )
            winning_title = refreshed.title
            uow.commit()

            return AssignConversationTitleResult(
                conversation_id=command.conversation_id,
                status=ConversationTitleAssignmentStatus.LOST_RACE,
                title=winning_title,
                source=None,
            )

    def _load_existing_title(self, *, conversation_id: uuid.UUID, principal: AuthenticatedPrincipal) -> str | None:
        with self._uow_factory() as uow:
            repositories = self._require_repositories(uow)
            conversation = repositories.conversations.get_by_id(conversation_id)
            self._validate_conversation_access(
                conversation=conversation,
                conversation_id=conversation_id,
                principal=principal,
            )

            # Reading does not require an explicit commit.
            return conversation.title

    @staticmethod
    def _validate_conversation_access(*, conversation: ConversationModel | None, conversation_id: uuid.UUID, principal: AuthenticatedPrincipal) -> None:
        if conversation is None:
            raise ConversationTitleConversationNotFoundError(conversation_id)

        if conversation.user_id != principal.user_id:
            raise ConversationTitleAccessDeniedError("The authenticated customer does not own this conversation")

    @staticmethod
    def _require_repositories(uow: SqlAlchemyUnitOfWork) -> _TitleRepositories:
        if uow.session is None:
            raise ConversationTitlePersistenceContractError("Active SQLAlchemy Session unavailable")

        if uow.conversations is None:
            raise ConversationTitlePersistenceContractError("ConversationRepository unavailable")

        if uow.audit_events is None:
            raise ConversationTitlePersistenceContractError("AuditEventRepository unavailable")

        return _TitleRepositories(conversations=uow.conversations, audit_events=uow.audit_events)