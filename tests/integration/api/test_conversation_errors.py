from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.ai.run import AIRunModel
from packages.database.models.support.message import MessageModel


class TestConversationErrors:

    def test_returns_404_for_unknown_conversation(
        self,
        client: TestClient,
    ) -> None:
        conversation_id = uuid7()

        response = client.post(
            f"/v1/conversations/{conversation_id}/messages",
            json={
                "message": "Hello",
            },
        )

        assert response.status_code == 404

        body = response.json()

        assert body["error"]["code"] == (
            "CONVERSATION_NOT_FOUND"
        )

        assert body["error"]["message"]
        assert uuid.UUID(
            body["error"]["trace_id"]
        )


    def test_unknown_conversation_creates_no_partial_writes(
        self,
        client: TestClient,
        test_session_factory,
    ) -> None:
        conversation_id = uuid7()

        response = client.post(
            f"/v1/conversations/{conversation_id}/messages",
            json={
                "message": "Hello",
            },
        )

        assert response.status_code == 404

        with test_session_factory() as session:
            message_count = (
                session.query(MessageModel)
                .filter(
                    MessageModel.conversation_id
                    == conversation_id
                )
                .count()
            )

            ai_run_count = (
                session.query(AIRunModel)
                .filter(
                    AIRunModel.conversation_id
                    == conversation_id
                )
                .count()
            )

            assert message_count == 0
            assert ai_run_count == 0