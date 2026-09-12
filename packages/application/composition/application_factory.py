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
from packages.application.conversations.create_conversation import CreateConversation
from packages.application.conversations.query_conversations import ListConversations, GetConversation
from packages.application.conversations.get_conversation_messages import GetConversationMessages
from packages.application.conversations.close_conversation import CloseConversation
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
from packages.application.feedback.query_feedback import GetFeedback, ListFeedback
from packages.application.feedback.review_feedback import ReviewFeedback
from packages.application.feedback.submit_feedback import SubmitFeedback
from packages.application.observability.record_api_request import RecordAPIRequest
from packages.application.audit.query_audit_events import GetAuditEvent, GetEntityAuditHistory, GetTraceAuditEvents, ListAuditEvents
from packages.application.dashboard.get_overview import GetDashboardOverview
from packages.application.dashboard.query_traces import QueryDashboardTraces
from packages.application.dashboard.get_trace_detail import GetTraceDetail
from packages.application.dashboard.query_llm_calls import QueryDashboardLLMCalls
from packages.application.dashboard.query_retrieval_runs import QueryDashboardRetrievalRuns
from packages.application.dashboard.query_api_requests import QueryDashboardAPIRequests
from packages.application.dashboard.query_audit_events import QueryDashboardAuditEvents
from packages.application.auth.authenticate_access_token import AuthenticateAccessToken
from packages.application.auth.get_current_user import GetCurrentUser
from packages.application.auth.login_user import LoginUser
from packages.application.auth.logout_user import LogoutUser
from packages.application.auth.password_hasher import Argon2PasswordHasher
from packages.application.auth.refresh_session import RefreshSession
from packages.application.auth.register_user import RegisterUser
from packages.application.auth.token_service import TokenService, TokenServiceConfig
from packages.application.escalations.get_customer_escalation_status import GetCustomerEscalationStatus

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
    create_conversation: CreateConversation
    list_conversations: ListConversations
    get_conversation: GetConversation
    get_conversation_messages: GetConversationMessages
    process_customer_message: ProcessCustomerMessage
    close_conversation: CloseConversation
    record_api_request: RecordAPIRequest
    
    register_user: RegisterUser
    login_user: LoginUser
    refresh_session: RefreshSession
    logout_user: LogoutUser
    authenticate_access_token: AuthenticateAccessToken
    get_current_user: GetCurrentUser
    
    get_dashboard_overview: GetDashboardOverview
    query_dashboard_traces: QueryDashboardTraces
    get_dashboard_trace_detail: GetTraceDetail
    query_dashboard_llm_calls: QueryDashboardLLMCalls
    query_dashboard_retrieval_runs: QueryDashboardRetrievalRuns
    query_dashboard_api_requests: QueryDashboardAPIRequests
    query_dashboard_audit_events: QueryDashboardAuditEvents
    
    get_audit_event: GetAuditEvent
    list_audit_events: ListAuditEvents
    get_entity_audit_history: GetEntityAuditHistory
    get_trace_audit_events: GetTraceAuditEvents
    
    get_escalation: GetEscalation
    list_escalations: ListEscalations
    list_conversation_escalations: ListConversationEscalations
    get_customer_escalation_status: GetCustomerEscalationStatus
    update_escalation: UpdateEscalation
    
    create_ticket: CreateTicket
    add_ticket_comment: AddTicketComment
    get_ticket: GetTicket
    list_tickets: ListTickets
    update_ticket: UpdateTicket
    
    submit_feedback: SubmitFeedback
    get_feedback: GetFeedback
    list_feedback: ListFeedback
    review_feedback: ReviewFeedback
    
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

    create_conversation = CreateConversation(uow_factory=uow_factory)
    list_conversations = ListConversations(uow_factory=uow_factory)
    get_conversation = GetConversation(uow_factory=uow_factory)
    get_conversation_messages = GetConversationMessages(uow_factory=uow_factory)
    process_customer_message = ProcessCustomerMessage(
        uow_factory=uow_factory,
        pipeline_factory=pipeline_factory,
        embedding_provider=embedding_services.provider,
        embedding_input_descriptor=embedding_input_builder.descriptor,
        retrieval_profile=retrieval_profile,
        grounding_context_budget=grounding_budget,
    )
    
    close_conversation = CloseConversation(uow_factory=uow_factory)
    password_hasher = Argon2PasswordHasher()
    token_service = TokenService(
        TokenServiceConfig(
            secret_key=settings.auth_jwt_secret,
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            access_token_ttl=settings.auth_access_token_ttl,
            clock_skew_seconds=settings.auth_clock_skew_seconds,
        )
    )

    register_user = RegisterUser(
        uow_factory=uow_factory,
        password_hasher=password_hasher,
        token_service=token_service,
        refresh_token_ttl=settings.auth_refresh_token_ttl,
    )

    login_user = LoginUser(
        uow_factory=uow_factory,
        password_hasher=password_hasher,
        token_service=token_service,
        refresh_token_ttl=settings.auth_refresh_token_ttl,
        maximum_failed_attempts=settings.auth_login_max_failed_attempts,
        lockout_duration=settings.auth_login_lockout_duration,
    )

    refresh_session = RefreshSession(uow_factory=uow_factory, token_service=token_service)
    logout_user = LogoutUser(uow_factory=uow_factory)
    authenticate_access_token = AuthenticateAccessToken(uow_factory=uow_factory, token_service=token_service)
    get_current_user = GetCurrentUser(uow_factory=uow_factory)
    record_api_request = RecordAPIRequest(uow_factory=uow_factory)
    get_dashboard_overview = GetDashboardOverview(uow_factory=uow_factory)
    query_dashboard_traces = QueryDashboardTraces(uow_factory=uow_factory)
    get_dashboard_trace_detail = GetTraceDetail(uow_factory=uow_factory)
    query_dashboard_llm_calls = QueryDashboardLLMCalls(uow_factory=uow_factory)
    query_dashboard_retrieval_runs = QueryDashboardRetrievalRuns(uow_factory=uow_factory)
    query_dashboard_api_requests = QueryDashboardAPIRequests(uow_factory=uow_factory)
    query_dashboard_audit_events = QueryDashboardAuditEvents(uow_factory=uow_factory)
    get_audit_event = GetAuditEvent(uow_factory=uow_factory)
    list_audit_events = ListAuditEvents(uow_factory=uow_factory)
    get_entity_audit_history = GetEntityAuditHistory(uow_factory=uow_factory)
    get_trace_audit_events = GetTraceAuditEvents(uow_factory=uow_factory)
    get_escalation = GetEscalation(uow_factory=uow_factory)
    list_escalations = ListEscalations(uow_factory=uow_factory)
    list_conversation_escalations = ListConversationEscalations(uow_factory=uow_factory)
    get_customer_escalation_status = GetCustomerEscalationStatus(uow_factory=uow_factory)
    update_escalation = UpdateEscalation(uow_factory=uow_factory)
    create_ticket = CreateTicket(uow_factory=uow_factory)
    add_ticket_comment = AddTicketComment(uow_factory=uow_factory)
    get_ticket = GetTicket(uow_factory=uow_factory)
    list_tickets = ListTickets(uow_factory=uow_factory)
    update_ticket = UpdateTicket(uow_factory=uow_factory)
    submit_feedback = SubmitFeedback(uow_factory=uow_factory)
    get_feedback = GetFeedback(uow_factory=uow_factory)
    list_feedback = ListFeedback(uow_factory=uow_factory)
    review_feedback = ReviewFeedback(uow_factory=uow_factory)

    return ApplicationServices(
        create_conversation=create_conversation,
        list_conversations=list_conversations,
        get_conversation=get_conversation,
        get_conversation_messages=get_conversation_messages,
        process_customer_message=process_customer_message,
        close_conversation = close_conversation,
        record_api_request=record_api_request,
        register_user=register_user,
        login_user=login_user,
        refresh_session=refresh_session,
        logout_user=logout_user,
        authenticate_access_token=authenticate_access_token,
        get_current_user=get_current_user,
        get_dashboard_overview=get_dashboard_overview,
        query_dashboard_traces=query_dashboard_traces,
        get_dashboard_trace_detail=get_dashboard_trace_detail,
        query_dashboard_llm_calls=query_dashboard_llm_calls,
        query_dashboard_retrieval_runs=query_dashboard_retrieval_runs,
        query_dashboard_api_requests=query_dashboard_api_requests,
        query_dashboard_audit_events=query_dashboard_audit_events,
        get_audit_event=get_audit_event,
        list_audit_events=list_audit_events,
        get_entity_audit_history=get_entity_audit_history,
        get_trace_audit_events=get_trace_audit_events,
        get_escalation=get_escalation,
        list_escalations=list_escalations,
        list_conversation_escalations=list_conversation_escalations,
        get_customer_escalation_status=get_customer_escalation_status,
        update_escalation=update_escalation,
        create_ticket=create_ticket,
        add_ticket_comment=add_ticket_comment,
        get_ticket=get_ticket,
        list_tickets=list_tickets,
        update_ticket=update_ticket,
        submit_feedback=submit_feedback,
        get_feedback=get_feedback,
        list_feedback=list_feedback,
        review_feedback=review_feedback,
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