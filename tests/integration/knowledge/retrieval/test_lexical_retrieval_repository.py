from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session, sessionmaker

from packages.database.models.knowledge.chunk import KnowledgeChunkModel
from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.document_version import (
    KnowledgeDocumentVersionModel,
)
from packages.database.repositories.knowledge.lexical_retrieval_repository import (
    SQLAlchemyLexicalRetrievalRepository,
)
from packages.knowledge.domain.enums import (
    KnowledgeContentType,
    KnowledgeDocumentStatus,
    KnowledgeIngestionStatus,
    KnowledgeVersionStatus,
    KnowledgeVisibility,
)
from packages.knowledge.retrieval.lexical.repository import (
    LexicalSearchRequest,
)
from packages.knowledge.retrieval.models import (
    RetrievalFilters,
    RetrievalMethod,
)


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test safety
# ---------------------------------------------------------------------------


EXPECTED_TEST_DATABASE = "support_ai_test"


def assert_test_database(session: Session) -> None:
    """
    Prevent accidental integration-test writes against the development DB.

    This guard is intentionally explicit because these tests insert and
    delete real knowledge rows.
    """

    database_name = session.scalar(
        text("select current_database()")
    )

    if database_name != EXPECTED_TEST_DATABASE:
        raise RuntimeError(
            "Refusing lexical retrieval integration-test writes: "
            f"connected to {database_name!r}, expected "
            f"{EXPECTED_TEST_DATABASE!r}."
        )


# ---------------------------------------------------------------------------
# Seed tracking
# ---------------------------------------------------------------------------


@dataclass
class SeedTracker:
    session: Session
    document_ids: list[UUID] = field(default_factory=list)

    def track_document(
        self,
        document_id: UUID,
    ) -> UUID:
        self.document_ids.append(document_id)
        return document_id


@pytest.fixture()
def retrieval_session(
    test_session_factory: sessionmaker[Session],
):
    session = test_session_factory()

    assert_test_database(session)

    tracker = SeedTracker(session=session)

    try:
        yield tracker

    finally:
        session.rollback()

        if tracker.document_ids:
            session.execute(
                delete(KnowledgeDocumentModel).where(
                    KnowledgeDocumentModel.id.in_(
                        tracker.document_ids
                    )
                )
            )
            session.commit()

        session.close()


def repository_for(
    session: Session,
) -> SQLAlchemyLexicalRetrievalRepository:
    return SQLAlchemyLexicalRetrievalRepository(
        session=session
    )


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def seed_document(
    tracker: SeedTracker,
    *,
    title: str,
    content_type: str = KnowledgeContentType.POLICY.value,
    visibility: str = KnowledgeVisibility.CUSTOMER.value,
    status: str = KnowledgeDocumentStatus.ACTIVE.value,
    metadata: dict | None = None,
) -> UUID:
    document_id = tracker.track_document(
        uuid4()
    )

    tracker.session.add(
        KnowledgeDocumentModel(
            id=document_id,
            title=title,
            description=None,
            content_type=content_type,
            visibility=visibility,
            status=status,
            metadata_=metadata or {},
            created_at=utc_now(),
            updated_at=utc_now(),
            archived_at=(
                utc_now()
                if status
                == KnowledgeDocumentStatus.ARCHIVED.value
                else None
            ),
            deleted_at=(
                utc_now()
                if status
                == KnowledgeDocumentStatus.DELETED.value
                else None
            ),
        )
    )

    tracker.session.flush()

    return document_id


def seed_version(
    tracker: SeedTracker,
    *,
    document_id: UUID,
    version_number: int = 1,
    status: str = KnowledgeVersionStatus.PUBLISHED.value,
    ingestion_status: str = (
        KnowledgeIngestionStatus.COMPLETED.value
    ),
) -> UUID:
    version_id = uuid4()
    now = utc_now()

    tracker.session.add(
        KnowledgeDocumentVersionModel(
            id=version_id,
            document_id=document_id,
            version_number=version_number,
            source_type="markdown",
            source_content="# Integration test source",
            content_hash=uuid4().hex + uuid4().hex,
            status=status,
            ingestion_status=ingestion_status,
            source_name="integration-test.md",
            source_uri=None,
            metadata_={},
            created_at=now,
            updated_at=now,
            processing_started_at=(
                now
                if ingestion_status
                != KnowledgeIngestionStatus.PENDING.value
                else None
            ),
            processing_completed_at=(
                now
                if ingestion_status
                == KnowledgeIngestionStatus.COMPLETED.value
                else None
            ),
            published_at=(
                now
                if status
                == KnowledgeVersionStatus.PUBLISHED.value
                else None
            ),
            superseded_at=None,
            archived_at=None,
            failure_code=None,
            failure_message=None,
        )
    )

    tracker.session.flush()

    return version_id


