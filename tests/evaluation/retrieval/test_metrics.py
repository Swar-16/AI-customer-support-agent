from __future__ import annotations

import pytest

from evaluation.retrieval.metrics import (
    RetrievalMetrics,
    compute_metrics,
    hit_at_k,
    hit_rate_at_k,
    mean_recall_at_k,
    mean_reciprocal_rank,
    recall_at_k,
    reciprocal_rank,
)
from evaluation.retrieval.models import (
    RetrievalEvaluationHit,
    RetrievalEvaluationResult,
)

TARGET_1 = "target:1"
TARGET_2 = "target:2"
TARGET_3 = "target:3"
TARGET_4 = "target:4"

MATCH_1 = frozenset({TARGET_1})
MATCH_2 = frozenset({TARGET_2})
MATCH_3 = frozenset({TARGET_3})
MATCH_4 = frozenset({TARGET_4})
NO_MATCH = frozenset()

def make_result(
    *,
    case_id: str = "case_001",
    method: str = "hybrid",
    matched_targets: tuple[frozenset[str], ...] = (),
    relevance_target_ids: frozenset[str] | None = None,
) -> RetrievalEvaluationResult:
    if relevance_target_ids is None:
        inferred_targets = {
            target
            for targets in matched_targets
            for target in targets
        }

        relevance_target_ids = frozenset(
            inferred_targets or {TARGET_1}
        )

    hits = tuple(
        RetrievalEvaluationHit(
            rank=index,
            document_title=f"Document {index}",
            section_title=f"Section {index}",
            chunk_id=f"chunk-{index}",
            matched_target_ids=targets,
        )
        for index, targets in enumerate(
            matched_targets,
            start=1,
        )
    )

    return RetrievalEvaluationResult(
        case_id=case_id,
        method=method,
        relevance_target_ids=relevance_target_ids,
        hits=hits,
    )

class TestHitAtK:
    def test_returns_one_when_relevant_hit_is_at_rank_one(self) -> None:
        result = make_result(
            matched_targets=(
                MATCH_1,
                NO_MATCH,
                NO_MATCH,
            ),
        )

        assert hit_at_k(result, k=1) == 1.0

    def test_returns_zero_when_first_relevant_hit_is_after_k(self) -> None:
        result = make_result(
            matched_targets=(
                NO_MATCH,
                NO_MATCH,
                MATCH_3
            ),
        )

        assert hit_at_k(result, k=2) == 0.0

    def test_returns_one_when_relevant_hit_is_exactly_at_k(self) -> None:
        result = make_result(
            matched_targets=(
                NO_MATCH,
                NO_MATCH,
                MATCH_3
            ),
        )

        assert hit_at_k(result, k=3) == 1.0

    def test_returns_zero_when_no_relevant_hits_exist(self) -> None:
        result = make_result(
            matched_targets=(
                NO_MATCH,
                NO_MATCH,
                NO_MATCH,
            ),
        )

        assert hit_at_k(result, k=5) == 0.0

    def test_k_may_exceed_number_of_hits(self) -> None:
        result = make_result(
            matched_targets=(
                NO_MATCH,
                MATCH_1,
            )
        )

        assert hit_at_k(result, k=100) == 1.0

    def test_empty_result_returns_zero(self) -> None:
        result = make_result()

        assert hit_at_k(result, k=1) == 0.0


class TestReciprocalRank:
    def test_rank_one_relevant_hit_returns_one(self) -> None:
        result = make_result(
            matched_targets=(
                MATCH_1,
                NO_MATCH,
                NO_MATCH,
            )
        )

        assert reciprocal_rank(result) == 1.0

    def test_rank_two_relevant_hit_returns_half(self) -> None:
        result = make_result(
            matched_targets=(
            NO_MATCH,
            MATCH_2,
            NO_MATCH,
        )
        )

        assert reciprocal_rank(result) == 0.5

    def test_rank_four_relevant_hit_returns_quarter(self) -> None:
        result = make_result(
            matched_targets=(
                NO_MATCH,
                NO_MATCH,
                NO_MATCH,
                MATCH_4
            ),
        )

        assert reciprocal_rank(result) == 0.25

    def test_only_first_relevant_hit_matters(self) -> None:
        result = make_result(
            matched_targets=(
                NO_MATCH,
                MATCH_2,
                MATCH_3,
                MATCH_4
            )
        )

        assert reciprocal_rank(result) == 0.5

    def test_no_relevant_hit_returns_zero(self) -> None:
        result = make_result(
            matched_targets=(
                NO_MATCH,
                NO_MATCH,
            )
        )

        assert reciprocal_rank(result) == 0.0

    def test_empty_result_returns_zero(self) -> None:
        assert reciprocal_rank(
            make_result(),
        ) == 0.0


