# AI-customer-support-agent\tests\integration\api\test_knowledge_upload.py
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from uuid6 import uuid7

from packages.config.settings import Settings
from packages.database.models.audit.audit_event import AuditEventModel
from packages.database.models.knowledge.document import (
    KnowledgeDocumentModel,
)
from packages.database.models.knowledge.document_version import (
    KnowledgeDocumentVersionModel,
)

from packages.knowledge.application.exceptions import (
    InvalidKnowledgeUploadFilenameError,
)
from packages.knowledge.application.knowledge_upload_policy import (
    KnowledgeUploadPolicy,
)


def test_policy_rejects_windows_path(
    test_settings: Settings,
) -> None:
    policy = KnowledgeUploadPolicy(
        max_upload_bytes=(
            test_settings.knowledge_upload_max_bytes
        )
    )

    with pytest.raises(InvalidKnowledgeUploadFilenameError):
        policy.validate(
            filename=r"C:\temp\policy.md",
            media_type="text/markdown",
            content=b"# Policy\n\nValid body content.",
        )


def _trace_headers(trace_id: UUID) -> dict[str, str]:
    return {"X-Trace-ID": str(trace_id)}


def _document_form(
    *,
    title: str = "Uploaded Refund Policy",
    content_type: str = "policy",
    visibility: str = "customer",
    description: str = "Uploaded through the KM API.",
) -> dict[str, str]:
    return {
        "title": title,
        "content_type": content_type,
        "visibility": visibility,
        "description": description,
    }


def _upload_document(
    client: TestClient,
    *,
    trace_id: UUID,
    filename: str = "refund-policy.md",
    content: bytes = (
        b"# Refund Policy\n\n"
        b"Customers may request refunds within fourteen days."
    ),
    media_type: str = "text/markdown",
    title: str = "Uploaded Refund Policy",
) -> Any:
    return client.post(
        "/v1/knowledge/documents/upload",
        headers=_trace_headers(trace_id),
        data=_document_form(title=title),
        files={
            "file": (
                filename,
                content,
                media_type,
            )
        },
    )


def _upload_version(
    client: TestClient,
    *,
    document_id: str,
    trace_id: UUID,
    filename: str,
    content: bytes,
    media_type: str,
) -> Any:
    return client.post(
        (
            f"/v1/knowledge/documents/"
            f"{document_id}/versions/upload"
        ),
        headers=_trace_headers(trace_id),
        files={
            "file": (
                filename,
                content,
                media_type,
            )
        },
    )


