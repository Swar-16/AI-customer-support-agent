from __future__ import annotations
from dataclasses import replace
from math import isfinite
from typing import Final
from uuid import UUID

from packages.knowledge.retrieval.errors import FusionInputError, RetrievalFusionError
from packages.knowledge.retrieval.fusion.base import FusionInput, FusionResult, RetrievalFusionStrategy
from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalScores

_DEFAULT_RRF_K: Final[int] = 60

class ReciprocalRankFusion(RetrievalFusionStrategy):
    """
    Reciprocal Rank Fusion (RRF).

    RRF combines independently ranked retrieval results without assuming
    that their raw scores are directly comparable.

    For a candidate appearing at rank r in a ranking:

        contribution = 1 / (k + r)

    Contributions from every ranking containing the candidate are summed.

    Design properties:
      - rank based, not raw-score based;
      - supports any number of retrieval rankings;
      - deduplicates candidates by chunk_id across rankings;
      - preserves and merges retrieval provenance;
      - preserves available source-specific scores;
      - produces deterministic output ordering;
      - does not mutate input candidates.
    """
    STRATEGY_ID: Final[str] = "reciprocal_rank_fusion"

    def __init__(self, *, k: int = _DEFAULT_RRF_K) -> None:
        if isinstance(k, bool) or not isinstance(k, int):
            raise TypeError("k must be an integer.")

        if k <= 0:
            raise ValueError("k must be greater than zero.")

        self._k = k

    @property
    def strategy_id(self) -> str:
        return self.STRATEGY_ID

    @property
    def k(self) -> int:
        return self._k

    def fuse(self, *, fusion_input: FusionInput, limit: int) -> FusionResult:
        """
        Fuse ranked candidate lists using Reciprocal Rank Fusion.

        Candidates are identified by chunk_id.

        If the same chunk appears in multiple rankings:
          - its RRF contributions are accumulated;
          - its retrieval methods are unioned;
          - its retrieval scores are merged;
          - its metadata/content provenance must remain consistent.

        Ordering is deterministic:
          1. fusion score descending;
          2. best observed rank ascending;
          3. total rank sum ascending;
          4. chunk_id ascending.

        The additional tie-breakers do not change RRF scoring. They only make equal-score output deterministic and reproducible.
        """
        self._validate_input(fusion_input=fusion_input, limit=limit)
        if fusion_input.is_empty:
            return FusionResult(query=fusion_input.query, candidates=())

        accumulators: dict[UUID, _CandidateAccumulator] = {}
        for ranking in fusion_input.rankings:
            for rank, candidate in enumerate(ranking, start=1):
                contribution = 1.0 / (self._k + rank)
                accumulator = accumulators.get(candidate.chunk_id)
                if accumulator is None:
                    accumulators[candidate.chunk_id] = (_CandidateAccumulator.from_candidate(candidate=candidate, rank=rank, contribution=contribution))
                    continue

                accumulator.merge(candidate=candidate, rank=rank, contribution=contribution)

        ranked_accumulators = sorted(
            accumulators.values(),
            key=lambda item: (
                -item.fusion_score,
                item.best_rank,
                item.rank_sum,
                str(item.candidate.chunk_id),
            ),
        )

        candidates = tuple(accumulator.to_candidate() for accumulator in ranked_accumulators[:limit])
        
        return FusionResult(query=fusion_input.query, candidates=candidates)

    @staticmethod
    def _validate_input(*, fusion_input: FusionInput, limit: int) -> None:
        if not isinstance(fusion_input, FusionInput):
            raise TypeError("fusion_input must be a FusionInput instance.")

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer.")

        if limit <= 0:
            raise ValueError("limit must be greater than zero.")

