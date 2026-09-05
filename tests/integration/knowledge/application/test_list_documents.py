from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID
from uuid6 import uuid7

import pytest
from sqlalchemy.orm import Session, sessionmaker

from packages.database.models.knowledge.document import (
    KnowledgeDocumentModel,
)
from packages.database.unit_of_work.knowledge import (
    SQLAlchemyKnowledgeUnitOfWork,
)

from packages.knowledge.application.list_documents import (
    ListKnowledgeDocuments,
    ListKnowledgeDocumentsQuery,
)
from packages.knowledge.domain.enums import (
    KnowledgeContentType,
    KnowledgeDocumentStatus,
    KnowledgeVisibility,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("clean_database"),
]

UTC = timezone.utc


# ===========================================================================
# Helpers
# ===========================================================================


def utc_now() -> datetime:
    return datetime.now(UTC)


def seed_document(
    session_factory: sessionmaker[Session],
    *,
    title: str,
    status: str = "active",
    content_type: str = "policy",
    visibility: str = "customer",
    created_at: datetime | None = None,
) -> UUID:
    document_id = uuid7()

    now = created_at or utc_now()

    archived_at = (
        now
        if status == "archived"
        else None
    )

    deleted_at = (
        now
        if status == "deleted"
        else None
    )

    with session_factory() as session:
        session.add(
            KnowledgeDocumentModel(
                id=document_id,
                title=title,
                description=f"Integration test document: {title}",
                content_type=content_type,
                visibility=visibility,
                status=status,
                metadata_={
                    "integration_test": True,
                    "title": title,
                },
                created_at=now,
                updated_at=now,
                archived_at=archived_at,
                deleted_at=deleted_at,
            )
        )

        session.commit()

    return document_id


def build_service(
    session_factory: sessionmaker[Session],
) -> ListKnowledgeDocuments:
    return ListKnowledgeDocuments(
        uow_factory=lambda: SQLAlchemyKnowledgeUnitOfWork(
            session_factory
        )
    )


# ===========================================================================
# Basic listing
# ===========================================================================


class TestListDocuments:

    def test_returns_persisted_documents(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        first_id = seed_document(
            test_session_factory,
            title="Refund Policy",
        )

        second_id = seed_document(
            test_session_factory,
            title="Shipping Policy",
        )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery()
        )

        ids = {
            document.id
            for document in result.documents
        }

        assert first_id in ids
        assert second_id in ids

        assert result.total >= 2
        assert result.limit == 50
        assert result.offset == 0


    def test_returns_empty_result_when_no_documents_exist(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery()
        )

        assert result.documents == ()
        assert result.total == 0
        assert result.has_more is False


# ===========================================================================
# Status filtering
# ===========================================================================


class TestStatusFiltering:

    def test_filters_active_documents(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        active_id = seed_document(
            test_session_factory,
            title="Active Refund Policy",
            status="active",
        )

        archived_id = seed_document(
            test_session_factory,
            title="Archived Shipping Policy",
            status="archived",
        )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                status=KnowledgeDocumentStatus.ACTIVE
            )
        )

        ids = {
            document.id
            for document in result.documents
        }

        assert active_id in ids
        assert archived_id not in ids

        assert all(
            document.status
            is KnowledgeDocumentStatus.ACTIVE
            for document in result.documents
        )


    def test_filters_archived_documents(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        active_id = seed_document(
            test_session_factory,
            title="Active Policy",
            status="active",
        )

        archived_id = seed_document(
            test_session_factory,
            title="Archived Policy",
            status="archived",
        )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                status=KnowledgeDocumentStatus.ARCHIVED
            )
        )

        ids = {
            document.id
            for document in result.documents
        }

        assert archived_id in ids
        assert active_id not in ids


    def test_filters_deleted_documents(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        deleted_id = seed_document(
            test_session_factory,
            title="Deleted Policy",
            status="deleted",
        )

        active_id = seed_document(
            test_session_factory,
            title="Active Policy",
            status="active",
        )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                status=KnowledgeDocumentStatus.DELETED
            )
        )

        ids = {
            document.id
            for document in result.documents
        }

        assert deleted_id in ids
        assert active_id not in ids


# ===========================================================================
# Content type filtering
# ===========================================================================


class TestContentTypeFiltering:

    def test_filters_by_content_type(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        policy_id = seed_document(
            test_session_factory,
            title="Refund Policy",
            content_type="policy",
        )

        faq_id = seed_document(
            test_session_factory,
            title="Refund FAQ",
            content_type="faq",
        )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                content_type=KnowledgeContentType.POLICY
            )
        )

        ids = {
            document.id
            for document in result.documents
        }

        assert policy_id in ids
        assert faq_id not in ids

        assert all(
            document.content_type
            is KnowledgeContentType.POLICY
            for document in result.documents
        )


# ===========================================================================
# Visibility filtering
# ===========================================================================


