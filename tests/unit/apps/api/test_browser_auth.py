# AI-customer-support-agent\tests\unit\apps\api\test_browser_auth.py
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

import pytest
from fastapi import HTTPException, Request, Response

from apps.api.app.api.browser_auth import (
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    clear_refresh_cookie,
    read_refresh_cookie,
    require_browser_origin,
    set_refresh_cookie,
)
from packages.application.auth.exceptions import InvalidRefreshTokenError
from packages.config.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        auth_jwt_secret="test-only-secret-material-" * 3,
        database_name="support_ai_test",
        database_password="test-only-password",
        llm_provider="mock",
        embedding_provider="deterministic",
        browser_allowed_origins=("https://support.example.com",),
        auth_refresh_cookie_secure=True,
    )


def make_request(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/v1/auth/refresh",
            "root_path": "",
            "query_string": b"",
            "headers": headers,
            "server": ("api.example.com", 443),
            "client": ("127.0.0.1", 12345),
        }
    )


def test_allowed_origin_is_accepted(settings):
    request = make_request(
        [(b"origin", b"https://support.example.com")]
    )
    require_browser_origin(request, settings)


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"origin", b"null")],
        [(b"origin", b"https://untrusted.example.com")],
        [(b"origin", b"https://support.example.com.attacker.example")],
        [(b"origin", b"https://support.example.com/")],
        [
            (b"origin", b"https://support.example.com"),
            (b"origin", b"https://support.example.com"),
        ],
        [(b"host", b"support.example.com")],
    ],
)
def test_untrusted_or_missing_origin_is_rejected(settings, headers):
    with pytest.raises(HTTPException) as captured:
        require_browser_origin(make_request(headers), settings)

    assert captured.value.status_code == 403
    assert captured.value.detail["code"] == "BROWSER_ORIGIN_FORBIDDEN"
    assert "no-store" in captured.value.headers["Cache-Control"]


def test_refresh_cookie_is_read():
    request = make_request(
        [(b"cookie", f"{REFRESH_COOKIE_NAME}=test-token".encode())]
    )
    assert read_refresh_cookie(request) == "test-token"


def test_missing_refresh_cookie_is_rejected():
    with pytest.raises(InvalidRefreshTokenError):
        read_refresh_cookie(make_request([]))


def test_cookie_security_and_deletion_scope(settings):
    response = Response()
    set_refresh_cookie(
        response,
        refresh_token="test-token",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        settings=settings,
    )

    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    issued = cookies[REFRESH_COOKIE_NAME]

    assert issued["httponly"]
    assert issued["secure"]
    assert issued["samesite"].lower() == "lax"
    assert issued["path"] == REFRESH_COOKIE_PATH
    assert issued["domain"] == ""
    assert issued["expires"]
    assert "no-store" in response.headers["cache-control"]

    cleared_response = Response()
    clear_refresh_cookie(cleared_response, settings=settings)

    cleared_cookies = SimpleCookie()
    cleared_cookies.load(cleared_response.headers["set-cookie"])
    cleared = cleared_cookies[REFRESH_COOKIE_NAME]

    assert cleared["max-age"] == "0"
    assert cleared["path"] == issued["path"]
    assert cleared["domain"] == issued["domain"]
    assert cleared["httponly"]
    assert cleared["secure"]


def test_naive_cookie_expiry_is_rejected(settings):
    with pytest.raises(ValueError, match="timezone-aware"):
        set_refresh_cookie(
            Response(),
            refresh_token="test-token",
            expires_at=datetime(2030, 1, 1),
            settings=settings,
        )