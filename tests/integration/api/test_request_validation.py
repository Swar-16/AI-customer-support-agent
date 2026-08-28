from __future__ import annotations
import uuid
import pytest
from fastapi.testclient import TestClient

class TestRequestValidation:
    def test_rejects_empty_message(self, client: TestClient, seeded_conversation: uuid.UUID) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            json={ "message": "" }
        )

        assert response.status_code == 422
        
        body = response.json()
        
        assert body["error"]["code"] == "INVALID_REQUEST"

    @pytest.mark.parametrize("message", [" ", "   ", "\t", "\n", "\r\n"])
    def test_rejects_blank_message(self, client: TestClient, seeded_conversation: uuid.UUID, message: str) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            json={ "message": message }
        )

        assert response.status_code == 422

    def test_rejects_message_above_maximum_length(self, client: TestClient, seeded_conversation: uuid.UUID) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            json={ "message": "x" * 20_001 },
        )

        assert response.status_code == 422

    def test_accepts_message_at_maximum_length(self, client: TestClient, seeded_conversation: uuid.UUID) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            json={ "message": "x" * 20_000 }
        )

        assert response.status_code == 200

    def test_rejects_invalid_conversation_uuid(self, client: TestClient) -> None:
        response = client.post(
            "/v1/conversations/not-a-uuid/messages",
            json={ "message": "Hello" }
        )

        assert response.status_code == 422