class TestVisibilityFiltering:

    def test_filters_by_visibility(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        customer_id = seed_document(
            test_session_factory,
            title="Customer Policy",
            visibility="customer",
        )

        internal_id = seed_document(
            test_session_factory,
            title="Internal Runbook",
            visibility="internal",
        )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                visibility=KnowledgeVisibility.CUSTOMER
            )
        )

        ids = {
            document.id
            for document in result.documents
        }

        assert customer_id in ids
        assert internal_id not in ids

        assert all(
            document.visibility
            is KnowledgeVisibility.CUSTOMER
            for document in result.documents
        )


# ===========================================================================
# Combined filtering
# ===========================================================================


class TestCombinedFiltering:

    def test_applies_all_filters_together(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        expected_id = seed_document(
            test_session_factory,
            title="Active Customer Policy",
            status="active",
            content_type="policy",
            visibility="customer",
        )

        seed_document(
            test_session_factory,
            title="Archived Customer Policy",
            status="archived",
            content_type="policy",
            visibility="customer",
        )

        seed_document(
            test_session_factory,
            title="Active Internal Policy",
            status="active",
            content_type="policy",
            visibility="internal",
        )

        seed_document(
            test_session_factory,
            title="Active Customer FAQ",
            status="active",
            content_type="faq",
            visibility="customer",
        )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                status=KnowledgeDocumentStatus.ACTIVE,
                content_type=KnowledgeContentType.POLICY,
                visibility=KnowledgeVisibility.CUSTOMER,
            )
        )

        ids = {
            document.id
            for document in result.documents
        }

        assert ids == {
            expected_id
        }

        assert result.total == 1


# ===========================================================================
# Pagination
# ===========================================================================


class TestPagination:

    def test_limit_restricts_number_of_returned_documents(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        for index in range(5):
            seed_document(
                test_session_factory,
                title=f"Policy {index}",
            )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                limit=2,
                offset=0,
            )
        )

        assert len(result.documents) == 2
        assert result.total == 5
        assert result.limit == 2
        assert result.offset == 0
        assert result.has_more is True


    def test_offset_skips_previous_rows(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        base_time = utc_now()

        ids = []

        for index in range(4):
            document_id = seed_document(
                test_session_factory,
                title=f"Policy {index}",
                created_at=(
                    base_time
                    + timedelta(seconds=index)
                ),
            )

            ids.append(document_id)

        first_page = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                limit=2,
                offset=0,
            )
        )

        second_page = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                limit=2,
                offset=2,
            )
        )

        first_ids = {
            document.id
            for document in first_page.documents
        }

        second_ids = {
            document.id
            for document in second_page.documents
        }

        assert first_ids.isdisjoint(
            second_ids
        )

        assert len(first_ids) == 2
        assert len(second_ids) == 2


    def test_has_more_false_on_final_page(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        for index in range(5):
            seed_document(
                test_session_factory,
                title=f"Policy {index}",
            )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                limit=2,
                offset=4,
            )
        )

        assert len(result.documents) == 1
        assert result.total == 5
        assert result.has_more is False


    def test_offset_beyond_total_returns_empty_page(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        seed_document(
            test_session_factory,
            title="Refund Policy",
        )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                limit=10,
                offset=100,
            )
        )

        assert result.documents == ()
        assert result.total == 1
        assert result.has_more is False


# ===========================================================================
# Deterministic ordering
# ===========================================================================


class TestOrdering:

    def test_documents_are_ordered_newest_first(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        base_time = utc_now()

        oldest_id = seed_document(
            test_session_factory,
            title="Oldest",
            created_at=base_time,
        )

        middle_id = seed_document(
            test_session_factory,
            title="Middle",
            created_at=(
                base_time + timedelta(seconds=1)
            ),
        )

        newest_id = seed_document(
            test_session_factory,
            title="Newest",
            created_at=(
                base_time + timedelta(seconds=2)
            ),
        )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery()
        )

        result_ids = [
            document.id
            for document in result.documents
        ]

        assert result_ids == [
            newest_id,
            middle_id,
            oldest_id,
        ]


# ===========================================================================
# Count contract
# ===========================================================================


class TestFilteredCount:

    def test_total_reflects_filtered_dataset_not_all_documents(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        for index in range(3):
            seed_document(
                test_session_factory,
                title=f"Active {index}",
                status="active",
            )

        for index in range(2):
            seed_document(
                test_session_factory,
                title=f"Archived {index}",
                status="archived",
            )

        result = build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery(
                status=KnowledgeDocumentStatus.ARCHIVED
            )
        )

        assert result.total == 2
        assert len(result.documents) == 2


# ===========================================================================
# Read-only behavior
# ===========================================================================


class TestReadOnlyBehavior:

    def test_listing_does_not_modify_documents(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory,
            title="Refund Policy",
        )

        with test_session_factory() as session:
            before = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            assert before is not None

            original_status = before.status
            original_updated_at = before.updated_at

        build_service(
            test_session_factory
        ).execute(
            ListKnowledgeDocumentsQuery()
        )

        with test_session_factory() as session:
            after = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            assert after is not None

            assert after.status == original_status
            assert after.updated_at == original_updated_at