class TestRecallAtK:
    def test_returns_fraction_of_ground_truth_targets_matched_within_k(
        self,
    ) -> None:
        result = make_result(
            relevance_target_ids=frozenset(
                {
                    TARGET_1,
                    TARGET_2,
                    TARGET_3,
                }
            ),
            matched_targets=(
                MATCH_1,
                NO_MATCH,
                MATCH_2,
                MATCH_3,
            ),
        )

        assert recall_at_k(
            result,
            k=3,
        ) == pytest.approx(
            2 / 3,
        )

    def test_returns_one_when_all_targets_are_matched_within_k(
        self,
    ) -> None:
        result = make_result(
            relevance_target_ids=frozenset(
                {
                    TARGET_1,
                    TARGET_2,
                }
            ),
            matched_targets=(
                MATCH_1,
                NO_MATCH,
                MATCH_2,
            ),
        )

        assert recall_at_k(
            result,
            k=3,
        ) == 1.0

    def test_returns_zero_when_no_targets_are_matched_within_k(
        self,
    ) -> None:
        result = make_result(
            relevance_target_ids=frozenset(
                {
                    TARGET_1,
                    TARGET_2,
                }
            ),
            matched_targets=(
                NO_MATCH,
                NO_MATCH,
                MATCH_1,
            ),
        )

        assert recall_at_k(
            result,
            k=2,
        ) == 0.0

    def test_empty_result_returns_zero(self) -> None:
        result = make_result(
            relevance_target_ids=frozenset(
                {
                    TARGET_1,
                    TARGET_2,
                }
            ),
        )

        assert recall_at_k(
            result,
            k=3,
        ) == 0.0

    def test_duplicate_matches_for_same_target_count_once(
        self,
    ) -> None:
        result = make_result(
            relevance_target_ids=frozenset(
                {
                    TARGET_1,
                    TARGET_2,
                }
            ),
            matched_targets=(
                MATCH_1,
                MATCH_1,
                MATCH_1,
            ),
        )

        assert recall_at_k(
            result,
            k=3,
        ) == pytest.approx(
            0.5,
        )

    def test_single_hit_can_satisfy_multiple_targets(
        self,
    ) -> None:
        result = make_result(
            relevance_target_ids=frozenset(
                {
                    TARGET_1,
                    TARGET_2,
                    TARGET_3,
                }
            ),
            matched_targets=(
                frozenset(
                    {
                        TARGET_1,
                        TARGET_2,
                    }
                ),
                NO_MATCH,
            ),
        )

        assert recall_at_k(
            result,
            k=1,
        ) == pytest.approx(
            2 / 3,
        )

    def test_targets_after_k_are_not_counted(self) -> None:
        result = make_result(
            relevance_target_ids=frozenset(
                {
                    TARGET_1,
                    TARGET_2,
                }
            ),
            matched_targets=(
                MATCH_1,
                NO_MATCH,
                MATCH_2,
            ),
        )

        assert recall_at_k(
            result,
            k=2,
        ) == pytest.approx(
            0.5,
        )

    def test_k_larger_than_result_uses_all_retrieved_targets(
        self,
    ) -> None:
        result = make_result(
            relevance_target_ids=frozenset(
                {
                    TARGET_1,
                    TARGET_2,
                }
            ),
            matched_targets=(
                MATCH_1,
                NO_MATCH,
                MATCH_2,
            ),
        )

        assert recall_at_k(
            result,
            k=100,
        ) == 1.0


class TestMeanReciprocalRank:
    def test_computes_mean_across_cases(self) -> None:
        results = (
            make_result(
                case_id="case_1",
                matched_targets=(MATCH_1,),
            ),
            make_result(
                case_id="case_2",
                matched_targets=(
                    NO_MATCH,
                    MATCH_1,
                )
            ),
            make_result(
                case_id="case_3",
                matched_targets=(
                    NO_MATCH,
                    NO_MATCH,
                    NO_MATCH,
                )
            ),
        )

        expected = (
            1.0
            + 0.5
            + 0.0
        ) / 3

        assert mean_reciprocal_rank(results) == pytest.approx(
            expected,
        )

    def test_empty_population_returns_zero(self) -> None:
        assert mean_reciprocal_rank(()) == 0.0

    def test_accepts_generator(self) -> None:
        results = (
            make_result(
                case_id=f"case_{index}",
                matched_targets=(MATCH_1,),
            )
            for index in range(3)
        )

        assert mean_reciprocal_rank(results) == 1.0


