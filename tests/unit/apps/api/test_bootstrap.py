from __future__ import annotations
from unittest.mock import Mock, patch
import pytest
from collections.abc import Generator

from apps.api.app.bootstrap.application import APIBootstrapError, build_application_services, clear_application_services_cache, get_application_services
from packages.application.composition.application_factory import ApplicationServices
from packages.config.settings import Settings

# Helpers
def make_settings(**overrides) -> Settings:
    """
    Build an isolated Settings object for unit tests.

    _env_file=None is important: unit tests must not accidentally read
    development or test environment files.
    """
    values = {
        "app_env": "test",
        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "support_ai_test",
        "database_user": "support_ai_admin",
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


def make_application_services() -> ApplicationServices:
    """
    Build a real ApplicationServices container using test doubles for its
    collaborators.

    We intentionally use the real container rather than mocking the entire
    type because production code performs isinstance checks.
    """

    return ApplicationServices(
        process_customer_message=Mock(),
        ai_pipeline_factory=Mock(),
        base_llm_provider=Mock(),
        orchestration_observer=Mock(),
    )

# Cache isolation
@pytest.fixture(autouse=True)
def clear_services_cache() -> Generator[None, None, None]:
    """
    Ensure cached bootstrap state never leaks between unit tests.
    """
    clear_application_services_cache()
    yield
    clear_application_services_cache()

# build_application_services
class TestBuildApplicationServices:
    @patch("apps.api.app.bootstrap.application.create_application")
    def test_builds_services_using_explicit_settings(self, create_application_mock: Mock) -> None:
        settings = make_settings()
        expected = make_application_services()
        create_application_mock.return_value = expected
        result = build_application_services(settings=settings)

        assert result is expected

        create_application_mock.assert_called_once_with(settings=settings)

    @patch("apps.api.app.bootstrap.application.get_settings")
    @patch("apps.api.app.bootstrap.application.create_application")
    def test_uses_default_settings_when_none_are_supplied(self, create_application_mock: Mock, get_settings_mock: Mock) -> None:
        settings = make_settings()
        expected = make_application_services()
        get_settings_mock.return_value = settings
        create_application_mock.return_value = expected
        result = build_application_services()

        assert result is expected

        get_settings_mock.assert_called_once_with()
        create_application_mock.assert_called_once_with(settings=settings)

    @patch("apps.api.app.bootstrap.application.create_application")
    def test_does_not_resolve_default_settings_when_explicit_settings_given(self, create_application_mock: Mock) -> None:
        settings = make_settings()
        create_application_mock.return_value = make_application_services()

        with patch("apps.api.app.bootstrap.application.get_settings") as get_settings_mock:
            build_application_services(settings=settings)

        get_settings_mock.assert_not_called()

    def test_rejects_invalid_settings_type(self) -> None:
        with pytest.raises(TypeError, match="settings must be a Settings instance"):
            build_application_services(settings=object())

    @patch("apps.api.app.bootstrap.application.create_application")
    def test_wraps_application_construction_failure(self, create_application_mock: Mock) -> None:
        settings = make_settings()
        underlying = RuntimeError("provider construction failed")
        create_application_mock.side_effect = underlying

        with pytest.raises(APIBootstrapError, match="Failed to initialize application services") as exc_info:
            build_application_services(settings=settings)

        assert exc_info.value.__cause__ is underlying

    @patch("apps.api.app.bootstrap.application.create_application")
    def test_does_not_expose_underlying_failure_in_public_message(self, create_application_mock: Mock) -> None:
        settings = make_settings()
        sensitive_detail = ("postgresql://admin:secret@localhost/support_ai")
        create_application_mock.side_effect = RuntimeError(sensitive_detail)

        with pytest.raises(APIBootstrapError) as exc_info:
            build_application_services(settings=settings)

        assert sensitive_detail not in str(exc_info.value)

# get_application_services
class TestGetApplicationServices:
    @patch("apps.api.app.bootstrap.application.build_application_services")
    def test_constructs_services_on_first_call(self, build_mock: Mock) -> None:
        expected = make_application_services()
        build_mock.return_value = expected
        result = get_application_services()

        assert result is expected
        build_mock.assert_called_once_with()

    @patch("apps.api.app.bootstrap.application.build_application_services")
    def test_returns_same_cached_instance_on_repeated_calls(self, build_mock: Mock) -> None:
        expected = make_application_services()
        build_mock.return_value = expected
        first = get_application_services()
        second = get_application_services()
        third = get_application_services()

        assert first is expected
        assert second is expected
        assert third is expected

        build_mock.assert_called_once_with()

    @patch("apps.api.app.bootstrap.application.build_application_services")
    def test_cache_clear_forces_reconstruction(self, build_mock: Mock) -> None:
        first_services = make_application_services()
        second_services = make_application_services()
        build_mock.side_effect = [first_services, second_services]
        first = get_application_services()
        clear_application_services_cache()
        second = get_application_services()

        assert first is first_services
        assert second is second_services
        assert first is not second
        assert build_mock.call_count == 2

    @patch("apps.api.app.bootstrap.application.build_application_services")
    def test_failed_construction_is_not_cached(self, build_mock: Mock) -> None:
        expected = make_application_services()
        build_mock.side_effect = [APIBootstrapError("Failed to initialize application services"), expected]

        with pytest.raises(APIBootstrapError):
            get_application_services()

        result = get_application_services()

        assert result is expected
        assert build_mock.call_count == 2

# clear_application_services_cache
class TestClearApplicationServicesCache:
    @patch("apps.api.app.bootstrap.application.build_application_services")
    def test_can_be_called_when_cache_is_empty(self, build_mock: Mock) -> None:
        clear_application_services_cache()
        build_mock.assert_not_called()

    @patch("apps.api.app.bootstrap.application.build_application_services")
    def test_is_safe_to_call_multiple_times(self, build_mock: Mock) -> None:
        clear_application_services_cache()
        clear_application_services_cache()
        clear_application_services_cache()
        build_mock.assert_not_called()