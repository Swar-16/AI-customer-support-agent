from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

from evaluation.retrieval.models import RetrievalEvaluationCase, RetrievalEvaluationHit, RetrievalEvaluationResult
from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalResult


class RetrievalEvaluationError(Exception):
    """
    Base error for retrieval evaluation failures.
    """

class RetrievalEvaluationConfigurationError(RetrievalEvaluationError):
    """
    Raised when the evaluator is constructed with invalid dependencies or configuration.
    """

class RetrievalEvaluationExecutionError(RetrievalEvaluationError):
    """
    Raised when retrieval execution fails during evaluation.
    """

class RetrievalEvaluationContractError(RetrievalEvaluationError):
    """
    Raised when a runner or matcher violates the evaluation contract.
    """

@runtime_checkable
class RetrievalEvaluationRunner(Protocol):
    """
    Adapter responsible for executing one retrieval strategy.

    Implementations may internally use lexical retrieval, vector retrieval, hybrid retrieval, reranking, or any future strategy.

    The evaluator deliberately does not know how retrieval works.
    """
    @property
    def method(self) -> str:
        """
        Stable identifier used in evaluation reports.

        Examples:
            lexical
            vector
            hybrid
            hybrid_reranked
        """
        ...

    def retrieve(self, *, case: RetrievalEvaluationCase) -> RetrievalResult:
        """
        Execute retrieval for one benchmark case.
        """
        ...


@runtime_checkable
class RetrievalRelevanceMatcher(Protocol):
    """
    Determines which ground-truth relevance targets a retrieved candidate satisfies.

    Relevance matching is intentionally separate from retrieval execution so benchmark semantics remain explicit and testable.
    """
    def match(self, *, case: RetrievalEvaluationCase, candidate: RetrievalCandidate) -> frozenset[str]:
        """
        Return the exact relevance target IDs satisfied by candidate.

        Returned IDs must be a subset of:
            case.relevance_target_ids
        """
        ...


