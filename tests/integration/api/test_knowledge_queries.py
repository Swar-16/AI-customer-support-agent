# AI-customer-support-agent\tests\integration\api\test_knowledge_queries.py
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from uuid6 import uuid7


def _create_document(
    admin_client: TestClient,
    *,
    title: str = "Refund Policy",
    content_type: str = "policy",
    visibility: str = "customer",
    description: str | None = "Customer refund rules.",
) -> dict:
    response = admin_client.post(
        "/v1/knowledge/documents",
        headers={"X-Trace-ID": str(uuid7())},
        json={
            "title": title,
            "description": description,
            "content_type": content_type,
            "visibility": visibility,
        },
    )

    assert response.status_code == 201, response.text
    return response.json()


def _create_version(
    admin_client: TestClient,
    *,
    document_id: str,
    source_type: str = "markdown",
    source_content: str = "# Refund Policy\n\nRefunds take 5 days.",
    source_name: str | None = "refund-policy.md",
) -> dict:
    response = admin_client.post(
        f"/v1/knowledge/documents/{document_id}/versions",
        headers={"X-Trace-ID": str(uuid7())},
        json={
            "source_type": source_type,
            "source_content": source_content,
            "source_name": source_name,
        },
    )

    assert response.status_code == 201, response.text
    return response.json()


class TestKnowledgeDocumentQueries:
    def test_lists_empty_catalog(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            "/v1/knowledge/documents"
        )

        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "total": 0,
            "count": 0,
            "limit": 50,
            "offset": 0,
            "has_more": False,
            "next_offset": None,
        }

    def test_lists_and_filters_documents(
        self,
        admin_client: TestClient,
    ) -> None:
        policy = _create_document(
            admin_client,
            title="Refund Policy",
            content_type="policy",
            visibility="customer",
        )
        _create_document(
            admin_client,
            title="Agent Procedure",
            content_type="procedure",
            visibility="internal",
        )

        response = admin_client.get(
            "/v1/knowledge/documents",
            params={
                "content_type": "policy",
                "visibility": "customer",
                "status": "active",
            },
        )

        assert response.status_code == 200
        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1
        assert body["items"][0]["document_id"] == (
            policy["document_id"]
        )
        assert body["items"][0]["title"] == "Refund Policy"
        assert body["items"][0]["content_type"] == "policy"
        assert body["items"][0]["visibility"] == "customer"
        assert body["items"][0]["status"] == "active"

    def test_paginates_documents_without_duplicates(
        self,
        admin_client: TestClient,
    ) -> None:
        for index in range(3):
            _create_document(
                admin_client,
                title=f"Knowledge Document {index}",
            )

        first = admin_client.get(
            "/v1/knowledge/documents",
            params={"limit": 2, "offset": 0},
        )
        second = admin_client.get(
            "/v1/knowledge/documents",
            params={"limit": 2, "offset": 2},
        )

        assert first.status_code == 200
        assert second.status_code == 200

        first_body = first.json()
        second_body = second.json()

        assert first_body["total"] == 3
        assert first_body["count"] == 2
        assert first_body["has_more"] is True
        assert first_body["next_offset"] == 2

        assert second_body["total"] == 3
        assert second_body["count"] == 1
        assert second_body["has_more"] is False
        assert second_body["next_offset"] is None

        first_ids = {
            item["document_id"]
            for item in first_body["items"]
        }
        second_ids = {
            item["document_id"]
            for item in second_body["items"]
        }

        assert first_ids.isdisjoint(second_ids)

    def test_returns_document_detail(
        self,
        admin_client: TestClient,
    ) -> None:
        created = _create_document(admin_client)
        document_id = created["document_id"]

        _create_version(
            admin_client,
            document_id=document_id,
        )

        response = admin_client.get(
            f"/v1/knowledge/documents/{document_id}"
        )

        assert response.status_code == 200
        body = response.json()

        assert body["document_id"] == document_id
        assert body["title"] == "Refund Policy"
        assert body["status"] == "active"
        assert body["version_count"] == 1
        assert body["published_version_id"] is None

    def test_missing_document_returns_canonical_404(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            f"/v1/knowledge/documents/{uuid.uuid4()}"
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "KNOWLEDGE_NOT_FOUND"
        )