class TestInitialKnowledgeUpload:
    @pytest.mark.parametrize(
        ("filename", "media_type", "expected_source_type"),
        [
            (
                "refund-policy.md",
                "text/markdown",
                "markdown",
            ),
            (
                "refund-policy.txt",
                "text/plain",
                "plain_text",
            ),
        ],
    )
    def test_uploads_supported_text_formats(
        self,
        admin_client: TestClient,
        filename: str,
        media_type: str,
        expected_source_type: str,
    ) -> None:
        response = _upload_document(
            admin_client,
            trace_id=uuid7(),
            filename=filename,
            media_type=media_type,
            content=(
                b"Refund requests are accepted within "
                b"fourteen calendar days."
            ),
        )

        assert response.status_code == 201, response.text

        body = response.json()

        assert body["version_number"] == 1
        assert body["filename"] == filename
        assert body["source_type"] == expected_source_type
        assert body["document_status"] == "active"
        assert body["version_status"] == "draft"
        assert body["ingestion_status"] == "pending"
        assert body["uploaded_size_bytes"] > 0
        assert len(body["content_hash"]) == 64

    def test_persists_document_version_and_audit_events(
        self,
        admin_client: TestClient,
        admin_identity,
        test_session_factory,
    ) -> None:
        trace_id = uuid7()
        source_content = (
            b"# Secure Refund Policy\n\n"
            b"Refunds require an eligible purchase."
        )

        response = _upload_document(
            admin_client,
            trace_id=trace_id,
            content=source_content,
        )

        assert response.status_code == 201, response.text
        body = response.json()

        with test_session_factory() as session:
            document = session.get(
                KnowledgeDocumentModel,
                UUID(body["document_id"]),
            )
            version = session.get(
                KnowledgeDocumentVersionModel,
                UUID(body["version_id"]),
            )
            audit_events = tuple(
                session.scalars(
                    select(AuditEventModel)
                    .where(AuditEventModel.trace_id == trace_id)
                    .order_by(
                        AuditEventModel.occurred_at.asc(),
                        AuditEventModel.id.asc(),
                    )
                )
            )

        assert document is not None
        assert document.title == "Uploaded Refund Policy"
        assert document.status == "active"

        assert version is not None
        assert version.document_id == document.id
        assert version.version_number == 1
        assert version.source_type == "markdown"
        assert version.source_name == "refund-policy.md"
        assert version.source_content == source_content.decode("utf-8")
        assert version.content_hash == body["content_hash"]

        assert [event.event_type for event in audit_events] == [
            "knowledge_document.created",
            "knowledge_version.created",
        ]

        for event in audit_events:
            assert event.actor_type == "admin"
            assert event.actor_id == admin_identity.user_id
            assert event.trace_id == trace_id

        # Uploaded source text must not appear in audit payloads.
        serialized_audit = repr(
            [
                (
                    event.before_state,
                    event.after_state,
                    event.reason,
                    event.metadata_,
                )
                for event in audit_events
            ]
        )
        assert "Refunds require an eligible purchase" not in (
            serialized_audit
        )

        # Source content must not appear in the HTTP response.
        assert "source_content" not in body
        assert source_content.decode("utf-8") not in response.text

    def test_same_filename_does_not_determine_document_identity(
        self,
        admin_client: TestClient,
    ) -> None:
        first = _upload_document(
            admin_client,
            trace_id=uuid7(),
            filename="refund-policy.md",
            content=b"# Refund Policy\n\nFirst logical document.",
            title="First Refund Policy",
        )
        second = _upload_document(
            admin_client,
            trace_id=uuid7(),
            filename="refund-policy.md",
            content=b"# Refund Policy\n\nSecond logical document.",
            title="Second Refund Policy",
        )

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert (
            first.json()["document_id"]
            != second.json()["document_id"]
        )
        assert first.json()["version_number"] == 1
        assert second.json()["version_number"] == 1


