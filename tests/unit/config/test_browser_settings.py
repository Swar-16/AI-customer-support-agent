# AI-customer-support-agent\tests\unit\config\test_browser_settings.py
import pytest
from pydantic import ValidationError

from packages.config.settings import Settings


def make_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "auth_jwt_secret": "test-only-secret-material-" * 3,
        "database_name": "support_ai_test",
        "database_password": "test-only-password",
        "llm_provider": "mock",
        "embedding_provider": "deterministic",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_browser_defaults_authorize_no_origins_and_require_secure_cookie():
    settings = make_settings()

    assert settings.browser_allowed_origins == ()
    assert settings.auth_refresh_cookie_secure is True


def test_local_development_can_use_http():
    settings = make_settings(
        app_env="development",
        browser_allowed_origins=("http://localhost:5173",),
        auth_refresh_cookie_secure=False,
    )

    assert settings.browser_allowed_origins == ("http://localhost:5173",)


def test_origins_are_normalized_and_deduplicated():
    settings = make_settings(
        browser_allowed_origins=(
            "https://EXAMPLE.com:443",
            "https://example.com",
        )
    )

    assert settings.browser_allowed_origins == ("https://example.com",)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "null",
        "https://*.example.com",
        "https://example.com/path",
        "https://example.com/",
        "https://user:password@example.com",
        "https://example.com?query=value",
        "https://example.com#fragment",
        "https://example.com:",
        "https://example.com:0",
        "http://example.com",
    ],
)
def test_invalid_browser_origins_are_rejected(origin):
    with pytest.raises(ValidationError):
        make_settings(browser_allowed_origins=(origin,))


def test_production_rejects_insecure_cookies():
    with pytest.raises(ValidationError):
        make_settings(
            app_env="production",
            auth_refresh_cookie_secure=False,
        )


def test_production_rejects_http_origins():
    with pytest.raises(ValidationError):
        make_settings(
            app_env="production",
            browser_allowed_origins=("http://localhost:5173",),
        )