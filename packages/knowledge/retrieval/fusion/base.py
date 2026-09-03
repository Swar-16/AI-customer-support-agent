from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalQuery


@dataclass(frozen=True, slots=True)
class FusionInput:
    """
    Ranked candidate lists produced by independent retrieval strategies.

    Each inner tuple represents one ranked retrieval result, ordered from most relevant to least relevant.

    Fusion implementations must treat the ordering of each candidate list as meaningful.Raw retrieval scores are intentionally 
    not exposed as fusion inputs because scores produced by different retrieval systems are generally not directly comparable.
    """
    query: RetrievalQuery
    rankings: tuple[tuple[RetrievalCandidate, ...], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query, RetrievalQuery):
            raise TypeError("query must be a RetrievalQuery instance.")

        if not isinstance(self.rankings, tuple):
            raise TypeError("rankings must be a tuple.")

        for ranking in self.rankings:
            if not isinstance(ranking, tuple):
                raise TypeError("each ranking must be a tuple.")

            seen_chunk_ids = set()
            for candidate in ranking:
                if not isinstance(candidate, RetrievalCandidate):
                    raise TypeError("rankings must contain RetrievalCandidate instances.")

                if candidate.chunk_id in seen_chunk_ids:
                    raise ValueError("a ranking must not contain duplicate chunk IDs.")

                seen_chunk_ids.add(candidate.chunk_id)

    @property
    def ranking_count(self) -> int:
        return len(self.rankings)

    @property
    def is_empty(self) -> bool:
        return all(not ranking for ranking in self.rankings)


@dataclass(frozen=True, slots=True)
class FusionResult:
    """
    Result produced by a retrieval fusion strategy.

    Candidates must already be ordered from highest fused relevance to lowest fused relevance.
    """
    query: RetrievalQuery
    candidates: tuple[RetrievalCandidate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query, RetrievalQuery):
            raise TypeError("query must be a RetrievalQuery instance.")

        if not isinstance(self.candidates, tuple):
            raise TypeError("candidates must be a tuple.")

        seen_chunk_ids = set()

        for candidate in self.candidates:
            if not isinstance(candidate, RetrievalCandidate):
                raise TypeError("candidates must contain RetrievalCandidate instances.")

            if candidate.chunk_id in seen_chunk_ids:
                raise ValueError("fusion result must not contain duplicate chunk IDs.")

            seen_chunk_ids.add(candidate.chunk_id)

    @property
    def count(self) -> int:
        return len(self.candidates)

    @property
    def is_empty(self) -> bool:
        return not self.candidates

class RetrievalFusionStrategy(ABC):
    """
    Strategy contract for combining independently ranked retrieval results.

    Implementations may use Reciprocal Rank Fusion, weighted rank fusion, learned fusion, or another ranking algorithm
    without affecting the retrieval orchestration layer.
    """

    @property
    @abstractmethod
    def strategy_id(self) -> str:
        """
        Stable identifier for this fusion strategy.

        Used for configuration, observability, and reproducibility.
        """
        raise NotImplementedError

    @abstractmethod
    def fuse(self, *, fusion_input: FusionInput, limit: int) -> FusionResult:
        """
        Combine ranked retrieval results into one ordered result.

        Implementations must:
          - return at most ``limit`` candidates;
          - return each chunk at most once;
          - preserve candidate provenance;
          - attach their fusion score to RetrievalScores.fusion_score;
          - return candidates ordered from highest to lowest fused relevance.
        """
        raise NotImplementedError