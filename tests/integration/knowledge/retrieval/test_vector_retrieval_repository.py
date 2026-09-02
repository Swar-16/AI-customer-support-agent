from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

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
from packages.database.repositories.knowledge.vector_retrieval_repository import (
    SQLAlchemyVectorRetrievalRepository,
)
from packages.knowledge.embeddings.models import (
    EmbeddingInputDescriptor,
    EmbeddingProviderDescriptor,
    EmbeddingVector,
)
from packages.knowledge.retrieval.models import (
    RetrievalFilters,
    RetrievalMethod,
)
from packages.knowledge.retrieval.vector.repository import (
    VectorSearchRequest,
)


pytestmark = pytest.mark.integration

UTC = timezone.utc


# ===========================================================================
# Fixed retrieval profile used by these integration tests
# ===========================================================================


TEST_PROVIDER = EmbeddingProviderDescriptor(
    provider="integration-test",
    model="deterministic-v1",
    revision="1",
    dimensions=3,
)

TEST_INPUT_DESCRIPTOR = EmbeddingInputDescriptor(
    strategy_id="integration-contextual",
    version="1",
    config_fingerprint="a" * 64,
)


# ===========================================================================
# Test-data helpers
# ===========================================================================


def utc_now() -> datetime:
    return datetime.now(UTC)


def seed_document(
    session: Session,
    *,
    title: str = "Refund Policy",
    content_type: str = "policy",
    visibility: str = "customer",
    status: str = "active",
    metadata: dict[str, object] | None = None,
) -> UUID:
    document_id = uuid4()
    now = utc_now()

    session.add(
        KnowledgeDocumentModel(
            id=document_id,
            title=title,
            description="Vector retrieval integration test document.",
            content_type=content_type,
            visibility=visibility,
            status=status,
            metadata_=(
                {
                    "integration_test": True,
                    **(metadata or {}),
                }
            ),
            created_at=now,
            updated_at=now,
            archived_at=(
                now
                if status == "archived"
                else None
            ),
            deleted_at=(
                now
                if status == "deleted"
                else None
            ),
        )
    )

    # Explicit flush makes FK ordering obvious and keeps failures local.
    session.flush()

    return document_id


def seed_version(
    session: Session,
    *,
    document_id: UUID,
    version_number: int = 1,
    status: str = "published",
    ingestion_status: str = "completed",
) -> UUID:
    version_id = uuid4()

    now = utc_now()
    created_at = now - timedelta(seconds=10)
    processing_started_at = now - timedelta(seconds=9)
    processing_completed_at = now - timedelta(seconds=5)

    is_published = status == "published"
    is_ready_or_published = status in {
        "ready",
        "published",
        "superseded",
    }

    session.add(
        KnowledgeDocumentVersionModel(
            id=version_id,
            document_id=document_id,
            version_number=version_number,
            source_type="plain_text",
            source_content=(
                f"Integration test knowledge version "
                f"{version_number}."
            ),
            content_hash=uuid4().hex + uuid4().hex,
            status=status,
            ingestion_status=ingestion_status,
            source_name=(
                f"integration-vector-v{version_number}.txt"
            ),
            source_uri=None,
            metadata_={
                "integration_test": True,
            },
            created_at=created_at,
            updated_at=now,
            processing_started_at=(
                processing_started_at
                if ingestion_status == "completed"
                else None
            ),
            processing_completed_at=(
                processing_completed_at
                if ingestion_status == "completed"
                else None
            ),
            ready_at=(
                processing_completed_at
                if is_ready_or_published
                else None
            ),
            published_at=(
                now
                if is_published
                else None
            ),
            superseded_at=None,
            archived_at=None,
            failure_code=None,
            failure_message=None,
        )
    )

    session.flush()

    return version_id


def seed_chunk(
    session: Session,
    *,
    version_id: UUID,
    chunk_index: int,
    content: str,
    section_title: str | None = None,
    metadata: dict[str, object] | None = None,
) -> UUID:
    chunk_id = uuid4()
    now = utc_now()

    session.add(
        KnowledgeChunkModel(
            id=chunk_id,
            version_id=version_id,
            chunk_index=chunk_index,
            content=content,
            section_title=section_title,
            start_offset=None,
            end_offset=None,
            token_count=None,
            metadata_=(
                {
                    "integration_test": True,
                    **(metadata or {}),
                }
            ),
            created_at=now,
            updated_at=now,
        )
    )

    session.flush()

    return chunk_id