class TestHitRateAtK:
    def test_computes_fraction_of_cases_with_relevant_hit(self) -> None:
        results = (
            make_result(
                case_id="case_1",
                matched_targets=(MATCH_1,),
            ),
            make_result(
                case_id="case_2",
                matched_targets=(
                    NO_MATCH,
                    MATCH_1,
                )
            ),
            make_result(
                case_id="case_3",
                matched_targets=(
                    NO_MATCH,
                    NO_MATCH,
                ),
            ),
        )

        assert hit_rate_at_k(
            results,
            k=1,
        ) == pytest.approx(
            1 / 3,
        )

        assert hit_rate_at_k(
            results,
            k=2,
        ) == pytest.approx(
            2 / 3,
        )

    def test_empty_population_returns_zero(self) -> None:
        assert hit_rate_at_k(
            (),
            k=3,
        ) == 0.0

    def test_accepts_generator(self) -> None:
        results = (
            make_result(
                case_id=f"case_{index}",
                matched_targets=(MATCH_1,),
            )
            for index in range(4)
        )

        assert hit_rate_at_k(
            results,
            k=1,
        ) == 1.0


class TestMeanRecallAtK:
    def test_computes_mean_per_case_recall(self) -> None:
        results = (
            make_result(
                case_id="case_1",
                relevance_target_ids=frozenset(
                    {
                        TARGET_1,
                        TARGET_2,
                    }
                ),
                matched_targets=(
                    MATCH_1,
                    MATCH_2,
                ),
            ),
            make_result(
                case_id="case_2",
                relevance_target_ids=frozenset(
                    {
                        TARGET_1,
                        TARGET_2,
                    }
                ),
                matched_targets=(
                    NO_MATCH,
                    MATCH_1,
                ),
            ),
            make_result(
                case_id="case_3",
                relevance_target_ids=frozenset(
                    {
                        TARGET_1,
                        TARGET_2,
                    }
                ),
                matched_targets=(
                    NO_MATCH,
                    NO_MATCH,
                ),
            ),
        )

        expected = (
            0.5
            + 0.0
            + 0.0
        ) / 3

        assert mean_recall_at_k(
            results,
            k=1,
        ) == pytest.approx(expected)

    def test_empty_population_returns_zero(self) -> None:
        assert mean_recall_at_k(
            (),
            k=5,
        ) == 0.0

    def test_accepts_generator(self) -> None:
        results = (
            make_result(
                case_id=f"case_{index}",
                matched_targets=(
                    MATCH_1,
                ),
            )
            for index in range(3)
        )

        assert mean_recall_at_k(
            results,
            k=1,
        ) == 1.0


class TestComputeMetrics:
    def test_computes_standard_metric_summary(self) -> None:
        results = (
            make_result(
                case_id="case_1",
                relevance_target_ids=frozenset(
                    {
                        TARGET_1,
                        TARGET_2,
                    }
                ),
                matched_targets=(
                    MATCH_1,
                    NO_MATCH,
                    MATCH_2,
                ),
            ),
            make_result(
                case_id="case_2",
                relevance_target_ids=frozenset(
                    {
                        TARGET_1,
                    }
                ),
                matched_targets=(
                    NO_MATCH,
                    MATCH_1,
                    NO_MATCH,
                ),
            ),
            make_result(
                case_id="case_3",
                relevance_target_ids=frozenset(
                    {
                        TARGET_1,
                    }
                ),
                matched_targets=(
                    NO_MATCH,
                    NO_MATCH,
                    NO_MATCH,
                ),
            ),
        )

        metrics = compute_metrics(results)

        assert metrics.case_count == 3

        assert metrics.hit_rate_at_1 == pytest.approx(
            1 / 3,
        )

        assert metrics.hit_rate_at_3 == pytest.approx(
            2 / 3,
        )

        assert metrics.hit_rate_at_5 == pytest.approx(
            2 / 3,
        )

        assert metrics.recall_at_1 == pytest.approx(
            (
                0.5
                + 0.0
                + 0.0
            )
            / 3
        )

        assert metrics.recall_at_3 == pytest.approx(
            (
                1.0
                + 1.0
                + 0.0
            )
            / 3
        )

        assert metrics.recall_at_5 == pytest.approx(
            (
                1.0
                + 1.0
                + 0.0
            )
            / 3
        )

        assert metrics.mrr == pytest.approx(
            (
                1.0
                + 0.5
                + 0.0
            )
            / 3
        )

    def test_empty_population_produces_zero_metrics(self) -> None:
        metrics = compute_metrics(())

        assert metrics == RetrievalMetrics(
            case_count=0,
            hit_rate_at_1=0.0,
            hit_rate_at_3=0.0,
            hit_rate_at_5=0.0,
            recall_at_1=0.0,
            recall_at_3=0.0,
            recall_at_5=0.0,
            mrr=0.0,
        )

    def test_accepts_single_use_generator(self) -> None:
        results = (
            make_result(
                case_id=f"case_{index}",
                matched_targets=(MATCH_1,),
            )
            for index in range(5)
        )

        metrics = compute_metrics(results)

        assert metrics.case_count == 5
        assert metrics.hit_rate_at_1 == 1.0
        assert metrics.hit_rate_at_3 == 1.0
        assert metrics.hit_rate_at_5 == 1.0
        assert metrics.recall_at_1 == 1.0
        assert metrics.recall_at_3 == 1.0
        assert metrics.recall_at_5 == 1.0
        assert metrics.mrr == 1.0


