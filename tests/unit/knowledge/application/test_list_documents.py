from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from packages.knowledge.application.list_documents import (
    ListKnowledgeDocuments,
    ListKnowledgeDocumentsQuery,
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
    title="Policy",
):
    return KnowledgeDocument(
        id=uuid4(),
        title=title,
        content_type=KnowledgeContentType.POLICY,
        visibility=KnowledgeVisibility.CUSTOMER,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeDocumentRepository:
    def __init__(
        self,
        *,
        documents=(),
        total=0,
    ):
        self.documents = list(documents)
        self.total = total

        self.list_call = None
        self.count_filter = None

    def list(
        self,
        *,
        filter_,
        limit,
        offset,
    ):
        self.list_call = {
            "filter": filter_,
            "limit": limit,
            "offset": offset,
        }

        return list(self.documents)

    def count(
        self,
        *,
        filter_,
    ):
        self.count_filter = filter_
        return self.total


class FakeUoW:
    def __init__(
        self,
        *,
        documents=(),
        total=0,
    ):
        self.documents = FakeDocumentRepository(
            documents=documents,
            total=total,
        )

        self.commit_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.commit_count += 1


def test_query_defaults_are_bounded():
    query = ListKnowledgeDocumentsQuery()

    assert query.limit == 50
    assert query.offset == 0
    assert query.status is None
    assert query.content_type is None
    assert query.visibility is None


@pytest.mark.parametrize(
    "limit",
    [
        0,
        -1,
        201,
        10_000,
    ],
)
def test_query_rejects_invalid_limit(limit):
    with pytest.raises(ValueError):
        ListKnowledgeDocumentsQuery(
            limit=limit
        )


def test_query_rejects_boolean_limit():
    with pytest.raises(TypeError):
        ListKnowledgeDocumentsQuery(
            limit=True
        )


def test_query_rejects_negative_offset():
    with pytest.raises(ValueError):
        ListKnowledgeDocumentsQuery(
            offset=-1
        )


def test_query_rejects_boolean_offset():
    with pytest.raises(TypeError):
        ListKnowledgeDocumentsQuery(
            offset=False
        )


def test_filters_must_use_domain_enums():
    with pytest.raises(TypeError):
        ListKnowledgeDocumentsQuery(
            status="active"
        )

    with pytest.raises(TypeError):
        ListKnowledgeDocumentsQuery(
            content_type="policy"
        )

    with pytest.raises(TypeError):
        ListKnowledgeDocumentsQuery(
            visibility="customer"
        )


def test_returns_documents_and_pagination_metadata():
    documents = [
        make_document(title="A"),
        make_document(title="B"),
    ]

    uow = FakeUoW(
        documents=documents,
        total=7,
    )

    service = ListKnowledgeDocuments(
        uow_factory=lambda: uow
    )

    result = service.execute(
        ListKnowledgeDocumentsQuery(
            limit=2,
            offset=2,
        )
    )

    assert result.documents == tuple(documents)
    assert result.total == 7
    assert result.limit == 2
    assert result.offset == 2
    assert result.has_more is True

    assert uow.commit_count == 0


def test_has_more_false_on_final_page():
    documents = [
        make_document(),
    ]

    uow = FakeUoW(
        documents=documents,
        total=5,
    )

    result = ListKnowledgeDocuments(
        uow_factory=lambda: uow
    ).execute(
        ListKnowledgeDocumentsQuery(
            limit=2,
            offset=4,
        )
    )

    assert result.has_more is False


def test_passes_filters_to_repository():
    uow = FakeUoW(
        documents=[],
        total=0,
    )

    query = ListKnowledgeDocumentsQuery(
        status=KnowledgeDocumentStatus.ACTIVE,
        content_type=KnowledgeContentType.POLICY,
        visibility=KnowledgeVisibility.CUSTOMER,
        limit=25,
        offset=50,
    )

    ListKnowledgeDocuments(
        uow_factory=lambda: uow
    ).execute(query)

    list_filter = (
        uow.documents.list_call["filter"]
    )

    count_filter = (
        uow.documents.count_filter
    )

    assert (
        list_filter.status
        is KnowledgeDocumentStatus.ACTIVE
    )

    assert (
        list_filter.content_type
        is KnowledgeContentType.POLICY
    )

    assert (
        list_filter.visibility
        is KnowledgeVisibility.CUSTOMER
    )

    assert list_filter == count_filter

    assert (
        uow.documents.list_call["limit"]
        == 25
    )

    assert (
        uow.documents.list_call["offset"]
        == 50
    )