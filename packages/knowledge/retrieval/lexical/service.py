from __future__ import annotations
from dataclasses import replace

from packages.knowledge.retrieval.errors import LexicalRetrievalRepositoryError, LexicalSearchError
from packages.knowledge.retrieval.lexical.repository import LexicalRetrievalRepository, LexicalSearchRequest
from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalMethod, RetrievalQuery, RetrievalScores

class LexicalRetrievalService:
    """
    Application-facing lexical retrieval service.

    Responsibilities:
      - validate lexical retrieval inputs;
      - build a backend-agnostic lexical search request;
      - invoke the configured lexical repository;
      - translate backend lexical rank into RetrievalScores;
      - preserve existing candidate provenance and scores;
      - translate known repository failures into lexical service errors.
    """
    def __init__(self, *, repository: LexicalRetrievalRepository) -> None:
        if repository is None:
            raise TypeError("repository must not be None.")

        search_method = getattr(repository, "search", None)
        if search_method is None or not callable(search_method):
            raise TypeError("repository must provide a callable search method.")

        self._repository = repository

    def search(self, *, query: RetrievalQuery, limit: int) -> tuple[RetrievalCandidate, ...]:
        """
        Execute lexical retrieval for one canonical retrieval query.

        Returned candidates carry:
          - RetrievalMethod.LEXICAL;
          - the raw lexical relevance score in candidate.scores.lexical_score.

        The lexical score is intentionally preserved as an opaque ranking signal.
        Higher layers must not assume that it is directly comparable to vector similarity.
        """
        self._validate_search_input(query=query, limit=limit)
        request = LexicalSearchRequest(query_text=query.text, filters=query.filters, limit=limit)

        try:
            matches = self._repository.search(request)
            
        except LexicalRetrievalRepositoryError as exc:
            raise LexicalSearchError("Lexical knowledge search failed.") from exc

        candidates: list[RetrievalCandidate] = []
        for match in matches:
            candidate = match.candidate
            updated_scores = replace(candidate.scores, lexical_score=match.score)
            updated_methods = frozenset({*candidate.methods, RetrievalMethod.LEXICAL})
            candidates.append(replace(candidate, methods=updated_methods, scores=updated_scores))

        return tuple(candidates)

    @staticmethod
    def _validate_search_input(*, query: RetrievalQuery, limit: int) -> None:
        if not isinstance(query, RetrievalQuery):
            raise TypeError("query must be a RetrievalQuery instance.")

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer.")

        if limit <= 0:
            raise ValueError("limit must be greater than zero.")