# AI-customer-support-agent\packages\application\composition\answer_service_factory.py
from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy.orm import Session

from packages.ai.generation.generator import GroundedResponseGenerator
from packages.application.ai.answer_service import AnswerService
from packages.application.knowledge.evidence_mapper import KnowledgeEvidenceMapper
from packages.application.composition.knowledge_application_factory import KnowledgeApplicationComponents, create_knowledge_application_components
from packages.knowledge.embeddings.models import EmbeddingInputDescriptor
from packages.knowledge.embeddings.provider.base import EmbeddingProvider
from packages.knowledge.retrieval.context.builder import TokenEstimator
from packages.knowledge.retrieval.context.models import GroundingContextBudget
from packages.application.composition.knowledge_retrieval_factory import KnowledgeRetrievalComponents, create_knowledge_retrieval_components
from packages.knowledge.retrieval.profiles import RetrievalProfile
from packages.knowledge.retrieval.reranking.base import Reranker
from packages.ai.telemetry.retrieval_recorder import RetrievalTelemetryRecorder
from packages.ai.telemetry.reranker_recorder import RerankerTelemetryRecorder

# Composed result
@dataclass(frozen=True, slots=True)
class AnswerServiceComponents:
    """
    Request-scoped application components required for grounded answering.

    `answer_service` is the normal entry point.

    The lower-level component bundles remain exposed intentionally for:
        - integration tests;
        - diagnostics;
        - health/observability wiring;
        - future orchestration telemetry;
        - controlled application-level customization.

    This object owns no resources itself.
    """
    answer_service: AnswerService
    knowledge_application: KnowledgeApplicationComponents
    knowledge_retrieval: KnowledgeRetrievalComponents
    evidence_mapper: KnowledgeEvidenceMapper

# Factory
def create_answer_service_components(*, session: Session, profile: RetrievalProfile, default_context_budget: GroundingContextBudget, 
                                     response_generator: GroundedResponseGenerator, embedding_provider: EmbeddingProvider | None = None, 
                                     embedding_input_descriptor: EmbeddingInputDescriptor | None = None, reranker: Reranker | None = None,
                                     token_estimator: TokenEstimator | None = None, evidence_mapper: KnowledgeEvidenceMapper | None = None,
                                     knowledge_application: KnowledgeApplicationComponents | None = None, knowledge_retrieval: KnowledgeRetrievalComponents | None = None,
                                     retrieval_telemetry_recorder: RetrievalTelemetryRecorder | None = None, reranker_telemetry_recorder: RerankerTelemetryRecorder | None = None
) -> AnswerServiceComponents:
    """
    Compose the application-level grounded-answer boundary.

    Normal dependency graph
    -----------------------

        SQLAlchemy Session
                |
                v
        knowledge retrieval infrastructure
                |
                +--> query preparation
                |
                +--> vector / lexical retrieval
                |
                +--> fusion / reranking
                |
                +--> grounding context
                |
                v
        KnowledgeEvidenceMapper
                |
                v
        GroundedResponseGenerator
                |
                v
            AnswerService


    Separate AI -> knowledge translation path
    -----------------------------------------

        IntentResult
            |
            v
        KnowledgeApplicationComponents
            |
            v
        KnowledgeRetrievalContextService
            |
            v
        RetrievalQueryContext


    Lifecycle
    ---------
    This factory is intended to be called inside an already-established request/application operation.

    The caller owns `session`. It only constructs the object graph.


    Optional injection
    ------------------
    `knowledge_application`, `knowledge_retrieval`, and `evidence_mapper` may be supplied explicitly.

    This is useful for:
        - unit tests;
        - integration tests;
        - alternate composition roots;
        - future retrieval strategies.

    When a precomposed `knowledge_retrieval` bundle is supplied, the retrieval-specific construction arguments are intentionally not used to rebuild that bundle.
    """
    _validate_core_dependencies(session=session, profile=profile, default_context_budget=default_context_budget, response_generator=response_generator)
    effective_knowledge_application = knowledge_application if knowledge_application is not None else create_knowledge_application_components()
    if not isinstance(effective_knowledge_application, KnowledgeApplicationComponents):
        raise TypeError("knowledge_application must be a KnowledgeApplicationComponents instance or None.")

    effective_knowledge_retrieval = knowledge_retrieval if knowledge_retrieval is not None else create_knowledge_retrieval_components(
        session=session,
        profile=profile,
        default_context_budget=default_context_budget,
        embedding_provider=embedding_provider,
        embedding_input_descriptor=embedding_input_descriptor,
        reranker=reranker,
        token_estimator=token_estimator,
        telemetry_recorder=retrieval_telemetry_recorder,
        reranker_telemetry_recorder=reranker_telemetry_recorder
    )

    if not isinstance(effective_knowledge_retrieval, KnowledgeRetrievalComponents):
        raise TypeError("knowledge_retrieval must be a KnowledgeRetrievalComponents instance or None.")

    effective_evidence_mapper = evidence_mapper if evidence_mapper is not None else KnowledgeEvidenceMapper()
    if not isinstance(effective_evidence_mapper, KnowledgeEvidenceMapper):
        raise TypeError("evidence_mapper must be a KnowledgeEvidenceMapper instance or None.")

    answer_service = AnswerService(
        retrieval_context_service=effective_knowledge_application.retrieval_context_service,
        query_preparation_service=effective_knowledge_retrieval.query_preparation_service,
        build_grounding_context=effective_knowledge_retrieval.build_grounding_context,
        evidence_mapper=effective_evidence_mapper,
        response_generator=response_generator,
    )

    return AnswerServiceComponents(
        answer_service=answer_service,
        knowledge_application=effective_knowledge_application,
        knowledge_retrieval=effective_knowledge_retrieval,
        evidence_mapper=effective_evidence_mapper,
    )

# Validation
def _validate_core_dependencies(*, session: Session, profile: RetrievalProfile, default_context_budget: GroundingContextBudget, response_generator: GroundedResponseGenerator) -> None:
    """
    Validate dependencies owned directly by this composition boundary.

    Lower-level optional dependencies are deliberately validated by their respective lower-level factories.

    This avoids duplicating validation rules across composition roots.
    """
    if not isinstance(session, Session):
        raise TypeError("session must be a SQLAlchemy Session instance.")

    if not isinstance(profile, RetrievalProfile):
        raise TypeError("profile must be a RetrievalProfile instance.")

    if not isinstance(default_context_budget, GroundingContextBudget):
        raise TypeError("default_context_budget must be a GroundingContextBudget instance.")

    if not isinstance(response_generator, GroundedResponseGenerator):
        raise TypeError("response_generator must be a GroundedResponseGenerator instance.")