def seed_chunk(
    tracker: SeedTracker,
    *,
    version_id: UUID,
    chunk_index: int,
    content: str,
    section_title: str | None = None,
    metadata: dict | None = None,
) -> UUID:
    chunk_id = uuid4()

    tracker.session.add(
        KnowledgeChunkModel(
            id=chunk_id,
            version_id=version_id,
            chunk_index=chunk_index,
            content=content,
            section_title=section_title,
            start_offset=0,
            end_offset=len(content),
            token_count=max(
                1,
                len(content.split()),
            ),
            metadata_=metadata or {},
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    tracker.session.flush()

    return chunk_id


def seed_retrievable_chunk(
    tracker: SeedTracker,
    *,
    title: str,
    section_title: str | None,
    content: str,
    content_type: str = KnowledgeContentType.POLICY.value,
    visibility: str = KnowledgeVisibility.CUSTOMER.value,
    document_status: str = KnowledgeDocumentStatus.ACTIVE.value,
    version_status: str = KnowledgeVersionStatus.PUBLISHED.value,
    ingestion_status: str = (
        KnowledgeIngestionStatus.COMPLETED.value
    ),
    document_metadata: dict | None = None,
    chunk_metadata: dict | None = None,
) -> tuple[UUID, UUID, UUID]:
    document_id = seed_document(
        tracker,
        title=title,
        content_type=content_type,
        visibility=visibility,
        status=document_status,
        metadata=document_metadata,
    )

    version_id = seed_version(
        tracker,
        document_id=document_id,
        status=version_status,
        ingestion_status=ingestion_status,
    )

    chunk_id = seed_chunk(
        tracker,
        version_id=version_id,
        chunk_index=0,
        content=content,
        section_title=section_title,
        metadata=chunk_metadata,
    )

    tracker.session.commit()

    return (
        document_id,
        version_id,
        chunk_id,
    )


def build_request(
    *,
    query_text: str,
    filters: RetrievalFilters | None = None,
    limit: int = 20,
) -> LexicalSearchRequest:
    return LexicalSearchRequest(
        query_text=query_text,
        filters=(
            filters
            if filters is not None
            else RetrievalFilters()
        ),
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Core matching
# ---------------------------------------------------------------------------


class TestLexicalRetrievalMatching:
    def test_returns_matching_chunk(
        self,
        retrieval_session: SeedTracker,
    ):
        _, _, chunk_id = seed_retrievable_chunk(
            retrieval_session,
            title="Refund Policy",
            section_title="Refund Eligibility",
            content=(
                "Customers can request a refund within "
                "thirty days of purchase."
            ),
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="refund eligibility"
            )
        )

        assert matches
        assert matches[0].candidate.chunk_id == chunk_id
        assert matches[0].score > 0.0
        assert matches[0].candidate.methods == frozenset(
            {
                RetrievalMethod.LEXICAL,
            }
        )

    def test_returns_empty_tuple_for_no_match(
        self,
        retrieval_session: SeedTracker,
    ):
        seed_retrievable_chunk(
            retrieval_session,
            title="Shipping Policy",
            section_title="Domestic Delivery",
            content=(
                "Domestic orders normally arrive "
                "within five business days."
            ),
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="cryptocurrency mining"
            )
        )

        assert matches == ()

    def test_candidate_preserves_provenance(
        self,
        retrieval_session: SeedTracker,
    ):
        document_id, version_id, chunk_id = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Payment Policy",
                section_title="Card Payments",
                content=(
                    "Customers may pay using supported "
                    "credit and debit cards."
                ),
                chunk_metadata={
                    "section_path": [
                        "Payments",
                        "Cards",
                    ]
                },
            )
        )

        repository = repository_for(
            retrieval_session.session
        )

        match = repository.search(
            build_request(
                query_text="credit card"
            )
        )[0]

        candidate = match.candidate

        assert candidate.chunk_id == chunk_id
        assert candidate.version_id == version_id
        assert candidate.document_id == document_id
        assert candidate.document_title == "Payment Policy"
        assert candidate.section_title == "Card Payments"
        assert candidate.metadata == {
            "section_path": [
                "Payments",
                "Cards",
            ]
        }


