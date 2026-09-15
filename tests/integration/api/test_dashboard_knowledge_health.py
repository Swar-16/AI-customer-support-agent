# AI-customer-support-agent\tests\integration\api\test_dashboard_knowledge_health.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from uuid6 import uuid7

from packages.database.models.knowledge.chunk import (
    KnowledgeChunkModel,
)
from packages.database.models.knowledge.chunk_embedding import (
    KnowledgeChunkEmbeddingModel,
)
from packages.database.models.knowledge.document import (
    KnowledgeDocumentModel,
)
from packages.database.models.knowledge.document_version import (
    KnowledgeDocumentVersionModel,
)


_ENDPOINT = "/v1/dashboard/knowledge-health"


def _analytics_params(
    *,
    started_at: datetime,
    ended_at: datetime,
    bucket: str = "day",
) -> dict[str, str]:
    return {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "bucket": bucket,
    }


def _distribution(
    items: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        str(item["category"]): int(item["count"])
        for item in items
    }


def _document(
    *,
    document_id: UUID,
    title: str,
    content_type: str,
    visibility: str,
    status: str,
    created_at: datetime,
) -> KnowledgeDocumentModel:
    archived_at = (
        created_at + timedelta(hours=1)
        if status == "archived"
        else None
    )
    deleted_at = (
        created_at + timedelta(hours=1)
        if status == "deleted"
        else None
    )
    updated_at = archived_at or deleted_at or created_at

    return KnowledgeDocumentModel(
        id=document_id,
        title=title,
        description="Knowledge health integration fixture.",
        content_type=content_type,
        visibility=visibility,
        status=status,
        metadata_={},
        created_at=created_at,
        updated_at=updated_at,
        archived_at=archived_at,
        deleted_at=deleted_at,
    )


def _version(
    *,
    version_id: UUID,
    document_id: UUID,
    version_number: int,
    created_at: datetime,
    status: str,
    ingestion_status: str,
    processing_started_at: datetime | None = None,
    processing_completed_at: datetime | None = None,
    failure_code: str | None = None,
    failure_message: str | None = None,
) -> KnowledgeDocumentVersionModel:
    ready_at = (
        processing_completed_at
        if status in ("ready", "published")
        else None
    )
    published_at = (
        processing_completed_at
        if status == "published"
        else None
    )

    updated_at = (
        processing_completed_at
        or processing_started_at
        or created_at
    )

    return KnowledgeDocumentVersionModel(
        id=version_id,
        document_id=document_id,
        version_number=version_number,
        source_type="markdown",
        source_content=(
            "# Private source\n\n"
            "SECRET_SOURCE_CONTENT_MUST_NOT_APPEAR"
        ),
        content_hash=f"{version_number:064x}",
        source_name=f"fixture-v{version_number}.md",
        source_uri=None,
        metadata_={},
        status=status,
        ingestion_status=ingestion_status,
        processing_started_at=processing_started_at,
        processing_completed_at=processing_completed_at,
        ready_at=ready_at,
        published_at=published_at,
        superseded_at=None,
        archived_at=None,
        failure_code=failure_code,
        failure_message=failure_message,
        created_at=created_at,
        updated_at=updated_at,
    )


def _chunk(
    *,
    chunk_id: UUID,
    version_id: UUID,
    chunk_index: int,
    created_at: datetime,
) -> KnowledgeChunkModel:
    return KnowledgeChunkModel(
        id=chunk_id,
        version_id=version_id,
        chunk_index=chunk_index,
        content="Sensitive derived chunk content.",
        section_title="Private section",
        start_offset=None,
        end_offset=None,
        token_count=5,
        metadata_={},
        created_at=created_at,
        updated_at=created_at,
    )


def _embedding(
    *,
    embedding_id: UUID,
    chunk_id: UUID,
    created_at: datetime,
    fingerprint_character: str,
) -> KnowledgeChunkEmbeddingModel:
    fingerprint = fingerprint_character * 64

    return KnowledgeChunkEmbeddingModel(
        id=embedding_id,
        chunk_id=chunk_id,
        provider="integration-provider",
        model="integration-model",
        model_revision="1",
        dimensions=3,
        embedding=[0.1, 0.2, 0.3],
        input_strategy_id="integration-contextual",
        input_strategy_version="1",
        input_config_fingerprint=fingerprint,
        input_fingerprint=fingerprint,
        created_at=created_at,
    )


