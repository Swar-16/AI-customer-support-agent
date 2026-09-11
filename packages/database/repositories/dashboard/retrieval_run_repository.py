# AI-customer-support-agent\packages\database\repositories\dashboard\retrieval_run_repository.py
from __future__ import annotations
import uuid
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from packages.database.models.ai.embedding_call import EmbeddingCallModel
from packages.database.models.ai.reranker_call import RerankerCallModel
from packages.database.models.ai.retrieval_run import RetrievalRunModel

VALID_RETRIEVAL_MODES = frozenset({"vector", "lexical", "hybrid",})
VALID_RETRIEVAL_STATUSES = frozenset({"started", "success", "failed", "timeout",})

@dataclass(frozen=True, slots=True)
class DashboardRetrievalRunRecord:
    id: uuid.UUID
    ai_run_id: uuid.UUID | None
    trace_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    retrieval_mode: str
    profile_identity: str
    query_fingerprint: str
    query_character_count: int
    requested_limit: int
    vector_candidate_count: int
    lexical_candidate_count: int
    fused_candidate_count: int
    reranked_candidate_count: int
    selected_candidate_count: int
    context_block_count: int
    context_token_count: int
    reranker_used: bool
    context_truncated: bool
    zero_result: bool | None
    vector_latency_ms: int | None
    lexical_latency_ms: int | None
    fusion_latency_ms: int | None
    reranker_latency_ms: int | None
    context_build_latency_ms: int | None
    total_latency_ms: int | None
    status: str
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None
    embedding_call_id: uuid.UUID | None
    embedding_provider: str | None
    embedding_model: str | None
    embedding_status: str | None
    embedding_dimensions: int | None
    embedding_latency_ms: int | None
    embedding_error_code: str | None
    reranker_call_count: int
    failed_reranker_call_count: int
    maximum_reranker_call_latency_ms: int | None

