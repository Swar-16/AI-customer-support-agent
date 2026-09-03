from __future__ import annotations
from dataclasses import dataclass

from packages.application.knowledge.ai_request_factory import AIKnowledgeRetrievalRequestFactory
from packages.application.knowledge.retrieval_context_factory import KnowledgeRetrievalContextFactory
from packages.application.knowledge.retrieval_context_service import KnowledgeRetrievalContextService


@dataclass(frozen=True, slots=True)
class KnowledgeApplicationComponents:
    """
    Application-level components that bridge AI understanding and the knowledge subsystem.

    These components translate already-classified customer requests into knowledge retrieval context.
    They do not perform retrieval themselves and do not decide whether retrieval should occur.
    """
    retrieval_context_service: KnowledgeRetrievalContextService

def create_knowledge_application_components(*, ai_request_factory: AIKnowledgeRetrievalRequestFactory | None = None,
                                            retrieval_context_factory: KnowledgeRetrievalContextFactory | None = None) -> KnowledgeApplicationComponents:
    """
    Compose the application boundary between AI semantic understanding and knowledge retrieval.

    Default implementations are created when explicit dependencies are not supplied.
    Optional injection exists primarily for testing, future strategy replacement, and application-level customization.

    Dependency direction:

        packages.ai --> packages.application --> packages.knowledge

    The knowledge subsystem therefore remains independent of AI-specific schemas such as IntentResult.
    """
    effective_ai_request_factory = ai_request_factory if ai_request_factory is not None else AIKnowledgeRetrievalRequestFactory()
    effective_retrieval_context_factory = retrieval_context_factory if retrieval_context_factory is not None else KnowledgeRetrievalContextFactory()
    _validate_dependencies(ai_request_factory=effective_ai_request_factory, retrieval_context_factory=effective_retrieval_context_factory)
    retrieval_context_service = KnowledgeRetrievalContextService(ai_request_factory=effective_ai_request_factory, context_factory=effective_retrieval_context_factory)

    return KnowledgeApplicationComponents(retrieval_context_service=retrieval_context_service)

def _validate_dependencies(*, ai_request_factory: AIKnowledgeRetrievalRequestFactory, retrieval_context_factory: KnowledgeRetrievalContextFactory) -> None:
    if not isinstance(ai_request_factory, AIKnowledgeRetrievalRequestFactory):
        raise TypeError("ai_request_factory must be an AIKnowledgeRetrievalRequestFactory instance.")

    if not isinstance(retrieval_context_factory, KnowledgeRetrievalContextFactory):
        raise TypeError("retrieval_context_factory must be a KnowledgeRetrievalContextFactory instance.")