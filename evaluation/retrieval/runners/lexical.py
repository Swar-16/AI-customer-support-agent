from __future__ import annotations

from packages.knowledge.retrieval.lexical.service import LexicalRetrievalService
from packages.knowledge.retrieval.models import RetrievalQuery, RetrievalResult
from packages.knowledge.retrieval.query.models import PreparedRetrievalQuery
from packages.knowledge.retrieval.query.service import RetrievalQueryPreparationService
from evaluation.retrieval.runners.base import BaseRetrievalEvaluationRunner, RetrievalRunnerConfigurationError, RetrievalRunnerContractError


class LexicalRetrievalEvaluationRunner(BaseRetrievalEvaluationRunner):
    """
    Evaluation runner for the production lexical retrieval branch.

    Pipeline:

        RetrievalEvaluationCase -> query preparation -> PreparedRetrievalQuery
                                                                  ↓
           RetrievalResult  <-  LexicalRetrievalService  <-  lexical query

    The runner intentionally bypasses:

        - vector retrieval
        - fusion
        - reranking

    This allows the benchmark to measure lexical retrieval quality independently from the other retrieval strategies.
    """
    METHOD = "lexical"

    def __init__(self, *, query_preparation_service: RetrievalQueryPreparationService,
                 lexical_service: LexicalRetrievalService, candidate_limit: int
    ) -> None:
        super().__init__(query_preparation_service=query_preparation_service)

        if not isinstance(lexical_service, LexicalRetrievalService):
            raise RetrievalRunnerConfigurationError("lexical_service must be a LexicalRetrievalService instance.")

        if isinstance(candidate_limit, bool) or not isinstance(candidate_limit, int) or candidate_limit <= 0:
            raise RetrievalRunnerConfigurationError("candidate_limit must be a positive integer.")

        self._lexical_service = lexical_service
        self._candidate_limit = candidate_limit

    @property
    def method(self) -> str:
        return self.METHOD

    @property
    def candidate_limit(self) -> int:
        return self._candidate_limit

    @property
    def lexical_service(self) -> LexicalRetrievalService:
        return self._lexical_service

    def _execute_retrieval(self, *, prepared_query: PreparedRetrievalQuery) -> RetrievalResult:
        if not isinstance(prepared_query, PreparedRetrievalQuery):
            raise RetrievalRunnerContractError("prepared_query must be a PreparedRetrievalQuery instance.")

        lexical_query_text = self._select_lexical_query(prepared_query=prepared_query)
        # Query passed to the real lexical retriever.
        # The lexical branch receives the lexical representation produced by query preparation, not the raw customer text.
        lexical_query = RetrievalQuery(text=lexical_query_text, filters=prepared_query.filters)
        candidates = self._lexical_service.search(query=lexical_query, limit=self._candidate_limit)
        if not isinstance(candidates, tuple):
            raise RetrievalRunnerContractError("LexicalRetrievalService.search() must return a tuple of retrieval candidates.")

        # Important:
        # The RetrievalResult exposed to the evaluation layer uses the ORIGINAL customer query as its canonical query.
        # The lexical representation is only an internal retrieval representation.
        canonical_query = RetrievalQuery(text=prepared_query.original_query, filters=prepared_query.filters)

        return RetrievalResult(
            query=canonical_query,
            candidates=candidates,
        )

    @staticmethod
    def _select_lexical_query(*, prepared_query: PreparedRetrievalQuery) -> str:
        """
        Select the lexical representation used by V1 retrieval.

        PreparedRetrievalQuery supports multiple lexical queries so future query-expansion 
        strategies do not require changing its model contract.

        The production V1 retrieval pipeline, however, executes one lexical ranking. Evaluation must mirror that behavior rather
        than treating multiple lexical variants as independent rankings, which could overweight lexical retrieval during fusion.
        """
        lexical_queries = prepared_query.lexical_queries
        if not isinstance(lexical_queries, tuple):
            raise RetrievalRunnerContractError("prepared_query.lexical_queries must be a tuple.")

        if not lexical_queries:
            raise RetrievalRunnerContractError("prepared_query must contain at least one lexical query.")

        lexical_query = lexical_queries[0]
        if not isinstance(lexical_query, str):
            raise RetrievalRunnerContractError("lexical query must be a string.")

        normalized_query = lexical_query.strip()
        if not normalized_query:
            raise RetrievalRunnerContractError("lexical query must not be empty.")

        return normalized_query