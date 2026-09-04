from __future__ import annotations

from dataclasses import dataclass
from uuid6 import uuid7

import pytest

from evaluation.retrieval.evaluator import (
    RetrievalEvaluationConfigurationError,
    RetrievalEvaluationContractError,
    RetrievalEvaluationExecutionError,
    RetrievalEvaluationRunner,
    RetrievalEvaluator,
    RetrievalRelevanceMatcher,
)
from evaluation.retrieval.models import (
    RetrievalEvaluationCase,
)
from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalMethod,
    RetrievalQuery,
    RetrievalResult,
    RetrievalScores,
)


def make_candidate(
    *,
    document_title: str = "Refund Policy",
    section_title: str | None = "Processing Time",
    chunk_id=None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id or uuid7(),
        document_id=uuid7(),
        version_id=uuid7(),
        chunk_index=0,
        content="Refunds may take several business days.",
        document_title=document_title,
        section_title=section_title,
        methods=frozenset(
            {
                RetrievalMethod.HYBRID,
            }
        ),
        scores=RetrievalScores(
            fusion_score=0.75,
        ),
        metadata={},
    )


def make_case() -> RetrievalEvaluationCase:
    return RetrievalEvaluationCase(
        case_id="refund_delay_001",
        query="How long does a refund take?",
        intent_key="refund_request",
        expected_document_titles=(
            "Refund Policy",
        ),
        expected_section_titles=(
            "Processing Time",
        ),
    )


def make_retrieval_result(
    candidates: tuple[
        RetrievalCandidate,
        ...
    ],
) -> RetrievalResult:
    return RetrievalResult(
        query=RetrievalQuery(
            text="How long does a refund take?",
        ),
        candidates=candidates,
    )


@dataclass
class FakeRunner:
    result: RetrievalResult
    method_value: str = "hybrid"

    @property
    def method(self) -> str:
        return self.method_value

    def retrieve(
        self,
        *,
        case: RetrievalEvaluationCase,
    ) -> RetrievalResult:
        return self.result


@dataclass
class RecordingRunner:
    result: RetrievalResult
    method_value: str = "hybrid"

    def __post_init__(self) -> None:
        self.calls: list[
            RetrievalEvaluationCase
        ] = []

    @property
    def method(self) -> str:
        return self.method_value

    def retrieve(
        self,
        *,
        case: RetrievalEvaluationCase,
    ) -> RetrievalResult:
        self.calls.append(case)
        return self.result


class RaisingRunner:
    @property
    def method(self) -> str:
        return "hybrid"

    def retrieve(
        self,
        *,
        case: RetrievalEvaluationCase,
    ) -> RetrievalResult:
        raise RuntimeError(
            "database unavailable"
        )


class InvalidResultRunner:
    @property
    def method(self) -> str:
        return "hybrid"

    def retrieve(
        self,
        *,
        case: RetrievalEvaluationCase,
    ):
        return object()


@dataclass
class FakeMatcher:
    matched_targets: frozenset[str]

    def match(
        self,
        *,
        case: RetrievalEvaluationCase,
        candidate: RetrievalCandidate,
    ) -> frozenset[str]:
        return self.matched_targets


class RecordingMatcher:
    def __init__(
        self,
        *,
        match_by_chunk_id: dict[
            str,
            frozenset[str],
        ],
    ) -> None:
        self.match_by_chunk_id = (
            match_by_chunk_id
        )
        self.calls: list[
            tuple[
                RetrievalEvaluationCase,
                RetrievalCandidate,
            ]
        ] = []

    def match(
        self,
        *,
        case: RetrievalEvaluationCase,
        candidate: RetrievalCandidate,
    ) -> frozenset[str]:
        self.calls.append(
            (
                case,
                candidate,
            )
        )

        return self.match_by_chunk_id.get(
            str(candidate.chunk_id),
            frozenset(),
        )


class RaisingMatcher:
    def match(
        self,
        *,
        case: RetrievalEvaluationCase,
        candidate: RetrievalCandidate,
    ) -> frozenset[str]:
        raise RuntimeError(
            "matcher failed"
        )


class InvalidMatcherResult:
    def match(
        self,
        *,
        case: RetrievalEvaluationCase,
        candidate: RetrievalCandidate,
    ):
        return {
            "document:refund policy",
        }


class UnknownTargetMatcher:
    def match(
        self,
        *,
        case: RetrievalEvaluationCase,
        candidate: RetrievalCandidate,
    ) -> frozenset[str]:
        return frozenset(
            {
                "document:shipping policy",
            }
        )


