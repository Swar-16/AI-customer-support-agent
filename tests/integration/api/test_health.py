from __future__ import annotations
from unittest.mock import Mock, patch
import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_api_app
from packages.application.composition.application_factory import ApplicationServices

def make_application_services(*, provider_healthy: bool = True) -> ApplicationServices:
    """
    Build a real ApplicationServices container while mocking only
    external/runtime collaborators.
    """
    provider = Mock()
    provider.provider_name = "mock"
    provider.model_name = "mock-model"
    provider.health_check.return_value = provider_healthy

    return ApplicationServices(
        process_customer_message=Mock(),
        ai_pipeline_factory=Mock(),
        base_llm_provider=provider,
        orchestration_observer=Mock(),
    )


class TestLivenessEndpoint:
    @patch("apps.api.app.main.get_application_services")
    def test_returns_ok(self, get_services_mock: Mock) -> None:
        services = make_application_services()
        get_services_mock.return_value = services
        app = create_api_app()

        with TestClient(app) as client:
            response = client.get("/v1/health")

        assert response.status_code == 200
        assert response.json() == { "status": "ok" }

    @patch("apps.api.app.main.get_application_services")
    def test_does_not_call_llm_provider_health_check(self, get_services_mock: Mock) -> None:
        services = make_application_services()
        get_services_mock.return_value = services
        app = create_api_app()

        with TestClient(app) as client:
            response = client.get("/v1/health")

        assert response.status_code == 200

        services.base_llm_provider.health_check.assert_not_called()


class TestReadinessEndpoint:
    @patch("apps.api.app.main.get_application_services")
    def test_returns_ready_when_provider_is_healthy(self, get_services_mock: Mock) -> None:
        services = make_application_services(provider_healthy=True)
        get_services_mock.return_value = services
        app = create_api_app()

        with TestClient(app) as client:
            response = client.get("/v1/health/ready")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "llm_provider": { "status": "ok" },
        }

        services.base_llm_provider.health_check.assert_called_once_with()

    @patch("apps.api.app.main.get_application_services")
    def test_returns_service_unavailable_when_provider_is_unhealthy(self, get_services_mock: Mock) -> None:
        services = make_application_services(provider_healthy=False)
        get_services_mock.return_value = services
        app = create_api_app()

        with TestClient(app) as client:
            response = client.get("/v1/health/ready")

        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "llm_provider": { "status": "unavailable" },
        }

        services.base_llm_provider.health_check.assert_called_once_with()

    @patch("apps.api.app.main.get_application_services")
    def test_returns_service_unavailable_when_health_check_raises(self, get_services_mock: Mock) -> None:
        services = make_application_services()
        services.base_llm_provider.health_check.side_effect = RuntimeError("provider temporarily unavailable")
        get_services_mock.return_value = services
        app = create_api_app()

        with TestClient(app) as client:
            response = client.get("/v1/health/ready")

        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "llm_provider": { "status": "unavailable" },
        }

    @patch("apps.api.app.main.get_application_services")
    def test_provider_failure_does_not_make_liveness_fail(self, get_services_mock: Mock) -> None:
        services = make_application_services()
        services.base_llm_provider.health_check.side_effect = RuntimeError("provider unavailable")
        get_services_mock.return_value = services
        app = create_api_app()

        with TestClient(app) as client:
            liveness_response = client.get("/v1/health")
            readiness_response = client.get("/v1/health/ready")

        assert liveness_response.status_code == 200
        assert liveness_response.json() == { "status": "ok" }
        assert readiness_response.status_code == 503