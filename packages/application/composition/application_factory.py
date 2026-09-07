# AI-customer-support-agent\packages\application\composition\application_factory.py
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from sqlalchemy.orm import Session, sessionmaker

from packages.ai.orchestration.orchestrator import OrchestrationObserver
from packages.ai.providers.base import LLMProvider
from packages.ai.telemetry.observer import TelemetryOrchestrationObserver
from packages.application.composition.ai_pipeline_factory import AIPipelineFactory
from packages.application.composition.provider_factory import create_llm_provider
from packages.application.conversations.process_customer_message import ProcessCustomerMessage
from packages.config.settings import Settings
from packages.database.session import SessionLocal
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork
from packages.application.composition.knowledge_embedding_factory import create_knowledge_embedding_services
from packages.knowledge.retrieval.context.models import GroundingContextBudget
from packages.knowledge.retrieval.profiles import create_default_customer_support_profile
from packages.knowledge.embeddings.input.contextual import ContextualEmbeddingInputBuilder
from packages.application.escalations.query_escalations import GetEscalation, ListConversationEscalations, ListEscalations
from packages.application.escalations.update_escalation import UpdateEscalation
from packages.application.tickets.add_ticket_comment import AddTicketComment
from packages.application.tickets.create_ticket import CreateTicket
from packages.application.tickets.query_tickets import GetTicket, ListTickets
from packages.application.tickets.update_ticket import UpdateTicket

SessionFactory = sessionmaker[Session]
ProviderFactory = Callable[..., LLMProvider]

@dataclass(frozen=True, slots=True)
class ApplicationServices:
    """
    Long-lived application service container.

    This object contains reusable application dependencies that are safe to keep for the lifetime of the process.

    It deliberately does NOT contain:
    - active SQLAlchemy sessions
    - UnitOfWork instances
    - request-specific AI runs
    - request-specific telemetry recorders
    - request-specific InstrumentedLLMProvider instances

    Those are created per request / per application transaction.
    """
    process_customer_message: ProcessCustomerMessage
    get_escalation: GetEscalation
    list_escalations: ListEscalations
    list_conversation_escalations: ListConversationEscalations
    update_escalation: UpdateEscalation
    create_ticket: CreateTicket
    add_ticket_comment: AddTicketComment
    get_ticket: GetTicket
    list_tickets: ListTickets
    update_ticket: UpdateTicket
    ai_pipeline_factory: AIPipelineFactory
    base_llm_provider: LLMProvider
    orchestration_observer: OrchestrationObserver

class ApplicationConfigurationError(RuntimeError):
    """
    Raised when the application cannot be composed from the supplied configuration.

    This represents a startup/configuration failure rather than a normal request failure.
    """

def create_application(*, settings: Settings, session_factory: SessionFactory = SessionLocal,
                       base_provider: LLMProvider | None = None, observer: OrchestrationObserver | None = None,
) -> ApplicationServices:
    """
    Compose the application's long-lived dependencies.

    Typical production usage:

        services = create_application(
            settings=get_settings("development")
        )

    Typical test usage:

        services = create_application(
            settings=test_settings,
            session_factory=test_session_factory,
            base_provider=mock_provider,
        )

    Design principles:
    - configuration is validated once at startup
    - provider creation happens once
    - database Sessions are NOT opened here
    - UnitOfWork instances are created per operation
    - AI instrumentation remains request-scoped
    """
    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")

    if session_factory is None:
        raise TypeError("session_factory cannot be None")

    resolved_provider = _resolve_provider(settings=settings, base_provider=base_provider)
    resolved_observer = _resolve_observer(observer=observer)
    pipeline_factory = AIPipelineFactory(base_provider=resolved_provider, observer=resolved_observer)
    embedding_services = create_knowledge_embedding_services(settings)
    retrieval_profile = create_default_customer_support_profile()
    embedding_input_builder = ContextualEmbeddingInputBuilder()
    grounding_budget = GroundingContextBudget(
        max_tokens=settings.rag_context_max_tokens,
        max_blocks=settings.rag_context_max_blocks,
    )

    def uow_factory() -> SqlAlchemyUnitOfWork:
        """
        Create a fresh UnitOfWork for each application transaction.

        No Session is opened until the UoW context manager is entered.
        """
        return SqlAlchemyUnitOfWork(session_factory=session_factory)

    process_customer_message = ProcessCustomerMessage(
        uow_factory=uow_factory,
        pipeline_factory=pipeline_factory,
        embedding_provider=embedding_services.provider,
        embedding_input_descriptor=embedding_input_builder.descriptor,
        retrieval_profile=retrieval_profile,
        grounding_context_budget=grounding_budget,
    )
    
    get_escalation = GetEscalation(uow_factory=uow_factory)
    list_escalations = ListEscalations(uow_factory=uow_factory)
    list_conversation_escalations = ListConversationEscalations(uow_factory=uow_factory)
    update_escalation = UpdateEscalation(uow_factory=uow_factory)
    create_ticket = CreateTicket(uow_factory=uow_factory)
    add_ticket_comment = AddTicketComment(uow_factory=uow_factory)
    get_ticket = GetTicket(uow_factory=uow_factory)
    list_tickets = ListTickets(uow_factory=uow_factory)
    update_ticket = UpdateTicket(uow_factory=uow_factory)

    return ApplicationServices(
        process_customer_message=process_customer_message,
        get_escalation=get_escalation,
        list_escalations=list_escalations,
        list_conversation_escalations=list_conversation_escalations,
        update_escalation=update_escalation,
        create_ticket=create_ticket,
        add_ticket_comment=add_ticket_comment,
        get_ticket=get_ticket,
        list_tickets=list_tickets,
        update_ticket=update_ticket,
        ai_pipeline_factory=pipeline_factory,
        base_llm_provider=resolved_provider,
        orchestration_observer=resolved_observer,
    )

def _resolve_provider(*, settings: Settings, base_provider: LLMProvider | None) -> LLMProvider:
    """
    Resolve the application's base LLM provider.

    Explicit dependency injection wins over configuration-based creation.

    This is useful for:
    - unit tests
    - integration tests
    - local experiments
    - provider failover experiments
    """

    if base_provider is not None:
        if not isinstance(base_provider, LLMProvider):
            raise TypeError("base_provider must implement LLMProvider")

        return base_provider

    try:
        return create_llm_provider(settings=settings)

    except Exception as exc:
        raise ApplicationConfigurationError("Failed to configure LLM provider") from exc

def _resolve_observer(*, observer: OrchestrationObserver | None) -> OrchestrationObserver:
    """
    Resolve orchestration observability.

    A caller may inject a custom observer for tests or an alternate
    OpenTelemetry/metrics implementation.

    Otherwise the production-safe telemetry observer is used.
    """
    if observer is not None:
        if not isinstance(observer, OrchestrationObserver):
            raise TypeError("observer must implement OrchestrationObserver")

        return observer

    return TelemetryOrchestrationObserver()