class TestEvaluatorConstruction:
    def test_accepts_valid_dependencies(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    ()
                )
            ),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        assert isinstance(
            evaluator.runner,
            RetrievalEvaluationRunner,
        )

        assert isinstance(
            evaluator.relevance_matcher,
            RetrievalRelevanceMatcher,
        )

    def test_rejects_invalid_runner(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalEvaluationConfigurationError,
            match=(
                "runner must implement "
                "RetrievalEvaluationRunner"
            ),
        ):
            RetrievalEvaluator(
                runner=object(),  # type: ignore[arg-type]
                relevance_matcher=FakeMatcher(
                    matched_targets=frozenset()
                ),
            )

    def test_rejects_invalid_matcher(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalEvaluationConfigurationError,
            match=(
                "relevance_matcher must implement "
                "RetrievalRelevanceMatcher"
            ),
        ):
            RetrievalEvaluator(
                runner=FakeRunner(
                    result=make_retrieval_result(
                        ()
                    )
                ),
                relevance_matcher=object(),  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "invalid_method",
        [
            "",
            "   ",
        ],
    )
    def test_rejects_empty_method(
        self,
        invalid_method: str,
    ) -> None:
        with pytest.raises(
            RetrievalEvaluationConfigurationError,
            match="runner.method must not be empty",
        ):
            RetrievalEvaluator(
                runner=FakeRunner(
                    result=make_retrieval_result(
                        ()
                    ),
                    method_value=invalid_method,
                ),
                relevance_matcher=FakeMatcher(
                    matched_targets=frozenset()
                ),
            )


class TestEvaluateCase:
    def test_builds_evaluation_result(
        self,
    ) -> None:
        candidate = make_candidate()

        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    (
                        candidate,
                    )
                )
            ),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset(
                    {
                        "document:refund policy",
                        "section:processing time",
                    }
                )
            ),
        )

        result = evaluator.evaluate_case(
            case=make_case()
        )

        assert result.case_id == (
            "refund_delay_001"
        )
        assert result.method == "hybrid"

        assert (
            result.relevance_target_ids
            == frozenset(
                {
                    "document:refund policy",
                    "section:processing time",
                }
            )
        )

        assert len(result.hits) == 1

        hit = result.hits[0]

        assert hit.rank == 1
        assert hit.chunk_id == str(
            candidate.chunk_id
        )
        assert hit.document_title == (
            "Refund Policy"
        )
        assert hit.section_title == (
            "Processing Time"
        )

        assert (
            hit.matched_target_ids
            == frozenset(
                {
                    "document:refund policy",
                    "section:processing time",
                }
            )
        )

        assert hit.relevant is True

    def test_preserves_retrieval_order(
        self,
    ) -> None:
        first = make_candidate(
            document_title="Refund Policy",
        )
        second = make_candidate(
            document_title="Shipping Policy",
        )

        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    (
                        first,
                        second,
                    )
                )
            ),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        result = evaluator.evaluate_case(
            case=make_case()
        )

        assert [
            hit.chunk_id
            for hit in result.hits
        ] == [
            str(first.chunk_id),
            str(second.chunk_id),
        ]

        assert [
            hit.rank
            for hit in result.hits
        ] == [
            1,
            2,
        ]

    def test_evaluates_every_candidate(
        self,
    ) -> None:
        first = make_candidate()
        second = make_candidate()

        matcher = RecordingMatcher(
            match_by_chunk_id={
                str(first.chunk_id): frozenset(
                    {
                        "document:refund policy",
                    }
                ),
                str(second.chunk_id): frozenset(),
            }
        )

        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    (
                        first,
                        second,
                    )
                )
            ),
            relevance_matcher=matcher,
        )

        evaluator.evaluate_case(
            case=make_case()
        )

        assert len(
            matcher.calls
        ) == 2

        assert matcher.calls[0][1] is first
        assert matcher.calls[1][1] is second

    def test_allows_empty_retrieval_result(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    ()
                )
            ),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        result = evaluator.evaluate_case(
            case=make_case()
        )

        assert result.hits == ()

    def test_rejects_invalid_case(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    ()
                )
            ),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        with pytest.raises(
            TypeError,
            match=(
                "case must be a "
                "RetrievalEvaluationCase instance"
            ),
        ):
            evaluator.evaluate_case(
                case=object()  # type: ignore[arg-type]
            )


