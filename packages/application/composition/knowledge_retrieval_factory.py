from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy.orm import Session, sessionmaker

from packages.database.repositories.knowledge.lexical_retrieval_repository import SQLAlchemyLexicalRetrievalRepository
from packages.database.repositories.knowledge.vector_retrieval_repository import SQLAlchemyVectorRetrievalRepository
from packages.knowledge.embeddings.models import EmbeddingInputDescriptor
from packages.knowledge.embeddings.provider.base import EmbeddingProvider
from packages.knowledge.retrieval.application.build_grounding_context import BuildGroundingContext
from packages.knowledge.retrieval.application.retrieve_knowledge import RetrieveKnowledge
from packages.knowledge.retrieval.context.builder import CharacterTokenEstimator, GroundingContextBuilder, TokenEstimator
from packages.knowledge.retrieval.context.models import GroundingContextBudget
from packages.knowledge.retrieval.fusion.reciprocal_rank import ReciprocalRankFusion
from packages.knowledge.retrieval.lexical.service import LexicalRetrievalService
from packages.knowledge.retrieval.profiles import RetrievalProfile
from packages.knowledge.retrieval.reranking.base import Reranker
from packages.knowledge.retrieval.reranking.passthrough import PassthroughReranker
from packages.knowledge.retrieval.reranking.service import RerankingService
from packages.knowledge.retrieval.vector.service import VectorRetrievalService


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalComponents:
    """
    Fully composed knowledge-retrieval application boundary.

    Exposing the individual components is useful for:
      - application startup health checks;
      - integration tests;
      - diagnostics;
      - future observability wiring.

    Normal callers should generally use ``build_grounding_context``.
    """
    retrieve_knowledge: RetrieveKnowledge
    build_grounding_context: BuildGroundingContext
    vector_service: VectorRetrievalService | None
    lexical_service: LexicalRetrievalService | None
    reranking_service: RerankingService | None
    context_builder: GroundingContextBuilder

def create_knowledge_retrieval_components(*, session: Session, embedding_provider: EmbeddingProvider, 
                                          embedding_input_descriptor: EmbeddingInputDescriptor, profile: RetrievalProfile,
                                          default_context_budget: GroundingContextBudget, reranker: Reranker | None = None, token_estimator: TokenEstimator | None = None,
) -> KnowledgeRetrievalComponents:
    """
    Compose the complete knowledge retrieval and grounding pipeline.

    Pipeline:
        1. Vector retrieval
        - EmbeddingProvider
        - SQLAlchemyVectorRetrievalRepository
        - VectorRetrievalService

        2. Lexical retrieval
        - SQLAlchemyLexicalRetrievalRepository
        - LexicalRetrievalService

        3. Retrieval orchestration
        - ReciprocalRankFusion
        - optional RerankingService
        - RetrieveKnowledge

        4. Grounding context construction
        - TokenEstimator
        - GroundingContextBuilder
        - BuildGroundingContext

    The vector and lexical retrieval branches execute independently and produce ranked candidates.
    RetrieveKnowledge combines those rankings using the configured fusion strategy and optionally applies reranking.

    The resulting candidates are converted into bounded grounding context by GroundingContextBuilder.

    This function is the composition root for concrete knowledge-retrieval infrastructure.
    Application and domain code must not instantiate PostgreSQL repositories, fusion implementations, token estimators, or rerankers directly.
    """
    _validate_inputs(
        session=session, embedding_provider=embedding_provider, embedding_input_descriptor=embedding_input_descriptor,
        profile=profile, default_context_budget=default_context_budget, reranker=reranker, token_estimator=token_estimator
    )

    vector_service = _build_vector_service(
        session=session, embedding_provider=embedding_provider, embedding_input_descriptor=embedding_input_descriptor, profile=profile
    )

    lexical_service = _build_lexical_service(session=session, profile=profile)
    reranking_service = _build_reranking_service(profile=profile, reranker=reranker)
    fusion_strategy = ReciprocalRankFusion(k=profile.rrf_k)

    retrieve_knowledge = RetrieveKnowledge(
        profile=profile, fusion_strategy=fusion_strategy, vector_service=vector_service,
        lexical_service=lexical_service, reranking_service=reranking_service,
    )

    effective_token_estimator = token_estimator if token_estimator is not None else CharacterTokenEstimator()
    context_builder = GroundingContextBuilder(token_estimator=effective_token_estimator)
    build_grounding_context = BuildGroundingContext(retrieve_knowledge=retrieve_knowledge, context_builder=context_builder, default_budget=default_context_budget)

    return KnowledgeRetrievalComponents(
        retrieve_knowledge=retrieve_knowledge,
        build_grounding_context=build_grounding_context,
        vector_service=vector_service,
        lexical_service=lexical_service,
        reranking_service=reranking_service,
        context_builder=context_builder,
    )

def _build_vector_service(*, session: Session, embedding_provider: EmbeddingProvider, 
                          embedding_input_descriptor: EmbeddingInputDescriptor, profile: RetrievalProfile
) -> VectorRetrievalService | None:
    if not profile.vector_enabled:
        return None

    repository = SQLAlchemyVectorRetrievalRepository(session=session)

    return VectorRetrievalService(
        provider=embedding_provider, repository=repository, input_descriptor=embedding_input_descriptor
    )

def _build_lexical_service(*, session: Session, profile: RetrievalProfile) -> LexicalRetrievalService | None:
    if not profile.lexical_enabled:
        return None

    repository = SQLAlchemyLexicalRetrievalRepository(session=session)

    return LexicalRetrievalService(repository=repository)

def _build_reranking_service(*, profile: RetrievalProfile, reranker: Reranker | None) -> RerankingService | None:
    if not profile.reranking_enabled:
        return None

    effective_reranker = reranker if reranker is not None else PassthroughReranker()

    return RerankingService(reranker=effective_reranker)

def _validate_inputs(*, session: Session, embedding_provider: EmbeddingProvider, embedding_input_descriptor: EmbeddingInputDescriptor, 
                     profile: RetrievalProfile, default_context_budget: GroundingContextBudget, reranker: Reranker | None, token_estimator: TokenEstimator | None
) -> None:
    if not isinstance(session, Session):
        raise TypeError("session must be a SQLAlchemy Session instance.")

    if not isinstance(embedding_provider, EmbeddingProvider):
        raise TypeError("embedding_provider must be an EmbeddingProvider instance.")

    if not isinstance(embedding_input_descriptor, EmbeddingInputDescriptor):
        raise TypeError("embedding_input_descriptor must be an EmbeddingInputDescriptor instance.")

    if not isinstance(profile, RetrievalProfile):
        raise TypeError("profile must be a RetrievalProfile instance.")

    if not isinstance(default_context_budget, GroundingContextBudget):
        raise TypeError("default_context_budget must be a GroundingContextBudget instance.")

    if reranker is not None and not isinstance(reranker, Reranker):
        raise TypeError("reranker must be a Reranker instance or None.")

    if token_estimator is not None and not isinstance(token_estimator, TokenEstimator):
        raise TypeError("token_estimator must be a TokenEstimator instance or None.")