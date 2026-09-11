# AI-customer-support-agent\tests\integration\api\test_dashboard_retrieval_runs.py

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.ai.embedding_call import (
    EmbeddingCallModel,
)
from packages.database.models.ai.reranker_call import (
    RerankerCallModel,
)
from packages.database.models.ai.retrieval_run import (
    RetrievalRunModel,
)


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolate_database(clean_database):
    """Keep retrieval dashboard assertions isolated."""
    yield


def _create_ai_run(
    *,
    client: TestClient,
    conversation_id: uuid.UUID,
    trace_id: uuid.UUID,
) -> dict[str, Any]:
    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers={
            "X-Trace-ID": str(trace_id),
        },
        json={
            "message": "Where is my order ORD-12345?",
        },
    )

    assert response.status_code == 200

    return response.json()


def _seed_retrieval_run(
    *,
    client: TestClient,
    test_session_factory,
    conversation_id: uuid.UUID,
    trace_id: uuid.UUID | None = None,
    retrieval_mode: str = "hybrid",
    zero_result: bool = False,
    reranker_used: bool = True,
) -> dict[str, uuid.UUID]:
    resolved_trace_id = trace_id or uuid7()

    ai_result = _create_ai_run(
        client=client,
        conversation_id=conversation_id,
        trace_id=resolved_trace_id,
    )

    ai_run_id = uuid.UUID(ai_result["ai_run_id"])
    embedding_call_id = uuid7()
    retrieval_run_id = uuid7()

    started_at = datetime.now(timezone.utc)
    embedding_completed_at = (
        started_at + timedelta(milliseconds=2)
    )
    retrieval_completed_at = (
        started_at + timedelta(milliseconds=12)
    )

    selected_count = 0 if zero_result else 2
    context_block_count = 0 if zero_result else 2
    context_token_count = 0 if zero_result else 120

    with test_session_factory() as session:
        embedding_call = EmbeddingCallModel(
            id=embedding_call_id,
            ai_run_id=ai_run_id,
            trace_id=resolved_trace_id,
            knowledge_version_id=None,
            purpose="query",
            provider="integration-test",
            model="deterministic-v1",
            provider_revision="test-revision",
            input_count=1,
            total_input_characters=32,
            request_fingerprint="a" * 64,
            dimensions=3,
            latency_ms=2,
            status="success",
            provider_request_id=None,
            error_code=None,
            error_message=None,
            metadata_={},
            started_at=started_at,
            completed_at=embedding_completed_at,
        )
        session.add(embedding_call)
        session.flush()

        retrieval_run = RetrievalRunModel(
            id=retrieval_run_id,
            ai_run_id=ai_run_id,
            embedding_call_id=embedding_call_id,
            trace_id=resolved_trace_id,
            conversation_id=conversation_id,
            retrieval_mode=retrieval_mode,
            profile_identity="integration-test-profile",
            configuration_fingerprint="b" * 64,
            query_fingerprint="c" * 64,
            query_character_count=32,
            requested_limit=5,
            vector_candidate_count=3,
            lexical_candidate_count=2,
            fused_candidate_count=4,
            reranked_candidate_count=(
                2 if reranker_used else 0
            ),
            selected_candidate_count=selected_count,
            context_block_count=context_block_count,
            context_token_count=context_token_count,
            reranker_used=reranker_used,
            context_truncated=False,
            zero_result=zero_result,
            vector_latency_ms=3,
            lexical_latency_ms=2,
            fusion_latency_ms=1,
            reranker_latency_ms=(
                2 if reranker_used else None
            ),
            context_build_latency_ms=1,
            total_latency_ms=12,
            status="success",
            error_code=None,
            error_message=None,
            metadata_={},
            started_at=started_at,
            completed_at=retrieval_completed_at,
        )
        session.add(retrieval_run)
        session.flush()

        if reranker_used:
            reranker_call = RerankerCallModel(
                id=uuid7(),
                retrieval_run_id=retrieval_run_id,
                trace_id=resolved_trace_id,
                reranker_id="integration-test-reranker",
                provider="integration-test",
                model="passthrough-v1",
                revision="test-revision",
                query_fingerprint="c" * 64,
                input_candidate_count=4,
                requested_limit=2,
                output_candidate_count=2,
                latency_ms=2,
                status="success",
                provider_request_id=None,
                error_code=None,
                error_message=None,
                metadata_={},
                started_at=started_at,
                completed_at=(
                    started_at
                    + timedelta(milliseconds=2)
                ),
            )
            session.add(reranker_call)

        session.commit()

    return {
        "trace_id": resolved_trace_id,
        "ai_run_id": ai_run_id,
        "embedding_call_id": embedding_call_id,
        "retrieval_run_id": retrieval_run_id,
    }


