from __future__ import annotations

from packages.application.knowledge.models import KnowledgeRetrievalRequest
from packages.knowledge.retrieval.query.models import RetrievalQueryContext


class KnowledgeRetrievalContextFactory:
    """
    Translates application-level knowledge retrieval requests into knowledge-subsystem retrieval query context.

    This adapter deliberately preserves the trust boundary:

    - customer/AI-derived entities remain retrieval hints
    - trusted application filters remain hard retrieval constraints
    - the knowledge package stays independent from packages.ai
    """
    def create(self, *, request: KnowledgeRetrievalRequest) -> RetrievalQueryContext:
        if not isinstance(request, KnowledgeRetrievalRequest):
            raise TypeError("request must be a KnowledgeRetrievalRequest instance.")

        return RetrievalQueryContext(
            customer_message=request.customer_message,
            intent_key=request.intent_key,
            entities=request.entities,
            filters=request.filters,
            conversation_context=request.conversation_context,
        )