class TestMetricInputValidation:
    @pytest.mark.parametrize(
        "invalid_k",
        [
            0,
            -1,
            -100,
        ],
    )
    def test_rejects_non_positive_k(
        self,
        invalid_k: int,
    ) -> None:
        result = make_result(
            matched_targets=(MATCH_1,),
        )

        with pytest.raises(
            ValueError,
            match="k must be greater than zero",
        ):
            hit_at_k(
                result,
                k=invalid_k,
            )

        with pytest.raises(
            ValueError,
            match="k must be greater than zero",
        ):
            recall_at_k(
                result,
                k=invalid_k,
            )

        with pytest.raises(
            ValueError,
            match="k must be greater than zero",
        ):
            hit_rate_at_k(
                (result,),
                k=invalid_k,
            )

        with pytest.raises(
            ValueError,
            match="k must be greater than zero",
        ):
            mean_recall_at_k(
                (result,),
                k=invalid_k,
            )

    @pytest.mark.parametrize(
        "invalid_k",
        [
            True,
            False,
            1.5,
            "3",
            None,
        ],
    )
    def test_rejects_non_integer_k(
        self,
        invalid_k: object,
    ) -> None:
        result = make_result(
            matched_targets=(MATCH_1,),
        )

        with pytest.raises(
            TypeError,
            match="k must be an integer",
        ):
            hit_at_k(
                result,
                k=invalid_k,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "function_name",
        [
            "hit_at_k",
            "reciprocal_rank",
            "recall_at_k",
        ],
    )
    def test_single_result_functions_reject_invalid_result(
        self,
        function_name: str,
    ) -> None:
        if function_name == "hit_at_k":
            with pytest.raises(
                TypeError,
                match=(
                    "result must be a "
                    "RetrievalEvaluationResult instance"
                ),
            ):
                hit_at_k(
                    object(),  # type: ignore[arg-type]
                    k=1,
                )

        elif function_name == "reciprocal_rank":
            with pytest.raises(
                TypeError,
                match=(
                    "result must be a "
                    "RetrievalEvaluationResult instance"
                ),
            ):
                reciprocal_rank(
                    object(),  # type: ignore[arg-type]
                )

        else:
            with pytest.raises(
                TypeError,
                match=(
                    "result must be a "
                    "RetrievalEvaluationResult instance"
                ),
            ):
                recall_at_k(
                    object(),  # type: ignore[arg-type]
                    k=1,
                )

    def test_aggregate_functions_reject_non_iterable(self) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "results must be an iterable of "
                "RetrievalEvaluationResult instances"
            ),
        ):
            compute_metrics(
                123,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "invalid_results",
        [
            "invalid",
            b"invalid",
        ],
    )
    def test_rejects_string_like_iterables(
        self,
        invalid_results: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "results must be an iterable of "
                "RetrievalEvaluationResult instances"
            ),
        ):
            compute_metrics(
                invalid_results,  # type: ignore[arg-type]
            )

    def test_rejects_invalid_item_inside_population(self) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "result must be a "
                "RetrievalEvaluationResult instance"
            ),
        ):
            compute_metrics(
                (
                    make_result(),
                    object(),  # type: ignore[arg-type]
                )
            )


