from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Iterable

from evaluation.retrieval.models import RetrievalEvaluationResult


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    """
    Aggregate retrieval-quality metrics for one evaluation population.

    Metrics are represented in [0.0, 1.0].

    `case_count` is kept alongside the averages so reports never present an aggregate score without making its sample size available.
    """
    case_count: int
    hit_rate_at_1: float
    hit_rate_at_3: float
    hit_rate_at_5: float
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mrr: float

    def __post_init__(self) -> None:
        if isinstance(self.case_count, bool) or not isinstance(self.case_count, int):
            raise TypeError("case_count must be an integer.")

        if self.case_count < 0:
            raise ValueError("case_count must not be negative.")

        metric_names = ("hit_rate_at_1", "hit_rate_at_3", "hit_rate_at_5", "recall_at_1", "recall_at_3", "recall_at_5", "mrr",)
        for metric_name in metric_names:
            value = getattr(self, metric_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{metric_name} must be a numeric value.")

            numeric_value = float(value)
            if not isfinite(numeric_value):
                raise ValueError(f"{metric_name} must be finite.")

            if not 0.0 <= numeric_value <= 1.0:
                raise ValueError(f"{metric_name} must be between 0.0 and 1.0.")

            object.__setattr__(self, metric_name, numeric_value)


def hit_at_k(result: RetrievalEvaluationResult, *, k: int) -> float:
    """
    Return 1.0 when at least one relevant result appears within top-k.

    Otherwise return 0.0.
    """
    _validate_result(result)
    _validate_k(k)

    return float(any(hit.relevant for hit in result.hits if hit.rank <= k))

def reciprocal_rank(result: RetrievalEvaluationResult) -> float:
    """
    Reciprocal rank of the first relevant result.

    Examples:
        first relevant at rank 1 -> 1.0
        first relevant at rank 2 -> 0.5
        first relevant at rank 4 -> 0.25
        no relevant result       -> 0.0
    """
    _validate_result(result)
    for hit in result.hits:
        if hit.relevant:
            return 1.0 / hit.rank

    return 0.0

def recall_at_k(result: RetrievalEvaluationResult, *, k: int) -> float:
    """
    Fraction of ground-truth relevance targets satisfied within top-k.

    Multiple retrieved chunks matching the same target count only once.

    Example:
        expected targets:
            document:refund policy
            section:processing time

        top-k matches:
            chunk 1 -> document:refund policy
            chunk 2 -> document:refund policy

        recall@k = 1 / 2, not 2 / 2.
    """
    _validate_result(result)
    _validate_k(k)
    matched_targets: set[str] = set()
    for hit in result.hits:
        if hit.rank > k:
            break

        matched_targets.update(hit.matched_target_ids)

    return len(matched_targets) / result.relevance_target_count

def mean_reciprocal_rank(results: Iterable[RetrievalEvaluationResult]) -> float:
    """
    Mean reciprocal rank across evaluation cases.

    Empty populations produce 0.0.
    """
    normalized_results = _materialize_results(results)
    if not normalized_results:
        return 0.0

    return sum(reciprocal_rank(result) for result in normalized_results) / len(normalized_results)

def hit_rate_at_k(results: Iterable[RetrievalEvaluationResult], *, k: int) -> float:
    """
    Fraction of evaluation cases with at least one relevant hit in top-k.

    Empty populations produce 0.0.
    """
    _validate_k(k)
    normalized_results = _materialize_results(results)
    if not normalized_results:
        return 0.0

    return sum(hit_at_k(result, k=k) for result in normalized_results) / len(normalized_results)

def mean_recall_at_k(results: Iterable[RetrievalEvaluationResult], *, k: int) -> float:
    """
    Mean per-case recall@k.

    Empty populations produce 0.0.
    """
    _validate_k(k)
    normalized_results = _materialize_results(results)
    if not normalized_results:
        return 0.0

    return sum(recall_at_k(result, k=k) for result in normalized_results) / len(normalized_results)

def compute_metrics(results: Iterable[RetrievalEvaluationResult]) -> RetrievalMetrics:
    """
    Compute the standard retrieval benchmark summary.

    The iterable is materialized exactly once so generators are safe to pass.
    """
    normalized_results = _materialize_results(results)

    return RetrievalMetrics(
        case_count=len(normalized_results),
        hit_rate_at_1=hit_rate_at_k(normalized_results, k=1),
        hit_rate_at_3=hit_rate_at_k(normalized_results, k=3),
        hit_rate_at_5=hit_rate_at_k(normalized_results, k=5),
        recall_at_1=mean_recall_at_k(normalized_results, k=1),
        recall_at_3=mean_recall_at_k(normalized_results, k=3),
        recall_at_5=mean_recall_at_k(normalized_results, k=5),
        mrr=mean_reciprocal_rank(normalized_results),
    )

def _materialize_results(results: Iterable[RetrievalEvaluationResult]) -> tuple[RetrievalEvaluationResult, ...]:
    if isinstance(results, (str, bytes)):
        raise TypeError("results must be an iterable of RetrievalEvaluationResult instances.")

    try:
        materialized = tuple(results)
        
    except TypeError as exc:
        raise TypeError("results must be an iterable of RetrievalEvaluationResult instances.") from exc

    for result in materialized:
        _validate_result(result)

    return materialized

def _validate_result(result: RetrievalEvaluationResult) -> None:
    if not isinstance(result, RetrievalEvaluationResult):
        raise TypeError("result must be a RetrievalEvaluationResult instance.")

def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int):
        raise TypeError("k must be an integer.")

    if k <= 0:
        raise ValueError("k must be greater than zero.")