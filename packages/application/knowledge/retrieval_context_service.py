from __future__ import annotations

from packages.ai.intent.schemas import IntentResult
from packages.application.knowledge.ai_request_factory import AIKnowledgeRetrievalRequestFactory
from packages.application.knowledge.retrieval_context_factory import KnowledgeRetrievalContextFactory
from packages.knowledge.retrieval.models import RetrievalFilters
from packages.knowledge.retrieval.query.models import RetrievalQueryContext


class KnowledgeRetrievalContextService:
    """
    Application facade for translating AI understanding plus trusted application scope into a knowledge RetrievalQueryContext.

    This service exists so higher-level orchestration code does not need to know about the intermediate KnowledgeRetrievalRequest DTO.

    Responsibilities:
    - accept already-classified semantic intent
    - preserve trusted retrieval filters
    - preserve optional bounded conversation context
    - coordinate the two application translation boundaries
    """
    def __init__(self, *, ai_request_factory: AIKnowledgeRetrievalRequestFactory, context_factory: KnowledgeRetrievalContextFactory) -> None:
        if not isinstance(ai_request_factory, AIKnowledgeRetrievalRequestFactory):
            raise TypeError("ai_request_factory must be an AIKnowledgeRetrievalRequestFactory instance.")

        if not isinstance(context_factory, KnowledgeRetrievalContextFactory):
            raise TypeError("context_factory must be a KnowledgeRetrievalContextFactory instance.")

        self._ai_request_factory = ai_request_factory
        self._context_factory = context_factory

    def create(self, *, customer_message: str, intent_result: IntentResult, trusted_filters: RetrievalFilters | None = None, conversation_context: str | None = None) -> RetrievalQueryContext:
        request = self._ai_request_factory.create(
            customer_message=customer_message,
            intent_result=intent_result,
            trusted_filters=trusted_filters,
            conversation_context=conversation_context,
        )

        return self._context_factory.create(request=request)