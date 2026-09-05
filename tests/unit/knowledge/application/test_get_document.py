from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from packages.knowledge.application.get_document import (
    GetKnowledgeDocument,
    GetKnowledgeDocumentQuery,
    KnowledgeDocumentDoesNotExistError,
)
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import (
    KnowledgeContentType,
    KnowledgeDocumentStatus,
    KnowledgeVisibility,
)


NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def make_document(
    *,
    document_id=None,
    status=KnowledgeDocumentStatus.ACTIVE,
):
    kwargs = {}

    if status is KnowledgeDocumentStatus.ARCHIVED:
        kwargs["archived_at"] = NOW

    if status is KnowledgeDocumentStatus.DELETED:
        kwargs["deleted_at"] = NOW

    return KnowledgeDocument(
        id=document_id or uuid4(),
        title="Refund Policy",
        content_type=KnowledgeContentType.POLICY,
        visibility=KnowledgeVisibility.CUSTOMER,
        status=status,
        created_at=NOW,
        updated_at=NOW,
        **kwargs,
    )

class FakeDocumentRepository:
    def __init__(self, document=None):
        self.document = document
        self.requested_id = None

    def get_by_id(self, document_id):
        self.requested_id = document_id

        if (
            self.document is not None
            and self.document.id == document_id
        ):
            return self.document

        return None


class FakeVersionRepository:
    def __init__(
        self,
        *,
        versions=(),
        published=None,
    ):
        self.versions = list(versions)
        self.published = published
        self.list_document_id = None
        self.published_document_id = None

    def list_for_document(self, document_id):
        self.list_document_id = document_id
        return list(self.versions)

    def get_published_for_document(self, document_id):
        self.published_document_id = document_id
        return self.published


class FakeUoW:
    def __init__(
        self,
        *,
        document=None,
        versions=(),
        published=None,
    ):
        self.documents = FakeDocumentRepository(
            document
        )

        self.versions = FakeVersionRepository(
            versions=versions,
            published=published,
        )

        self.commit_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.commit_count += 1


def test_query_rejects_non_uuid():
    with pytest.raises(TypeError):
        GetKnowledgeDocumentQuery(
            document_id="invalid"
        )


def test_returns_document_and_empty_version_history():
    document = make_document()

    uow = FakeUoW(
        document=document
    )

    service = GetKnowledgeDocument(
        uow_factory=lambda: uow
    )

    result = service.execute(
        GetKnowledgeDocumentQuery(
            document_id=document.id
        )
    )

    assert result.document == document
    assert result.versions == ()
    assert result.published_version_id is None

    assert (
        uow.documents.requested_id
        == document.id
    )

    assert uow.commit_count == 0


def test_returns_version_history_and_published_version_id():
    document = make_document()

    version_1 = object()
    version_2 = object()

    class Published:
        id = uuid4()

    published = Published()

    uow = FakeUoW(
        document=document,
        versions=[version_1, version_2],
        published=published,
    )

    service = GetKnowledgeDocument(
        uow_factory=lambda: uow
    )

    result = service.execute(
        GetKnowledgeDocumentQuery(
            document_id=document.id
        )
    )

    assert result.versions == (
        version_1,
        version_2,
    )

    assert (
        result.published_version_id
        == published.id
    )


def test_missing_document_raises_without_loading_versions():
    document_id = uuid4()

    uow = FakeUoW(
        document=None
    )

    service = GetKnowledgeDocument(
        uow_factory=lambda: uow
    )

    with pytest.raises(
        KnowledgeDocumentDoesNotExistError
    ):
        service.execute(
            GetKnowledgeDocumentQuery(
                document_id=document_id
            )
        )

    assert (
        uow.versions.list_document_id
        is None
    )

    assert (
        uow.versions.published_document_id
        is None
    )

    assert uow.commit_count == 0


def test_direct_lookup_allows_archived_document():
    document = make_document(
        status=KnowledgeDocumentStatus.ARCHIVED
    )

    uow = FakeUoW(
        document=document
    )

    result = GetKnowledgeDocument(
        uow_factory=lambda: uow
    ).execute(
        GetKnowledgeDocumentQuery(
            document_id=document.id
        )
    )

    assert result.document.is_archived