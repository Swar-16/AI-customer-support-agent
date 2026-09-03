from __future__ import annotations

from unittest.mock import create_autospec

import pytest
from sqlalchemy.orm import Session

from packages.application.composition.knowledge_retrieval_factory import (
    KnowledgeRetrievalComponents,
    create_knowledge_retrieval_components,
)
from packages.knowledge.embeddings.models import (
    EmbeddingInputDescriptor,
    EmbeddingProviderDescriptor,
    EmbeddingVector,
)
from packages.knowledge.embeddings.provider.base import (
    EmbeddingProvider,
)
from packages.knowledge.retrieval.context.builder import (
    CharacterTokenEstimator,
    TokenEstimator,
)
from packages.knowledge.retrieval.context.models import (
    GroundingContextBudget,
)
from packages.knowledge.retrieval.fusion.reciprocal_rank import (
    ReciprocalRankFusion,
)
from packages.knowledge.retrieval.profiles import (
    RetrievalProfile,
)
from packages.knowledge.retrieval.reranking.base import (
    Reranker,
)
from packages.knowledge.retrieval.reranking.models import (
    RerankerDescriptor,
    RerankingRequest,
    RerankingResponse,
)
from packages.knowledge.retrieval.reranking.passthrough import (
    PassthroughReranker,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeEmbeddingProvider(EmbeddingProvider):
    @property
    def descriptor(self) -> EmbeddingProviderDescriptor:
        return EmbeddingProviderDescriptor(
            provider="fake",
            model="fake-model",
            revision=None,
            dimensions=3,
        )

    def embed_documents(self, texts):
        raise NotImplementedError

    def embed_query(self, text: str) -> EmbeddingVector:
        return EmbeddingVector(
            values=(0.1, 0.2, 0.3),
        )


class FakeTokenEstimator(TokenEstimator):
    @property
    def estimator_id(self) -> str:
        return "fake-estimator"

    def estimate(self, text: str) -> int:
        return max(1, len(text) // 4)


class FakeReranker(Reranker):
    @property
    def descriptor(self) -> RerankerDescriptor:
        return RerankerDescriptor(
            reranker_id="fake-reranker",
            provider="fake",
            model="fake-model",
            revision=None,
        )

    def rerank(
        self,
        request: RerankingRequest,
    ) -> RerankingResponse:
        return RerankingResponse(
            results=(),
            descriptor=self.descriptor,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_session():
    return create_autospec(
        Session,
        instance=True,
        spec_set=True,
    )


def make_embedding_provider() -> EmbeddingProvider:
    return FakeEmbeddingProvider()


def make_input_descriptor() -> EmbeddingInputDescriptor:
    return EmbeddingInputDescriptor(
        strategy_id="contextual_chunk",
        version="1",
        config_fingerprint="test-fingerprint",
    )


def make_budget() -> GroundingContextBudget:
    return GroundingContextBudget(
        max_tokens=2_000,
        max_blocks=8,
    )


def make_profile(
    *,
    vector_enabled: bool = True,
    lexical_enabled: bool = True,
    reranking_enabled: bool = False,
) -> RetrievalProfile:
    return RetrievalProfile(
        profile_id="test-profile",
        vector_enabled=vector_enabled,
        lexical_enabled=lexical_enabled,
        reranking_enabled=reranking_enabled,
        vector_candidate_limit=20,
        lexical_candidate_limit=20,
        fused_candidate_limit=20,
        final_candidate_limit=8,
        rrf_k=60,
    )


# ---------------------------------------------------------------------------
# Basic composition
# ---------------------------------------------------------------------------


class TestKnowledgeRetrievalFactoryComposition:
    def test_builds_complete_hybrid_pipeline(self):
        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(),
            default_context_budget=make_budget(),
        )

        assert isinstance(
            components,
            KnowledgeRetrievalComponents,
        )

        assert components.vector_service is not None
        assert components.lexical_service is not None
        assert components.reranking_service is None

        assert (
            components.retrieve_knowledge.profile.profile_id
            == "test-profile"
        )

        assert isinstance(
            components.retrieve_knowledge.fusion_strategy,
            ReciprocalRankFusion,
        )

        assert (
            components.build_grounding_context.retrieve_knowledge
            is components.retrieve_knowledge
        )

        assert (
            components.build_grounding_context.context_builder
            is components.context_builder
        )

    def test_vector_only_profile_builds_only_vector_branch(self):
        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(
                vector_enabled=True,
                lexical_enabled=False,
            ),
            default_context_budget=make_budget(),
        )

        assert components.vector_service is not None
        assert components.lexical_service is None

    def test_lexical_only_profile_builds_only_lexical_branch(self):
        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(
                vector_enabled=False,
                lexical_enabled=True,
            ),
            default_context_budget=make_budget(),
        )

        assert components.vector_service is None
        assert components.lexical_service is not None