class TestRunnerFailures:
    def test_wraps_unexpected_runner_failure(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=RaisingRunner(),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        with pytest.raises(
            RetrievalEvaluationExecutionError,
            match=(
                "Retrieval runner failed while "
                "evaluating case"
            ),
        ) as exc_info:
            evaluator.evaluate_case(
                case=make_case()
            )

        assert isinstance(
            exc_info.value.__cause__,
            RuntimeError,
        )

    def test_rejects_invalid_runner_result(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=InvalidResultRunner(),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        with pytest.raises(
            RetrievalEvaluationContractError,
            match=(
                "Retrieval runner must return a "
                "RetrievalResult instance"
            ),
        ):
            evaluator.evaluate_case(
                case=make_case()
            )


class TestMatcherFailures:
    def test_wraps_unexpected_matcher_failure(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    (
                        make_candidate(),
                    )
                )
            ),
            relevance_matcher=RaisingMatcher(),
        )

        with pytest.raises(
            RetrievalEvaluationExecutionError,
            match=(
                "Relevance matcher failed while "
                "evaluating case"
            ),
        ) as exc_info:
            evaluator.evaluate_case(
                case=make_case()
            )

        assert isinstance(
            exc_info.value.__cause__,
            RuntimeError,
        )

    def test_rejects_non_frozenset_match_result(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    (
                        make_candidate(),
                    )
                )
            ),
            relevance_matcher=InvalidMatcherResult(),
        )

        with pytest.raises(
            RetrievalEvaluationContractError,
            match=(
                "Relevance matcher must return "
                "a frozenset"
            ),
        ):
            evaluator.evaluate_case(
                case=make_case()
            )

    def test_rejects_unknown_relevance_target(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    (
                        make_candidate(),
                    )
                )
            ),
            relevance_matcher=UnknownTargetMatcher(),
        )

        with pytest.raises(
            RetrievalEvaluationContractError,
            match=(
                "Relevance matcher returned "
                "target IDs that are not part "
                "of the case ground truth"
            ),
        ):
            evaluator.evaluate_case(
                case=make_case()
            )


class TestEvaluatePopulation:
    def test_evaluates_cases_in_input_order(
        self,
    ) -> None:
        runner = RecordingRunner(
            result=make_retrieval_result(
                ()
            )
        )

        evaluator = RetrievalEvaluator(
            runner=runner,
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        first = RetrievalEvaluationCase(
            case_id="case_1",
            query="First query",
            expected_document_titles=(
                "Document",
            ),
        )

        second = RetrievalEvaluationCase(
            case_id="case_2",
            query="Second query",
            expected_document_titles=(
                "Document",
            ),
        )

        results = evaluator.evaluate(
            cases=(
                first,
                second,
            )
        )

        assert [
            result.case_id
            for result in results
        ] == [
            "case_1",
            "case_2",
        ]

        assert runner.calls == [
            first,
            second,
        ]

    def test_accepts_generator(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    ()
                )
            ),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        cases = (
            RetrievalEvaluationCase(
                case_id=f"case_{index}",
                query=f"Query {index}",
                expected_document_titles=(
                    "Document",
                ),
            )
            for index in range(3)
        )

        results = evaluator.evaluate(
            cases=cases
        )

        assert len(results) == 3

    def test_empty_population_returns_empty_tuple(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    ()
                )
            ),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        assert evaluator.evaluate(
            cases=()
        ) == ()

    def test_rejects_non_iterable_population(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    ()
                )
            ),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        with pytest.raises(
            TypeError,
            match=(
                "cases must be an iterable of "
                "RetrievalEvaluationCase instances"
            ),
        ):
            evaluator.evaluate(
                cases=123  # type: ignore[arg-type]
            )

    def test_rejects_string_population(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    ()
                )
            ),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        with pytest.raises(
            TypeError,
            match=(
                "cases must be an iterable of "
                "RetrievalEvaluationCase instances"
            ),
        ):
            evaluator.evaluate(
                cases="invalid"  # type: ignore[arg-type]
            )

    def test_rejects_invalid_case_inside_population(
        self,
    ) -> None:
        evaluator = RetrievalEvaluator(
            runner=FakeRunner(
                result=make_retrieval_result(
                    ()
                )
            ),
            relevance_matcher=FakeMatcher(
                matched_targets=frozenset()
            ),
        )

        with pytest.raises(
            TypeError,
            match=(
                "case must be a "
                "RetrievalEvaluationCase instance"
            ),
        ):
            evaluator.evaluate(
                cases=(
                    make_case(),
                    object(),  # type: ignore[arg-type]
                )
            )