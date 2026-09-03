from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy.orm import Session

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
from packages.knowledge.retrieval.query.builder import DeterministicRetrievalQueryBuilder
from packages.knowledge.retrieval.query.service import RetrievalQueryPreparationService
from packages.knowledge.retrieval.reranking.base import Reranker
from packages.knowledge.retrieval.reranking.passthrough import PassthroughReranker
from packages.knowledge.retrieval.reranking.service import RerankingService
from packages.knowledge.retrieval.vector.service import VectorRetrievalService

@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalComponents:
    """
    Fully composed knowledge-retrieval application boundary.

    Normal application callers generally use:

        query_preparation_service
            Converts an already-understood customer request into retrieval-specific query representations.

        build_grounding_context
            Executes retrieval and constructs bounded grounding context.

    Individual components remain exposed for health checks, integration tests, diagnostics, and observability wiring.
    """
    query_preparation_service: RetrievalQueryPreparationService
    retrieve_knowledge: RetrieveKnowledge
    build_grounding_context: BuildGroundingContext
    vector_service: VectorRetrievalService | None
    lexical_service: LexicalRetrievalService | None
    reranking_service: RerankingService | None
    context_builder: GroundingContextBuilder

def create_knowledge_retrieval_components(*, session: Session, profile: RetrievalProfile, default_context_budget: GroundingContextBudget,
                                          embedding_provider: EmbeddingProvider | None = None, embedding_input_descriptor: EmbeddingInputDescriptor | None = None,
                                          reranker: Reranker | None = None, token_estimator: TokenEstimator | None = None
) -> KnowledgeRetrievalComponents:
    """
    Compose the complete knowledge retrieval and grounding pipeline.

    Pipeline:

        RetrievalQueryContext
                |
                v
        query preparation
                |
                v
        PreparedRetrievalQuery
                |
                +--> semantic query --> vector retrieval --+
                |                                          |
                +--> lexical query  --> lexical retrieval -+
                                                           |
                                                           v
                                                        fusion
                                                           |
                                                           v
                                                       reranking
                                                           |
                                                           v
                                                grounding context

    Vector infrastructure is required only when vector retrieval is
    enabled by the configured RetrievalProfile.

    Lexical-only profiles therefore do not require an embedding
    provider or embedding-input descriptor.

    This function is the composition root for concrete
    knowledge-retrieval infrastructure.
    """
    _validate_inputs(
        session=session,
        embedding_provider=embedding_provider,
        embedding_input_descriptor=embedding_input_descriptor,
        profile=profile,
        default_context_budget=default_context_budget,
        reranker=reranker,
        token_estimator=token_estimator,
    )

    # Query preparation
    query_builder = DeterministicRetrievalQueryBuilder()
    query_preparation_service = (RetrievalQueryPreparationService(builder=query_builder))

    # Retrieval branches
    vector_service = _build_vector_service(
        session=session,
        embedding_provider=embedding_provider,
        embedding_input_descriptor=embedding_input_descriptor,
        profile=profile,
    )

    lexical_service = _build_lexical_service(session=session, profile=profile)

    # Fusion / reranking
    reranking_service = _build_reranking_service(profile=profile, reranker=reranker)
    fusion_strategy = ReciprocalRankFusion(k=profile.rrf_k)
    retrieve_knowledge = RetrieveKnowledge(
        profile=profile,
        fusion_strategy=fusion_strategy,
        vector_service=vector_service,
        lexical_service=lexical_service,
        reranking_service=reranking_service,
    )

    # Grounding context
    effective_token_estimator = token_estimator if token_estimator is not None else CharacterTokenEstimator()
    context_builder = GroundingContextBuilder(token_estimator=effective_token_estimator)
    build_grounding_context = BuildGroundingContext(
        retrieve_knowledge=retrieve_knowledge,
        context_builder=context_builder,
        default_budget=default_context_budget,
    )

    return KnowledgeRetrievalComponents(
        query_preparation_service=query_preparation_service,
        retrieve_knowledge=retrieve_knowledge,
        build_grounding_context=build_grounding_context,
        vector_service=vector_service,
        lexical_service=lexical_service,
        reranking_service=reranking_service,
        context_builder=context_builder,
    )

def _build_vector_service(*, session: Session, embedding_provider: EmbeddingProvider | None,
                          embedding_input_descriptor: EmbeddingInputDescriptor | None, profile: RetrievalProfile
) -> VectorRetrievalService | None:
    if not profile.vector_enabled:
        return None

    # These invariants were already validated by _validate_inputs().
    # Keeping these checks here makes this helper independently safe against future direct/internal use.
    if embedding_provider is None:
        raise RuntimeError("embedding_provider is required when vector retrieval is enabled.")

    if embedding_input_descriptor is None:
        raise RuntimeError("embedding_input_descriptor is required when vector retrieval is enabled.")

    repository = SQLAlchemyVectorRetrievalRepository(session=session)
    return VectorRetrievalService(
        provider=embedding_provider,
        repository=repository,
        input_descriptor=embedding_input_descriptor,
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

def _validate_inputs(*, session: Session, embedding_provider: EmbeddingProvider | None, embedding_input_descriptor: EmbeddingInputDescriptor | None,
                     profile: RetrievalProfile, default_context_budget: GroundingContextBudget, reranker: Reranker | None, token_estimator: TokenEstimator | None
) -> None:
    if not isinstance(session, Session):
        raise TypeError("session must be a SQLAlchemy Session instance.")

    if not isinstance(profile, RetrievalProfile):
        raise TypeError("profile must be a RetrievalProfile instance.")

    if not isinstance(default_context_budget, GroundingContextBudget):
        raise TypeError("default_context_budget must be a GroundingContextBudget instance.")

    # Embedding infrastructure belongs exclusively to the vector branch.
    if profile.vector_enabled:
        if not isinstance(embedding_provider, EmbeddingProvider):
            raise TypeError("embedding_provider must be an EmbeddingProvider instance when vector retrieval is enabled.")

        if not isinstance(embedding_input_descriptor, EmbeddingInputDescriptor):
            raise TypeError("embedding_input_descriptor must be an EmbeddingInputDescriptor instance when vector retrieval is enabled.")

    else:
        # Reject malformed supplied dependencies even though this particular profile will not use them.
        # This catches composition mistakes instead of silently ignoring invalid objects.
        if embedding_provider is not None and not isinstance(embedding_provider, EmbeddingProvider):
            raise TypeError("embedding_provider must be an EmbeddingProvider instance or None.")

        if embedding_input_descriptor is not None and not isinstance(embedding_input_descriptor, EmbeddingInputDescriptor):
            raise TypeError("embedding_input_descriptor must be an EmbeddingInputDescriptor instance or None.")

    if reranker is not None and not isinstance(reranker, Reranker):
        raise TypeError("reranker must be a Reranker instance or None.")

    if token_estimator is not None and not isinstance(token_estimator, TokenEstimator):
        raise TypeError("token_estimator must be a TokenEstimator instance or None.")