def seed_embedding(
    session: Session,
    *,
    chunk_id: UUID,
    vector: Sequence[float],
    provider: EmbeddingProviderDescriptor = TEST_PROVIDER,
    input_descriptor: EmbeddingInputDescriptor = (
        TEST_INPUT_DESCRIPTOR
    ),
    input_fingerprint: str | None = None,
) -> UUID:
    embedding_id = uuid4()

    session.add(
        KnowledgeChunkEmbeddingModel(
            id=embedding_id,
            chunk_id=chunk_id,
            provider=provider.provider,
            model=provider.model,
            model_revision=provider.revision,
            dimensions=provider.dimensions,
            embedding=list(vector),
            input_strategy_id=input_descriptor.strategy_id,
            input_strategy_version=input_descriptor.version,
            input_config_fingerprint=(
                input_descriptor.config_fingerprint
            ),
            input_fingerprint=(
                input_fingerprint
                or uuid4().hex + uuid4().hex
            ),
        )
    )

    session.flush()

    return embedding_id


def seed_retrievable_chunk(
    session: Session,
    *,
    vector: Sequence[float],
    chunk_index: int = 0,
    content: str = "Refunds are processed within five business days.",
    title: str = "Refund Policy",
    section_title: str | None = "Refund Timing",
    content_type: str = "policy",
    visibility: str = "customer",
    document_status: str = "active",
    version_status: str = "published",
    ingestion_status: str = "completed",
    document_metadata: dict[str, object] | None = None,
    chunk_metadata: dict[str, object] | None = None,
    provider: EmbeddingProviderDescriptor = TEST_PROVIDER,
    input_descriptor: EmbeddingInputDescriptor = (
        TEST_INPUT_DESCRIPTOR
    ),
) -> tuple[UUID, UUID, UUID]:
    """
    Seed one complete document -> version -> chunk -> embedding graph.

    Returns:
        (document_id, version_id, chunk_id)
    """

    document_id = seed_document(
        session,
        title=title,
        content_type=content_type,
        visibility=visibility,
        status=document_status,
        metadata=document_metadata,
    )

    version_id = seed_version(
        session,
        document_id=document_id,
        status=version_status,
        ingestion_status=ingestion_status,
    )

    chunk_id = seed_chunk(
        session,
        version_id=version_id,
        chunk_index=chunk_index,
        content=content,
        section_title=section_title,
        metadata=chunk_metadata,
    )

    seed_embedding(
        session,
        chunk_id=chunk_id,
        vector=vector,
        provider=provider,
        input_descriptor=input_descriptor,
    )

    return document_id, version_id, chunk_id


def build_request(
    *,
    vector: Sequence[float] = (1.0, 0.0, 0.0),
    filters: RetrievalFilters | None = None,
    limit: int = 20,
    provider: EmbeddingProviderDescriptor = TEST_PROVIDER,
    input_descriptor: EmbeddingInputDescriptor = (
        TEST_INPUT_DESCRIPTOR
    ),
) -> VectorSearchRequest:
    return VectorSearchRequest(
        query_vector=EmbeddingVector.from_sequence(vector),
        provider=provider,
        input_descriptor=input_descriptor,
        filters=(
            RetrievalFilters()
            if filters is None
            else filters
        ),
        limit=limit,
    )


# ===========================================================================
# Cleanup
# ===========================================================================


@pytest.fixture()
def retrieval_session(
    test_session_factory: sessionmaker[Session],
):
    """
    Give each test one real PostgreSQL session and remove all documents
    created by this file afterward.

    Deleting documents is enough because version -> chunk -> embedding rows
    are connected through ON DELETE CASCADE.
    """

    session = test_session_factory()
    created_document_ids: set[UUID] = set()

    class SeedTracker:
        @property
        def session(self) -> Session:
            return session

        def track(self, document_id: UUID) -> None:
            created_document_ids.add(document_id)

        def seed(
            self,
            **kwargs,
        ) -> tuple[UUID, UUID, UUID]:
            result = seed_retrievable_chunk(
                session,
                **kwargs,
            )

            created_document_ids.add(result[0])

            return result

    tracker = SeedTracker()

    try:
        yield tracker

        # Ensure data is visible to subsequent operations in the test.
        session.rollback()

    finally:
        session.rollback()

        if created_document_ids:
            session.execute(
                delete(KnowledgeDocumentModel).where(
                    KnowledgeDocumentModel.id.in_(
                        created_document_ids
                    )
                )
            )
            session.commit()

        session.close()


def repository_for(
    session: Session,
) -> SQLAlchemyVectorRetrievalRepository:
    return SQLAlchemyVectorRetrievalRepository(
        session
    )


