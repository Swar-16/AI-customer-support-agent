from __future__ import annotations
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI

from apps.api.app.api.v1.router import router as v1_router
from apps.api.app.bootstrap.application import APIBootstrapError, get_application_services
from apps.api.app.api.errors import register_exception_handlers as register_api_exception_handlers

logger = logging.getLogger(__name__)

# Application metadata
APP_TITLE = "AI Customer Support API"
APP_DESCRIPTION = "HTTP API for the AI-powered customer support platform."
APP_VERSION = "1.0.0"
OPENAPI_URL = "/openapi.json"
DOCS_URL = "/docs"
REDOC_URL = "/redoc"

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage API process startup and shutdown.

    Startup responsibilities:
    - construct/validate long-lived application services
    - fail fast when application composition is invalid
    - expose application services through app.state

    Shutdown currently has no explicit resources to release because
    individual database sessions are request scoped and the provider
    abstraction does not currently expose a close lifecycle.
    """
    logger.info(
        "api_starting",
        extra={
            "application": APP_TITLE,
            "version": APP_VERSION,
        },
    )

    try:
        services = get_application_services()

    except APIBootstrapError:
        logger.exception("api_bootstrap_failed")
        raise

    except Exception:
        logger.exception("api_startup_failed")
        raise

    # Exposing the container through app.state gives us a natural
    # application-scoped dependency location and makes future testing
    # and lifecycle management straightforward.
    app.state.application_services = services

    logger.info(
        "api_started",
        extra={
            "application": APP_TITLE,
            "version": APP_VERSION,
            "llm_provider": services.base_llm_provider.provider_name,
            "llm_model": services.base_llm_provider.model_name,
        },
    )

    try:
        yield

    finally:
        logger.info(
            "api_stopping",
            extra={
                "application": APP_TITLE,
                "version": APP_VERSION,
            },
        )

        # Remove references held by the FastAPI application.
        #
        # We intentionally do not clear the bootstrap cache here because
        # cache ownership belongs to the bootstrap module and clearing it
        # can be useful only during controlled tests/reinitialization.
        if hasattr(app.state, "application_services"):
            del app.state.application_services

        logger.info(
            "api_stopped",
            extra={
                "application": APP_TITLE,
                "version": APP_VERSION,
            },
        )


# Application factory
def create_api_app() -> FastAPI:
    """
    Construct the FastAPI application.
    Keeping app construction behind a factory provides several advantages:

    - tests can construct isolated application instances
    - importing the module does not perform application bootstrap
    - configuration/middleware can evolve without global side effects
    - future worker or CLI processes remain independent from FastAPI
    """

    application = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
        lifespan=lifespan,
        openapi_url=OPENAPI_URL,
        docs_url=DOCS_URL,
        redoc_url=REDOC_URL,
    )

    _register_routers(application)
    _register_middleware(application)
    _register_exception_handlers(application)

    return application

# Router registration
def _register_routers(application: FastAPI) -> None:
    """
    Register the HTTP routing tree.

    Version-specific routing remains owned by api/v1/router.py.
    """
    application.include_router(v1_router)

# Middleware registration
def _register_middleware(application: FastAPI) -> None:
    """
    Register process-wide HTTP middleware.

    Kept intentionally empty for now.

    Middleware should be introduced here when we implement concerns such as:

    - request/response tracing
    - structured access logging
    - request timing
    - security headers
    - CORS
    - trusted proxy handling

    We deliberately avoid enabling permissive middleware defaults,
    particularly wildcard CORS, before deployment requirements are known.
    """

    _ = application


# Exception handlers
def _register_exception_handlers(application: FastAPI) -> None:
    """
    Register API-wide exception-to-HTTP mappings.
    """
    register_api_exception_handlers(application)

# ASGI application
app = create_api_app()