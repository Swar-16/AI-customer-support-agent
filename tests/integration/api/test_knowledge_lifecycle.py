# AI-customer-support-agent\tests\integration\api\test_knowledge_lifecycle.py
from __future__ import annotations

from uuid import UUID
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from uuid6 import uuid7
import pytest

from packages.database.models.ai.embedding_call import (
    EmbeddingCallModel,
)
from packages.database.models.audit.audit_event import (
    AuditEventModel,
)
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
from packages.knowledge.application.process_version import (
    ProcessKnowledgeVersion,
)
from packages.database.repositories.audit.audit_event_repository import (
    AuditEventRepository,
)


def _trace_headers(trace_id: UUID) -> dict[str, str]:
    return {"X-Trace-ID": str(trace_id)}


def _create_document(
    admin_client: TestClient,
    *,
    trace_id: UUID,
    title: str = "Lifecycle Refund Policy",
) -> dict:
    response = admin_client.post(
        "/v1/knowledge/documents",
        headers=_trace_headers(trace_id),
        json={
            "title": title,
            "description": "Knowledge lifecycle integration test.",
            "content_type": "policy",
            "visibility": "customer",
        },
    )

    assert response.status_code == 201, response.text
    return response.json()


def _create_version(
    admin_client: TestClient,
    *,
    document_id: str,
    trace_id: UUID,
    content: str,
    source_name: str,
) -> dict:
    response = admin_client.post(
        f"/v1/knowledge/documents/{document_id}/versions",
        headers=_trace_headers(trace_id),
        json={
            "source_type": "markdown",
            "source_content": content,
            "source_name": source_name,
        },
    )

    assert response.status_code == 201, response.text
    return response.json()


def _process_version(
    admin_client: TestClient,
    *,
    version_id: str,
    trace_id: UUID,
) -> dict:
    response = admin_client.post(
        f"/v1/knowledge/versions/{version_id}/process",
        headers=_trace_headers(trace_id),
    )

    assert response.status_code == 200, response.text
    return response.json()


def _publish_version(
    admin_client: TestClient,
    *,
    version_id: str,
    trace_id: UUID,
) -> dict:
    response = admin_client.post(
        f"/v1/knowledge/versions/{version_id}/publish",
        headers=_trace_headers(trace_id),
    )

    assert response.status_code == 200, response.text
    return response.json()