# ===========================================================================
# Basic vector retrieval
# ===========================================================================


class TestVectorRetrievalRanking:
    def test_returns_nearest_chunks_in_cosine_distance_order(
        self,
        retrieval_session,
    ) -> None:
        _, _, exact_chunk_id = retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            content="Exact semantic match.",
            title="Exact Match",
        )

        _, _, medium_chunk_id = retrieval_session.seed(
            vector=(0.8, 0.6, 0.0),
            content="Related semantic match.",
            title="Medium Match",
        )

        _, _, distant_chunk_id = retrieval_session.seed(
            vector=(0.0, 1.0, 0.0),
            content="Distant semantic match.",
            title="Distant Match",
        )

        retrieval_session.session.commit()

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request()
        )

        returned_ids = [
            match.candidate.chunk_id
            for match in matches
        ]

        assert returned_ids == [
            exact_chunk_id,
            medium_chunk_id,
            distant_chunk_id,
        ]

        assert matches[0].distance == pytest.approx(
            0.0,
            abs=1e-6,
        )

        assert matches[1].distance == pytest.approx(
            0.2,
            abs=1e-6,
        )

        assert matches[2].distance == pytest.approx(
            1.0,
            abs=1e-6,
        )

    def test_returns_candidate_provenance_and_content(
        self,
        retrieval_session,
    ) -> None:
        (
            document_id,
            version_id,
            chunk_id,
        ) = retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            content="Refunds take five business days.",
            title="Refund Policy",
            section_title="Processing Time",
            chunk_metadata={
                "section_path": [
                    "Refunds",
                    "Processing",
                ],
            },
        )

        retrieval_session.session.commit()

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(limit=1)
        )

        assert len(matches) == 1

        candidate = matches[0].candidate

        assert candidate.document_id == document_id
        assert candidate.version_id == version_id
        assert candidate.chunk_id == chunk_id

        assert candidate.chunk_index == 0
        assert (
            candidate.content
            == "Refunds take five business days."
        )
        assert candidate.document_title == "Refund Policy"
        assert candidate.section_title == "Processing Time"

        assert candidate.methods == frozenset(
            {RetrievalMethod.VECTOR}
        )

        assert candidate.metadata["section_path"] == [
            "Refunds",
            "Processing",
        ]

    def test_respects_result_limit(
        self,
        retrieval_session,
    ) -> None:
        for index, vector in enumerate(
            (
                (1.0, 0.0, 0.0),
                (0.9, 0.1, 0.0),
                (0.8, 0.2, 0.0),
            )
        ):
            retrieval_session.seed(
                vector=vector,
                content=f"Candidate {index}",
                title=f"Document {index}",
            )

        retrieval_session.session.commit()

        repository = repository_for(
            retrieval_session.session
        )

        matches = repository.search(
            build_request(limit=2)
        )

        assert len(matches) == 2


# ===========================================================================
# Embedding-profile isolation
# ===========================================================================


class TestEmbeddingProfileMatching:
    def test_ignores_embedding_from_different_provider(
        self,
        retrieval_session,
    ) -> None:
        other_provider = EmbeddingProviderDescriptor(
            provider="another-provider",
            model=TEST_PROVIDER.model,
            revision=TEST_PROVIDER.revision,
            dimensions=3,
        )

        retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            provider=other_provider,
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request()
        )

        assert matches == ()

    def test_ignores_embedding_from_different_model(
        self,
        retrieval_session,
    ) -> None:
        other_provider = EmbeddingProviderDescriptor(
            provider=TEST_PROVIDER.provider,
            model="different-model",
            revision=TEST_PROVIDER.revision,
            dimensions=3,
        )

        retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            provider=other_provider,
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request()
        )

        assert matches == ()

    def test_ignores_embedding_from_different_revision(
        self,
        retrieval_session,
    ) -> None:
        other_provider = EmbeddingProviderDescriptor(
            provider=TEST_PROVIDER.provider,
            model=TEST_PROVIDER.model,
            revision="2",
            dimensions=3,
        )

        retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            provider=other_provider,
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request()
        )

        assert matches == ()

    def test_matches_null_model_revision_exactly(
        self,
        retrieval_session,
    ) -> None:
        revisionless_provider = EmbeddingProviderDescriptor(
            provider=TEST_PROVIDER.provider,
            model=TEST_PROVIDER.model,
            revision=None,
            dimensions=3,
        )

        _, _, chunk_id = retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            provider=revisionless_provider,
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request(
                provider=revisionless_provider
            )
        )

        assert len(matches) == 1
        assert matches[0].candidate.chunk_id == chunk_id

    def test_ignores_different_input_strategy_version(
        self,
        retrieval_session,
    ) -> None:
        other_input = EmbeddingInputDescriptor(
            strategy_id=(
                TEST_INPUT_DESCRIPTOR.strategy_id
            ),
            version="2",
            config_fingerprint=(
                TEST_INPUT_DESCRIPTOR.config_fingerprint
            ),
        )

        retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            input_descriptor=other_input,
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request()
        )

        assert matches == ()

    def test_ignores_different_input_config_fingerprint(
        self,
        retrieval_session,
    ) -> None:
        other_input = EmbeddingInputDescriptor(
            strategy_id=(
                TEST_INPUT_DESCRIPTOR.strategy_id
            ),
            version=TEST_INPUT_DESCRIPTOR.version,
            config_fingerprint="b" * 64,
        )

        retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            input_descriptor=other_input,
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request()
        )

        assert matches == ()


