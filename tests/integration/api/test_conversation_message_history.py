# AI-customer-support-agent\tests\integration\api\test_conversation_message_history.py
from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.support.conversation import (
    ConversationModel,
)
from packages.database.models.support.message import MessageModel


@dataclass(frozen=True, slots=True)
class MessageHistoryContext:
    owner_conversation_id: uuid.UUID
    other_conversation_id: uuid.UUID
    owner_headers: dict[str, str]
    other_customer_headers: dict[str, str]
    agent_headers: dict[str, str]
    admin_headers: dict[str, str]


@pytest.fixture()
def message_history_context(
    authenticated_identity_factory,
    test_session_factory,
) -> MessageHistoryContext:
    owner = authenticated_identity_factory(
        role="customer",
    )
    other_customer = authenticated_identity_factory(
        role="customer",
    )
    agent = authenticated_identity_factory(
        role="support_agent",
    )
    admin = authenticated_identity_factory(
        role="admin",
    )

    owner_conversation_id = uuid7()
    other_conversation_id = uuid7()

    with test_session_factory() as session:
        session.add_all(
            [
                ConversationModel(
                    id=owner_conversation_id,
                    user_id=owner.user_id,
                    status="open",
                    channel="web",
                    title="Owner conversation",
                    next_message_sequence=6,
                ),
                ConversationModel(
                    id=other_conversation_id,
                    user_id=other_customer.user_id,
                    status="open",
                    channel="web",
                    title="Other customer conversation",
                    next_message_sequence=2,
                ),
            ]
        )
        session.flush()

        session.add_all(
            [
                MessageModel(
                    id=uuid7(),
                    conversation_id=owner_conversation_id,
                    role="customer",
                    content="Where is my order?",
                    sequence_number=1,
                    metadata_={
                        "private_value": "must-not-be-returned",
                    },
                ),
                MessageModel(
                    id=uuid7(),
                    conversation_id=owner_conversation_id,
                    role="system",
                    content="Internal orchestration instruction",
                    sequence_number=2,
                    metadata_={
                        "prompt": "private-system-prompt",
                    },
                ),
                MessageModel(
                    id=uuid7(),
                    conversation_id=owner_conversation_id,
                    role="assistant",
                    content="I am checking your order.",
                    sequence_number=3,
                    metadata_={
                        "provider_payload": "must-not-be-returned",
                    },
                ),
                MessageModel(
                    id=uuid7(),
                    conversation_id=owner_conversation_id,
                    role="tool",
                    content="Internal tool result",
                    sequence_number=4,
                    metadata_={
                        "tool_secret": "must-not-be-returned",
                    },
                ),
                MessageModel(
                    id=uuid7(),
                    conversation_id=owner_conversation_id,
                    role="support_agent",
                    content="A support agent has joined.",
                    sequence_number=5,
                    metadata_={
                        "internal_note": "must-not-be-returned",
                    },
                ),
                MessageModel(
                    id=uuid7(),
                    conversation_id=other_conversation_id,
                    role="customer",
                    content="Another customer's message",
                    sequence_number=1,
                    metadata_={},
                ),
            ]
        )

        session.commit()

    return MessageHistoryContext(
        owner_conversation_id=owner_conversation_id,
        other_conversation_id=other_conversation_id,
        owner_headers=owner.authorization_headers,
        other_customer_headers=(
            other_customer.authorization_headers
        ),
        agent_headers=agent.authorization_headers,
        admin_headers=admin.authorization_headers,
    )


class TestCustomerMessageHistory:
    def test_customer_lists_owned_visible_messages(
        self,
        client: TestClient,
        message_history_context: MessageHistoryContext,
    ) -> None:
        response = client.get(
            (
                "/v1/conversations/"
                f"{message_history_context.owner_conversation_id}"
                "/messages"
            ),
            headers=message_history_context.owner_headers,
        )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["total"] == 3
        assert body["count"] == 3
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert body["has_more"] is False
        assert body["next_offset"] is None

        assert [
            item["sequence_number"]
            for item in body["items"]
        ] == [1, 3, 5]

        assert [
            item["role"]
            for item in body["items"]
        ] == [
            "customer",
            "assistant",
            "support_agent",
        ]

        assert [
            item["content"]
            for item in body["items"]
        ] == [
            "Where is my order?",
            "I am checking your order.",
            "A support agent has joined.",
        ]

    def test_customer_cannot_read_another_customers_messages(
        self,
        client: TestClient,
        message_history_context: MessageHistoryContext,
    ) -> None:
        response = client.get(
            (
                "/v1/conversations/"
                f"{message_history_context.other_conversation_id}"
                "/messages"
            ),
            headers=message_history_context.owner_headers,
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "CONVERSATION_NOT_FOUND"
        )

    def test_response_does_not_expose_message_metadata(
        self,
        client: TestClient,
        message_history_context: MessageHistoryContext,
    ) -> None:
        response = client.get(
            (
                "/v1/conversations/"
                f"{message_history_context.owner_conversation_id}"
                "/messages"
            ),
            headers=message_history_context.owner_headers,
        )

        assert response.status_code == 200

        for item in response.json()["items"]:
            assert "metadata" not in item
            assert "metadata_" not in item
            assert "prompt" not in item
            assert "reasoning" not in item
            assert "provider_payload" not in item

    def test_system_and_tool_messages_are_excluded(
        self,
        client: TestClient,
        message_history_context: MessageHistoryContext,
    ) -> None:
        response = client.get(
            (
                "/v1/conversations/"
                f"{message_history_context.owner_conversation_id}"
                "/messages"
            ),
            headers=message_history_context.owner_headers,
        )

        assert response.status_code == 200

        roles = {
            item["role"]
            for item in response.json()["items"]
        }
        contents = {
            item["content"]
            for item in response.json()["items"]
        }

        assert "system" not in roles
        assert "tool" not in roles
        assert "Internal orchestration instruction" not in contents
        assert "Internal tool result" not in contents