class TestKnowledgeVersionUpload:
    def test_uploads_next_version(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        initial = _upload_document(
            admin_client,
            trace_id=uuid7(),
        )
        assert initial.status_code == 201, initial.text

        document_id = initial.json()["document_id"]
        trace_id = uuid7()

        response = _upload_version(
            admin_client,
            document_id=document_id,
            trace_id=trace_id,
            filename="refund-policy-v2.md",
            media_type="text/markdown",
            content=(
                b"# Refund Policy Version Two\n\n"
                b"Customers now have twenty-one calendar days."
            ),
        )

        assert response.status_code == 201, response.text
        body = response.json()

        assert body["document_id"] == document_id
        assert body["version_number"] == 2
        assert body["created"] is True
        assert body["status"] == "draft"
        assert body["ingestion_status"] == "pending"

        with test_session_factory() as session:
            version_count = session.scalar(
                select(
                    func.count(KnowledgeDocumentVersionModel.id)
                ).where(
                    KnowledgeDocumentVersionModel.document_id
                    == UUID(document_id)
                )
            )

            events = tuple(
                session.scalars(
                    select(AuditEventModel).where(
                        AuditEventModel.trace_id == trace_id
                    )
                )
            )

        assert version_count == 2
        assert len(events) == 1
        assert events[0].event_type == "knowledge_version.created"

    def test_identical_version_retry_is_idempotent(
        self,
        admin_client: TestClient,
        test_session_factory,
    ) -> None:
        initial = _upload_document(
            admin_client,
            trace_id=uuid7(),
        )
        document_id = initial.json()["document_id"]

        content = (
            b"# Updated Refund Policy\n\n"
            b"Customers have twenty-one days."
        )

        first_trace = uuid7()
        second_trace = uuid7()

        first = _upload_version(
            admin_client,
            document_id=document_id,
            trace_id=first_trace,
            filename="refund-policy-v2.md",
            media_type="text/markdown",
            content=content,
        )
        second = _upload_version(
            admin_client,
            document_id=document_id,
            trace_id=second_trace,
            filename="renamed-refund-policy.md",
            media_type="text/markdown",
            content=content,
        )

        assert first.status_code == 201, first.text
        assert second.status_code == 200, second.text

        first_body = first.json()
        second_body = second.json()

        assert first_body["created"] is True
        assert second_body["created"] is False
        assert second_body["version_id"] == first_body["version_id"]
        assert second_body["version_number"] == 2
        assert second_body["source_name"] == "refund-policy-v2.md"

        with test_session_factory() as session:
            version_count = session.scalar(
                select(
                    func.count(KnowledgeDocumentVersionModel.id)
                ).where(
                    KnowledgeDocumentVersionModel.document_id
                    == UUID(document_id)
                )
            )
            retry_audit_count = session.scalar(
                select(func.count(AuditEventModel.id)).where(
                    AuditEventModel.trace_id == second_trace
                )
            )

        assert version_count == 2
        assert retry_audit_count == 0

    def test_crlf_and_lf_content_are_idempotent(
        self,
        admin_client: TestClient,
    ) -> None:
        initial = _upload_document(
            admin_client,
            trace_id=uuid7(),
            content=(
                b"# Refund Policy\n\n"
                b"Customers have fourteen days.\n"
            ),
        )
        assert initial.status_code == 201, initial.text

        repeated = _upload_version(
            admin_client,
            document_id=initial.json()["document_id"],
            trace_id=uuid7(),
            filename="refund-policy-windows.md",
            media_type="text/markdown",
            content=(
                b"# Refund Policy\r\n\r\n"
                b"Customers have fourteen days.\r\n"
            ),
        )

        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["created"] is False
        assert (
            repeated.json()["version_id"]
            == initial.json()["version_id"]
        )

    def test_missing_document_returns_404(
        self,
        admin_client: TestClient,
    ) -> None:
        response = _upload_version(
            admin_client,
            document_id=str(uuid7()),
            trace_id=uuid7(),
            filename="missing.md",
            media_type="text/markdown",
            content=b"# Missing\n\nValid body content.",
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "KNOWLEDGE_NOT_FOUND"
        )

    def test_archived_document_rejects_new_version(
        self,
        admin_client: TestClient,
    ) -> None:
        initial = _upload_document(
            admin_client,
            trace_id=uuid7(),
        )
        document_id = initial.json()["document_id"]

        archived = admin_client.post(
            f"/v1/knowledge/documents/{document_id}/archive",
            headers=_trace_headers(uuid7()),
        )
        assert archived.status_code == 200, archived.text

        response = _upload_version(
            admin_client,
            document_id=document_id,
            trace_id=uuid7(),
            filename="forbidden.md",
            media_type="text/markdown",
            content=b"# Forbidden\n\nCannot add after archival.",
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == (
            "KNOWLEDGE_CONFLICT"
        )


class TestKnowledgeUploadAuthorization:
    def test_missing_authentication_returns_401(
        self,
        client: TestClient,
    ) -> None:
        response = _upload_document(
            client,
            trace_id=uuid7(),
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"

    @pytest.mark.parametrize(
        "headers_fixture_name",
        [
            "customer_auth_headers",
            "support_agent_auth_headers",
        ],
    )
    def test_non_admin_roles_are_rejected(
        self,
        client: TestClient,
        request: pytest.FixtureRequest,
        headers_fixture_name: str,
    ) -> None:
        headers = dict(request.getfixturevalue(headers_fixture_name))
        headers.update(_trace_headers(uuid7()))

        response = client.post(
            "/v1/knowledge/documents/upload",
            headers=headers,
            data=_document_form(),
            files={
                "file": (
                    "refund-policy.md",
                    b"# Refund Policy\n\nValid body.",
                    "text/markdown",
                )
            },
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


class TestKnowledgeUploadValidation:
    @pytest.mark.parametrize(
        "content",
        [
            b"",
            b" ",
            b"\n\t\r\n",
        ],
    )
    def test_rejects_empty_or_blank_files(
        self,
        admin_client: TestClient,
        content: bytes,
    ) -> None:
        response = _upload_document(
            admin_client,
            trace_id=uuid7(),
            content=content,
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == (
            "INVALID_KNOWLEDGE_UPLOAD"
        )

    def test_rejects_oversized_file(
        self,
        admin_client: TestClient,
        test_settings: Settings,
    ) -> None:
        content = b"a" * (
            test_settings.knowledge_upload_max_bytes + 1
        )

        response = _upload_document(
            admin_client,
            trace_id=uuid7(),
            filename="oversized.txt",
            media_type="text/plain",
            content=content,
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == (
            "KNOWLEDGE_UPLOAD_TOO_LARGE"
        )

    def test_rejects_invalid_utf8(
        self,
        admin_client: TestClient,
    ) -> None:
        response = _upload_document(
            admin_client,
            trace_id=uuid7(),
            filename="invalid.txt",
            media_type="text/plain",
            content=b"\xff\xfe\xfa\xfb",
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == (
            "INVALID_KNOWLEDGE_UPLOAD"
        )

    @pytest.mark.parametrize(
        ("filename", "media_type"),
        [
            ("policy.pdf", "application/pdf"),
            ("policy.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("policy.exe", "application/octet-stream"),
            ("policy.md.exe", "application/octet-stream"),
            ("policy", "text/plain"),
        ],
    )
    def test_rejects_unsupported_extensions(
        self,
        admin_client: TestClient,
        filename: str,
        media_type: str,
    ) -> None:
        response = _upload_document(
            admin_client,
            trace_id=uuid7(),
            filename=filename,
            media_type=media_type,
            content=b"Valid textual-looking content.",
        )

        assert response.status_code == 415
        assert response.json()["error"]["code"] == (
            "UNSUPPORTED_KNOWLEDGE_UPLOAD"
        )

    @pytest.mark.parametrize(
        ("filename", "media_type"),
        [
            ("policy.md", "application/pdf"),
            ("policy.txt", "text/html"),
            ("policy.md", "application/octet-stream"),
        ],
    )
    def test_rejects_mismatched_media_types(
        self,
        admin_client: TestClient,
        filename: str,
        media_type: str,
    ) -> None:
        response = _upload_document(
            admin_client,
            trace_id=uuid7(),
            filename=filename,
            media_type=media_type,
            content=b"# Policy\n\nValid text.",
        )

        assert response.status_code == 415
        assert response.json()["error"]["code"] == (
            "UNSUPPORTED_KNOWLEDGE_UPLOAD"
        )

    @pytest.mark.parametrize(
        "content",
        [
            b"MZ\x90\x00binary executable",
            b"\x7fELF\x02\x01binary executable",
            b"PK\x03\x04fake archive",
            b"%PDF-1.7 fake PDF",
            b"text\x00with-null",
        ],
    )
    def test_rejects_disguised_binary_content(
        self,
        admin_client: TestClient,
        content: bytes,
    ) -> None:
        response = _upload_document(
            admin_client,
            trace_id=uuid7(),
            filename="disguised.md",
            media_type="text/markdown",
            content=content,
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == (
            "INVALID_KNOWLEDGE_UPLOAD"
        )

    @pytest.mark.parametrize(
        "content",
        [
            "Text containing a forbidden control: \x01",
            "Text containing bidi override: \u202eevil.exe",
        ],
    )
    def test_rejects_unsafe_unicode_controls(
        self,
        admin_client: TestClient,
        content: str,
    ) -> None:
        response = _upload_document(
            admin_client,
            trace_id=uuid7(),
            filename="unsafe.md",
            media_type="text/markdown",
            content=content.encode("utf-8"),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == (
            "INVALID_KNOWLEDGE_UPLOAD"
        )

    @pytest.mark.parametrize(
        "filename",
        [
            "../policy.md",
            r"..\policy.md",
            "/tmp/policy.md",
            "CON.md",
            "policy.md.",
        ],
    )
    def test_rejects_unsafe_filenames(
        self,
        admin_client: TestClient,
        filename: str,
    ) -> None:
        response = _upload_document(
            admin_client,
            trace_id=uuid7(),
            filename=filename,
            media_type="text/markdown",
            content=b"# Policy\n\nValid body content.",
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == (
            "INVALID_KNOWLEDGE_UPLOAD"
        )