# ---------------------------------------------------------------------------
# Structural weighting
# ---------------------------------------------------------------------------


class TestLexicalRetrievalWeighting:
    def test_document_title_match_ranks_above_body_only_match(
        self,
        retrieval_session: SeedTracker,
    ):
        _, _, title_match_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="International Refund Policy",
                section_title="Eligibility",
                content=(
                    "Customers should contact support "
                    "for assistance."
                ),
            )
        )

        _, _, body_match_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="General Customer Policy",
                section_title="Support",
                content=(
                    "International refund requests "
                    "may require manual review."
                ),
            )
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="international refund"
            )
        )

        ids = [
            match.candidate.chunk_id
            for match in matches
        ]

        assert title_match_chunk in ids
        assert body_match_chunk in ids

        assert ids.index(
            title_match_chunk
        ) < ids.index(
            body_match_chunk
        )

    def test_section_title_match_gets_ranked_relevance(
        self,
        retrieval_session: SeedTracker,
    ):
        _, _, section_match = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Order Policy",
                section_title="Order Cancellation",
                content=(
                    "Contact support before fulfillment."
                ),
            )
        )

        _, _, body_match = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Order Policy",
                section_title="General Information",
                content=(
                    "Order cancellation may be requested "
                    "before fulfillment."
                ),
            )
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="order cancellation"
            )
        )

        ids = [
            match.candidate.chunk_id
            for match in matches
        ]

        assert section_match in ids
        assert body_match in ids

        assert ids.index(
            section_match
        ) < ids.index(
            body_match
        )


# ---------------------------------------------------------------------------
# Lifecycle invariants
# ---------------------------------------------------------------------------


class TestLexicalRetrievalLifecycle:
    def test_excludes_archived_document(
        self,
        retrieval_session: SeedTracker,
    ):
        _, _, archived_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Archived Refund Policy",
                section_title="Refunds",
                content="Refunds are allowed.",
                document_status=(
                    KnowledgeDocumentStatus.ARCHIVED.value
                ),
            )
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="refund"
            )
        )

        assert archived_chunk not in {
            match.candidate.chunk_id
            for match in matches
        }

    def test_excludes_ready_but_unpublished_version(
        self,
        retrieval_session: SeedTracker,
    ):
        _, _, ready_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Draft Refund Policy",
                section_title="Refunds",
                content="Refunds are available.",
                version_status=(
                    KnowledgeVersionStatus.READY.value
                ),
            )
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="refund"
            )
        )

        assert ready_chunk not in {
            match.candidate.chunk_id
            for match in matches
        }

    def test_excludes_incomplete_ingestion(
        self,
        retrieval_session: SeedTracker,
    ):
        _, _, processing_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Refund Policy",
                section_title="Refunds",
                content="Refunds are available.",
                ingestion_status=(
                    KnowledgeIngestionStatus.RUNNING.value
                ),
            )
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="refund"
            )
        )

        assert processing_chunk not in {
            match.candidate.chunk_id
            for match in matches
        }


# ---------------------------------------------------------------------------
# Business filters
# ---------------------------------------------------------------------------