class DashboardRetrievalRunRepository:
    """
    Read-only repository for the dashboard retrieval-run explorer.

    It exposes fingerprints, counts, timing and provider status, while excluding raw queries, retrieved chunk content,
    vectors, provider request identifiers, error messages and unrestricted metadata.
    """
    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session instance")

        self._session = session

    def query_retrieval_runs(self, *, started_at: datetime, ended_at: datetime, trace_id: uuid.UUID | None = None, 
                             conversation_id: uuid.UUID | None = None, ai_run_id: uuid.UUID | None = None, retrieval_mode: str | None = None,
                             profile_identity: str | None = None, status: str | None = None, zero_result: bool | None = None, 
                             reranker_used: bool | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[tuple[DashboardRetrievalRunRecord, ...], int,]:
        self._validate_time_range(started_at=started_at, ended_at=ended_at)
        self._validate_pagination(limit=limit, offset=offset)
        for field_name, value in (("trace_id", trace_id), ("conversation_id", conversation_id), ("ai_run_id", ai_run_id),):
            if value is not None:
                self._validate_uuid(value, field_name=field_name)

        normalized_mode = self._normalize_choice(retrieval_mode, field_name="retrieval_mode", valid_values=VALID_RETRIEVAL_MODES)
        normalized_status = self._normalize_choice(status, field_name="status", valid_values=VALID_RETRIEVAL_STATUSES)
        normalized_profile = self._normalize_optional_text(profile_identity, field_name="profile_identity")
        self._validate_optional_bool(zero_result, field_name="zero_result")
        self._validate_optional_bool(reranker_used, field_name="reranker_used")
        reranker_aggregates = (select(RerankerCallModel.retrieval_run_id.label("retrieval_run_id"),
                                      func.count(RerankerCallModel.id).label("reranker_call_count"),
                                      func.sum(case((RerankerCallModel.status.in_(("failed", "timeout")), 1), else_=0,)).label("failed_reranker_call_count"),
                                      func.max(RerankerCallModel.latency_ms).label("maximum_reranker_call_latency_ms"),
            ).group_by(RerankerCallModel.retrieval_run_id)
             .subquery("dashboard_reranker_aggregates")
        )

        statement = (select(RetrievalRunModel.id.label("id"),
                            RetrievalRunModel.ai_run_id.label("ai_run_id"),
                            RetrievalRunModel.trace_id.label("trace_id"),
                            RetrievalRunModel.conversation_id.label("conversation_id"),
                            RetrievalRunModel.retrieval_mode.label("retrieval_mode"),
                            RetrievalRunModel.profile_identity.label("profile_identity"),
                            RetrievalRunModel.query_fingerprint.label("query_fingerprint"),
                            RetrievalRunModel.query_character_count.label("query_character_count"),
                            RetrievalRunModel.requested_limit.label("requested_limit"),
                            RetrievalRunModel.vector_candidate_count.label("vector_candidate_count"),
                            RetrievalRunModel.lexical_candidate_count.label("lexical_candidate_count"),
                            RetrievalRunModel.fused_candidate_count.label("fused_candidate_count"),
                            RetrievalRunModel.reranked_candidate_count.label("reranked_candidate_count"),
                            RetrievalRunModel.selected_candidate_count.label("selected_candidate_count"),
                            RetrievalRunModel.context_block_count.label("context_block_count"),
                            RetrievalRunModel.context_token_count.label("context_token_count"),
                            RetrievalRunModel.reranker_used.label("reranker_used"),
                            RetrievalRunModel.context_truncated.label("context_truncated"),
                            RetrievalRunModel.zero_result.label("zero_result"),
                            RetrievalRunModel.vector_latency_ms.label("vector_latency_ms"),
                            RetrievalRunModel.lexical_latency_ms.label("lexical_latency_ms"),
                            RetrievalRunModel.fusion_latency_ms.label("fusion_latency_ms"),
                            RetrievalRunModel.reranker_latency_ms.label("reranker_latency_ms"),
                            RetrievalRunModel.context_build_latency_ms.label("context_build_latency_ms"),
                            RetrievalRunModel.total_latency_ms.label("total_latency_ms"),
                            RetrievalRunModel.status.label("status"),
                            RetrievalRunModel.error_code.label("error_code"),
                            RetrievalRunModel.started_at.label("started_at"),
                            RetrievalRunModel.completed_at.label("completed_at"),
                            EmbeddingCallModel.id.label("embedding_call_id"),
                            EmbeddingCallModel.provider.label("embedding_provider"),
                            EmbeddingCallModel.model.label("embedding_model"),
                            EmbeddingCallModel.status.label("embedding_status"),
                            EmbeddingCallModel.dimensions.label("embedding_dimensions"),
                            EmbeddingCallModel.latency_ms.label("embedding_latency_ms"),
                            EmbeddingCallModel.error_code.label("embedding_error_code"),
                            func.coalesce(reranker_aggregates.c.reranker_call_count, 0,).label("reranker_call_count"),
                            func.coalesce(reranker_aggregates.c.failed_reranker_call_count, 0,).label("failed_reranker_call_count"),
                            reranker_aggregates.c.maximum_reranker_call_latency_ms.label("maximum_reranker_call_latency_ms")
            ).outerjoin(EmbeddingCallModel, EmbeddingCallModel.id == RetrievalRunModel.embedding_call_id)
             .outerjoin(reranker_aggregates, reranker_aggregates.c.retrieval_run_id == RetrievalRunModel.id)
             .where(RetrievalRunModel.started_at >= started_at, RetrievalRunModel.started_at <= ended_at)
        )

        if trace_id is not None:
            statement = statement.where(RetrievalRunModel.trace_id == trace_id)

        if conversation_id is not None:
            statement = statement.where(RetrievalRunModel.conversation_id == conversation_id)

        if ai_run_id is not None:
            statement = statement.where(RetrievalRunModel.ai_run_id == ai_run_id)

        if normalized_mode is not None:
            statement = statement.where(RetrievalRunModel.retrieval_mode == normalized_mode)

        if normalized_profile is not None:
            statement = statement.where(RetrievalRunModel.profile_identity == normalized_profile)

        if normalized_status is not None:
            statement = statement.where(RetrievalRunModel.status == normalized_status)

        if zero_result is not None:
            statement = statement.where(RetrievalRunModel.zero_result == zero_result)

        if reranker_used is not None:
            statement = statement.where(RetrievalRunModel.reranker_used == reranker_used)

        count_statement = (select(func.count()).select_from(statement.order_by(None).subquery()))
        total = int(self._session.scalar(count_statement) or 0)
        statement = (statement.order_by(RetrievalRunModel.started_at.desc(),
                                        RetrievalRunModel.id.desc())
                              .offset(offset)
                              .limit(limit)
        )

        rows = self._session.execute(statement).all()
        records = tuple(DashboardRetrievalRunRecord(
            id=row.id,
            ai_run_id=row.ai_run_id,
            trace_id=row.trace_id,
            conversation_id=row.conversation_id,
            retrieval_mode=row.retrieval_mode,
            profile_identity=row.profile_identity,
            query_fingerprint=row.query_fingerprint,
            query_character_count=int(row.query_character_count),
            requested_limit=int(row.requested_limit),
            vector_candidate_count=int(row.vector_candidate_count),
            lexical_candidate_count=int(row.lexical_candidate_count),
            fused_candidate_count=int(row.fused_candidate_count),
            reranked_candidate_count=int(row.reranked_candidate_count),
            selected_candidate_count=int(row.selected_candidate_count),
            context_block_count=int(row.context_block_count),
            context_token_count=int(row.context_token_count),
            reranker_used=bool(row.reranker_used),
            context_truncated=bool(row.context_truncated),
            zero_result=row.zero_result,
            vector_latency_ms=self._optional_int(row.vector_latency_ms),
            lexical_latency_ms=self._optional_int(row.lexical_latency_ms),
            fusion_latency_ms=self._optional_int(row.fusion_latency_ms),
            reranker_latency_ms=self._optional_int(row.reranker_latency_ms),
            context_build_latency_ms=self._optional_int(row.context_build_latency_ms),
            total_latency_ms=self._optional_int(row.total_latency_ms),
            status=row.status,
            error_code=row.error_code,
            started_at=row.started_at,
            completed_at=row.completed_at,
            embedding_call_id=row.embedding_call_id,
            embedding_provider=row.embedding_provider,
            embedding_model=row.embedding_model,
            embedding_status=row.embedding_status,
            embedding_dimensions=self._optional_int(row.embedding_dimensions),
            embedding_latency_ms=self._optional_int(row.embedding_latency_ms),
            embedding_error_code=(row.embedding_error_code),
            reranker_call_count=int(row.reranker_call_count),
            failed_reranker_call_count=int(row.failed_reranker_call_count),
            maximum_reranker_call_latency_ms=self._optional_int(row.maximum_reranker_call_latency_ms),
            )
            for row in rows
        )

        return records, total

    @staticmethod
    def _optional_int(value: int | None) -> int | None:
        return int(value) if value is not None else None

    @staticmethod
    def _validate_uuid(value: uuid.UUID, *, field_name: str) -> None:
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be a UUID")

    @staticmethod
    def _validate_optional_bool(value: bool | None, *, field_name: str) -> None:
        if value is not None and not isinstance(value, bool):
            raise TypeError(f"{field_name} must be a boolean or None")

    @staticmethod
    def _validate_time_range(*, started_at: datetime, ended_at: datetime) -> None:
        for field_name, value in (("started_at", started_at), ("ended_at", ended_at),):
            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime")

            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")

        if started_at > ended_at:
            raise ValueError("started_at cannot be later than ended_at")

    @staticmethod
    def _validate_pagination(*, limit: int, offset: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if limit > 500:
            raise ValueError("limit must not exceed 500")

        if offset < 0:
            raise ValueError("offset must not be negative")

    @staticmethod
    def _normalize_optional_text(value: str | None, *, field_name: str) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or None")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        return normalized

    @classmethod
    def _normalize_choice(cls, value: str | None, *, field_name: str, valid_values: frozenset[str]) -> str | None:
        normalized = cls._normalize_optional_text(value, field_name=field_name)
        if normalized is None:
            return None

        normalized = normalized.lower()
        if normalized not in valid_values:
            expected = ", ".join(sorted(valid_values))
            raise ValueError(f"{field_name} must be one of: {expected}")

        return normalized