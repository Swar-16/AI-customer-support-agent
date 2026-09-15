# AI-customer-support-agent\tests\unit\apps\api\test_openapi_contract.py
from copy import deepcopy

from apps.api.app.api.openapi_contract import apply_transport_contract
from apps.api.app.main import create_api_app


ERROR_REF = "#/components/schemas/APIErrorResponse"
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def operations(schema):
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method in METHODS:
                yield path, method, operation


def test_authentication_transport_is_documented():
    schema = create_api_app().openapi()

    cookie = schema["components"]["securitySchemes"]["RefreshCookie"]
    assert cookie["type"] == "apiKey"
    assert cookie["in"] == "cookie"
    assert cookie["name"] == "support_ai_refresh"

    refresh = schema["paths"]["/v1/auth/refresh"]["post"]
    assert refresh["security"] == [{"RefreshCookie": []}]
    assert "requestBody" not in refresh
    assert refresh["responses"]["422"]["content"]["application/json"][
        "schema"
    ] == {"$ref": ERROR_REF}

    for suffix in ("register", "login", "refresh", "logout"):
        operation = schema["paths"][f"/v1/auth/{suffix}"]["post"]
        origin = [
            parameter
            for parameter in operation["parameters"]
            if parameter["in"] == "header"
            and parameter["name"] == "Origin"
        ]
        assert len(origin) == 1
        assert origin[0]["required"] is True

    tokens = schema["components"]["schemas"]["BrowserAccessTokenResponse"]
    assert "refresh_token" not in tokens["properties"]


def test_validation_responses_use_the_runtime_error_envelope():
    schema = create_api_app().openapi()

    for _, _, operation in operations(schema):
        response = operation["responses"].get("422")
        if response is not None:
            assert response["content"]["application/json"]["schema"] == {
                "$ref": ERROR_REF,
            }


def test_headers_and_unique_operation_ids():
    schema = create_api_app().openapi()
    identifiers = []

    for path, _, operation in operations(schema):
        identifiers.append(operation["operationId"])

        for response in operation["responses"].values():
            assert "X-Trace-ID" in response["headers"]
            if path.startswith("/v1/auth/"):
                assert "no-store" in response["headers"]["Cache-Control"][
                    "schema"
                ]["const"]

    assert len(identifiers) == len(set(identifiers))

    analytics = schema["paths"]["/v1/dashboard/conversation-analytics"]["get"]
    assert analytics["responses"]["503"]["headers"]["Retry-After"][
        "schema"
    ]["const"] == "5"

    message = schema["paths"]["/v1/conversations/{conversation_id}/messages"]
    assert "Retry-After" not in message["post"]["responses"]["503"]["headers"]


def test_policy_preserves_explicit_readiness_response_and_is_idempotent():
    schema = create_api_app().openapi()
    original = deepcopy(schema)
    readiness = deepcopy(
        schema["paths"]["/v1/health/ready"]["get"]["responses"]["503"]["content"]
    )

    updated = apply_transport_contract(schema)

    assert schema == original
    assert updated == schema
    assert updated["paths"]["/v1/health/ready"]["get"]["responses"]["503"][
        "content"
    ] == readiness


def test_openapi_is_cached_per_application():
    application = create_api_app()
    assert application.openapi() is application.openapi()