def _seed_knowledge_health(
    *,
    test_session_factory,
    started_at: datetime,
) -> None:
    active_policy_id = uuid7()
    active_faq_id = uuid7()
    archived_guide_id = uuid7()

    ready_version_id = uuid7()
    published_version_id = uuid7()
    draft_version_id = uuid7()
    failed_version_id = uuid7()
    processing_version_id = uuid7()

    ready_started = started_at + timedelta(hours=1)
    ready_completed = ready_started + timedelta(hours=1)

    published_started = started_at + timedelta(
        days=1,
        hours=1,
    )
    published_completed = published_started + timedelta(hours=2)

    failed_started = started_at + timedelta(
        days=2,
        hours=1,
    )
    failed_completed = failed_started + timedelta(hours=3)

    ready_chunk_one_id = uuid7()
    ready_chunk_two_id = uuid7()
    published_chunk_id = uuid7()

    with test_session_factory() as session:
        session.add_all(
            [
                _document(
                    document_id=active_policy_id,
                    title="Active Policy",
                    content_type="policy",
                    visibility="customer",
                    status="active",
                    created_at=started_at - timedelta(days=5),
                ),
                _document(
                    document_id=active_faq_id,
                    title="Active FAQ",
                    content_type="faq",
                    visibility="both",
                    status="active",
                    created_at=started_at - timedelta(days=4),
                ),
                _document(
                    document_id=archived_guide_id,
                    title="Archived Internal Guide",
                    content_type="guide",
                    visibility="internal",
                    status="archived",
                    created_at=started_at - timedelta(days=3),
                ),
            ]
        )
        session.flush()

        session.add_all(
            [
                _version(
                    version_id=ready_version_id,
                    document_id=active_policy_id,
                    version_number=1,
                    created_at=ready_started,
                    status="ready",
                    ingestion_status="completed",
                    processing_started_at=ready_started,
                    processing_completed_at=ready_completed,
                ),
                _version(
                    version_id=published_version_id,
                    document_id=active_faq_id,
                    version_number=1,
                    created_at=published_started,
                    status="published",
                    ingestion_status="completed",
                    processing_started_at=published_started,
                    processing_completed_at=published_completed,
                ),
                _version(
                    version_id=draft_version_id,
                    document_id=active_policy_id,
                    version_number=2,
                    created_at=started_at
                    + timedelta(days=1, hours=4),
                    status="draft",
                    ingestion_status="pending",
                ),
                _version(
                    version_id=failed_version_id,
                    document_id=archived_guide_id,
                    version_number=1,
                    created_at=failed_started,
                    status="failed",
                    ingestion_status="failed",
                    processing_started_at=failed_started,
                    processing_completed_at=failed_completed,
                    failure_code="PARSER_FAILURE",
                    failure_message=(
                        "SECRET_FAILURE_MESSAGE_MUST_NOT_APPEAR"
                    ),
                ),
                _version(
                    version_id=processing_version_id,
                    document_id=active_faq_id,
                    version_number=2,
                    created_at=started_at
                    + timedelta(days=2, hours=5),
                    status="processing",
                    ingestion_status="running",
                    processing_started_at=started_at
                    + timedelta(days=2, hours=5),
                ),
            ]
        )
        session.flush()

        session.add_all(
            [
                _chunk(
                    chunk_id=ready_chunk_one_id,
                    version_id=ready_version_id,
                    chunk_index=0,
                    created_at=ready_completed,
                ),
                _chunk(
                    chunk_id=ready_chunk_two_id,
                    version_id=ready_version_id,
                    chunk_index=1,
                    created_at=ready_completed,
                ),
                _chunk(
                    chunk_id=published_chunk_id,
                    version_id=published_version_id,
                    chunk_index=0,
                    created_at=published_completed,
                ),
            ]
        )
        session.flush()

        # The ready version is only partially covered:
        # one of its two chunks has an embedding.
        # The published version is fully covered.
        session.add_all(
            [
                _embedding(
                    embedding_id=uuid7(),
                    chunk_id=ready_chunk_one_id,
                    created_at=ready_completed,
                    fingerprint_character="a",
                ),
                _embedding(
                    embedding_id=uuid7(),
                    chunk_id=published_chunk_id,
                    created_at=published_completed,
                    fingerprint_character="b",
                ),
            ]
        )

        session.commit()