# ---------------------------------------------------------------------------
# Reranking composition
# ---------------------------------------------------------------------------


class TestKnowledgeRetrievalFactoryReranking:
    def test_reranking_disabled_does_not_build_reranking_service(self):
        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(
                reranking_enabled=False,
            ),
            default_context_budget=make_budget(),
            reranker=FakeReranker(),
        )

        assert components.reranking_service is None

    def test_reranking_enabled_defaults_to_passthrough_reranker(self):
        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(
                reranking_enabled=True,
            ),
            default_context_budget=make_budget(),
        )

        assert components.reranking_service is not None
        assert isinstance(
            components.reranking_service.reranker,
            PassthroughReranker,
        )

    def test_reranking_enabled_uses_supplied_reranker(self):
        reranker = FakeReranker()

        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(
                reranking_enabled=True,
            ),
            default_context_budget=make_budget(),
            reranker=reranker,
        )

        assert components.reranking_service is not None
        assert (
            components.reranking_service.reranker
            is reranker
        )


# ---------------------------------------------------------------------------
# Token estimator composition
# ---------------------------------------------------------------------------


class TestKnowledgeRetrievalFactoryTokenEstimator:
    def test_defaults_to_character_token_estimator(self):
        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(),
            default_context_budget=make_budget(),
        )

        assert isinstance(
            components.context_builder.token_estimator,
            CharacterTokenEstimator,
        )

    def test_uses_supplied_token_estimator(self):
        estimator = FakeTokenEstimator()

        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(),
            default_context_budget=make_budget(),
            token_estimator=estimator,
        )

        assert (
            components.context_builder.token_estimator
            is estimator
        )


# ---------------------------------------------------------------------------
# Shared dependency wiring
# ---------------------------------------------------------------------------


