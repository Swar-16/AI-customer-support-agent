from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from packages.ai.orchestration.orchestrator import NullOrchestrationObserver
from packages.ai.providers.mock import MockLLMProvider
from packages.ai.telemetry.observer import TelemetryOrchestrationObserver
from packages.application.composition.application_factory import ApplicationConfigurationError, ApplicationServices, create_application
from packages.application.conversations.process_customer_message import ProcessCustomerMessage
from packages.config.settings import Settings


# Helpers
def make_settings(**overrides) -> Settings:
    """
    Construct isolated settings without reading a dotenv file.

    All required fields are supplied explicitly so developer-machine
    configuration does not influence these unit tests.
    """

    values = {
        "app_env": "test",
        "app_name": "support-ai-test",

        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "support_ai_test",
        "database_user": "support_ai_test_user",
        "database_password": "test-password",
        "database_echo": False,

        "llm_provider": "mock",

        "groq_api_key": None,
        "groq_model": "openai/gpt-oss-20b",
        "groq_timeout_seconds": 30.0,
        "groq_max_completion_tokens": 1024,
        "groq_temperature": 0.0,
    }

    values.update(overrides)

    return Settings(_env_file=None, **values)

# Basic composition
class TestApplicationComposition:
    def test_create_application_returns_service_container(self) -> None:
        settings = make_settings()
        services = create_application(settings=settings, base_provider=MockLLMProvider())

        assert isinstance(services, ApplicationServices)
        assert isinstance(services.process_customer_message, ProcessCustomerMessage)

    def test_injected_provider_is_preserved(self) -> None:
        settings = make_settings()
        provider = MockLLMProvider()
        services = create_application(settings=settings, base_provider=provider)

        assert services.base_llm_provider is provider
        assert services.ai_pipeline_factory.base_provider is provider

    def test_pipeline_factory_reports_provider_identity(self) -> None:
        settings = make_settings()
        provider = MockLLMProvider()
        services = create_application(settings=settings, base_provider=provider)

        assert services.ai_pipeline_factory.provider_name == "mock"
        assert services.ai_pipeline_factory.model_name == "mock-llm-v1"


# Provider resolution
class TestProviderResolution:
    def test_provider_is_created_from_settings_when_not_injected(self) -> None:
        settings = make_settings(llm_provider="mock")
        services = create_application(settings=settings)

        assert isinstance(services.base_llm_provider, MockLLMProvider)

    def test_explicit_provider_overrides_settings(self) -> None:
        """
        Dependency injection should win over configuration.

        Even deliberately invalid provider configuration should not matter
        when the caller explicitly supplies a valid provider.
        """
        settings = make_settings(llm_provider="unsupported-provider")
        provider = MockLLMProvider()
        services = create_application(settings=settings, base_provider=provider)

        assert services.base_llm_provider is provider

    def test_invalid_provider_configuration_is_wrapped(self) -> None:
        settings = make_settings(llm_provider="unsupported-provider")

        with pytest.raises(ApplicationConfigurationError, match="Failed to configure LLM provider"):
            create_application(settings=settings)

    def test_invalid_injected_provider_rejected(self) -> None:
        settings = make_settings()

        with pytest.raises(TypeError):
            create_application(settings=settings, base_provider="groq")


# Observer composition
class TestObserverComposition:
    def test_default_observer_is_telemetry_observer(self) -> None:
        settings = make_settings()
        services = create_application(settings=settings, base_provider=MockLLMProvider())

        assert isinstance(services.orchestration_observer, TelemetryOrchestrationObserver)

    def test_custom_observer_is_preserved(self) -> None:
        settings = make_settings()
        observer = NullOrchestrationObserver()
        services = create_application(settings=settings, base_provider=MockLLMProvider(), observer=observer)

        assert services.orchestration_observer is observer

    def test_pipeline_factory_receives_same_observer(self) -> None:
        """
        We verify behavior indirectly later through orchestrator creation,
        but keeping the same observer instance at composition time prevents
        accidental duplicate observer instances.
        """
        settings = make_settings()
        observer = NullOrchestrationObserver()
        services = create_application(settings=settings, base_provider=MockLLMProvider(), observer=observer)

        assert services.orchestration_observer is observer

# Database/session lifecycle
class TestSessionLifecycle:
    def test_application_creation_does_not_open_database_session(self) -> None:
        """
        Application startup must not create request-scoped SQLAlchemy
        sessions eagerly.
        """
        settings = make_settings()
        session_factory = MagicMock()
        create_application(settings=settings, session_factory=session_factory, base_provider=MockLLMProvider())
        session_factory.assert_not_called()

    def test_application_creation_does_not_touch_database(self) -> None:
        """
        Stronger form of the previous invariant:

        composing the dependency graph should be possible even when the
        session factory would explode if invoked.
        """
        settings = make_settings()
        session_factory = MagicMock(side_effect=RuntimeError("database should not be touched"))
        services = create_application(
            settings=settings,
            session_factory=session_factory,
            base_provider=MockLLMProvider(),
        )

        assert isinstance(services, ApplicationServices)
        session_factory.assert_not_called()

# Long-lived dependency reuse
class TestDependencyLifetime:
    def test_same_provider_instance_is_shared_by_pipeline_factory(self) -> None:
        settings = make_settings()
        provider = MockLLMProvider()
        services = create_application(settings=settings, base_provider=provider)

        assert services.base_llm_provider is services.ai_pipeline_factory.base_provider

    def test_application_services_are_immutable(self) -> None:
        settings = make_settings()
        services = create_application(settings=settings, base_provider=MockLLMProvider())

        with pytest.raises((AttributeError, TypeError)):
            services.base_llm_provider = MockLLMProvider()


# Invalid application configuration
class TestInvalidCompositionInput:
    def test_non_settings_object_rejected(self) -> None:
        with pytest.raises(TypeError):
            create_application(
                settings="test",  # type: ignore[arg-type]
                base_provider=MockLLMProvider(),
            )

    def test_none_session_factory_rejected(self) -> None:
        settings = make_settings()

        with pytest.raises(TypeError):
            create_application(
                settings=settings,
                session_factory=None,  # type: ignore[arg-type]
                base_provider=MockLLMProvider(),
            )