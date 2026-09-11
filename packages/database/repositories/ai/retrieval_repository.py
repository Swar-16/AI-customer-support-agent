# AI-customer-support-agent\packages\database\repositories\ai\retrieval_repository.py
from __future__ import annotations
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.ai.retrieval_candidate import RetrievalCandidateModel
from packages.database.models.ai.retrieval_run import RetrievalRunModel


class RetrievalRepository:
    """
    Persistence adapter for retrieval runs and candidate provenance.

    Retrieval-run lifecycle fields may be updated. Candidate records are append-only. The repository never commits.
    """
    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Writes
    def add_run(self, run: RetrievalRunModel) -> None:
        self._validate_run(run)
        self._session.add(run)

    def add_candidate(self, candidate: RetrievalCandidateModel) -> None:
        self._validate_candidate(candidate)
        self._session.add(candidate)

    def add_candidates(self, candidates: Iterable[RetrievalCandidateModel]) -> None:
        if isinstance(candidates, RetrievalCandidateModel):
            raise TypeError("candidates must be an iterable")

        try:
            records = tuple(candidates)
            
        except TypeError as exc:
            raise TypeError("candidates must be an iterable") from exc

        for candidate in records:
            self._validate_candidate(candidate)

        self._session.add_all(records)

    def flush(self) -> None:
        self._session.flush()

    # Lookups
    def get_run_by_id(self, retrieval_run_id: uuid.UUID) -> RetrievalRunModel | None:
        self._validate_uuid(retrieval_run_id, field_name="retrieval_run_id")
        statement = (select(RetrievalRunModel)
                     .where(RetrievalRunModel.id == retrieval_run_id)
        )

        return self._session.scalar(statement)

    def list_candidates(self, retrieval_run_id: uuid.UUID, *, selected_only: bool = False, limit: int = 500) -> Sequence[RetrievalCandidateModel]:
        self._validate_uuid(retrieval_run_id, field_name="retrieval_run_id")
        self._validate_limit(limit)
        if not isinstance(selected_only, bool):
            raise TypeError("selected_only must be a boolean")

        statement = select(RetrievalCandidateModel).where(RetrievalCandidateModel.retrieval_run_id == retrieval_run_id)
        if selected_only:
            statement = statement.where(RetrievalCandidateModel.selected_for_context.is_(True))

        statement = (statement.order_by(RetrievalCandidateModel.final_rank.asc().nulls_last(),
                                        RetrievalCandidateModel.id.asc())
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_for_ai_run(self, ai_run_id: uuid.UUID, *, limit: int = 100) -> Sequence[RetrievalRunModel]:
        self._validate_uuid(ai_run_id, field_name="ai_run_id")
        self._validate_limit(limit)
        statement = (select(RetrievalRunModel)
                     .where(RetrievalRunModel.ai_run_id == ai_run_id)
                     .order_by(RetrievalRunModel.started_at.asc(),
                               RetrievalRunModel.id.asc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_for_trace(self, trace_id: uuid.UUID, *, limit: int = 100) -> Sequence[RetrievalRunModel]:
        self._validate_uuid(trace_id, field_name="trace_id")
        self._validate_limit(limit)
        statement = (select(RetrievalRunModel)
                     .where(RetrievalRunModel.trace_id == trace_id)
                     .order_by(RetrievalRunModel.started_at.asc(),
                               RetrievalRunModel.id.asc())
                     .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def list_recent(self, *, status: str | None = None, retrieval_mode: str | None = None, zero_result: bool | None = None, 
                    profile_identity: str | None = None, started_from: datetime | None = None, started_to: datetime | None = None, 
                    limit: int = 100, offset: int = 0) -> Sequence[RetrievalRunModel]:
        self._validate_pagination(limit=limit, offset=offset)
        normalized_status = self._normalize_optional_choice(
            status,
            field_name="status",
            valid_values={"started", "success", "failed", "timeout",},
        )
        normalized_mode = self._normalize_optional_choice(
            retrieval_mode,
            field_name="retrieval_mode",
            valid_values={"vector", "lexical", "hybrid",},
        )
        normalized_profile = self._normalize_optional_text(profile_identity, field_name="profile_identity", uppercase=False)
        if zero_result is not None and not isinstance(zero_result, bool):
            raise TypeError("zero_result must be a boolean or None")

        self._validate_datetime_range(started_from=started_from, started_to=started_to)
        statement = select(RetrievalRunModel)
        if normalized_status is not None:
            statement = statement.where(RetrievalRunModel.status == normalized_status)

        if normalized_mode is not None:
            statement = statement.where(RetrievalRunModel.retrieval_mode == normalized_mode)

        if zero_result is not None:
            statement = statement.where(RetrievalRunModel.zero_result == zero_result)

        if normalized_profile is not None:
            statement = statement.where(RetrievalRunModel.profile_identity == normalized_profile)

        if started_from is not None:
            statement = statement.where(RetrievalRunModel.started_at >= started_from)

        if started_to is not None:
            statement = statement.where(RetrievalRunModel.started_at <= started_to)

        statement = (statement.order_by(RetrievalRunModel.started_at.desc(),
                                        RetrievalRunModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    # Lifecycle updates
    def mark_succeeded(self, run: RetrievalRunModel, *, completed_at: datetime, total_latency_ms: int, vector_candidate_count: int,
                       lexical_candidate_count: int, fused_candidate_count: int, reranked_candidate_count: int, selected_candidate_count: int,
                       context_block_count: int, context_token_count: int, reranker_used: bool, context_truncated: bool, vector_latency_ms: int | None = None,
                       lexical_latency_ms: int | None = None, fusion_latency_ms: int | None = None, reranker_latency_ms: int | None = None, context_build_latency_ms: int | None = None,
    ) -> None:
        self._validate_run(run)
        self._validate_completion(completed_at=completed_at, total_latency_ms=total_latency_ms)
        counts = {
            "vector_candidate_count": vector_candidate_count,
            "lexical_candidate_count": lexical_candidate_count,
            "fused_candidate_count": fused_candidate_count,
            "reranked_candidate_count": reranked_candidate_count,
            "selected_candidate_count": selected_candidate_count,
            "context_block_count": context_block_count,
            "context_token_count": context_token_count,
        }

        for field_name, value in counts.items():
            self._validate_non_negative_integer(value, field_name=field_name)

        for field_name, value in (
            ("vector_latency_ms", vector_latency_ms), ("lexical_latency_ms", lexical_latency_ms), ("fusion_latency_ms", fusion_latency_ms),
            ("reranker_latency_ms", reranker_latency_ms), ("context_build_latency_ms", context_build_latency_ms,),
        ):
            if value is not None:
                self._validate_non_negative_integer(value, field_name=field_name)

        if not isinstance(reranker_used, bool):
            raise TypeError("reranker_used must be a boolean")

        if not isinstance(context_truncated, bool):
            raise TypeError("context_truncated must be a boolean")

        run.status = "success"
        run.vector_candidate_count = vector_candidate_count
        run.lexical_candidate_count = lexical_candidate_count
        run.fused_candidate_count = fused_candidate_count
        run.reranked_candidate_count = reranked_candidate_count
        run.selected_candidate_count = selected_candidate_count
        run.context_block_count = context_block_count
        run.context_token_count = context_token_count
        run.reranker_used = reranker_used
        run.context_truncated = context_truncated
        run.zero_result = selected_candidate_count == 0
        run.vector_latency_ms = vector_latency_ms
        run.lexical_latency_ms = lexical_latency_ms
        run.fusion_latency_ms = fusion_latency_ms
        run.reranker_latency_ms = reranker_latency_ms
        run.context_build_latency_ms = context_build_latency_ms
        run.total_latency_ms = total_latency_ms
        run.error_code = None
        run.error_message = None
        run.completed_at = completed_at

    def mark_failed(self, run: RetrievalRunModel, *, completed_at: datetime, total_latency_ms: int, error_code: str, error_message: str, timeout: bool = False) -> None:
        self._validate_run(run)
        self._validate_completion(completed_at=completed_at, total_latency_ms=total_latency_ms)
        if not isinstance(timeout, bool):
            raise TypeError("timeout must be a boolean")

        run.status = "timeout" if timeout else "failed"
        run.total_latency_ms = total_latency_ms
        run.zero_result = None
        run.error_code = self._normalize_required_text(error_code, field_name="error_code", uppercase=True)
        run.error_message = self._normalize_required_text(error_message, field_name="error_message", uppercase=False)
        run.completed_at = completed_at

    # Validation helpers
    @staticmethod
    def _validate_run(run: RetrievalRunModel) -> None:
        if not isinstance(run, RetrievalRunModel):
            raise TypeError("run must be a RetrievalRunModel")

    @staticmethod
    def _validate_candidate(candidate: RetrievalCandidateModel) -> None:
        if not isinstance(candidate, RetrievalCandidateModel):
            raise TypeError("candidate must be a RetrievalCandidateModel")

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_non_negative_integer(value: int, *, field_name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")

        if value < 0:
            raise ValueError(f"{field_name} cannot be negative")

    @classmethod
    def _validate_completion(cls, *, completed_at: datetime, total_latency_ms: int) -> None:
        if not isinstance(completed_at, datetime):
            raise TypeError("completed_at must be a datetime")

        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")

        cls._validate_non_negative_integer(total_latency_ms, field_name="total_latency_ms")

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str, uppercase: bool) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        return normalized.upper() if uppercase else normalized

    @classmethod
    def _normalize_optional_text(cls, value: str | None, *, field_name: str, uppercase: bool) -> str | None:
        if value is None:
            return None

        return cls._normalize_required_text(value, field_name=field_name, uppercase=uppercase)

    @staticmethod
    def _normalize_optional_choice(value: str | None, *, field_name: str, valid_values: set[str]) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip().lower()
        if normalized not in valid_values:
            expected = ", ".join(sorted(valid_values))
            raise ValueError(f"{field_name} must be one of: {expected}")

        return normalized

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0 or limit > 1_000:
            raise ValueError("limit must be between 1 and 1000")

    @classmethod
    def _validate_pagination(cls, *, limit: int, offset: int) -> None:
        cls._validate_limit(limit)

        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")

        if offset < 0:
            raise ValueError("offset cannot be negative")

    @staticmethod
    def _validate_datetime_range(*, started_from: datetime | None, started_to: datetime | None) -> None:
        for field_name, value in (("started_from", started_from), ("started_to", started_to),):
            if value is None:
                continue

            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime or None")

            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")

        if started_from is not None and started_to is not None and started_from > started_to:
            raise ValueError("started_from cannot be later than started_to")