class TestKnowledgeLifecycle:
    def test_executes_complete_document_lifecycle(
        self,
        admin_client: TestClient,
        admin_identity,
        test_session_factory,
    ) -> None:
        create_document_trace = uuid7()
        create_version_trace = uuid7()
        process_trace = uuid7()
        embed_trace = uuid7()
        publish_trace = uuid7()
        archive_trace = uuid7()

        document = _create_document(
            admin_client,
            trace_id=create_document_trace,
        )
        document_id = document["document_id"]

        version = _create_version(
            admin_client,
            document_id=document_id,
            trace_id=create_version_trace,
            content=(
                "# Refund Policy\n\n"
                "Customers may request a refund within fourteen "
                "calendar days of delivery.\n\n"
                "## Processing\n\n"
                "Approved refunds are returned to the original "
                "payment method."
            ),
            source_name="refund-policy.md",
        )
        version_id = version["version_id"]

        processed = _process_version(
            admin_client,
            version_id=version_id,
            trace_id=process_trace,
        )

        assert processed["version_id"] == version_id
        assert processed["document_id"] == document_id
        assert processed["chunk_count"] >= 1
        assert processed["version_status"] == "ready"
        assert processed["ingestion_status"] == "completed"

        
        detail_before_embedding = admin_client.get(f"/v1/knowledge/versions/{version_id}")

        assert detail_before_embedding.status_code == 200
        detail_before_embedding_body = detail_before_embedding.json()

        assert detail_before_embedding_body["total_chunk_count"] == processed["chunk_count"]
        assert detail_before_embedding_body["embedded_chunk_count"] == 0
        assert detail_before_embedding_body["is_fully_embedded"] is False

        embedded = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/embed",
            headers=_trace_headers(embed_trace),
        )

        assert embedded.status_code == 200, embedded.text
        embedded_body = embedded.json()

        assert embedded_body["version_id"] == version_id
        assert embedded_body["total_chunks"] == (
            processed["chunk_count"]
        )
        assert embedded_body["created_count"] == (
            processed["chunk_count"]
        )
        assert embedded_body["existing_count"] == 0

        # Exact re-execution must reuse immutable artifacts and must not
        # invoke the provider again.
        repeated_embed_trace = uuid7()
        repeated = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/embed",
            headers=_trace_headers(repeated_embed_trace),
        )

        assert repeated.status_code == 200, repeated.text
        repeated_body = repeated.json()

        assert repeated_body["created_count"] == 0
        assert repeated_body["existing_count"] == (
            processed["chunk_count"]
        )
        assert repeated_body["total_chunks"] == (
            processed["chunk_count"]
        )
        
        detail_after_embedding = admin_client.get(f"/v1/knowledge/versions/{version_id}")

        assert detail_after_embedding.status_code == 200
        detail_after_embedding_body = detail_after_embedding.json()

        assert detail_after_embedding_body["total_chunk_count"] == processed["chunk_count"]
        assert detail_after_embedding_body["embedded_chunk_count"] == processed["chunk_count"]
        assert detail_after_embedding_body["is_fully_embedded"] is True

        published = _publish_version(
            admin_client,
            version_id=version_id,
            trace_id=publish_trace,
        )

        assert published["status"] == "published"
        assert published["superseded_version_id"] is None

        detail = admin_client.get(
            f"/v1/knowledge/versions/{version_id}"
        )

        assert detail.status_code == 200
        
        detail_body = detail.json()

        assert detail_body["is_current_published_version"] is True
        assert detail_body["total_chunk_count"] == processed["chunk_count"]
        assert detail_body["embedded_chunk_count"] == processed["chunk_count"]
        assert detail_body["is_fully_embedded"] is True
        assert detail_body["is_current_published_version"] is True

        archived = admin_client.post(
            f"/v1/knowledge/documents/{document_id}/archive",
            headers=_trace_headers(archive_trace),
        )

        assert archived.status_code == 200, archived.text
        archived_body = archived.json()

        assert archived_body["status"] == "archived"
        assert archived_body["superseded_version_id"] == version_id

        with test_session_factory() as session:
            persisted_document = session.get(
                KnowledgeDocumentModel,
                UUID(document_id),
            )
            persisted_version = session.get(
                KnowledgeDocumentVersionModel,
                UUID(version_id),
            )

            chunk_count = session.scalar(
                select(func.count(KnowledgeChunkModel.id)).where(
                    KnowledgeChunkModel.version_id
                    == UUID(version_id)
                )
            )

            embedding_count = session.scalar(
                select(
                    func.count(KnowledgeChunkEmbeddingModel.id)
                )
                .join(
                    KnowledgeChunkModel,
                    KnowledgeChunkModel.id
                    == KnowledgeChunkEmbeddingModel.chunk_id,
                )
                .where(
                    KnowledgeChunkModel.version_id
                    == UUID(version_id)
                )
            )

            embedding_call_count = session.scalar(
                select(func.count(EmbeddingCallModel.id)).where(
                    EmbeddingCallModel.knowledge_version_id
                    == UUID(version_id)
                )
            )

            traces = (
                create_document_trace,
                create_version_trace,
                process_trace,
                embed_trace,
                repeated_embed_trace,
                publish_trace,
                archive_trace,
            )

            audit_events = tuple(
                session.scalars(
                    select(AuditEventModel)
                    .where(AuditEventModel.trace_id.in_(traces))
                    .order_by(
                        AuditEventModel.occurred_at.asc(),
                        AuditEventModel.id.asc(),
                    )
                )
            )

        assert persisted_document is not None
        assert persisted_document.status == "archived"
        assert persisted_document.archived_at is not None

        assert persisted_version is not None
        assert persisted_version.status == "superseded"
        assert persisted_version.ingestion_status == "completed"
        assert persisted_version.superseded_at is not None

        assert chunk_count == processed["chunk_count"]
        assert embedding_count == processed["chunk_count"]

        # The idempotent second embed performs no provider call.
        assert embedding_call_count == 1

        events_by_type = {
            event.event_type: event
            for event in audit_events
            if event.event_type.startswith("knowledge_")
        }

        assert {
            "knowledge_document.created",
            "knowledge_version.created",
            "knowledge_version.processing_started",
            "knowledge_version.processing_completed",
            "knowledge_version.embeddings_created",
            "knowledge_version.published",
            "knowledge_document.archived",
        }.issubset(events_by_type)

        admin_event_types = {
            "knowledge_document.created",
            "knowledge_version.created",
            "knowledge_version.processing_started",
            "knowledge_version.embeddings_created",
            "knowledge_version.published",
            "knowledge_document.archived",
        }

        for event_type in admin_event_types:
            event = events_by_type[event_type]
            assert event.actor_type == "admin"
            assert event.actor_id == admin_identity.user_id

        completed_event = events_by_type[
            "knowledge_version.processing_completed"
        ]
        assert completed_event.actor_type == "system"
        assert completed_event.actor_id is None
        assert completed_event.trace_id == process_trace

        assert events_by_type[
            "knowledge_document.created"
        ].trace_id == create_document_trace

        assert events_by_type[
            "knowledge_version.created"
        ].trace_id == create_version_trace

        assert events_by_type[
            "knowledge_version.embeddings_created"
        ].trace_id == embed_trace

        assert events_by_type[
            "knowledge_version.published"
        ].trace_id == publish_trace

        assert events_by_type[
            "knowledge_document.archived"
        ].trace_id == archive_trace

        # A true embedding no-op should not create another mutation audit.
        repeated_embed_events = [
            event
            for event in audit_events
            if (
                event.trace_id == repeated_embed_trace
                and event.event_type
                == "knowledge_version.embeddings_created"
            )
        ]
        assert repeated_embed_events == []

    def test_rejects_invalid_lifecycle_transitions(
        self,
        admin_client: TestClient,
    ) -> None:
        document = _create_document(
            admin_client,
            trace_id=uuid7(),
            title="Lifecycle Conflict Document",
        )

        version = _create_version(
            admin_client,
            document_id=document["document_id"],
            trace_id=uuid7(),
            content=(
                "# Draft Version\n\n"
                "This version contains valid semantic body content."
            ),
            source_name="draft.md",
        )
        version_id = version["version_id"]

        embed_draft = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/embed",
            headers=_trace_headers(uuid7()),
        )
        assert embed_draft.status_code == 409
        assert embed_draft.json()["error"]["code"] == (
            "KNOWLEDGE_CONFLICT"
        )

        publish_draft = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/publish",
            headers=_trace_headers(uuid7()),
        )
        assert publish_draft.status_code == 409
        assert publish_draft.json()["error"]["code"] == (
            "KNOWLEDGE_CONFLICT"
        )

        _process_version(
            admin_client,
            version_id=version_id,
            trace_id=uuid7(),
        )

        repeated_process = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/process",
            headers=_trace_headers(uuid7()),
        )
        assert repeated_process.status_code == 409
        assert repeated_process.json()["error"]["code"] == (
            "KNOWLEDGE_CONFLICT"
        )

        # A processed/ready version is still not publishable until
        # every chunk has a compatible persisted embedding.
        publish_without_embeddings = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/publish",
            headers=_trace_headers(uuid7()),
        )

        assert publish_without_embeddings.status_code == 409
        assert publish_without_embeddings.json()["error"][
            "code"
        ] == "KNOWLEDGE_CONFLICT"

        # Complete the required embedding step.
        embedded = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/embed",
            headers=_trace_headers(uuid7()),
        )

        assert embedded.status_code == 200, embedded.text
        assert embedded.json()["created_count"] >= 1

        # Publication succeeds after complete embedding coverage.
        first_publish = _publish_version(
            admin_client,
            version_id=version_id,
            trace_id=uuid7(),
        )

        # Retrying the completed publication is idempotent.
        repeated_publish = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/publish",
            headers=_trace_headers(uuid7()),
        )

        assert repeated_publish.status_code == 200
        repeated_publish_body = repeated_publish.json()

        assert repeated_publish_body["version_id"] == version_id
        assert repeated_publish_body["document_id"] == (
            document["document_id"]
        )
        assert repeated_publish_body["status"] == "published"
        first_published_at = datetime.fromisoformat(
            first_publish["published_at"].replace(
                "Z",
                "+00:00",
            )
        )
        repeated_published_at = datetime.fromisoformat(
            repeated_publish_body["published_at"].replace(
                "Z",
                "+00:00",
            )
        )

        assert repeated_published_at == first_published_at
        assert repeated_publish_body[
            "superseded_version_id"
        ] is None

        archive = admin_client.post(
            (
                f"/v1/knowledge/documents/"
                f"{document['document_id']}/archive"
            ),
            headers=_trace_headers(uuid7()),
        )
        assert archive.status_code == 200

        repeated_archive = admin_client.post(
            (
                f"/v1/knowledge/documents/"
                f"{document['document_id']}/archive"
            ),
            headers=_trace_headers(uuid7()),
        )
        assert repeated_archive.status_code == 409
        assert repeated_archive.json()["error"]["code"] == (
            "KNOWLEDGE_CONFLICT"
        )

        create_after_archive = admin_client.post(
            (
                f"/v1/knowledge/documents/"
                f"{document['document_id']}/versions"
            ),
            headers=_trace_headers(uuid7()),
            json={
                "source_type": "markdown",
                "source_content": "# Forbidden revision",
                "source_name": "forbidden.md",
            },
        )
        assert create_after_archive.status_code == 409
        assert create_after_archive.json()["error"]["code"] == (
            "KNOWLEDGE_CONFLICT"
        )

    def test_version_detail_reports_zero_chunk_coverage(
        self,
        admin_client: TestClient,
    ) -> None:
        document = _create_document(
            admin_client,
            trace_id=uuid7(),
            title="Unprocessed Coverage Document",
        )

        version = _create_version(
            admin_client,
            document_id=document["document_id"],
            trace_id=uuid7(),
            content=(
                "# Unprocessed Version\n\n"
                "This version has not been processed yet."
            ),
            source_name="unprocessed.md",
        )

        detail = admin_client.get(
            (
                f"/v1/knowledge/versions/"
                f"{version['version_id']}"
            )
        )

        assert detail.status_code == 200, detail.text
        body = detail.json()

        assert body["status"] == "draft"
        assert body["total_chunk_count"] == 0
        assert body["embedded_chunk_count"] == 0
        assert body["is_fully_embedded"] is False
    
    def test_partial_embedding_coverage_is_recoverable(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        document = _create_document(
            admin_client,
            trace_id=uuid7(),
            title="Partial Embedding Coverage",
        )

        version = _create_version(
            admin_client,
            document_id=document["document_id"],
            trace_id=uuid7(),
            content=(
                "# Partial Coverage\n\n"
                "This version is used to verify recovery from "
                "partially completed embedding persistence."
            ),
            source_name="partial-coverage.md",
        )
        version_id = version["version_id"]

        processed = _process_version(
            admin_client,
            version_id=version_id,
            trace_id=uuid7(),
        )

        first_embedding = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/embed",
            headers=_trace_headers(uuid7()),
        )

        assert first_embedding.status_code == 200, (
            first_embedding.text
        )
        assert first_embedding.json()["created_count"] == (
            processed["chunk_count"]
        )

        # Simulate a persisted partial state by introducing another
        # required processed chunk without an embedding artifact.
        with test_session_factory() as session:
            existing_chunks = tuple(
                session.scalars(
                    select(KnowledgeChunkModel)
                    .where(
                        KnowledgeChunkModel.version_id
                        == UUID(version_id)
                    )
                    .order_by(
                        KnowledgeChunkModel.chunk_index.asc()
                    )
                )
            )

            assert len(existing_chunks) == (
                processed["chunk_count"]
            )

            next_chunk_index = (
                max(
                    chunk.chunk_index
                    for chunk in existing_chunks
                )
                + 1
            )

            session.add(
                KnowledgeChunkModel(
                    id=uuid7(),
                    version_id=UUID(version_id),
                    chunk_index=next_chunk_index,
                    content=(
                        "Additional processed content requiring "
                        "a compatible embedding."
                    ),
                    section_title="Additional coverage",
                    start_offset=None,
                    end_offset=None,
                    token_count=None,
                    metadata_={
                        "integration_test": True,
                        "partial_coverage": True,
                    },
                )
            )
            session.commit()

        partial_detail = admin_client.get(
            f"/v1/knowledge/versions/{version_id}"
        )

        assert partial_detail.status_code == 200
        partial_body = partial_detail.json()

        assert partial_body["total_chunk_count"] == (
            processed["chunk_count"] + 1
        )
        assert partial_body["embedded_chunk_count"] == (
            processed["chunk_count"]
        )
        assert partial_body["is_fully_embedded"] is False

        blocked_publish = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/publish",
            headers=_trace_headers(uuid7()),
        )

        assert blocked_publish.status_code == 409
        assert blocked_publish.json()["error"]["code"] == (
            "KNOWLEDGE_CONFLICT"
        )

        # The idempotent embedding operation must reuse existing
        # artifacts and create only the missing embedding.
        retry_embedding = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/embed",
            headers=_trace_headers(uuid7()),
        )

        assert retry_embedding.status_code == 200, (
            retry_embedding.text
        )
        retry_body = retry_embedding.json()

        assert retry_body["total_chunks"] == (
            processed["chunk_count"] + 1
        )
        assert retry_body["existing_count"] == (
            processed["chunk_count"]
        )
        assert retry_body["created_count"] == 1

        completed_detail = admin_client.get(
            f"/v1/knowledge/versions/{version_id}"
        )

        assert completed_detail.status_code == 200
        completed_body = completed_detail.json()

        assert completed_body["total_chunk_count"] == (
            processed["chunk_count"] + 1
        )
        assert completed_body["embedded_chunk_count"] == (
            processed["chunk_count"] + 1
        )
        assert completed_body["is_fully_embedded"] is True

        published = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/publish",
            headers=_trace_headers(uuid7()),
        )

        assert published.status_code == 200, published.text
        assert published.json()["status"] == "published"
        
    def test_incompatible_embedding_configuration_does_not_count(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        document = _create_document(
            admin_client,
            trace_id=uuid7(),
            title="Embedding Configuration Compatibility",
        )

        version = _create_version(
            admin_client,
            document_id=document["document_id"],
            trace_id=uuid7(),
            content=(
                "# Configuration Compatibility\n\n"
                "Only embeddings created with the active provider "
                "and input configuration may permit publication."
            ),
            source_name="embedding-configuration.md",
        )
        version_id = version["version_id"]

        processed = _process_version(
            admin_client,
            version_id=version_id,
            trace_id=uuid7(),
        )

        initial_embedding = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/embed",
            headers=_trace_headers(uuid7()),
        )

        assert initial_embedding.status_code == 200, (
            initial_embedding.text
        )
        assert initial_embedding.json()["created_count"] == (
            processed["chunk_count"]
        )

        # Simulate artifacts produced by an obsolete embedding-input
        # configuration. Production code treats embedding artifacts as
        # immutable; direct mutation here is test setup only.
        with test_session_factory() as session:
            persisted_embeddings = tuple(
                session.scalars(
                    select(KnowledgeChunkEmbeddingModel)
                    .join(
                        KnowledgeChunkModel,
                        KnowledgeChunkModel.id
                        == KnowledgeChunkEmbeddingModel.chunk_id,
                    )
                    .where(
                        KnowledgeChunkModel.version_id
                        == UUID(version_id)
                    )
                )
            )

            assert len(persisted_embeddings) == (
                processed["chunk_count"]
            )

            for embedding in persisted_embeddings:
                embedding.input_config_fingerprint = (
                    "f" * 64
                    if embedding.input_config_fingerprint
                    != "f" * 64
                    else "e" * 64
                )

            session.commit()

        incompatible_detail = admin_client.get(
            f"/v1/knowledge/versions/{version_id}"
        )

        assert incompatible_detail.status_code == 200
        incompatible_body = incompatible_detail.json()

        assert incompatible_body["total_chunk_count"] == (
            processed["chunk_count"]
        )
        assert incompatible_body["embedded_chunk_count"] == 0
        assert incompatible_body["is_fully_embedded"] is False

        blocked_publish = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/publish",
            headers=_trace_headers(uuid7()),
        )

        assert blocked_publish.status_code == 409
        assert blocked_publish.json()["error"]["code"] == (
            "KNOWLEDGE_CONFLICT"
        )

        # Re-embedding under the active configuration creates new,
        # compatible artifacts rather than reusing obsolete ones.
        active_embedding = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/embed",
            headers=_trace_headers(uuid7()),
        )

        assert active_embedding.status_code == 200, (
            active_embedding.text
        )
        active_body = active_embedding.json()

        assert active_body["total_chunks"] == (
            processed["chunk_count"]
        )
        assert active_body["existing_count"] == 0
        assert active_body["created_count"] == (
            processed["chunk_count"]
        )

        completed_detail = admin_client.get(
            f"/v1/knowledge/versions/{version_id}"
        )

        assert completed_detail.status_code == 200
        completed_body = completed_detail.json()

        assert completed_body["total_chunk_count"] == (
            processed["chunk_count"]
        )
        assert completed_body["embedded_chunk_count"] == (
            processed["chunk_count"]
        )
        assert completed_body["is_fully_embedded"] is True

        published = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/publish",
            headers=_trace_headers(uuid7()),
        )

        assert published.status_code == 200, published.text
        assert published.json()["status"] == "published"
    
    def test_failed_embedding_provider_never_reports_completion(
        self,
        admin_client: TestClient,
        application_services,
        test_session_factory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        document = _create_document(
            admin_client,
            trace_id=uuid7(),
            title="Embedding Provider Failure",
        )

        version = _create_version(
            admin_client,
            document_id=document["document_id"],
            trace_id=uuid7(),
            content=(
                "# Provider Failure\n\n"
                "A failed embedding provider must not create "
                "successful embedding artifacts."
            ),
            source_name="provider-failure.md",
        )
        version_id = version["version_id"]

        processed = _process_version(
            admin_client,
            version_id=version_id,
            trace_id=uuid7(),
        )

        provider = (
            application_services
            .embed_knowledge_version
            ._provider
        )

        def fail_embedding_request(texts):
            raise RuntimeError(
                "simulated embedding provider failure"
            )

        monkeypatch.setattr(
            provider,
            "embed_documents",
            fail_embedding_request,
        )

        with pytest.raises(
            RuntimeError,
            match="simulated embedding provider failure",
        ):
            admin_client.post(
                f"/v1/knowledge/versions/{version_id}/embed",
                headers=_trace_headers(uuid7()),
            )

        detail = admin_client.get(
            f"/v1/knowledge/versions/{version_id}"
        )

        assert detail.status_code == 200
        detail_body = detail.json()

        assert detail_body["total_chunk_count"] == (
            processed["chunk_count"]
        )
        assert detail_body["embedded_chunk_count"] == 0
        assert detail_body["is_fully_embedded"] is False

        with test_session_factory() as session:
            persisted_embedding_count = session.scalar(
                select(
                    func.count(
                        KnowledgeChunkEmbeddingModel.id
                    )
                )
                .join(
                    KnowledgeChunkModel,
                    KnowledgeChunkModel.id
                    == KnowledgeChunkEmbeddingModel.chunk_id,
                )
                .where(
                    KnowledgeChunkModel.version_id
                    == UUID(version_id)
                )
            )

        assert persisted_embedding_count == 0

        blocked_publish = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/publish",
            headers=_trace_headers(uuid7()),
        )

        assert blocked_publish.status_code == 409
        assert blocked_publish.json()["error"]["code"] == (
            "KNOWLEDGE_CONFLICT"
        )
    
    def test_publish_audit_failure_rolls_back_supersession(
        self,
        admin_client: TestClient,
        test_session_factory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        document = _create_document(
            admin_client,
            trace_id=uuid7(),
            title="Atomic Publication Rollback",
        )
        document_id = document["document_id"]

        first = _create_version(
            admin_client,
            document_id=document_id,
            trace_id=uuid7(),
            content=(
                "# First Published Version\n\n"
                "This version must remain published if publishing "
                "its replacement fails."
            ),
            source_name="rollback-v1.md",
        )
        first_version_id = first["version_id"]

        _process_version(
            admin_client,
            version_id=first_version_id,
            trace_id=uuid7(),
        )

        first_embedding = admin_client.post(
            (
                f"/v1/knowledge/versions/"
                f"{first_version_id}/embed"
            ),
            headers=_trace_headers(uuid7()),
        )
        assert first_embedding.status_code == 200, (
            first_embedding.text
        )

        first_publish = admin_client.post(
            (
                f"/v1/knowledge/versions/"
                f"{first_version_id}/publish"
            ),
            headers=_trace_headers(uuid7()),
        )
        assert first_publish.status_code == 200, (
            first_publish.text
        )

        second = _create_version(
            admin_client,
            document_id=document_id,
            trace_id=uuid7(),
            content=(
                "# Replacement Version\n\n"
                "This replacement must remain ready when audit "
                "persistence fails."
            ),
            source_name="rollback-v2.md",
        )
        second_version_id = second["version_id"]

        _process_version(
            admin_client,
            version_id=second_version_id,
            trace_id=uuid7(),
        )

        second_embedding = admin_client.post(
            (
                f"/v1/knowledge/versions/"
                f"{second_version_id}/embed"
            ),
            headers=_trace_headers(uuid7()),
        )
        assert second_embedding.status_code == 200, (
            second_embedding.text
        )

        def fail_audit_insert(self, event) -> None:
            raise RuntimeError(
                "simulated publication audit failure"
            )

        monkeypatch.setattr(
            AuditEventRepository,
            "add",
            fail_audit_insert,
        )

        with pytest.raises(
            RuntimeError,
            match="simulated publication audit failure",
        ):
            admin_client.post(
                (
                    f"/v1/knowledge/versions/"
                    f"{second_version_id}/publish"
                ),
                headers=_trace_headers(uuid7()),
            )

        with test_session_factory() as session:
            first_model = session.get(
                KnowledgeDocumentVersionModel,
                UUID(first_version_id),
            )
            second_model = session.get(
                KnowledgeDocumentVersionModel,
                UUID(second_version_id),
            )

            published_versions = tuple(
                session.scalars(
                    select(KnowledgeDocumentVersionModel)
                    .where(
                        KnowledgeDocumentVersionModel.document_id
                        == UUID(document_id),
                        KnowledgeDocumentVersionModel.status
                        == "published",
                    )
                )
            )

            second_publication_events = tuple(
                session.scalars(
                    select(AuditEventModel).where(
                        AuditEventModel.event_type
                        == "knowledge_version.published",
                        AuditEventModel.entity_id
                        == UUID(second_version_id),
                    )
                )
            )

        assert first_model is not None
        assert first_model.status == "published"
        assert first_model.published_at is not None
        assert first_model.superseded_at is None

        assert second_model is not None
        assert second_model.status == "ready"
        assert second_model.published_at is None
        assert second_model.superseded_at is None

        assert len(published_versions) == 1
        assert published_versions[0].id == UUID(
            first_version_id
        )

        assert second_publication_events == ()
    
    def test_new_publication_supersedes_previous_version(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        document = _create_document(
            admin_client,
            trace_id=uuid7(),
            title="Version Supersession Policy",
        )
        document_id = document["document_id"]

        first = _create_version(
            admin_client,
            document_id=document_id,
            trace_id=uuid7(),
            content=(
                "# Policy Version One\n\n"
                "Customers may request support under the original policy."
            ),
            source_name="policy-v1.md",
        )
        _process_version(
            admin_client,
            version_id=first["version_id"],
            trace_id=uuid7(),
        )
        first_embedding = admin_client.post(
            (
                f"/v1/knowledge/versions/"
                f"{first['version_id']}/embed"
            ),
            headers=_trace_headers(uuid7()),
        )

        assert first_embedding.status_code == 200, (
            first_embedding.text
        )
        assert first_embedding.json()["created_count"] >= 1
        
        _publish_version(
            admin_client,
            version_id=first["version_id"],
            trace_id=uuid7(),
        )

        second = _create_version(
            admin_client,
            document_id=document_id,
            trace_id=uuid7(),
            content=(
                "# Policy Version Two\n\n"
                "Customers may request support under the updated policy."
            ),
            source_name="policy-v2.md",
        )
        _process_version(
            admin_client,
            version_id=second["version_id"],
            trace_id=uuid7(),
        )
        
        second_embedding = admin_client.post(
            (
                f"/v1/knowledge/versions/"
                f"{second['version_id']}/embed"
            ),
            headers=_trace_headers(uuid7()),
        )

        assert second_embedding.status_code == 200, (
            second_embedding.text
        )
        assert second_embedding.json()["created_count"] >= 1

        published_second = _publish_version(
            admin_client,
            version_id=second["version_id"],
            trace_id=uuid7(),
        )

        assert published_second["status"] == "published"
        assert published_second["superseded_version_id"] == (
            first["version_id"]
        )

        with test_session_factory() as session:
            first_model = session.get(
                KnowledgeDocumentVersionModel,
                UUID(first["version_id"]),
            )
            second_model = session.get(
                KnowledgeDocumentVersionModel,
                UUID(second["version_id"]),
            )

            published_count = session.scalar(
                select(
                    func.count(KnowledgeDocumentVersionModel.id)
                ).where(
                    KnowledgeDocumentVersionModel.document_id
                    == UUID(document_id),
                    KnowledgeDocumentVersionModel.status
                    == "published",
                )
            )

        assert first_model is not None
        assert first_model.status == "superseded"
        assert first_model.superseded_at is not None

        assert second_model is not None
        assert second_model.status == "published"
        assert second_model.published_at is not None

        assert published_count == 1
        
class TestUploadedKnowledgeLifecycle:
    @pytest.mark.parametrize(
        (
            "filename",
            "media_type",
            "content",
            "expected_source_type",
            "expected_identity_token",
        ),
        [
            (
                "uploaded-refund-policy.md",
                "text/markdown",
                (
                    b"# Uploaded Refund Policy\n\n"
                    b"Customers may request refunds within fourteen "
                    b"calendar days.\n\n"
                    b"## Processing\n\n"
                    b"Approved refunds return to the original payment "
                    b"method."
                ),
                "markdown",
                "markdown",
            ),
            (
                "uploaded-refund-policy.txt",
                "text/plain",
                (
                    b"Uploaded Refund Policy\n\n"
                    b"Customers may request refunds within fourteen "
                    b"calendar days.\n\n"
                    b"Processing\n\n"
                    b"Approved refunds return to the original payment "
                    b"method."
                ),
                "plain_text",
                "plain_text",
            ),
        ],
    )
    def test_uploaded_file_completes_full_lifecycle(
        self,
        admin_client: TestClient,
        filename: str,
        media_type: str,
        content: bytes,
        expected_source_type: str,
        expected_identity_token: str,
    ) -> None:
        upload_trace = uuid7()
        process_trace = uuid7()
        embed_trace = uuid7()
        publish_trace = uuid7()

        uploaded = admin_client.post(
            "/v1/knowledge/documents/upload",
            headers=_trace_headers(upload_trace),
            data={
                "title": f"Lifecycle Test: {filename}",
                "description": (
                    "End-to-end uploaded knowledge lifecycle test."
                ),
                "content_type": "policy",
                "visibility": "customer",
            },
            files={
                "file": (
                    filename,
                    content,
                    media_type,
                )
            },
        )

        assert uploaded.status_code == 201, uploaded.text
        uploaded_body = uploaded.json()

        document_id = uploaded_body["document_id"]
        version_id = uploaded_body["version_id"]

        assert uploaded_body["version_number"] == 1
        assert uploaded_body["filename"] == filename
        assert uploaded_body["source_type"] == expected_source_type
        assert uploaded_body["document_status"] == "active"
        assert uploaded_body["version_status"] == "draft"
        assert uploaded_body["ingestion_status"] == "pending"

        processed = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/process",
            headers=_trace_headers(process_trace),
        )

        assert processed.status_code == 200, processed.text
        processed_body = processed.json()

        assert processed_body["document_id"] == document_id
        assert processed_body["version_id"] == version_id
        assert processed_body["chunk_count"] >= 1
        assert processed_body["version_status"] == "ready"
        assert processed_body["ingestion_status"] == "completed"

        parser_identity = (
            processed_body["parser_identity"]
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        normalizer_identity = (
            processed_body["normalizer_identity"]
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )

        assert expected_identity_token in parser_identity
        assert expected_identity_token in normalizer_identity

        embedded = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/embed",
            headers=_trace_headers(embed_trace),
        )

        assert embedded.status_code == 200, embedded.text
        embedded_body = embedded.json()

        assert embedded_body["document_id"] == document_id
        assert embedded_body["version_id"] == version_id
        assert embedded_body["total_chunks"] == (
            processed_body["chunk_count"]
        )
        assert embedded_body["created_count"] == (
            processed_body["chunk_count"]
        )
        assert embedded_body["existing_count"] == 0

        published = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/publish",
            headers=_trace_headers(publish_trace),
        )

        assert published.status_code == 200, published.text
        published_body = published.json()

        assert published_body["document_id"] == document_id
        assert published_body["version_id"] == version_id
        assert published_body["version_number"] == 1
        assert published_body["status"] == "published"
        assert published_body["superseded_version_id"] is None

        document_detail = admin_client.get(
            f"/v1/knowledge/documents/{document_id}"
        )

        assert document_detail.status_code == 200
        assert document_detail.json()["published_version_id"] == (
            version_id
        )
        assert document_detail.json()["version_count"] == 1

        version_detail = admin_client.get(
            f"/v1/knowledge/versions/{version_id}"
        )

        assert version_detail.status_code == 200
        version_detail_body = version_detail.json()

        assert version_detail_body["document_id"] == document_id
        assert version_detail_body["source_type"] == expected_source_type
        assert version_detail_body["source_name"] == filename
        assert version_detail_body["status"] == "published"
        assert (
            version_detail_body["is_current_published_version"]
            is True
        )
        assert version_detail_body["source_content_length"] > 0

        # Administrative read APIs expose metadata, not source contents.
        assert "source_content" not in version_detail_body
        assert content.decode("utf-8") not in version_detail.text
        
