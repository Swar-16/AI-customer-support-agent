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
    ai_pipeline_factory: AIPipelineFactory
    base_llm_provider: LLMProvider
    orchestration_observer: OrchestrationObserver


class ApplicationConfigurationError(RuntimeError):
    """
    Raised when the application cannot be composed from the supplied
    configuration.

    This represents a startup/configuration failure rather than a normal
    request failure.
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

    def uow_factory() -> SqlAlchemyUnitOfWork:
        """
        Create a fresh UnitOfWork for each application transaction.

        No Session is opened until the UoW context manager is entered.
        """
        return SqlAlchemyUnitOfWork(session_factory=session_factory)

    process_customer_message = (
        ProcessCustomerMessage(
            uow_factory=uow_factory,
            pipeline_factory=pipeline_factory,
        )
    )

    return ApplicationServices(
        process_customer_message=process_customer_message,
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