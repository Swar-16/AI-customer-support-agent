from __future__ import annotations
from unittest.mock import Mock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.main import (
    APP_DESCRIPTION,
    APP_TITLE,
    APP_VERSION,
    DOCS_URL,
    OPENAPI_URL,
    REDOC_URL,
    create_api_app,
    lifespan,
)
from packages.application.composition.application_factory import ApplicationServices

# Helpers
def make_application_services() -> ApplicationServices:
    """
    Build a real ApplicationServices container with mocked collaborators.

    The concrete container is preferable to mocking ApplicationServices
    itself because production code may perform runtime type checks.
    """
    provider = Mock()
    provider.provider_name = "mock"
    provider.model_name = "mock-model"

    return ApplicationServices(
        process_customer_message=Mock(),
        ai_pipeline_factory=Mock(),
        base_llm_provider=provider,
        orchestration_observer=Mock(),
    )

# Application factory
class TestCreateApiApp:
    def test_returns_fastapi_instance(self) -> None:
        app = create_api_app()

        assert isinstance(app, FastAPI)

    def test_configures_application_metadata(self) -> None:
        app = create_api_app()

        assert app.title == APP_TITLE
        assert app.description == APP_DESCRIPTION
        assert app.version == APP_VERSION

    def test_configures_documentation_urls(self) -> None:
        app = create_api_app()

        assert app.openapi_url == OPENAPI_URL
        assert app.docs_url == DOCS_URL
        assert app.redoc_url == REDOC_URL

    def test_registers_v1_routes(self) -> None:
        app = create_api_app()
        schema = app.openapi()
        paths = set(schema["paths"])
        
        assert "/v1/health" in paths
        assert "/v1/health/ready" in paths
        assert (
            "/v1/conversations/{conversation_id}/messages"
            in paths
        )

    def test_creating_multiple_apps_does_not_mutate_route_registration(self) -> None:
        first = create_api_app()
        first_schema_before = first.openapi()
        first_paths_before = set(first_schema_before["paths"])
        
        second = create_api_app()
        second_paths = set(second.openapi()["paths"])
        first_paths_after = set(first.openapi()["paths"])

        assert first_paths_before == first_paths_after
        assert first_paths_before == second_paths

    @patch("apps.api.app.main.get_application_services")
    def test_app_construction_does_not_bootstrap_services(self, get_services_mock: Mock) -> None:
        """
        create_api_app() should only assemble FastAPI.

        Application services belong to lifespan startup rather than module
        construction.
        """
        create_api_app()
        get_services_mock.assert_not_called()

# Lifespan
class TestLifespan:
    @pytest.mark.asyncio
    @patch("apps.api.app.main.get_application_services")
    async def test_initializes_application_services_on_startup(self, get_services_mock: Mock) -> None:
        app = FastAPI()
        services = make_application_services()
        get_services_mock.return_value = services

        assert not hasattr(app.state, "application_services")
        async with lifespan(app):
            assert app.state.application_services is services

        get_services_mock.assert_called_once_with()

    @pytest.mark.asyncio
    @patch("apps.api.app.main.get_application_services")
    async def test_removes_application_services_on_shutdown(self, get_services_mock: Mock) -> None:
        app = FastAPI()
        services = make_application_services()
        get_services_mock.return_value = services

        async with lifespan(app):
            assert hasattr(app.state, "application_services")

        assert not hasattr(app.state, "application_services")

    @pytest.mark.asyncio
    @patch("apps.api.app.main.get_application_services")
    async def test_propagates_bootstrap_failure(self, get_services_mock: Mock) -> None:
        from apps.api.app.bootstrap.application import APIBootstrapError

        app = FastAPI()
        get_services_mock.side_effect = APIBootstrapError("Failed to initialize application services")

        with pytest.raises(APIBootstrapError, match="Failed to initialize application services"):
            async with lifespan(app):
                pass

        assert not hasattr(app.state, "application_services")

    @pytest.mark.asyncio
    @patch("apps.api.app.main.get_application_services")
    async def test_propagates_unexpected_startup_failure(self, get_services_mock: Mock) -> None:
        app = FastAPI()
        get_services_mock.side_effect = RuntimeError("unexpected startup failure")

        with pytest.raises(RuntimeError, match="unexpected startup failure"):
            async with lifespan(app):
                pass

        assert not hasattr(app.state, "application_services")

    @pytest.mark.asyncio
    @patch("apps.api.app.main.get_application_services")
    async def test_cleanup_occurs_when_runtime_failure_happens(self, get_services_mock: Mock) -> None:
        """
        Once startup succeeds, shutdown cleanup must run even if the
        serving phase exits because of an exception.
        """
        app = FastAPI()
        services = make_application_services()
        get_services_mock.return_value = services

        with pytest.raises(RuntimeError, match="simulated runtime failure"):
            async with lifespan(app):
                assert app.state.application_services is services
                raise RuntimeError("simulated runtime failure")

        assert not hasattr(app.state, "application_services")

# Actual TestClient lifecycle
class TestFastApiLifecycle:
    @patch("apps.api.app.main.get_application_services")
    def test_testclient_executes_lifespan(self, get_services_mock: Mock) -> None:
        """
        Verify the FastAPI application factory is actually wired to the
        lifespan function rather than merely testing lifespan in isolation.
        """
        services = make_application_services()
        get_services_mock.return_value = services
        app = create_api_app()

        assert not hasattr(app.state, "application_services")
        with TestClient(app):
            assert app.state.application_services is services

        assert not hasattr(app.state, "application_services")

    @patch("apps.api.app.main.get_application_services")
    def test_health_route_is_reachable_after_startup(self, get_services_mock: Mock) -> None:
        services = make_application_services()
        get_services_mock.return_value = services
        app = create_api_app()
        
        with TestClient(app) as client:
            response = client.get("/v1/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# OpenAPI
class TestOpenApi:
    def test_openapi_schema_contains_expected_metadata(self) -> None:
        app = create_api_app()
        schema = app.openapi()

        assert schema["info"]["title"] == APP_TITLE
        assert schema["info"]["version"] == APP_VERSION

    def test_openapi_schema_contains_conversation_endpoint(self) -> None:
        app = create_api_app()
        schema = app.openapi()

        assert "/v1/conversations/{conversation_id}/messages" in schema["paths"]

    def test_openapi_schema_contains_health_endpoints(self) -> None:
        app = create_api_app()
        schema = app.openapi()

        assert "/v1/health" in schema["paths"]
        assert "/v1/health/ready" in schema["paths"]

# Exception handler registration
class TestExceptionHandlerRegistration:
    def test_global_exception_handlers_are_registered(self) -> None:
        from fastapi import HTTPException
        from fastapi.exceptions import RequestValidationError
        from packages.application.conversations.process_customer_message import ConversationDoesNotExistError, ConversationNotProcessableError, CustomerMessageValidationError

        app = create_api_app()
        handlers = app.exception_handlers

        assert RequestValidationError in handlers
        assert HTTPException in handlers
        assert ConversationDoesNotExistError in handlers
        assert ConversationNotProcessableError in handlers
        assert CustomerMessageValidationError in handlers
        assert Exception in handlers