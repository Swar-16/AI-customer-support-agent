## This file owns process startup composition only.

from __future__ import annotations
from functools import lru_cache

from packages.application.composition.application_factory import ApplicationServices, create_application
from packages.config.settings import Settings, get_settings

class APIBootstrapError(RuntimeError):
    """
    Raised when the API process cannot construct its application services.

    This is a startup/configuration failure, not a normal request failure.
    """


def build_application_services(*, settings: Settings | None = None) -> ApplicationServices:
    """
    Build the long-lived application service container used by the API.

    Responsibilities:
    - resolve runtime settings
    - construct ApplicationServices
    - translate composition/startup failures into an API bootstrap error

    This function deliberately does NOT:
    - open SQLAlchemy sessions
    - begin transactions
    - process customer messages
    - perform provider health checks
    - make external API calls
    """

    resolved_settings = settings if settings is not None else get_settings()
    if not isinstance(resolved_settings, Settings):
        raise TypeError("settings must be a Settings instance")

    try:
        return create_application(settings=resolved_settings)

    except Exception as exc:
        raise APIBootstrapError("Failed to initialize application services") from exc


@lru_cache(maxsize=1)
def get_application_services() -> ApplicationServices:
    """
    Return the process-wide ApplicationServices instance.

    The application service container is safe to reuse because it contains
    long-lived dependencies only:

        base provider
        pipeline factory
        orchestration observer
        application services

    Request-scoped objects such as:
        SQLAlchemy Session
        UnitOfWork
        AI run
        TelemetryRecorder
        InstrumentedLLMProvider

    are still created later per request.
    """
    return build_application_services()


def clear_application_services_cache() -> None:
    """
    Clear the cached service container.

    Intended primarily for tests and controlled application reinitialization.
    """

    get_application_services.cache_clear()