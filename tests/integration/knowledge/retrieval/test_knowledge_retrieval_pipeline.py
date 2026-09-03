from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from packages.application.composition.knowledge_retrieval_factory import (
    create_knowledge_retrieval_components,
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
from packages.knowledge.embeddings.models import (
    DocumentEmbedding,
    EmbeddingBatch,
    EmbeddingInputDescriptor,
    EmbeddingProviderDescriptor,
    EmbeddingVector,
)
from packages.knowledge.embeddings.provider.base import (
    EmbeddingProvider,
)
from packages.knowledge.retrieval.context.models import (
    GroundingContextBudget,
)
from packages.knowledge.retrieval.models import (
    RetrievalFilters,
    RetrievalMethod,
    RetrievalQuery,
)
from packages.knowledge.retrieval.profiles import (
    RetrievalProfile,
)
from packages.knowledge.retrieval.query.models import (
    PreparedRetrievalQuery,
    RetrievalQueryContext,
)


pytestmark = pytest.mark.integration

UTC = timezone.utc


# ===========================================================================
# Fixed retrieval configuration
# ===========================================================================


TEST_PROVIDER_DESCRIPTOR = EmbeddingProviderDescriptor(
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


TEST_PROFILE = RetrievalProfile(
    profile_id="integration-hybrid",
    vector_enabled=True,
    lexical_enabled=True,
    reranking_enabled=False,
    vector_candidate_limit=20,
    lexical_candidate_limit=20,
    fused_candidate_limit=20,
    final_candidate_limit=8,
    rrf_k=60,
)


DEFAULT_CONTEXT_BUDGET = GroundingContextBudget(
    max_tokens=2_000,
    max_blocks=8,
)


# ===========================================================================
# Deterministic embedding provider
# ===========================================================================


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic integration-test embedding provider.

    No network calls are made.

    Query semantics:
        refund -> (1, 0, 0)
        order  -> (0, 1, 0)
        other  -> (0, 0, 1)

    Persisted embeddings are seeded explicitly by the tests, which allows
    vector ranking to remain completely deterministic.
    """

    @property
    def descriptor(self) -> EmbeddingProviderDescriptor:
        return TEST_PROVIDER_DESCRIPTOR

    def embed_query(self, text: str) -> EmbeddingVector:
        normalized = text.strip().lower()

        if "refund" in normalized:
            return EmbeddingVector.from_sequence(
                (1.0, 0.0, 0.0)
            )

        if "order" in normalized:
            return EmbeddingVector.from_sequence(
                (0.0, 1.0, 0.0)
            )

        return EmbeddingVector.from_sequence(
            (0.0, 0.0, 1.0)
        )

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> EmbeddingBatch:
        embeddings = tuple(
            DocumentEmbedding(
                input_index=index,
                vector=self.embed_query(text),
            )
            for index, text in enumerate(texts)
        )

        return EmbeddingBatch(
            embeddings=embeddings,
            provider=self.descriptor,
        )


# ===========================================================================
# Test-data helpers
# ===========================================================================


def utc_now() -> datetime:
    return datetime.now(UTC)


def seed_document(
    session: Session,
    *,
    title: str,
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
            description="Hybrid retrieval pipeline integration test.",
            content_type=content_type,
            visibility=visibility,
            status=status,
            metadata_={
                "integration_test": True,
                **(metadata or {}),
            },
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
                f"Hybrid retrieval integration version "
                f"{version_number}."
            ),
            content_hash=uuid4().hex + uuid4().hex,
            status=status,
            ingestion_status=ingestion_status,
            source_name=(
                f"hybrid-retrieval-v{version_number}.txt"
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
            metadata_={
                "integration_test": True,
                **(metadata or {}),
            },
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
    provider: EmbeddingProviderDescriptor = (
        TEST_PROVIDER_DESCRIPTOR
    ),
    input_descriptor: EmbeddingInputDescriptor = (
        TEST_INPUT_DESCRIPTOR
    ),
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
            input_strategy_id=(
                input_descriptor.strategy_id
            ),
            input_strategy_version=(
                input_descriptor.version
            ),
            input_config_fingerprint=(
                input_descriptor.config_fingerprint
            ),
            input_fingerprint=(
                uuid4().hex + uuid4().hex
            ),
        )
    )

    session.flush()

    return embedding_id


def seed_retrievable_chunk(
    session: Session,
    *,
    vector: Sequence[float],
    title: str,
    content: str,
    section_title: str | None = None,
    chunk_index: int = 0,
    content_type: str = "policy",
    visibility: str = "customer",
    document_status: str = "active",
    version_status: str = "published",
    ingestion_status: str = "completed",
    document_metadata: dict[str, object] | None = None,
    chunk_metadata: dict[str, object] | None = None,
    provider: EmbeddingProviderDescriptor = (
        TEST_PROVIDER_DESCRIPTOR
    ),
    input_descriptor: EmbeddingInputDescriptor = (
        TEST_INPUT_DESCRIPTOR
    ),
) -> tuple[UUID, UUID, UUID]:
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

def make_query_context(
    *,
    customer_message: str,
    intent_key: str | None = None,
    filters: RetrievalFilters | None = None,
    entities: dict[str, str] | None = None,
) -> RetrievalQueryContext:
    return RetrievalQueryContext(
        customer_message=customer_message,
        intent_key=intent_key,
        entities=entities or {},
        filters=filters or RetrievalFilters(),
    )


def prepare_query(
    components,
    *,
    customer_message: str,
    intent_key: str | None = None,
    filters: RetrievalFilters | None = None,
    entities: dict[str, str] | None = None,
) -> PreparedRetrievalQuery:
    context = make_query_context(
        customer_message=customer_message,
        intent_key=intent_key,
        filters=filters,
        entities=entities,
    )

    return components.query_preparation_service.prepare(
        context=context,
    )


# ===========================================================================
# Pipeline fixture
# ===========================================================================


@pytest.fixture()
def pipeline_session(
    test_session_factory: sessionmaker[Session],
    clean_database,
):
    """
    One real PostgreSQL session for the complete retrieval pipeline.

    clean_database owns test isolation. This fixture owns only the Session
    lifecycle.
    """

    session = test_session_factory()

    try:
        yield session

    finally:
        session.rollback()
        session.close()


def build_pipeline(
    session: Session,
    *,
    profile: RetrievalProfile = TEST_PROFILE,
    budget: GroundingContextBudget = (
        DEFAULT_CONTEXT_BUDGET
    ),
):
    return create_knowledge_retrieval_components(
        session=session,
        embedding_provider=DeterministicEmbeddingProvider(),
        embedding_input_descriptor=TEST_INPUT_DESCRIPTOR,
        profile=profile,
        default_context_budget=budget,
    )


# ===========================================================================
# Complete hybrid pipeline
# ===========================================================================


class TestHybridRetrievalPipeline:
    def test_retrieves_and_fuses_vector_and_lexical_evidence(
        self,
        pipeline_session: Session,
    ) -> None:
        _, _, refund_chunk_id = seed_retrievable_chunk(
            pipeline_session,
            vector=(1.0, 0.0, 0.0),
            title="Customer Refund Policy",
            section_title="Refund Processing Time",
            content=(
                "Refund requests are processed within "
                "five business days."
            ),
        )

        seed_retrievable_chunk(
            pipeline_session,
            vector=(0.0, 1.0, 0.0),
            title="Order Tracking Guide",
            section_title="Tracking Orders",
            content=(
                "Customers can track their order from "
                "the order history page."
            ),
        )

        pipeline_session.commit()

        components = build_pipeline(
            pipeline_session
        )

        # result = components.retrieve_knowledge.retrieve(
        #     query=RetrievalQuery(
        #         # text="How long does my refund take?"
        #         text="refund"
        #     )
        # )
        
        prepared_query = prepare_query(
            components,
            customer_message="refund",
            intent_key="refund_request",
        )

        result = components.retrieve_knowledge.retrieve(
            prepared_query=prepared_query,
        )
        
        assert prepared_query.original_query == "refund"
        assert prepared_query.semantic_query == "refund"
        assert prepared_query.lexical_queries

        assert not result.is_empty
        assert result.count >= 1

        top_candidate = result.candidates[0]

        assert top_candidate.chunk_id == refund_chunk_id

        # The refund chunk should have been independently discovered
        # by semantic and lexical retrieval and then merged by RRF.
        assert RetrievalMethod.VECTOR in top_candidate.methods
        assert RetrievalMethod.LEXICAL in top_candidate.methods

        assert (
            top_candidate.scores.vector_distance
            == pytest.approx(0.0, abs=1e-6)
        )
        assert (
            top_candidate.scores.vector_similarity
            == pytest.approx(1.0, abs=1e-6)
        )

        assert top_candidate.scores.lexical_score is not None
        assert top_candidate.scores.lexical_score > 0

        assert top_candidate.scores.fusion_score is not None
        assert top_candidate.scores.fusion_score > 0


# ===========================================================================
# Grounding context
# ===========================================================================


class TestGroundingContextPipeline:
    def test_builds_grounding_context_from_real_retrieval_results(
        self,
        pipeline_session: Session,
    ) -> None:
        (
            document_id,
            version_id,
            chunk_id,
        ) = seed_retrievable_chunk(
            pipeline_session,
            vector=(1.0, 0.0, 0.0),
            title="Refund Policy",
            section_title="Refund Eligibility",
            content=(
                "Customers may request a refund within "
                "thirty days of purchase."
            ),
            chunk_metadata={
                "section_path": [
                    "Refunds",
                    "Eligibility",
                ],
            },
        )

        pipeline_session.commit()

        components = build_pipeline(
            pipeline_session
        )

        # query = RetrievalQuery(
        #     text="What is the refund eligibility?"
        # )

        # context = (
        #     components
        #     .build_grounding_context
        #     .build(query=query)
        # )
        
        prepared_query = prepare_query(
            components,
            customer_message="What is the refund eligibility?",
            intent_key="refund_request",
        )

        context = (
            components
            .build_grounding_context
            .build(
                prepared_query=prepared_query,
            )
        )
        
        expected_query = RetrievalQuery(
            text=prepared_query.original_query,
            filters=prepared_query.filters,
        )

        assert not context.is_empty
        assert context.block_count == 1
        assert context.query == expected_query

        block = context.blocks[0]

        assert block.chunk_id == chunk_id
        assert block.version_id == version_id
        assert block.document_id == document_id

        assert block.document_title == "Refund Policy"
        assert block.section_title == "Refund Eligibility"

        assert (
            block.content
            == (
                "Customers may request a refund within "
                "thirty days of purchase."
            )
        )

        assert block.metadata["section_path"] == [
            "Refunds",
            "Eligibility",
        ]

        assert block.retrieval_score is not None


# ===========================================================================
# Cross-branch lifecycle safety
# ===========================================================================


class TestPipelineLifecycleSafety:
    def test_unpublished_knowledge_cannot_leak_through_either_branch(
        self,
        pipeline_session: Session,
    ) -> None:
        _, _, published_chunk_id = seed_retrievable_chunk(
            pipeline_session,
            vector=(0.8, 0.2, 0.0),
            title="Published Refund Policy",
            section_title="Refund Rules",
            content=(
                "Published refund guidance for customers."
            ),
        )

        _, _, unpublished_chunk_id = seed_retrievable_chunk(
            pipeline_session,
            vector=(1.0, 0.0, 0.0),
            title="Secret Draft Refund Policy",
            section_title="Refund Rules",
            content=(
                "Refund immediately with no validation."
            ),
            version_status="ready",
            ingestion_status="completed",
        )

        pipeline_session.commit()

        # result = (
        #     build_pipeline(pipeline_session)
        #     .retrieve_knowledge
        #     .retrieve(
        #         query=RetrievalQuery(
        #             text="refund policy"
        #         )
        #     )
        # )
        
        components = build_pipeline(
            pipeline_session,
        )

        prepared_query = prepare_query(
            components,
            customer_message="refund policy",
            intent_key="refund_request",
        )

        result = components.retrieve_knowledge.retrieve(
            prepared_query=prepared_query,
        )

        returned_ids = {
            candidate.chunk_id
            for candidate in result.candidates
        }

        assert published_chunk_id in returned_ids
        assert unpublished_chunk_id not in returned_ids
        
        
    def test_semantic_retrieval_recovers_natural_language_query(
        self,
        pipeline_session: Session,
    ) -> None:
        _, _, refund_chunk_id = seed_retrievable_chunk(
            pipeline_session,
            vector=(1.0, 0.0, 0.0),
            title="Customer Refund Policy",
            section_title="Refund Processing Time",
            content=(
                "Refund requests are processed within "
                "five business days."
            ),
        )

        pipeline_session.commit()

        # result = (
        #     build_pipeline(pipeline_session)
        #     .retrieve_knowledge
        #     .retrieve(
        #         query=RetrievalQuery(
        #             text="How long does my refund take?"
        #         )
        #     )
        # )
        
        components = build_pipeline(
            pipeline_session,
        )

        prepared_query = prepare_query(
            components,
            customer_message="How long does my refund take?",
            intent_key="refund_request",
        )

        result = components.retrieve_knowledge.retrieve(
            prepared_query=prepared_query,
        )

        assert not result.is_empty

        candidate = next(
            candidate
            for candidate in result.candidates
            if candidate.chunk_id == refund_chunk_id
        )
        
        assert (
            prepared_query.semantic_query
            == "How long does my refund take?"
        )

        assert prepared_query.lexical_queries

        assert RetrievalMethod.VECTOR in candidate.methods

        assert candidate.scores.vector_similarity == pytest.approx(
            1.0,
            abs=1e-6,
        )


# ===========================================================================
# Filters across complete pipeline
# ===========================================================================


class TestPipelineBusinessFilters:
    def test_filters_are_respected_by_vector_and_lexical_branches(
        self,
        pipeline_session: Session,
    ) -> None:
        _, _, india_chunk_id = seed_retrievable_chunk(
            pipeline_session,
            vector=(0.8, 0.2, 0.0),
            title="India Refund Policy",
            section_title="Refund Processing",
            content=(
                "Refund processing guidance for India."
            ),
            document_metadata={
                "region": "india",
                "product": "payments",
            },
        )

        _, _, us_chunk_id = seed_retrievable_chunk(
            pipeline_session,
            vector=(1.0, 0.0, 0.0),
            title="US Refund Policy",
            section_title="Refund Processing",
            content=(
                "Refund processing guidance for the "
                "United States."
            ),
            document_metadata={
                "region": "us",
                "product": "payments",
            },
        )

        pipeline_session.commit()

        # query = RetrievalQuery(
        #     text="refund processing",
        #     filters=RetrievalFilters(
        #         visibilities=("customer",),
        #         content_types=("policy",),
        #         metadata={
        #             "region": "india",
        #             "product": "payments",
        #         },
        #     ),
        # )

        # result = (
        #     build_pipeline(pipeline_session)
        #     .retrieve_knowledge
        #     .retrieve(query=query)
        # )
        
        components = build_pipeline(
            pipeline_session,
        )
        
        filters = RetrievalFilters(
            visibilities=("customer",),
            content_types=("policy",),
            metadata={
                "region": "india",
                "product": "payments",
            },
        )

        prepared_query = prepare_query(
            components,
            customer_message="refund processing",
            intent_key="refund_request",
            filters=filters,
        )

        result = components.retrieve_knowledge.retrieve(
            prepared_query=prepared_query,
        )

        returned_ids = [
            candidate.chunk_id
            for candidate in result.candidates
        ]
        
        assert prepared_query.filters == filters

        assert returned_ids == [india_chunk_id]
        assert us_chunk_id not in returned_ids

        candidate = result.candidates[0]

        assert RetrievalMethod.VECTOR in candidate.methods
        assert RetrievalMethod.LEXICAL in candidate.methods


# ===========================================================================
# Embedding provenance across complete pipeline
# ===========================================================================


class TestPipelineEmbeddingIsolation:
    def test_wrong_embedding_profile_cannot_enter_vector_branch(
        self,
        pipeline_session: Session,
    ) -> None:
        wrong_provider = EmbeddingProviderDescriptor(
            provider="different-provider",
            model=TEST_PROVIDER_DESCRIPTOR.model,
            revision=TEST_PROVIDER_DESCRIPTOR.revision,
            dimensions=3,
        )

        _, _, chunk_id = seed_retrievable_chunk(
            pipeline_session,
            vector=(1.0, 0.0, 0.0),
            title="Refund Policy",
            section_title="Refund Information",
            content=(
                "Refund information is available here."
            ),
            provider=wrong_provider,
        )

        pipeline_session.commit()

        # result = (
        #     build_pipeline(pipeline_session)
        #     .retrieve_knowledge
        #     .retrieve(
        #         query=RetrievalQuery(
        #             text="refund information"
        #         )
        #     )
        # )
        
        components = build_pipeline(
            pipeline_session,
        )
        
        prepared_query = prepare_query(
            components,
            customer_message="refund information",
            intent_key="refund_request",
        )

        result = components.retrieve_knowledge.retrieve(
            prepared_query=prepared_query,
        )

        candidate = next(
            candidate
            for candidate in result.candidates
            if candidate.chunk_id == chunk_id
        )

        # Lexical retrieval may legitimately find the chunk.
        assert RetrievalMethod.LEXICAL in candidate.methods

        # But vector retrieval MUST NOT use an incompatible
        # persisted embedding artifact.
        assert RetrievalMethod.VECTOR not in candidate.methods

        assert candidate.scores.vector_distance is None
        assert candidate.scores.vector_similarity is None
        assert candidate.scores.lexical_score is not None


# ===========================================================================
# Empty retrieval
# ===========================================================================


class TestEmptyPipelineResult:
    def test_empty_database_produces_empty_grounding_context(
        self,
        pipeline_session: Session,
    ) -> None:
        components = build_pipeline(
            pipeline_session
        )

        prepared_query = prepare_query(
            components,
            customer_message="refund information",
            intent_key="refund_request",
        )

        context = (
            components
            .build_grounding_context
            .build(
                prepared_query=prepared_query,
            )
        )

        expected_query = RetrievalQuery(
            text=prepared_query.original_query,
            filters=prepared_query.filters,
        )

        assert context.is_empty
        assert context.block_count == 0
        assert context.blocks == ()
        assert context.query == expected_query
        assert context.estimated_token_count == 0
        assert context.truncated is False


# ===========================================================================
# Context budgeting
# ===========================================================================


class TestPipelineContextBudget:
    def test_context_budget_limits_real_retrieved_candidates(
        self,
        pipeline_session: Session,
    ) -> None:
        seed_retrievable_chunk(
            pipeline_session,
            vector=(1.0, 0.0, 0.0),
            title="Refund Policy A",
            section_title="Refund Timing",
            content=(
                "Refund requests are normally processed "
                "within five business days."
            ),
        )

        seed_retrievable_chunk(
            pipeline_session,
            vector=(0.9, 0.1, 0.0),
            title="Refund Policy B",
            section_title="Refund Eligibility",
            content=(
                "Refund eligibility depends on the "
                "purchase date and transaction state."
            ),
        )

        pipeline_session.commit()

        components = build_pipeline(
            pipeline_session
        )

        prepared_query = prepare_query(
            components,
            customer_message="refund policy",
            intent_key="refund_request",
        )

        context = (
            components
            .build_grounding_context
            .build(
                prepared_query=prepared_query,
                budget=GroundingContextBudget(
                    max_tokens=2_000,
                    max_blocks=1,
                ),
            )
        )

        assert context.block_count == 1
        assert len(context.blocks) == 1
        assert context.truncated is True
        
    def test_grounding_context_preserves_original_customer_query(
        self,
        pipeline_session: Session,
    ) -> None:
        seed_retrievable_chunk(
            pipeline_session,
            vector=(1.0, 0.0, 0.0),
            title="Refund Policy",
            section_title="Refund Timing",
            content=(
                "Refund requests are processed within "
                "five business days."
            ),
        )

        pipeline_session.commit()

        components = build_pipeline(
            pipeline_session,
        )

        prepared_query = prepare_query(
            components,
            customer_message="How long does my refund take?",
            intent_key="refund_request",
            entities={
                "issue_type": "refund delay",
            },
        )

        # Retrieval representations may differ.
        assert (
            prepared_query.semantic_query
            == "How long does my refund take?"
        )
        assert prepared_query.lexical_queries

        context = (
            components
            .build_grounding_context
            .build(
                prepared_query=prepared_query,
            )
        )

        expected_query = RetrievalQuery(
            text="How long does my refund take?",
            filters=prepared_query.filters,
        )

        # But public/canonical provenance must preserve
        # the original customer query.
        assert context.query == expected_query
        assert (
            context.query.text
            == prepared_query.original_query
        )