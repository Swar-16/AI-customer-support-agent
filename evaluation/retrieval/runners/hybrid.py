from __future__ import annotations

from packages.knowledge.retrieval.application.retrieve_knowledge import RetrieveKnowledge
from packages.knowledge.retrieval.models import RetrievalQuery, RetrievalResult
from packages.knowledge.retrieval.query.models import PreparedRetrievalQuery
from packages.knowledge.retrieval.query.service import RetrievalQueryPreparationService
from evaluation.retrieval.runners.base import BaseRetrievalEvaluationRunner, RetrievalRunnerConfigurationError, RetrievalRunnerContractError


class HybridRetrievalEvaluationRunner(BaseRetrievalEvaluationRunner):
    """
    Evaluation runner for the production hybrid retrieval pipeline.

    Pipeline:

        RetrievalEvaluationCase
                |
                v
        query preparation
                |
                v
        PreparedRetrievalQuery
                |
                v
        RetrieveKnowledge
            /         \\
           /           \\
      vector          lexical
           \\           /
            \\         /
                 RRF
                  |
                  v
          RetrievalResult

    This runner deliberately delegates hybrid orchestration to the production RetrieveKnowledge application service.

    For the baseline evaluation stage, the supplied RetrieveKnowledge instance must have:

        - vector retrieval enabled;
        - lexical retrieval enabled;
        - reranking disabled.

    This ensures that the measured "hybrid" baseline is specifically vector + lexical + fusion, before introducing reranking.
    """
    METHOD = "hybrid"

    def __init__(self, *, query_preparation_service: RetrievalQueryPreparationService, retrieve_knowledge: RetrieveKnowledge) -> None:
        super().__init__(query_preparation_service=query_preparation_service)
        if not isinstance(retrieve_knowledge, RetrieveKnowledge):
            raise RetrievalRunnerConfigurationError("retrieve_knowledge must be a RetrieveKnowledge instance.")

        self._validate_retrieval_pipeline(retrieve_knowledge=retrieve_knowledge)
        self._retrieve_knowledge = retrieve_knowledge

    @property
    def method(self) -> str:
        return self.METHOD

    @property
    def retrieve_knowledge(self) -> RetrieveKnowledge:
        return self._retrieve_knowledge

    def _execute_retrieval(self, *, prepared_query: PreparedRetrievalQuery) -> RetrievalResult:
        if not isinstance(prepared_query, PreparedRetrievalQuery):
            raise RetrievalRunnerContractError("prepared_query must be a PreparedRetrievalQuery instance.")

        result = self._retrieve_knowledge.retrieve(prepared_query=prepared_query)
        if not isinstance(result, RetrievalResult):
            raise RetrievalRunnerContractError("RetrieveKnowledge.retrieve() must return a RetrievalResult instance.")

        self._validate_result_provenance(prepared_query=prepared_query, result=result)
        return result

    @staticmethod
    def _validate_retrieval_pipeline(*, retrieve_knowledge: RetrieveKnowledge) -> None:
        """
        Ensure this runner represents the intended hybrid baseline.

        Evaluation configuration errors should fail immediately rather than silently benchmarking a 
        vector-only, lexical-only, or reranked pipeline under the name "hybrid".
        """
        profile = retrieve_knowledge.profile

        if not profile.vector_enabled:
            raise RetrievalRunnerConfigurationError("hybrid evaluation requires vector retrieval to be enabled.")

        if not profile.lexical_enabled:
            raise RetrievalRunnerConfigurationError("hybrid evaluation requires lexical retrieval to be enabled.")

        if profile.reranking_enabled:
            raise RetrievalRunnerConfigurationError("hybrid baseline evaluation requires reranking to be disabled.")

    @staticmethod
    def _validate_result_provenance(*, prepared_query: PreparedRetrievalQuery, result: RetrievalResult) -> None:
        """
        Validate that the production pipeline returns results associated with the original customer query and trusted retrieval filters.

        Internal semantic and lexical representations are retrieval implementation details and
        must not replace canonical benchmark provenance.
        """
        expected_query = RetrievalQuery(text=prepared_query.original_query, filters=prepared_query.filters)

        if result.query != expected_query:
            raise RetrievalRunnerContractError("RetrieveKnowledge returned a result for a different canonical retrieval query.")