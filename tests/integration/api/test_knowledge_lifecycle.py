# AI-customer-support-agent\tests\integration\api\test_knowledge_lifecycle.py
from __future__ import annotations

from uuid import UUID

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
        assert detail.json()["is_current_published_version"] is True

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

        _publish_version(
            admin_client,
            version_id=version_id,
            trace_id=uuid7(),
        )

        repeated_publish = admin_client.post(
            f"/v1/knowledge/versions/{version_id}/publish",
            headers=_trace_headers(uuid7()),
        )
        assert repeated_publish.status_code == 409
        assert repeated_publish.json()["error"]["code"] == (
            "KNOWLEDGE_CONFLICT"
        )

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