class TestKnowledgeVersionQueries:
    def test_lists_versions_with_filters(
        self,
        admin_client: TestClient,
    ) -> None:
        document = _create_document(admin_client)
        document_id = document["document_id"]

        markdown = _create_version(
            admin_client,
            document_id=document_id,
            source_type="markdown",
            source_content="# Version One",
            source_name="version-one.md",
        )
        _create_version(
            admin_client,
            document_id=document_id,
            source_type="plain_text",
            source_content="Version two",
            source_name="version-two.txt",
        )

        response = admin_client.get(
            f"/v1/knowledge/documents/{document_id}/versions",
            params={
                "source_type": "markdown",
                "status": "draft",
                "ingestion_status": "pending",
            },
        )

        assert response.status_code == 200
        body = response.json()

        assert body["document_id"] == document_id
        assert body["total"] == 1
        assert body["count"] == 1
        assert body["items"][0]["version_id"] == (
            markdown["version_id"]
        )
        assert body["items"][0]["source_type"] == "markdown"
        assert body["items"][0]["status"] == "draft"
        assert body["items"][0]["ingestion_status"] == "pending"

    def test_returns_version_detail_without_source_content(
        self,
        admin_client: TestClient,
    ) -> None:
        document = _create_document(admin_client)
        source_content = (
            "# Confidential Source\n\n"
            "This content must not appear in the response."
        )
        version = _create_version(
            admin_client,
            document_id=document["document_id"],
            source_content=source_content,
        )

        response = admin_client.get(
            f"/v1/knowledge/versions/{version['version_id']}"
        )

        assert response.status_code == 200
        body = response.json()

        assert body["version_id"] == version["version_id"]
        assert body["document_id"] == document["document_id"]
        assert body["document_title"] == "Refund Policy"
        assert body["source_content_length"] == len(source_content)
        assert body["is_current_published_version"] is False

        serialized = response.text.lower()

        assert "confidential source" not in serialized
        assert "source_content" not in body
        assert "source_uri" not in body
        assert "metadata" not in body
        assert "failure_message" not in body

    def test_paginates_versions_without_duplicates(
        self,
        admin_client: TestClient,
    ) -> None:
        document = _create_document(admin_client)
        document_id = document["document_id"]

        for index in range(3):
            _create_version(
                admin_client,
                document_id=document_id,
                source_content=f"# Version {index}",
                source_name=f"version-{index}.md",
            )

        first = admin_client.get(
            f"/v1/knowledge/documents/{document_id}/versions",
            params={"limit": 2, "offset": 0},
        )
        second = admin_client.get(
            f"/v1/knowledge/documents/{document_id}/versions",
            params={"limit": 2, "offset": 2},
        )

        assert first.status_code == 200
        assert second.status_code == 200

        first_body = first.json()
        second_body = second.json()

        assert first_body["total"] == 3
        assert first_body["count"] == 2
        assert first_body["next_offset"] == 2

        assert second_body["total"] == 3
        assert second_body["count"] == 1
        assert second_body["next_offset"] is None

        first_ids = {
            item["version_id"]
            for item in first_body["items"]
        }
        second_ids = {
            item["version_id"]
            for item in second_body["items"]
        }

        assert first_ids.isdisjoint(second_ids)

    def test_missing_version_returns_canonical_404(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            f"/v1/knowledge/versions/{uuid.uuid4()}"
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "KNOWLEDGE_NOT_FOUND"
        )

    def test_missing_document_version_list_returns_404(
        self,
        admin_client: TestClient,
    ) -> None:
        response = admin_client.get(
            f"/v1/knowledge/documents/{uuid.uuid4()}/versions"
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "KNOWLEDGE_NOT_FOUND"
        )