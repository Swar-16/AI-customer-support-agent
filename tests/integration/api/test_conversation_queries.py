# AI-customer-support-agent\tests\integration\api\test_conversation_queries.py
from __future__ import annotations

from uuid6 import uuid7
from typing import Any

from fastapi.testclient import TestClient


def _create_conversation(
    client: TestClient,
    identity,
    *,
    channel: str = "web",
    title: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "channel": channel,
    }

    if title is not None:
        payload["title"] = title

    response = client.post(
        "/v1/conversations",
        headers=identity.authorization_headers,
        json=payload,
    )

    assert response.status_code == 201, response.text
    return response.json()


class TestCustomerConversationQueries:
    def test_customer_lists_only_owned_conversations(
        self,
        client: TestClient,
        customer_identity,
        authenticated_identity_factory,
    ) -> None:
        other_customer = authenticated_identity_factory(
            role="customer",
            email="conversation-list-other@example.com",
        )

        first = _create_conversation(
            client,
            customer_identity,
            title="First owned conversation",
        )
        second = _create_conversation(
            client,
            customer_identity,
            channel="mobile",
            title="Second owned conversation",
        )
        _create_conversation(
            client,
            other_customer,
            title="Another customer's conversation",
        )

        response = client.get(
            "/v1/conversations",
            headers=customer_identity.authorization_headers,
        )

        assert response.status_code == 200, response.text

        body = response.json()
        returned_ids = {
            item["conversation_id"]
            for item in body["items"]
        }

        assert body["total"] == 2
        assert body["count"] == 2
        assert body["has_more"] is False
        assert body["next_offset"] is None
        assert returned_ids == {
            first["conversation_id"],
            second["conversation_id"],
        }

        assert all(
            item["customer_id"]
            == str(customer_identity.user_id)
            for item in body["items"]
        )

    def test_customer_gets_owned_conversation(
        self,
        client: TestClient,
        customer_identity,
    ) -> None:
        created = _create_conversation(
            client,
            customer_identity,
            channel="mobile",
            title="Owned conversation",
        )

        response = client.get(
            f"/v1/conversations/"
            f"{created['conversation_id']}",
            headers=customer_identity.authorization_headers,
        )

        assert response.status_code == 200, response.text

        body = response.json()

        assert (
            body["conversation_id"]
            == created["conversation_id"]
        )
        assert body["customer_id"] == str(
            customer_identity.user_id
        )
        assert body["channel"] == "mobile"
        assert body["title"] == "Owned conversation"
        assert body["status"] == "open"

    def test_cross_customer_detail_is_concealed(
        self,
        client: TestClient,
        customer_identity,
        authenticated_identity_factory,
    ) -> None:
        other_customer = authenticated_identity_factory(
            role="customer",
            email="conversation-detail-other@example.com",
        )

        created = _create_conversation(
            client,
            customer_identity,
        )

        response = client.get(
            f"/v1/conversations/"
            f"{created['conversation_id']}",
            headers=other_customer.authorization_headers,
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "CONVERSATION_NOT_FOUND"
        )
        assert response.json()["error"]["trace_id"] == (
            response.headers["X-Trace-ID"]
        )

    def test_customer_cannot_filter_by_another_customer(
        self,
        client: TestClient,
        customer_identity,
        authenticated_identity_factory,
    ) -> None:
        other_customer = authenticated_identity_factory(
            role="customer",
            email="conversation-filter-other@example.com",
        )

        response = client.get(
            "/v1/conversations",
            headers=customer_identity.authorization_headers,
            params={
                "customer_id": str(other_customer.user_id),
            },
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == (
            "CONVERSATION_ACCESS_DENIED"
        )

    def test_customer_filters_owned_conversations(
        self,
        client: TestClient,
        customer_identity,
    ) -> None:
        web_conversation = _create_conversation(
            client,
            customer_identity,
            channel="web",
            title="Web conversation",
        )
        _create_conversation(
            client,
            customer_identity,
            channel="mobile",
            title="Mobile conversation",
        )

        response = client.get(
            "/v1/conversations",
            headers=customer_identity.authorization_headers,
            params={
                "status": "open",
                "channel": "web",
            },
        )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1
        assert (
            body["items"][0]["conversation_id"]
            == web_conversation["conversation_id"]
        )


class TestAdministrativeConversationQueries:
    def test_admin_can_get_customer_conversation(
        self,
        client: TestClient,
        customer_identity,
        admin_identity,
    ) -> None:
        created = _create_conversation(
            client,
            customer_identity,
            title="Administrator-visible conversation",
        )

        response = client.get(
            f"/v1/conversations/"
            f"{created['conversation_id']}",
            headers=admin_identity.authorization_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["conversation_id"] == (
            created["conversation_id"]
        )

    def test_admin_can_filter_by_customer(
        self,
        client: TestClient,
        customer_identity,
        admin_identity,
        authenticated_identity_factory,
    ) -> None:
        other_customer = authenticated_identity_factory(
            role="customer",
            email="conversation-admin-filter@example.com",
        )

        owned = _create_conversation(
            client,
            customer_identity,
            title="Target customer conversation",
        )
        _create_conversation(
            client,
            other_customer,
            title="Other customer conversation",
        )

        response = client.get(
            "/v1/conversations",
            headers=admin_identity.authorization_headers,
            params={
                "customer_id": str(customer_identity.user_id),
            },
        )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1
        assert body["items"][0]["conversation_id"] == (
            owned["conversation_id"]
        )
        assert body["items"][0]["customer_id"] == str(
            customer_identity.user_id
        )

    def test_admin_can_list_all_conversations(
        self,
        client: TestClient,
        customer_identity,
        admin_identity,
        authenticated_identity_factory,
    ) -> None:
        other_customer = authenticated_identity_factory(
            role="customer",
            email="conversation-admin-list@example.com",
        )

        first = _create_conversation(
            client,
            customer_identity,
        )
        second = _create_conversation(
            client,
            other_customer,
        )

        response = client.get(
            "/v1/conversations",
            headers=admin_identity.authorization_headers,
        )

        assert response.status_code == 200, response.text

        body = response.json()
        returned_ids = {
            item["conversation_id"]
            for item in body["items"]
        }

        assert body["total"] == 2
        assert returned_ids == {
            first["conversation_id"],
            second["conversation_id"],
        }


class TestConversationQueryPagination:
    def test_paginates_without_duplicate_conversations(
        self,
        client: TestClient,
        customer_identity,
    ) -> None:
        created_ids = {
            _create_conversation(
                client,
                customer_identity,
                title=f"Conversation {index}",
            )["conversation_id"]
            for index in range(3)
        }

        first_response = client.get(
            "/v1/conversations",
            headers=customer_identity.authorization_headers,
            params={
                "limit": 2,
                "offset": 0,
            },
        )
        second_response = client.get(
            "/v1/conversations",
            headers=customer_identity.authorization_headers,
            params={
                "limit": 2,
                "offset": 2,
            },
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200

        first = first_response.json()
        second = second_response.json()

        assert first["total"] == 3
        assert first["count"] == 2
        assert first["has_more"] is True
        assert first["next_offset"] == 2

        assert second["total"] == 3
        assert second["count"] == 1
        assert second["has_more"] is False
        assert second["next_offset"] is None

        first_ids = {
            item["conversation_id"]
            for item in first["items"]
        }
        second_ids = {
            item["conversation_id"]
            for item in second["items"]
        }

        assert first_ids.isdisjoint(second_ids)
        assert first_ids | second_ids == created_ids


class TestConversationQueryAuthorization:
    def test_missing_authentication_returns_401(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/v1/conversations")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == (
            "UNAUTHENTICATED"
        )

    def test_support_agent_cannot_list_without_assignment(
        self,
        client: TestClient,
        support_agent_identity,
    ) -> None:
        response = client.get(
            "/v1/conversations",
            headers=(
                support_agent_identity.authorization_headers
            ),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == (
            "CONVERSATION_ACCESS_DENIED"
        )

    def test_support_agent_cannot_get_without_assignment(
        self,
        client: TestClient,
        customer_identity,
        support_agent_identity,
    ) -> None:
        created = _create_conversation(
            client,
            customer_identity,
        )

        response = client.get(
            f"/v1/conversations/"
            f"{created['conversation_id']}",
            headers=(
                support_agent_identity.authorization_headers
            ),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == (
            "CONVERSATION_ACCESS_DENIED"
        )

    def test_missing_conversation_returns_404(
        self,
        client: TestClient,
        customer_identity,
    ) -> None:
        missing_id = uuid7()

        response = client.get(
            f"/v1/conversations/{missing_id}",
            headers=customer_identity.authorization_headers,
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "CONVERSATION_NOT_FOUND"
        )
        assert response.json()["error"]["trace_id"] == (
            response.headers["X-Trace-ID"]
        )