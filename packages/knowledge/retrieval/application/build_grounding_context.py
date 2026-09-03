from __future__ import annotations

from packages.knowledge.retrieval.application.retrieve_knowledge import RetrieveKnowledge
from packages.knowledge.retrieval.context.builder import GroundingContextBuilder
from packages.knowledge.retrieval.context.models import GroundingContext, GroundingContextBudget
from packages.knowledge.retrieval.query.models import PreparedRetrievalQuery
from packages.knowledge.retrieval.errors import RetrievalPipelineError

class BuildGroundingContext:
    """
    Application service that converts a retrieval query into bounded,
    trusted grounding context.

    Pipeline:

        RetrievalQuery --> RetrieveKnowledge --> RetrievalResult
                                                        ↓
                        GroundingContext <-- GroundingContextBuilder

    Responsibilities:
      - execute the configured retrieval pipeline;
      - apply context-selection and budgeting policy;
      - return structured grounding context.

    This keeps the knowledge subsystem reusable independently of any specific LLM provider or RAG prompt implementation.
    """
    def __init__(self, *, retrieve_knowledge: RetrieveKnowledge, context_builder: GroundingContextBuilder, default_budget: GroundingContextBudget) -> None:
        if not isinstance(retrieve_knowledge, RetrieveKnowledge):
            raise TypeError("retrieve_knowledge must be a RetrieveKnowledge instance.")

        if not isinstance(context_builder, GroundingContextBuilder):
            raise TypeError("context_builder must be a GroundingContextBuilder instance.")

        if not isinstance(default_budget, GroundingContextBudget):
            raise TypeError("default_budget must be a GroundingContextBudget instance.")

        self._retrieve_knowledge = retrieve_knowledge
        self._context_builder = context_builder
        self._default_budget = default_budget

    @property
    def retrieve_knowledge(self) -> RetrieveKnowledge:
        return self._retrieve_knowledge

    @property
    def context_builder(self) -> GroundingContextBuilder:
        return self._context_builder

    @property
    def default_budget(self) -> GroundingContextBudget:
        return self._default_budget

    def build(self, *, prepared_query: PreparedRetrievalQuery, budget: GroundingContextBudget | None = None) -> GroundingContext:
        """
        Retrieve relevant knowledge and construct bounded grounding context.

        ``budget`` may override the application default for a particular invocation.
        This is useful when different callers or models have different available context windows.

        Known typed retrieval/context failures intentionally propagate.
        """
        if not isinstance(prepared_query, PreparedRetrievalQuery):
            raise TypeError("prepared_query must be a PreparedRetrievalQuery instance.")

        effective_budget = self._resolve_budget(budget)
        retrieval_result = self._retrieve_knowledge.retrieve(prepared_query=prepared_query)
        context = self._context_builder.build(retrieval_result=retrieval_result, budget=effective_budget)
        if context.query != retrieval_result.query:
            raise RetrievalPipelineError("Grounding context was produced for a different retrieval query.")

        return context

    def _resolve_budget(self, budget: GroundingContextBudget | None) -> GroundingContextBudget:
        if budget is None:
            return self._default_budget

        if not isinstance(budget, GroundingContextBudget):
            raise TypeError("budget must be a GroundingContextBudget instance or None.")

        return budget