@dataclass(frozen=True, slots=True)
class RetrievalEvaluator:
    """
    Converts production retrieval results into benchmark evaluation results.

    Responsibilities:
        - execute the supplied retrieval runner;
        - validate runner output;
        - evaluate every returned candidate using the supplied relevance matcher;
        - preserve retrieval ordering;
        - produce RetrievalEvaluationResult objects.
    """
    runner: RetrievalEvaluationRunner
    relevance_matcher: RetrievalRelevanceMatcher

    def __post_init__(self) -> None:
        if not isinstance(self.runner, RetrievalEvaluationRunner):
            raise RetrievalEvaluationConfigurationError("runner must implement RetrievalEvaluationRunner.")

        if not isinstance(self.relevance_matcher, RetrievalRelevanceMatcher):
            raise RetrievalEvaluationConfigurationError("relevance_matcher must implement RetrievalRelevanceMatcher.")

        self._validate_method(self.runner.method)

    def evaluate_case(self, *, case: RetrievalEvaluationCase) -> RetrievalEvaluationResult:
        """
        Evaluate one retrieval benchmark case.
        """
        self._validate_case(case)
        method = self._validate_method(self.runner.method)

        try:
            retrieval_result = self.runner.retrieve(case=case)
            
        except RetrievalEvaluationError:
            raise
        
        except Exception as exc:
            raise RetrievalEvaluationExecutionError(f"Retrieval runner failed while evaluating case '{case.case_id}' with method '{method}'.") from exc

        self._validate_retrieval_result(retrieval_result)
        hits = self._build_hits(case=case, retrieval_result=retrieval_result)

        return RetrievalEvaluationResult(
            case_id=case.case_id,
            method=method,
            relevance_target_ids=case.relevance_target_ids,
            hits=hits,
        )

    def evaluate(self, *, cases: Iterable[RetrievalEvaluationCase]) -> tuple[RetrievalEvaluationResult, ...]:
        """
        Evaluate multiple benchmark cases while preserving input order.

        The iterable is consumed exactly once, so generators are safe.
        """
        normalized_cases = self._materialize_cases(cases)
        results: list[RetrievalEvaluationResult] = []
        for case in normalized_cases:
            results.append(self.evaluate_case(case=case))

        return tuple(results)

    def _build_hits(self, *, case: RetrievalEvaluationCase, retrieval_result: RetrievalResult) -> tuple[RetrievalEvaluationHit, ...]:
        hits: list[RetrievalEvaluationHit] = []
        seen_chunk_ids: set[str] = set()

        for rank, candidate in enumerate(retrieval_result.candidates, start=1):
            self._validate_candidate(candidate)
            chunk_id = str(candidate.chunk_id).strip()
            if not chunk_id:
                raise RetrievalEvaluationContractError("Retrieved candidate contains an empty chunk ID.")

            if chunk_id in seen_chunk_ids:
                raise RetrievalEvaluationContractError("Retrieval result contains duplicate chunk IDs.")

            matched_target_ids = self._match_candidate(case=case, candidate=candidate)
            hits.append(
                RetrievalEvaluationHit(
                    rank=rank,
                    document_title=candidate.document_title,
                    section_title=candidate.section_title,
                    chunk_id=chunk_id,
                    matched_target_ids=matched_target_ids,
                )
            )

            seen_chunk_ids.add(chunk_id)

        return tuple(hits)

    def _match_candidate(self, *, case: RetrievalEvaluationCase, candidate: RetrievalCandidate) -> frozenset[str]:
        try:
            matched_target_ids = self.relevance_matcher.match(case=case, candidate=candidate)
            
        except RetrievalEvaluationError:
            raise
        
        except Exception as exc:
            raise RetrievalEvaluationExecutionError(
                f"Relevance matcher failed while evaluating case '{case.case_id}' for chunk '{candidate.chunk_id}'."
            ) from exc

        if not isinstance(matched_target_ids, frozenset):
            raise RetrievalEvaluationContractError("Relevance matcher must return a frozenset.")

        normalized_targets: set[str] = set()
        for target_id in matched_target_ids:
            if not isinstance(target_id, str):
                raise RetrievalEvaluationContractError("Relevance matcher returned a non-string target ID.")

            normalized_target = target_id.strip()
            if not normalized_target:
                raise RetrievalEvaluationContractError("Relevance matcher returned an empty target ID.")

            normalized_targets.add(normalized_target)

        normalized_target_ids = frozenset(normalized_targets)
        unknown_targets = (normalized_target_ids - case.relevance_target_ids)
        if unknown_targets:
            formatted = ", ".join(sorted(unknown_targets))
            raise RetrievalEvaluationContractError(f"Relevance matcher returned target IDs that are not part of the case ground truth: {formatted}.")

        return normalized_target_ids

    @staticmethod
    def _validate_case(case: RetrievalEvaluationCase) -> None:
        if not isinstance(case, RetrievalEvaluationCase):
            raise TypeError("case must be a RetrievalEvaluationCase instance.")

    @staticmethod
    def _validate_method(method: object) -> str:
        if not isinstance(method, str):
            raise RetrievalEvaluationConfigurationError("runner.method must be a string.")

        normalized = method.strip()
        if not normalized:
            raise RetrievalEvaluationConfigurationError("runner.method must not be empty.")

        return normalized

    @staticmethod
    def _validate_retrieval_result(result: object) -> None:
        if not isinstance(result, RetrievalResult):
            raise RetrievalEvaluationContractError("Retrieval runner must return a RetrievalResult instance.")

    @staticmethod
    def _validate_candidate(candidate: object) -> None:
        if not isinstance(candidate, RetrievalCandidate):
            raise RetrievalEvaluationContractError("RetrievalResult candidates must contain RetrievalCandidate instances.")

    @staticmethod
    def _materialize_cases(cases: Iterable[RetrievalEvaluationCase]) -> tuple[RetrievalEvaluationCase, ...]:
        if isinstance(cases, (str, bytes)):
            raise TypeError("cases must be an iterable of RetrievalEvaluationCase instances.")

        try:
            materialized = tuple(cases)
            
        except TypeError as exc:
            raise TypeError("cases must be an iterable of RetrievalEvaluationCase instances.") from exc

        for case in materialized:
            RetrievalEvaluator._validate_case(case)

        return materialized