class TestMessageHistoryPagination:
    def test_paginates_visible_messages_chronologically(
        self,
        client: TestClient,
        message_history_context: MessageHistoryContext,
    ) -> None:
        path = (
            "/v1/conversations/"
            f"{message_history_context.owner_conversation_id}"
            "/messages"
        )

        first_response = client.get(
            path,
            headers=message_history_context.owner_headers,
            params={
                "limit": 2,
                "offset": 0,
            },
        )

        assert first_response.status_code == 200
        first_page = first_response.json()

        assert first_page["total"] == 3
        assert first_page["count"] == 2
        assert first_page["has_more"] is True
        assert first_page["next_offset"] == 2
        assert [
            item["sequence_number"]
            for item in first_page["items"]
        ] == [1, 3]

        second_response = client.get(
            path,
            headers=message_history_context.owner_headers,
            params={
                "limit": 2,
                "offset": first_page["next_offset"],
            },
        )

        assert second_response.status_code == 200
        second_page = second_response.json()

        assert second_page["total"] == 3
        assert second_page["count"] == 1
        assert second_page["has_more"] is False
        assert second_page["next_offset"] is None
        assert [
            item["sequence_number"]
            for item in second_page["items"]
        ] == [5]

        first_ids = {
            item["message_id"]
            for item in first_page["items"]
        }
        second_ids = {
            item["message_id"]
            for item in second_page["items"]
        }

        assert first_ids.isdisjoint(second_ids)


class TestAdministrativeMessageHistory:
    def test_admin_can_read_customer_conversation(
        self,
        client: TestClient,
        message_history_context: MessageHistoryContext,
    ) -> None:
        response = client.get(
            (
                "/v1/conversations/"
                f"{message_history_context.owner_conversation_id}"
                "/messages"
            ),
            headers=message_history_context.admin_headers,
        )

        assert response.status_code == 200
        assert response.json()["total"] == 3

    def test_support_agent_is_denied_without_assignment(
        self,
        client: TestClient,
        message_history_context: MessageHistoryContext,
    ) -> None:
        response = client.get(
            (
                "/v1/conversations/"
                f"{message_history_context.owner_conversation_id}"
                "/messages"
            ),
            headers=message_history_context.agent_headers,
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == (
            "CONVERSATION_ACCESS_DENIED"
        )


class TestMessageHistoryAuthentication:
    def test_missing_authentication_returns_401(
        self,
        client: TestClient,
        message_history_context: MessageHistoryContext,
    ) -> None:
        response = client.get(
            (
                "/v1/conversations/"
                f"{message_history_context.owner_conversation_id}"
                "/messages"
            )
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == (
            "UNAUTHENTICATED"
        )

    def test_missing_conversation_returns_404(
        self,
        client: TestClient,
        message_history_context: MessageHistoryContext,
    ) -> None:
        response = client.get(
            f"/v1/conversations/{uuid7()}/messages",
            headers=message_history_context.admin_headers,
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "CONVERSATION_NOT_FOUND"
        )

    @pytest.mark.parametrize(
        ("limit", "offset"),
        [
            (0, 0),
            (201, 0),
            (50, -1),
        ],
    )
    def test_rejects_invalid_pagination(
        self,
        client: TestClient,
        message_history_context: MessageHistoryContext,
        limit: int,
        offset: int,
    ) -> None:
        response = client.get(
            (
                "/v1/conversations/"
                f"{message_history_context.owner_conversation_id}"
                "/messages"
            ),
            headers=message_history_context.owner_headers,
            params={
                "limit": limit,
                "offset": offset,
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "INVALID_REQUEST"
        )