class TestKnowledgeHealthAuthorization:
    def test_requires_authentication(
        self,
        client: TestClient,
    ) -> None:
        now = datetime.now(UTC)

        response = client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=now - timedelta(days=1),
                ended_at=now,
            ),
        )

        assert response.status_code == 401
        assert response.status_code != 200

    def test_rejects_customer(
        self,
        client: TestClient,
        customer_auth_headers: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)

        response = client.get(
            _ENDPOINT,
            headers=customer_auth_headers,
            params=_analytics_params(
                started_at=now - timedelta(days=1),
                ended_at=now,
            ),
        )

        assert response.status_code == 403
        assert response.status_code != 200

    def test_rejects_support_agent(
        self,
        client: TestClient,
        support_agent_auth_headers: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)

        response = client.get(
            _ENDPOINT,
            headers=support_agent_auth_headers,
            params=_analytics_params(
                started_at=now - timedelta(days=1),
                ended_at=now,
            ),
        )

        assert response.status_code == 403
        assert response.status_code != 200


class TestDashboardKnowledgeHealth:
    def test_returns_inventory_and_health_metrics(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        started_at = datetime(2026, 9, 1, tzinfo=UTC)
        ended_at = started_at + timedelta(days=3)

        _seed_knowledge_health(
            test_session_factory=test_session_factory,
            started_at=started_at,
        )

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=started_at,
                ended_at=ended_at,
            ),
        )

        assert response.status_code == 200, response.text
        body = response.json()

        assert body["total_documents"] == 3
        assert body["total_versions"] == 5
        assert body["total_chunks"] == 3
        assert body["total_embeddings"] == 2

        # Draft, failed, and processing versions have no chunks.
        assert body["versions_without_chunks"] == 3

        # Only the partially embedded ready version is counted.
        # Zero-chunk versions must not be counted again here.
        assert body["versions_missing_embeddings"] == 1

        assert body["processing_backlog"] == 2

        coverage = Decimal(
            str(body["embedding_coverage_rate"])
        )
        assert coverage == Decimal(2) / Decimal(3)

        measured_at = datetime.fromisoformat(
            body["snapshot_measured_at"].replace(
                "Z",
                "+00:00",
            )
        )
        assert measured_at.tzinfo is not None

    def test_returns_current_distributions(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        started_at = datetime(2026, 9, 1, tzinfo=UTC)
        ended_at = started_at + timedelta(days=3)

        _seed_knowledge_health(
            test_session_factory=test_session_factory,
            started_at=started_at,
        )

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=started_at,
                ended_at=ended_at,
            ),
        )

        assert response.status_code == 200, response.text
        body = response.json()

        assert _distribution(
            body["document_status_distribution"]
        ) == {
            "active": 2,
            "archived": 1,
        }

        assert _distribution(
            body["document_content_type_distribution"]
        ) == {
            "faq": 1,
            "guide": 1,
            "policy": 1,
        }

        assert _distribution(
            body["document_visibility_distribution"]
        ) == {
            "both": 1,
            "customer": 1,
            "internal": 1,
        }

        assert _distribution(
            body["version_status_distribution"]
        ) == {
            "draft": 1,
            "failed": 1,
            "processing": 1,
            "published": 1,
            "ready": 1,
        }

        assert _distribution(
            body["ingestion_status_distribution"]
        ) == {
            "completed": 2,
            "failed": 1,
            "pending": 1,
            "running": 1,
        }

        assert _distribution(
            body["failure_code_distribution"]
        ) == {
            "PARSER_FAILURE": 1,
        }

    def test_returns_processing_duration_summary(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        started_at = datetime(2026, 9, 1, tzinfo=UTC)
        ended_at = started_at + timedelta(days=3)

        _seed_knowledge_health(
            test_session_factory=test_session_factory,
            started_at=started_at,
        )

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=started_at,
                ended_at=ended_at,
            ),
        )

        assert response.status_code == 200, response.text
        duration = response.json()["processing_duration"]

        # Durations are one, two, and three hours.
        assert duration["sample_count"] == 3
        assert float(duration["average_ms"]) == 7_200_000
        assert float(duration["p50_ms"]) == 7_200_000
        assert float(duration["p95_ms"]) == 10_440_000

    def test_returns_zero_filled_daily_timeline(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        started_at = datetime(2026, 9, 1, tzinfo=UTC)
        ended_at = started_at + timedelta(days=4)

        _seed_knowledge_health(
            test_session_factory=test_session_factory,
            started_at=started_at,
        )

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=started_at,
                ended_at=ended_at,
                bucket="day",
            ),
        )

        assert response.status_code == 200, response.text
        timeline = response.json()["timeline"]

        assert len(timeline) == 4

        assert timeline[0]["versions_created"] == 1
        assert timeline[0]["processing_completed"] == 1
        assert timeline[0]["processing_failed"] == 0

        assert timeline[1]["versions_created"] == 2
        assert timeline[1]["processing_completed"] == 1
        assert timeline[1]["processing_failed"] == 0

        assert timeline[2]["versions_created"] == 2
        assert timeline[2]["processing_completed"] == 0
        assert timeline[2]["processing_failed"] == 1

        assert timeline[3] == {
            "bucket_started_at": timeline[3][
                "bucket_started_at"
            ],
            "versions_created": 0,
            "processing_completed": 0,
            "processing_failed": 0,
        }

    def test_empty_window_returns_zero_window_metrics(
        self,
        admin_client: TestClient,
    ) -> None:
        started_at = datetime(2035, 1, 1, tzinfo=UTC)
        ended_at = started_at + timedelta(days=3)

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=started_at,
                ended_at=ended_at,
            ),
        )

        assert response.status_code == 200, response.text
        body = response.json()

        assert body["failure_code_distribution"] == []
        assert body["processing_duration"] == {
            "sample_count": 0,
            "average_ms": None,
            "p50_ms": None,
            "p95_ms": None,
        }

        assert len(body["timeline"]) == 3
        for point in body["timeline"]:
            assert point["versions_created"] == 0
            assert point["processing_completed"] == 0
            assert point["processing_failed"] == 0

    def test_rejects_invalid_window_without_returning_200(
        self,
        admin_client: TestClient,
    ) -> None:
        boundary = datetime.now(UTC)

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=boundary,
                ended_at=boundary,
            ),
        )

        assert response.status_code == 422
        assert response.status_code != 200
        assert response.json()["error"]["code"] == (
            "INVALID_ANALYTICS_WINDOW"
        )

    def test_rejects_naive_timestamps_without_returning_200(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            _ENDPOINT,
            params={
                "started_at": "2026-09-01T00:00:00",
                "ended_at": "2026-09-02T00:00:00",
                "bucket": "day",
            },
        )

        assert response.status_code == 422
        assert response.status_code != 200

    def test_does_not_expose_knowledge_content_or_failure_messages(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        started_at = datetime(2026, 9, 1, tzinfo=UTC)
        ended_at = started_at + timedelta(days=3)

        _seed_knowledge_health(
            test_session_factory=test_session_factory,
            started_at=started_at,
        )

        response = admin_client.get(
            _ENDPOINT,
            params=_analytics_params(
                started_at=started_at,
                ended_at=ended_at,
            ),
        )

        assert response.status_code == 200, response.text
        serialized = response.text.lower()

        for forbidden in (
            "secret_source_content_must_not_appear",
            "secret_failure_message_must_not_appear",
            "sensitive derived chunk content",
            "private section",
            "active policy",
            "fixture-v1.md",
        ):
            assert forbidden not in serialized