class TestDashboardRetrievalRuns:
    def test_returns_correlated_retrieval_run(
        self,
        client: TestClient,
        test_session_factory,
        seeded_conversation: uuid.UUID,
    ) -> None:
        identifiers = _seed_retrieval_run(
            client=client,
            test_session_factory=test_session_factory,
            conversation_id=seeded_conversation,
        )

        response = client.get(
            "/v1/dashboard/retrieval-runs",
            params={
                "trace_id": str(identifiers["trace_id"]),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1
        assert body["has_more"] is False
        assert body["next_offset"] is None

        run = body["items"][0]

        assert run["id"] == str(
            identifiers["retrieval_run_id"]
        )
        assert run["ai_run_id"] == str(
            identifiers["ai_run_id"]
        )
        assert run["trace_id"] == str(
            identifiers["trace_id"]
        )
        assert run["conversation_id"] == str(
            seeded_conversation
        )
        assert run["embedding_call_id"] == str(
            identifiers["embedding_call_id"]
        )

        assert run["retrieval_mode"] == "hybrid"
        assert (
            run["profile_identity"]
            == "integration-test-profile"
        )
        assert run["status"] == "success"
        assert run["zero_result"] is False
        assert run["reranker_used"] is True

        assert run["vector_candidate_count"] == 3
        assert run["lexical_candidate_count"] == 2
        assert run["fused_candidate_count"] == 4
        assert run["reranked_candidate_count"] == 2
        assert run["selected_candidate_count"] == 2
        assert run["context_block_count"] == 2
        assert run["context_token_count"] == 120

        assert run["embedding_provider"] == (
            "integration-test"
        )
        assert run["embedding_model"] == (
            "deterministic-v1"
        )
        assert run["embedding_status"] == "success"
        assert run["embedding_dimensions"] == 3
        assert run["embedding_latency_ms"] == 2

        assert run["reranker_call_count"] == 1
        assert run["failed_reranker_call_count"] == 0
        assert (
            run["maximum_reranker_call_latency_ms"]
            == 2
        )

    def test_filters_by_correlation_and_configuration(
        self,
        client: TestClient,
        test_session_factory,
        seeded_conversation: uuid.UUID,
    ) -> None:
        identifiers = _seed_retrieval_run(
            client=client,
            test_session_factory=test_session_factory,
            conversation_id=seeded_conversation,
            retrieval_mode="hybrid",
            zero_result=False,
            reranker_used=True,
        )

        response = client.get(
            "/v1/dashboard/retrieval-runs",
            params={
                "trace_id": str(identifiers["trace_id"]),
                "conversation_id": str(
                    seeded_conversation
                ),
                "ai_run_id": str(
                    identifiers["ai_run_id"]
                ),
                "retrieval_mode": "hybrid",
                "profile_identity": (
                    "integration-test-profile"
                ),
                "status": "success",
                "zero_result": "false",
                "reranker_used": "true",
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["items"][0]["id"] == str(
            identifiers["retrieval_run_id"]
        )

    def test_filters_zero_result_queries(
        self,
        client: TestClient,
        test_session_factory,
        seeded_conversation: uuid.UUID,
    ) -> None:
        identifiers = _seed_retrieval_run(
            client=client,
            test_session_factory=test_session_factory,
            conversation_id=seeded_conversation,
            zero_result=True,
            reranker_used=False,
        )

        response = client.get(
            "/v1/dashboard/retrieval-runs",
            params={
                "trace_id": str(identifiers["trace_id"]),
                "zero_result": "true",
                "reranker_used": "false",
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1

        run = body["items"][0]

        assert run["zero_result"] is True
        assert run["selected_candidate_count"] == 0
        assert run["context_block_count"] == 0
        assert run["context_token_count"] == 0
        assert run["reranker_used"] is False
        assert run["reranker_call_count"] == 0

    def test_non_matching_filter_returns_empty_page(
        self,
        client: TestClient,
        test_session_factory,
        seeded_conversation: uuid.UUID,
    ) -> None:
        _seed_retrieval_run(
            client=client,
            test_session_factory=test_session_factory,
            conversation_id=seeded_conversation,
        )

        response = client.get(
            "/v1/dashboard/retrieval-runs",
            params={
                "trace_id": str(uuid7()),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["items"] == []
        assert body["total"] == 0
        assert body["count"] == 0
        assert body["has_more"] is False
        assert body["next_offset"] is None

    def test_paginates_without_duplicates(
        self,
        client: TestClient,
        test_session_factory,
        seeded_conversation: uuid.UUID,
    ) -> None:
        _seed_retrieval_run(
            client=client,
            test_session_factory=test_session_factory,
            conversation_id=seeded_conversation,
        )
        _seed_retrieval_run(
            client=client,
            test_session_factory=test_session_factory,
            conversation_id=seeded_conversation,
        )

        first_response = client.get(
            "/v1/dashboard/retrieval-runs",
            params={
                "limit": 1,
                "offset": 0,
            },
        )
        second_response = client.get(
            "/v1/dashboard/retrieval-runs",
            params={
                "limit": 1,
                "offset": 1,
            },
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200

        first_body = first_response.json()
        second_body = second_response.json()

        assert first_body["total"] == 2
        assert second_body["total"] == 2
        assert first_body["count"] == 1
        assert second_body["count"] == 1

        assert first_body["has_more"] is True
        assert first_body["next_offset"] == 1
        assert second_body["has_more"] is False
        assert second_body["next_offset"] is None

        assert (
            first_body["items"][0]["id"]
            != second_body["items"][0]["id"]
        )

    def test_rejects_invalid_filters(
        self,
        client: TestClient,
    ) -> None:
        invalid_mode = client.get(
            "/v1/dashboard/retrieval-runs",
            params={
                "retrieval_mode": "semantic-magic",
            },
        )
        invalid_status = client.get(
            "/v1/dashboard/retrieval-runs",
            params={
                "status": "unknown",
            },
        )

        assert invalid_mode.status_code == 422
        assert invalid_status.status_code == 422

    def test_does_not_expose_sensitive_retrieval_data(
        self,
        client: TestClient,
        test_session_factory,
        seeded_conversation: uuid.UUID,
    ) -> None:
        identifiers = _seed_retrieval_run(
            client=client,
            test_session_factory=test_session_factory,
            conversation_id=seeded_conversation,
        )

        response = client.get(
            "/v1/dashboard/retrieval-runs",
            params={
                "trace_id": str(identifiers["trace_id"]),
            },
        )

        assert response.status_code == 200

        run = response.json()["items"][0]

        prohibited_fields = {
            "query",
            "query_text",
            "content",
            "source_content",
            "vector",
            "embedding",
            "error_message",
            "provider_request_id",
            "metadata",
            "metadata_",
        }

        assert set(run).isdisjoint(prohibited_fields)