def test_processing_failure_is_persisted_and_version_can_be_retried(
    admin_client: TestClient,
    admin_identity,
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _create_document(
        admin_client,
        trace_id=uuid7(),
        title="Processing Failure Recovery",
    )
    version = _create_version(
        admin_client,
        document_id=document["document_id"],
        trace_id=uuid7(),
        content="# Recovery Policy\n\nCustomers can request support.",
        source_name="recovery-policy.md",
    )
    version_id = version["version_id"]
    failure_trace = uuid7()
    original_error = RuntimeError("Deterministic ingestion failure")

    def fail_processing(self, snapshot):
        raise original_error

    with monkeypatch.context() as patch:
        patch.setattr(
            ProcessKnowledgeVersion,
            "_process",
            fail_processing,
        )
        with pytest.raises(RuntimeError) as captured:
            admin_client.post(
                f"/v1/knowledge/versions/{version_id}/process",
                headers=_trace_headers(failure_trace),
            )

    assert captured.value is original_error

    with test_session_factory() as session:
        persisted = session.get(
            KnowledgeDocumentVersionModel,
            UUID(version_id),
        )
        assert persisted is not None
        assert persisted.status == "failed"
        assert persisted.ingestion_status == "failed"
        assert persisted.processing_completed_at is not None

        events = tuple(
            session.scalars(
                select(AuditEventModel).where(
                    AuditEventModel.trace_id == failure_trace,
                    AuditEventModel.event_type
                    == "knowledge_version.processing_failed",
                )
            )
        )
        assert len(events) == 1
        assert events[0].actor_type == "system"
        assert events[0].actor_id is None
        assert events[0].metadata_["initiated_by_admin_id"] == str(
            admin_identity.user_id
        )

    retried = _process_version(
        admin_client,
        version_id=version_id,
        trace_id=uuid7(),
    )
    assert retried["version_status"] == "ready"
    assert retried["ingestion_status"] == "completed"
    assert retried["chunk_count"] >= 1