# AI-customer-support-agent\tests\integration\api\test_knowledge_authorization.py
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7


READ_CASES = (
    ("GET", "/v1/knowledge/documents"),
    (
        "GET",
        f"/v1/knowledge/documents/{uuid7()}",
    ),
    (
        "GET",
        f"/v1/knowledge/documents/{uuid7()}/versions",
    ),
    (
        "GET",
        f"/v1/knowledge/versions/{uuid7()}",
    ),
)

MUTATION_CASES = (
    (
        "POST",
        "/v1/knowledge/documents",
        {
            "title": "Authorization Test",
            "description": "Authorization boundary test.",
            "content_type": "policy",
            "visibility": "customer",
        },
    ),
    (
        "POST",
        f"/v1/knowledge/documents/{uuid7()}/versions",
        {
            "source_type": "markdown",
            "source_content": "# Authorization Test",
            "source_name": "authorization-test.md",
        },
    ),
    (
        "POST",
        f"/v1/knowledge/versions/{uuid7()}/process",
        None,
    ),
    (
        "POST",
        f"/v1/knowledge/versions/{uuid7()}/embed",
        None,
    ),
    (
        "POST",
        f"/v1/knowledge/versions/{uuid7()}/publish",
        None,
    ),
    (
        "POST",
        f"/v1/knowledge/documents/{uuid7()}/archive",
        None,
    ),
)

ALL_CASES = tuple(
    (method, path, None)
    for method, path in READ_CASES
) + MUTATION_CASES


def _request(
    client: TestClient,
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
):
    kwargs: dict[str, Any] = {}

    if payload is not None:
        kwargs["json"] = payload

    return client.request(method, path, **kwargs)


class TestKnowledgeAuthentication:
    @pytest.mark.parametrize(
        ("method", "path", "payload"),
        ALL_CASES,
    )
    def test_missing_authentication_is_rejected(
        self,
        client: TestClient,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> None:
        response = _request(
            client,
            method=method,
            path=path,
            payload=payload,
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == (
            "UNAUTHENTICATED"
        )


class TestKnowledgeCustomerAuthorization:
    @pytest.mark.parametrize(
        ("method", "path", "payload"),
        ALL_CASES,
    )
    def test_customer_is_rejected(
        self,
        customer_client: TestClient,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> None:
        response = _request(
            customer_client,
            method=method,
            path=path,
            payload=payload,
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


class TestKnowledgeSupportAgentAuthorization:
    @pytest.mark.parametrize(
        ("method", "path", "payload"),
        ALL_CASES,
    )
    def test_support_agent_is_rejected(
        self,
        support_agent_client: TestClient,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> None:
        response = _request(
            support_agent_client,
            method=method,
            path=path,
            payload=payload,
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


class TestKnowledgeAdministratorAuthorization:
    def test_admin_can_list_documents(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            "/v1/knowledge/documents"
        )

        assert response.status_code == 200

    def test_admin_can_create_document(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.post(
            "/v1/knowledge/documents",
            headers={"X-Trace-ID": str(uuid7())},
            json={
                "title": "Administrator Knowledge",
                "description": "Created by an administrator.",
                "content_type": "policy",
                "visibility": "customer",
            },
        )

        assert response.status_code == 201, response.text

    @pytest.mark.parametrize(
        ("method", "path", "payload"),
        (
            (
                "GET",
                f"/v1/knowledge/documents/{uuid7()}",
                None,
            ),
            (
                "GET",
                f"/v1/knowledge/documents/{uuid7()}/versions",
                None,
            ),
            (
                "GET",
                f"/v1/knowledge/versions/{uuid7()}",
                None,
            ),
            (
                "POST",
                f"/v1/knowledge/documents/{uuid7()}/versions",
                {
                    "source_type": "markdown",
                    "source_content": "# Missing Parent",
                },
            ),
            (
                "POST",
                f"/v1/knowledge/versions/{uuid7()}/process",
                None,
            ),
            (
                "POST",
                f"/v1/knowledge/versions/{uuid7()}/embed",
                None,
            ),
            (
                "POST",
                f"/v1/knowledge/versions/{uuid7()}/publish",
                None,
            ),
            (
                "POST",
                f"/v1/knowledge/documents/{uuid7()}/archive",
                None,
            ),
        ),
    )
    def test_admin_passes_authorization_before_resource_lookup(
        self,
        admin_client: TestClient,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> None:
        response = _request(
            admin_client,
            method=method,
            path=path,
            payload=payload,
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "KNOWLEDGE_NOT_FOUND"
        )