class TestLexicalRetrievalFilters:
    def test_filters_by_document_id(
        self,
        retrieval_session: SeedTracker,
    ):
        first_document, _, first_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Refund Policy One",
                section_title="Refunds",
                content="Refund requests are supported.",
            )
        )

        _, _, second_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Refund Policy Two",
                section_title="Refunds",
                content="Refund requests are supported.",
            )
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="refund",
                filters=RetrievalFilters(
                    document_ids=(
                        first_document,
                    )
                ),
            )
        )

        ids = {
            match.candidate.chunk_id
            for match in matches
        }

        assert first_chunk in ids
        assert second_chunk not in ids

    def test_filters_by_content_type(
        self,
        retrieval_session: SeedTracker,
    ):
        _, _, policy_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Refund Policy",
                section_title="Refunds",
                content="Refund requests are supported.",
                content_type=(
                    KnowledgeContentType.POLICY.value
                ),
            )
        )

        _, _, faq_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Refund FAQ",
                section_title="Refunds",
                content="Refund requests are supported.",
                content_type=(
                    KnowledgeContentType.FAQ.value
                ),
            )
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="refund",
                filters=RetrievalFilters(
                    content_types=(
                        KnowledgeContentType.POLICY.value,
                    )
                ),
            )
        )

        ids = {
            match.candidate.chunk_id
            for match in matches
        }

        assert policy_chunk in ids
        assert faq_chunk not in ids

    def test_filters_by_visibility(
        self,
        retrieval_session: SeedTracker,
    ):
        _, _, customer_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Customer Refund Policy",
                section_title="Refunds",
                content="Refund requests are supported.",
                visibility=(
                    KnowledgeVisibility.CUSTOMER.value
                ),
            )
        )

        _, _, internal_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="Internal Refund Guidance",
                section_title="Refunds",
                content="Refund requests are supported.",
                visibility=(
                    KnowledgeVisibility.INTERNAL.value
                ),
            )
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="refund",
                filters=RetrievalFilters(
                    visibilities=(
                        KnowledgeVisibility.CUSTOMER.value,
                    )
                ),
            )
        )

        ids = {
            match.candidate.chunk_id
            for match in matches
        }

        assert customer_chunk in ids
        assert internal_chunk not in ids

    def test_filters_by_document_metadata_using_jsonb_containment(
        self,
        retrieval_session: SeedTracker,
    ):
        _, _, india_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="India Refund Policy",
                section_title="Refunds",
                content="Refund requests are supported.",
                document_metadata={
                    "region": "IN",
                    "product": "payments",
                },
            )
        )

        _, _, us_chunk = (
            seed_retrievable_chunk(
                retrieval_session,
                title="US Refund Policy",
                section_title="Refunds",
                content="Refund requests are supported.",
                document_metadata={
                    "region": "US",
                    "product": "payments",
                },
            )
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="refund",
                filters=RetrievalFilters(
                    metadata={
                        "region": "IN",
                    }
                ),
            )
        )

        ids = {
            match.candidate.chunk_id
            for match in matches
        }

        assert india_chunk in ids
        assert us_chunk not in ids


# ---------------------------------------------------------------------------
# Query handling
# ---------------------------------------------------------------------------


class TestLexicalRetrievalQueryHandling:
    @pytest.mark.parametrize(
        "query_text",
        [
            "refund OR cancellation",
            '"international shipping"',
            "payment -cash",
            "refund after 30 days",
        ],
    )
    def test_accepts_web_style_natural_language_queries(
        self,
        retrieval_session: SeedTracker,
        query_text: str,
    ):
        seed_retrievable_chunk(
            retrieval_session,
            title="Refund and Payment Policy",
            section_title="International Shipping",
            content=(
                "Customers can request cancellation, "
                "refunds, or card payment assistance "
                "within thirty days."
            ),
        )

        repository = repository_for(
            retrieval_session.session
        )

        result = repository.search(
            build_request(
                query_text=query_text
            )
        )

        assert isinstance(
            result,
            tuple,
        )

    def test_trims_query_text(
        self,
        retrieval_session: SeedTracker,
    ):
        _, _, chunk_id = seed_retrievable_chunk(
            retrieval_session,
            title="Refund Policy",
            section_title="Refunds",
            content="Refund requests are supported.",
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="   refund   "
            )
        )

        assert chunk_id in {
            match.candidate.chunk_id
            for match in matches
        }


# ---------------------------------------------------------------------------
# Limits and ordering
# ---------------------------------------------------------------------------


class TestLexicalRetrievalLimits:
    def test_respects_result_limit(
        self,
        retrieval_session: SeedTracker,
    ):
        for index in range(5):
            seed_retrievable_chunk(
                retrieval_session,
                title=f"Refund Policy {index}",
                section_title="Refunds",
                content=(
                    "Refund requests are supported "
                    "for eligible customers."
                ),
            )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="refund",
                limit=2,
            )
        )

        assert len(matches) == 2

    def test_scores_are_non_negative_and_descending(
        self,
        retrieval_session: SeedTracker,
    ):
        seed_retrievable_chunk(
            retrieval_session,
            title="Refund Policy",
            section_title="Refund Eligibility",
            content=(
                "Refund refund refund eligibility "
                "requirements are described here."
            ),
        )

        seed_retrievable_chunk(
            retrieval_session,
            title="General Policy",
            section_title="Customer Support",
            content=(
                "A refund may be requested "
                "under certain circumstances."
            ),
        )

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(
                query_text="refund eligibility"
            )
        )

        scores = [
            match.score
            for match in matches
        ]

        assert all(
            score >= 0.0
            for score in scores
        )

        assert scores == sorted(
            scores,
            reverse=True,
        )