class TestRetrievalMetricsValidation:
    def test_accepts_valid_values(self) -> None:
        metrics = RetrievalMetrics(
            case_count=10,
            hit_rate_at_1=0.5,
            hit_rate_at_3=0.7,
            hit_rate_at_5=0.8,
            recall_at_1=0.4,
            recall_at_3=0.6,
            recall_at_5=0.75,
            mrr=0.65,
        )

        assert metrics.case_count == 10
        assert metrics.mrr == 0.65

    def test_integer_metric_values_are_normalized_to_float(
        self,
    ) -> None:
        metrics = RetrievalMetrics(
            case_count=1,
            hit_rate_at_1=1,
            hit_rate_at_3=1,
            hit_rate_at_5=1,
            recall_at_1=1,
            recall_at_3=1,
            recall_at_5=1,
            mrr=1,
        )

        assert metrics.hit_rate_at_1 == 1.0
        assert isinstance(
            metrics.hit_rate_at_1,
            float,
        )

    @pytest.mark.parametrize(
        "invalid_case_count",
        [
            True,
            False,
            1.5,
            "10",
            None,
        ],
    )
    def test_rejects_invalid_case_count_type(
        self,
        invalid_case_count: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="case_count must be an integer",
        ):
            RetrievalMetrics(
                case_count=invalid_case_count,  # type: ignore[arg-type]
                hit_rate_at_1=0.0,
                hit_rate_at_3=0.0,
                hit_rate_at_5=0.0,
                recall_at_1=0.0,
                recall_at_3=0.0,
                recall_at_5=0.0,
                mrr=0.0,
            )

    def test_rejects_negative_case_count(self) -> None:
        with pytest.raises(
            ValueError,
            match="case_count must not be negative",
        ):
            RetrievalMetrics(
                case_count=-1,
                hit_rate_at_1=0.0,
                hit_rate_at_3=0.0,
                hit_rate_at_5=0.0,
                recall_at_1=0.0,
                recall_at_3=0.0,
                recall_at_5=0.0,
                mrr=0.0,
            )

    @pytest.mark.parametrize(
        "metric_name",
        [
            "hit_rate_at_1",
            "hit_rate_at_3",
            "hit_rate_at_5",
            "recall_at_1",
            "recall_at_3",
            "recall_at_5",
            "mrr",
        ],
    )
    def test_rejects_metric_below_zero(
        self,
        metric_name: str,
    ) -> None:
        kwargs = self._valid_metric_kwargs()
        kwargs[metric_name] = -0.1

        with pytest.raises(
            ValueError,
            match=f"{metric_name} must be between 0.0 and 1.0",
        ):
            RetrievalMetrics(**kwargs)

    @pytest.mark.parametrize(
        "metric_name",
        [
            "hit_rate_at_1",
            "hit_rate_at_3",
            "hit_rate_at_5",
            "recall_at_1",
            "recall_at_3",
            "recall_at_5",
            "mrr",
        ],
    )
    def test_rejects_metric_above_one(
        self,
        metric_name: str,
    ) -> None:
        kwargs = self._valid_metric_kwargs()
        kwargs[metric_name] = 1.1

        with pytest.raises(
            ValueError,
            match=f"{metric_name} must be between 0.0 and 1.0",
        ):
            RetrievalMetrics(**kwargs)

    @pytest.mark.parametrize(
        "invalid_value",
        [
            float("nan"),
            float("inf"),
            float("-inf"),
        ],
    )
    def test_rejects_non_finite_metric_values(
        self,
        invalid_value: float,
    ) -> None:
        kwargs = self._valid_metric_kwargs()
        kwargs["mrr"] = invalid_value

        with pytest.raises(
            ValueError,
            match="mrr must be finite",
        ):
            RetrievalMetrics(**kwargs)

    @pytest.mark.parametrize(
        "invalid_value",
        [
            True,
            False,
            "0.5",
            None,
            object(),
        ],
    )
    def test_rejects_non_numeric_metric_values(
        self,
        invalid_value: object,
    ) -> None:
        kwargs = self._valid_metric_kwargs()
        kwargs["mrr"] = invalid_value

        with pytest.raises(
            TypeError,
            match="mrr must be a numeric value",
        ):
            RetrievalMetrics(**kwargs)

    @staticmethod
    def _valid_metric_kwargs() -> dict[str, object]:
        return {
            "case_count": 1,
            "hit_rate_at_1": 0.5,
            "hit_rate_at_3": 0.5,
            "hit_rate_at_5": 0.5,
            "recall_at_1": 0.5,
            "recall_at_3": 0.5,
            "recall_at_5": 0.5,
            "mrr": 0.5,
        }