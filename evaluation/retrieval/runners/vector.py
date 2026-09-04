from __future__ import annotations

from packages.knowledge.retrieval.models import RetrievalQuery, RetrievalResult
from packages.knowledge.retrieval.query.models import PreparedRetrievalQuery
from packages.knowledge.retrieval.query.service import RetrievalQueryPreparationService
from packages.knowledge.retrieval.vector.service import VectorRetrievalService
from evaluation.retrieval.runners.base import BaseRetrievalEvaluationRunner, RetrievalRunnerConfigurationError, RetrievalRunnerContractError


class VectorRetrievalEvaluationRunner(BaseRetrievalEvaluationRunner):
    """
    Evaluation runner for the production vector retrieval branch.

    Pipeline:

        RetrievalEvaluationCase -> query preparation -> PreparedRetrievalQuery
                                                                   ↓
            RetrievalResult  <-  VectorRetrievalService  <-  semantic query

    The runner intentionally bypasses:

        - lexical retrieval
        - fusion
        - reranking

    This allows vector retrieval quality to be measured independently from the rest of the retrieval pipeline.
    """
    METHOD = "vector"

    def __init__(self, *, query_preparation_service: RetrievalQueryPreparationService, vector_service: VectorRetrievalService, candidate_limit: int) -> None:
        super().__init__(query_preparation_service=query_preparation_service)

        if not isinstance(vector_service, VectorRetrievalService):
            raise RetrievalRunnerConfigurationError("vector_service must be a VectorRetrievalService instance.")

        if isinstance(candidate_limit, bool) or not isinstance(candidate_limit, int) or candidate_limit <= 0:
            raise RetrievalRunnerConfigurationError("candidate_limit must be a positive integer.")

        self._vector_service = vector_service
        self._candidate_limit = candidate_limit

    @property
    def method(self) -> str:
        return self.METHOD

    @property
    def candidate_limit(self) -> int:
        return self._candidate_limit

    @property
    def vector_service(self) -> VectorRetrievalService:
        return self._vector_service

    def _execute_retrieval(self, *, prepared_query: PreparedRetrievalQuery) -> RetrievalResult:
        if not isinstance(prepared_query, PreparedRetrievalQuery):
            raise RetrievalRunnerContractError("prepared_query must be a PreparedRetrievalQuery instance.")

        semantic_query_text = self._select_semantic_query(prepared_query=prepared_query)
        # Internal query representation used by the vector branch.
        # VectorRetrievalService will embed this semantic representation using its configured production EmbeddingProvider.
        vector_query = RetrievalQuery(text=semantic_query_text, filters=prepared_query.filters)
        candidates = self._vector_service.search(query=vector_query, limit=self._candidate_limit)
        if not isinstance(candidates, tuple):
            raise RetrievalRunnerContractError("VectorRetrievalService.search() must return a tuple of retrieval candidates.")

        # Preserve the original customer request as canonical evaluation provenance.
        # The semantic representation is an internal retrieval representation only.
        canonical_query = RetrievalQuery(text=prepared_query.original_query, filters=prepared_query.filters)

        return RetrievalResult(query=canonical_query, candidates=candidates)

    @staticmethod
    def _select_semantic_query(*, prepared_query: PreparedRetrievalQuery) -> str:
        """
        Return the semantic representation intended for vector search.

        Unlike lexical retrieval, vector retrieval consumes the natural semantic query rather than token-oriented lexical terms.
        """
        semantic_query = prepared_query.semantic_query
        if not isinstance(semantic_query, str):
            raise RetrievalRunnerContractError("semantic query must be a string.")

        normalized_query = semantic_query.strip()
        if not normalized_query:
            raise RetrievalRunnerContractError("semantic query must not be empty.")

        return normalized_query