# ===========================================================================
# Knowledge lifecycle invariants
# ===========================================================================


class TestRetrievalLifecycleInvariants:
    def test_does_not_return_archived_document(
        self,
        retrieval_session,
    ) -> None:
        retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            document_status="archived",
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request()
        )

        assert matches == ()

    def test_does_not_return_unpublished_version(
        self,
        retrieval_session,
    ) -> None:
        retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            version_status="ready",
            ingestion_status="completed",
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request()
        )

        assert matches == ()


# ===========================================================================
# Business filters
# ===========================================================================


class TestVectorRetrievalFilters:
    def test_filters_by_document_id(
        self,
        retrieval_session,
    ) -> None:
        (
            wanted_document_id,
            _,
            wanted_chunk_id,
        ) = retrieval_session.seed(
            vector=(0.8, 0.6, 0.0),
            title="Wanted Document",
        )

        retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            title="Closer But Excluded",
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request(
                filters=RetrievalFilters(
                    document_ids=(
                        wanted_document_id,
                    )
                )
            )
        )

        assert len(matches) == 1
        assert (
            matches[0].candidate.chunk_id
            == wanted_chunk_id
        )

    def test_filters_by_content_type(
        self,
        retrieval_session,
    ) -> None:
        _, _, policy_chunk_id = retrieval_session.seed(
            vector=(0.8, 0.6, 0.0),
            content_type="policy",
            title="Policy",
        )

        retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            content_type="faq",
            title="FAQ",
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request(
                filters=RetrievalFilters(
                    content_types=("policy",)
                )
            )
        )

        assert len(matches) == 1
        assert (
            matches[0].candidate.chunk_id
            == policy_chunk_id
        )

    def test_filters_by_visibility(
        self,
        retrieval_session,
    ) -> None:
        _, _, customer_chunk_id = retrieval_session.seed(
            vector=(0.8, 0.6, 0.0),
            visibility="customer",
            title="Customer Knowledge",
        )

        retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            visibility="internal",
            title="Internal Knowledge",
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request(
                filters=RetrievalFilters(
                    visibilities=("customer",)
                )
            )
        )

        assert len(matches) == 1
        assert (
            matches[0].candidate.chunk_id
            == customer_chunk_id
        )

    def test_filters_by_document_metadata_containment(
        self,
        retrieval_session,
    ) -> None:
        _, _, india_chunk_id = retrieval_session.seed(
            vector=(0.8, 0.6, 0.0),
            title="India Refund Policy",
            document_metadata={
                "region": "india",
                "product": "payments",
                "language": "en",
            },
        )

        retrieval_session.seed(
            vector=(1.0, 0.0, 0.0),
            title="US Refund Policy",
            document_metadata={
                "region": "us",
                "product": "payments",
                "language": "en",
            },
        )

        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request(
                filters=RetrievalFilters(
                    metadata={
                        "region": "india",
                        "product": "payments",
                    }
                )
            )
        )

        assert len(matches) == 1
        assert (
            matches[0].candidate.chunk_id
            == india_chunk_id
        )


# ===========================================================================
# Empty-result semantics
# ===========================================================================


class TestEmptyVectorRetrieval:
    def test_returns_empty_tuple_when_no_compatible_embeddings_exist(
        self,
        retrieval_session,
    ) -> None:
        retrieval_session.session.commit()

        matches = repository_for(
            retrieval_session.session
        ).search(
            build_request()
        )

        assert matches == ()