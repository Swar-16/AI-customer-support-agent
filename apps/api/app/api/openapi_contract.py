# AI-customer-support-agent\apps\api\app\api\openapi_contract.py
"""Document confirmed middleware and authentication transport behavior."""
from __future__ import annotations
from copy import deepcopy
from typing import Any

from apps.api.app.api.browser_auth import REFRESH_COOKIE_NAME

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_ERROR_REF = "#/components/schemas/APIErrorResponse"
_VALIDATION_REF = "#/components/schemas/HTTPValidationError"
_BROWSER_MUTATIONS = {
    "/v1/auth/register", "/v1/auth/login", "/v1/auth/refresh", "/v1/auth/logout",
}
_ANALYTICS_PATHS = {
    "/v1/dashboard/conversation-analytics", "/v1/dashboard/ai-analytics", "/v1/dashboard/support-analytics", "/v1/dashboard/knowledge-health",
}

def _error_response(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": _ERROR_REF},},},
    }

def apply_transport_contract(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a schema documenting the API's confirmed transport policies."""
    result = deepcopy(schema)
    components = result.setdefault("components", {})

    if "APIErrorResponse" not in components.get("schemas", {}):
        raise RuntimeError("The canonical API error schema is missing.")

    components.setdefault("securitySchemes", {})["RefreshCookie"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": REFRESH_COOKIE_NAME,
        "description": (
            "HTTP-only refresh cookie issued by registration, login, and refresh. Browsers send it automatically"
            "with credentials enabled. Frontend JavaScript must not read or construct it."
        ),
    }

    for path, path_item in result["paths"].items():
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS:
                continue

            responses = operation.setdefault("responses", {})

            # These failures can originate in request middleware or the application's catch-all error handler.
            responses.setdefault("400", _error_response("Invalid request, including an invalid trace ID."))
            responses.setdefault("500", _error_response("Unexpected internal failure."))
            if any("BearerAuth" in requirement for requirement in operation.get("security", [])):
                responses.setdefault("401", _error_response("Authentication credentials are invalid or expired."))

            for code, response in responses.items():
                if "$ref" in response:
                    continue

                if code.isdigit() and int(code) >= 400:
                    content = response.get("content")
                    json_schema = (content or {}).get("application/json", {}).get("schema", {})
                    # Preserve explicit domain response schemas, including the health readiness endpoint's distinct 503 payload.
                    if not content or json_schema.get("$ref") == _VALIDATION_REF:
                        response["content"] = _error_response("")["content"]

                headers = response.setdefault("headers", {})
                headers.setdefault(
                    "X-Trace-ID",
                    {
                        "description": "Application request correlation identifier.",
                        "schema": {"type": "string", "format": "uuid"},
                    },
                )

                if path.startswith("/v1/auth/"):
                    headers["Cache-Control"] = {
                        "description": "Authentication responses must not be cached.",
                        "schema": {
                            "type": "string",
                            "const": "no-store, no-cache, must-revalidate, private",
                        },
                    }
                    headers["Pragma"] = {"schema": {"type": "string", "const": "no-cache"},}
                    headers["Expires"] = {"schema": {"type": "string", "const": "0"},}

            if method == "post" and path in _BROWSER_MUTATIONS:
                parameters = operation.setdefault("parameters", [])
                if not any(parameter.get("in") == "header" and parameter.get("name", "").lower() == "origin" for parameter in parameters):
                    parameters.append(
                        {
                            "name": "Origin",
                            "in": "header",
                            "required": True,
                            "description": (
                                "Browser-supplied origin. Exactly one value must match the deployment's configured allowlist. "
                                "Missing, null, or untrusted origins return 403. Frontend JavaScript does not set this header."
                            ),
                            "schema": {"type": "string"},
                        }
                    )

            if path in _ANALYTICS_PATHS and "503" in responses:
                responses["503"].setdefault("headers", {})["Retry-After"] = {
                    "description": "Seconds to wait before a bounded retry after an analytics query timeout.",
                    "schema": {"type": "string", "const": "5"},
                }

    refresh = result["paths"]["/v1/auth/refresh"]["post"]
    if "requestBody" in refresh:
        raise RuntimeError("Refresh must not advertise a request body.")
    refresh["security"] = [{"RefreshCookie": []}]

    for path, code in (("/v1/auth/register", "201"), ("/v1/auth/login", "200"), ("/v1/auth/refresh", "200"),):
        response = result["paths"][path]["post"]["responses"][code]
        response["headers"]["Set-Cookie"] = {
            "description": (
                f"Issues or rotates {REFRESH_COOKIE_NAME}. HttpOnly; SameSite=Lax; Path=/v1/auth; no Domain attribute. "
                "Secure outside explicitly configured local development/test. "
                "Expiry preserves the server session lifetime. "
                "Not readable by frontend JavaScript."
            ),
            "schema": {"type": "string"},
        }

    logout = result["paths"]["/v1/auth/logout"]["post"]
    logout["responses"]["200"]["headers"]["Set-Cookie"] = {
        "description": "Deletes the refresh cookie using its original scope.",
        "schema": {"type": "string"},
    }
    refresh["responses"]["401"]["headers"]["Set-Cookie"] = {
        "description": "Deletes the invalid refresh cookie.",
        "schema": {"type": "string"},
    }

    return result