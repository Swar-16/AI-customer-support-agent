from __future__ import annotations
import uuid
from uuid6 import uuid7
from fastapi.testclient import TestClient

from packages.database.models.ai.run import AIRunModel

class TestTracePropagation:
    def test_preserves_client_trace_id(self, client: TestClient, seeded_conversation: uuid.UUID, test_session_factory) -> None:
        trace_id = uuid7()
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            headers={ "X-Trace-ID": str(trace_id) },
            json={ "message": "Where is my order ORD-12345?" }
        )

        assert response.status_code == 200

        body = response.json()

        assert body["trace_id"] == str(trace_id)

        ai_run_id = uuid.UUID(body["ai_run_id"])

        with test_session_factory() as session:
            ai_run = session.get(AIRunModel, ai_run_id)

            assert ai_run is not None
            assert ai_run.trace_id == trace_id

    def test_generates_trace_id_when_absent(self, client: TestClient, seeded_conversation: uuid.UUID) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            json={ "message": "Where is my order ORD-12345?" }
        )

        assert response.status_code == 200

        trace_id = uuid.UUID(response.json()["trace_id"])

        assert isinstance(trace_id, uuid.UUID)

    def test_rejects_invalid_trace_id(self, client: TestClient, seeded_conversation: uuid.UUID) -> None:
        response = client.post(
            f"/v1/conversations/{seeded_conversation}/messages",
            headers={ "X-Trace-ID": "invalid-trace-id" },
            json={ "message": "Hello" },
        )

        assert response.status_code == 400

        body = response.json()

        assert body["error"]["code"] == "INVALID_TRACE_ID"