class TestKnowledgeRetrievalFactoryWiring:
    def test_build_grounding_context_uses_requested_default_budget(self):
        budget = GroundingContextBudget(
            max_tokens=1_234,
            max_blocks=5,
        )

        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(),
            default_context_budget=budget,
        )

        assert (
            components.build_grounding_context.default_budget
            is budget
        )

    def test_retrieve_knowledge_uses_same_vector_service_exposed_by_components(
        self,
    ):
        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(),
            default_context_budget=make_budget(),
        )

        assert (
            components.retrieve_knowledge._vector_service
            is components.vector_service
        )

    def test_retrieve_knowledge_uses_same_lexical_service_exposed_by_components(
        self,
    ):
        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(),
            default_context_budget=make_budget(),
        )

        assert (
            components.retrieve_knowledge._lexical_service
            is components.lexical_service
        )

    def test_retrieve_knowledge_uses_same_reranking_service_exposed_by_components(
        self,
    ):
        components = create_knowledge_retrieval_components(
            session=make_session(),
            embedding_provider=make_embedding_provider(),
            embedding_input_descriptor=make_input_descriptor(),
            profile=make_profile(
                reranking_enabled=True,
            ),
            default_context_budget=make_budget(),
        )

        assert (
            components.retrieve_knowledge._reranking_service
            is components.reranking_service
        )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestKnowledgeRetrievalFactoryValidation:
    @pytest.mark.parametrize(
        "session",
        [
            None,
            object(),
            "session",
            123,
        ],
    )
    def test_rejects_invalid_session(
        self,
        session,
    ):
        with pytest.raises(
            TypeError,
            match="session must be a SQLAlchemy Session instance",
        ):
            create_knowledge_retrieval_components(
                session=session,  # type: ignore[arg-type]
                embedding_provider=make_embedding_provider(),
                embedding_input_descriptor=make_input_descriptor(),
                profile=make_profile(),
                default_context_budget=make_budget(),
            )

    @pytest.mark.parametrize(
        "embedding_provider",
        [
            None,
            object(),
            "provider",
            123,
        ],
    )
    def test_rejects_invalid_embedding_provider(
        self,
        embedding_provider,
    ):
        with pytest.raises(
            TypeError,
            match=(
                "embedding_provider must be an "
                "EmbeddingProvider instance"
            ),
        ):
            create_knowledge_retrieval_components(
                session=make_session(),
                embedding_provider=embedding_provider,  # type: ignore[arg-type]
                embedding_input_descriptor=make_input_descriptor(),
                profile=make_profile(),
                default_context_budget=make_budget(),
            )

    @pytest.mark.parametrize(
        "descriptor",
        [
            None,
            object(),
            "descriptor",
            123,
        ],
    )
    def test_rejects_invalid_embedding_input_descriptor(
        self,
        descriptor,
    ):
        with pytest.raises(
            TypeError,
            match=(
                "embedding_input_descriptor must be an "
                "EmbeddingInputDescriptor instance"
            ),
        ):
            create_knowledge_retrieval_components(
                session=make_session(),
                embedding_provider=make_embedding_provider(),
                embedding_input_descriptor=descriptor,  # type: ignore[arg-type]
                profile=make_profile(),
                default_context_budget=make_budget(),
            )

    @pytest.mark.parametrize(
        "profile",
        [
            None,
            object(),
            "profile",
            123,
        ],
    )
    def test_rejects_invalid_profile(
        self,
        profile,
    ):
        with pytest.raises(
            TypeError,
            match="profile must be a RetrievalProfile instance",
        ):
            create_knowledge_retrieval_components(
                session=make_session(),
                embedding_provider=make_embedding_provider(),
                embedding_input_descriptor=make_input_descriptor(),
                profile=profile,  # type: ignore[arg-type]
                default_context_budget=make_budget(),
            )

    @pytest.mark.parametrize(
        "budget",
        [
            None,
            object(),
            "budget",
            123,
        ],
    )
    def test_rejects_invalid_default_context_budget(
        self,
        budget,
    ):
        with pytest.raises(
            TypeError,
            match=(
                "default_context_budget must be a "
                "GroundingContextBudget instance"
            ),
        ):
            create_knowledge_retrieval_components(
                session=make_session(),
                embedding_provider=make_embedding_provider(),
                embedding_input_descriptor=make_input_descriptor(),
                profile=make_profile(),
                default_context_budget=budget,  # type: ignore[arg-type]
            )

    def test_rejects_invalid_reranker(self):
        with pytest.raises(
            TypeError,
            match="reranker must be a Reranker instance or None",
        ):
            create_knowledge_retrieval_components(
                session=make_session(),
                embedding_provider=make_embedding_provider(),
                embedding_input_descriptor=make_input_descriptor(),
                profile=make_profile(),
                default_context_budget=make_budget(),
                reranker=object(),  # type: ignore[arg-type]
            )

    def test_rejects_invalid_token_estimator(self):
        with pytest.raises(
            TypeError,
            match=(
                "token_estimator must be a "
                "TokenEstimator instance or None"
            ),
        ):
            create_knowledge_retrieval_components(
                session=make_session(),
                embedding_provider=make_embedding_provider(),
                embedding_input_descriptor=make_input_descriptor(),
                profile=make_profile(),
                default_context_budget=make_budget(),
                token_estimator=object(),  # type: ignore[arg-type]
            )