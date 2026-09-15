# AI-customer-support-agent\tests\integration\api\test_browser_security.py
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


ALLOWED_ORIGIN = "https://testserver"
UNTRUSTED_ORIGIN = "https://untrusted.example"


def assert_auth_no_store(response) -> None:
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"


def test_preflight_allows_explicit_origin_and_request_headers(
    client: TestClient,
) -> None:
    response = client.options(
        "/v1/auth/refresh",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "authorization,content-type,x-trace-id"
            ),
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert response.headers["Access-Control-Allow-Credentials"] == "true"

    allowed_headers = {
        value.strip().lower()
        for value in response.headers["Access-Control-Allow-Headers"].split(",")
    }
    assert {"authorization", "content-type", "x-trace-id"} <= allowed_headers
    assert_auth_no_store(response)


@pytest.mark.parametrize(
    "overrides",
    [
        {"Origin": UNTRUSTED_ORIGIN},
        {"Access-Control-Request-Method": "DELETE"},
        {"Access-Control-Request-Headers": "x-unapproved-header"},
    ],
)
def test_preflight_rejects_unapproved_requests(
    client: TestClient,
    overrides: dict[str, str],
) -> None:
    headers = {
        "Origin": ALLOWED_ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    headers.update(overrides)

    response = client.options("/v1/auth/refresh", headers=headers)

    assert response.status_code == 400
    if headers["Origin"] == UNTRUSTED_ORIGIN:
        assert "Access-Control-Allow-Origin" not in response.headers

    assert_auth_no_store(response)


def test_actual_response_exposes_only_approved_custom_headers(
    client: TestClient,
) -> None:
    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert "X-Trace-ID" in response.headers

    exposed = {
        value.strip().lower()
        for value in response.headers["Access-Control-Expose-Headers"].split(",")
    }
    assert exposed == {"x-trace-id", "retry-after"}

    vary = {
        value.strip().lower()
        for value in response.headers["Vary"].split(",")
    }
    assert "origin" in vary


def test_untrusted_origin_receives_no_cors_permission(
    client: TestClient,
) -> None:
    response = client.get(
        "/v1/health",
        headers={"Origin": UNTRUSTED_ORIGIN},
    )

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize(
    ("method", "path", "payload", "expected_status"),
    [
        ("GET", "/v1/auth/me", None, 401),
        ("POST", "/v1/auth/login", {}, 422),
        ("POST", "/v1/auth/refresh", None, 401),
        ("GET", "/v1/auth/not-a-route", None, 404),
        ("GET", "/v1/auth/login", None, 405),
    ],
)
def test_auth_errors_are_not_cacheable(
    client: TestClient,
    method: str,
    path: str,
    payload,
    expected_status: int,
) -> None:
    kwargs = {} if payload is None else {"json": payload}
    response = client.request(method, path, **kwargs)

    assert response.status_code == expected_status
    assert_auth_no_store(response)
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN


def test_origin_rejection_is_not_cacheable(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/refresh",
        headers={"Origin": UNTRUSTED_ORIGIN},
    )

    assert response.status_code == 403
    assert_auth_no_store(response)
    assert "Access-Control-Allow-Origin" not in response.headers


def test_retry_after_is_preserved(client: TestClient) -> None:
    def unavailable():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "TEST_UNAVAILABLE",
                "message": "Temporarily unavailable.",
            },
            headers={"Retry-After": "5"},
        )

    client.app.add_api_route(
        "/v1/test-browser-unavailable",
        unavailable,
        methods=["GET"],
        include_in_schema=False,
    )

    response = client.get("/v1/test-browser-unavailable")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert "retry-after" in response.headers[
        "Access-Control-Expose-Headers"
    ].lower()


def test_unhandled_auth_error_retains_browser_headers(
    client: TestClient,
) -> None:
    def fail():
        raise RuntimeError("TEST-INTERNAL-DETAIL-MUST-NOT-LEAK")

    client.app.add_api_route(
        "/v1/auth/test-browser-failure",
        fail,
        methods=["GET"],
        include_in_schema=False,
    )

    # The fixture already owns the running lifespan. This second client
    # inspects the emitted 500 instead of re-raising the server exception.
    probe = TestClient(
        client.app,
        base_url=ALLOWED_ORIGIN,
        raise_server_exceptions=False,
    )
    try:
        response = probe.get(
            "/v1/auth/test-browser-failure",
            headers={"Origin": ALLOWED_ORIGIN},
        )
    finally:
        probe.close()

    assert response.status_code == 500
    assert_auth_no_store(response)
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert response.json()["error"]["trace_id"] == response.headers["X-Trace-ID"]
    assert "TEST-INTERNAL-DETAIL-MUST-NOT-LEAK" not in response.text