class _CandidateAccumulator:
    """
    Mutable internal aggregation state for one unique chunk.

    This is intentionally private. The public retrieval models remain immutable while the fusion algorithm performs temporary accumulation.
    """
    __slots__ = ("candidate", "fusion_score", "best_rank", "rank_sum",)

    def __init__(self, *, candidate: RetrievalCandidate, fusion_score: float, best_rank: int, rank_sum: int) -> None:
        self.candidate = candidate
        self.fusion_score = fusion_score
        self.best_rank = best_rank
        self.rank_sum = rank_sum

    @classmethod
    def from_candidate(cls, *, candidate: RetrievalCandidate, rank: int, contribution: float) -> "_CandidateAccumulator":
        _validate_rank(rank)
        _validate_contribution(contribution)

        return cls(
            candidate=candidate,
            fusion_score=contribution,
            best_rank=rank,
            rank_sum=rank,
        )

    def merge(self, *, candidate: RetrievalCandidate, rank: int, contribution: float) -> None:
        _validate_rank(rank)
        _validate_contribution(contribution)
        _validate_candidate_consistency(canonical=self.candidate, incoming=candidate)
        self.candidate = _merge_candidates(canonical=self.candidate, incoming=candidate)
        self.fusion_score += contribution
        self.best_rank = min(self.best_rank, rank)
        self.rank_sum += rank

    def to_candidate(self) -> RetrievalCandidate:
        if not isfinite(self.fusion_score):
            raise RetrievalFusionError("Computed fusion score is not finite.")

        if self.fusion_score < 0.0:
            raise RetrievalFusionError("Computed fusion score must not be negative.")

        merged_scores = replace(self.candidate.scores, fusion_score=self.fusion_score)

        return replace(self.candidate, scores=merged_scores)

def _merge_candidates(*, canonical: RetrievalCandidate, incoming: RetrievalCandidate) -> RetrievalCandidate:
    """
    Merge retrieval-specific information for the same logical chunk.

    Structural/provenance fields are required to match and are validated separately.
    Retrieval methods and method-specific scores are merged.
    """
    methods = frozenset({*canonical.methods, *incoming.methods,})
    scores = _merge_scores(canonical.scores, incoming.scores)

    return replace(canonical, methods=methods, scores=scores)

def _merge_scores(canonical: RetrievalScores, incoming: RetrievalScores) -> RetrievalScores:
    """
    Merge source-specific retrieval scores.

    A score available on only one candidate is preserved.

    If both candidates contain the same score type, they must agree. Conflicting values for the same chunk 
    indicate inconsistent upstream provenance and are rejected instead of being silently overwritten.

    fusion_score is intentionally ignored here because the current fusion invocation owns that field and computes it from scratch.
    """

    return RetrievalScores(
        vector_distance=_merge_optional_score(name="vector_distance", left=canonical.vector_distance, right=incoming.vector_distance),
        vector_similarity=_merge_optional_score(name="vector_similarity", left=canonical.vector_similarity, right=incoming.vector_similarity),
        lexical_score=_merge_optional_score(name="lexical_score", left=canonical.lexical_score, right=incoming.lexical_score),
        fusion_score=None,
        reranker_score=_merge_optional_score(name="reranker_score", left=canonical.reranker_score, right=incoming.reranker_score),
    )

def _merge_optional_score(*, name: str, left: float | None, right: float | None) -> float | None:
    if left is None:
        return right

    if right is None:
        return left

    if left != right:
        raise FusionInputError(f"Conflicting {name} values for the same chunk.")

    return left

def _validate_candidate_consistency(*, canonical: RetrievalCandidate, incoming: RetrievalCandidate) -> None:
    """
    Verify that two candidates with the same chunk_id actually describe the same persisted knowledge chunk.

    A chunk ID collision with inconsistent provenance is treated as an upstream data-integrity problem.
    """
    if canonical.chunk_id != incoming.chunk_id:
        raise FusionInputError("Cannot merge candidates with different chunk IDs.")

    consistency_fields = (
        ("version_id", canonical.version_id, incoming.version_id,),
        ("document_id", canonical.document_id, incoming.document_id,),
        ("chunk_index", canonical.chunk_index, incoming.chunk_index,),
        ("content", canonical.content, incoming.content,),
        ("document_title", canonical.document_title, incoming.document_title,),
        ("section_title", canonical.section_title, incoming.section_title,),
    )

    for field_name, left, right in consistency_fields:
        if left != right:
            raise FusionInputError(f"Conflicting candidate provenance for chunk {canonical.chunk_id}: {field_name} differs.")

    if dict(canonical.metadata) != dict(incoming.metadata):
        raise FusionInputError(f"Conflicting candidate provenance for chunk {canonical.chunk_id}: metadata differs.")

def _validate_rank(rank: int) -> None:
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise RetrievalFusionError("rank must be an integer.")

    if rank <= 0:
        raise RetrievalFusionError("rank must be greater than zero.")

def _validate_contribution(contribution: float) -> None:
    if isinstance(contribution, bool) or not isinstance(contribution, (int, float)):
        raise RetrievalFusionError("RRF contribution must be numeric.")

    if not isfinite(float(contribution)):
        raise RetrievalFusionError("RRF contribution must be finite.")

    if contribution <= 0.0:
        raise RetrievalFusionError("RRF contribution must be greater than zero.")