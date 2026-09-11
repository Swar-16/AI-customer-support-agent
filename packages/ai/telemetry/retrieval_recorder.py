# AI-customer-support-agent\packages\ai\telemetry\retrieval_recorder.py
from __future__ import annotations
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid6 import uuid7

from packages.database.models.ai.retrieval_candidate import RetrievalCandidateModel
from packages.database.models.ai.retrieval_run import RetrievalRunModel
from packages.database.repositories.ai.retrieval_repository import RetrievalRepository
from packages.knowledge.retrieval.context.models import GroundingContext
from packages.knowledge.retrieval.models import RetrievalCandidate
from packages.knowledge.retrieval.profiles import RetrievalProfile
from packages.knowledge.retrieval.query.models import PreparedRetrievalQuery


@dataclass(slots=True)
class _CandidateTelemetry:
    candidate: RetrievalCandidate
    vector_rank: int | None = None
    lexical_rank: int | None = None
    fusion_rank: int | None = None
    reranker_rank: int | None = None
    final_rank: int | None = None

class RetrievalTelemetryRecorder:
    """
    Request-scoped retrieval telemetry accumulator.

    It stores identifiers, ranks, scores, counts, fingerprints, and latency. It never stores query text or retrieved chunk content.

    The recorder does not commit. Its repository must belong to the active customer-message Unit of Work.
    """
    def __init__(self, *, repository: RetrievalRepository, ai_run_id: uuid.UUID | None = None, trace_id: uuid.UUID | None = None, 
                 conversation_id: uuid.UUID | None = None, profile: RetrievalProfile) -> None:
        if not isinstance(repository, RetrievalRepository):
            raise TypeError("repository must be a RetrievalRepository")

        for field_name, value in (("ai_run_id", ai_run_id), ("trace_id", trace_id), ("conversation_id", conversation_id),):
            if value is not None and not isinstance(value, uuid.UUID):
                raise TypeError(f"{field_name} must be a UUID or None")

        if not isinstance(profile, RetrievalProfile):
            raise TypeError("profile must be a RetrievalProfile")

        self._repository = repository
        self._ai_run_id = ai_run_id
        self._trace_id = trace_id
        self._conversation_id = conversation_id
        self._profile = profile
        self._run: RetrievalRunModel | None = None
        self._candidates: dict[uuid.UUID, _CandidateTelemetry] = {}
        self._vector_count = 0
        self._lexical_count = 0
        self._fused_count = 0
        self._reranked_count = 0
        self._vector_latency_ms: int | None = None
        self._lexical_latency_ms: int | None = None
        self._fusion_latency_ms: int | None = None
        self._reranker_latency_ms: int | None = None

    @property
    def retrieval_run_id(self) -> uuid.UUID | None:
        return self._run.id if self._run is not None else None

    def start(self, *, prepared_query: PreparedRetrievalQuery, started_at: datetime) -> uuid.UUID:
        if self._run is not None:
            raise RuntimeError("Retrieval telemetry has already started")

        if not isinstance(prepared_query, PreparedRetrievalQuery):
            raise TypeError("prepared_query must be a PreparedRetrievalQuery")

        self._validate_datetime(started_at, field_name="started_at")
        query = prepared_query.original_query
        run = RetrievalRunModel(
            id=uuid7(), ai_run_id=self._ai_run_id, embedding_call_id=None, trace_id=self._trace_id, conversation_id=self._conversation_id,
            retrieval_mode=self._retrieval_mode(), profile_identity=self._profile.identity, configuration_fingerprint=self._profile.config_fingerprint,
            query_fingerprint=self._fingerprint(query), query_character_count=len(query), requested_limit=self._profile.final_candidate_limit,
            vector_candidate_count=0, lexical_candidate_count=0, fused_candidate_count=0, reranked_candidate_count=0, selected_candidate_count=0,
            context_block_count=0, context_token_count=0, reranker_used=self._profile.reranking_enabled, context_truncated=False, 
            zero_result=None, vector_latency_ms=None, lexical_latency_ms=None, fusion_latency_ms=None, reranker_latency_ms=None, 
            context_build_latency_ms=None, total_latency_ms=None, status="started", error_code=None, error_message=None,
            metadata_={
                "vector_enabled": self._profile.vector_enabled,
                "lexical_enabled": self._profile.lexical_enabled,
            },
            started_at=started_at,
            completed_at=None,
        )

        self._repository.add_run(run)
        self._repository.flush()
        self._run = run

        return run.id

    def attach_embedding_call(self, embedding_call_id: uuid.UUID | None) -> None:
        if embedding_call_id is None:
            return

        if not isinstance(embedding_call_id, uuid.UUID):
            raise TypeError("embedding_call_id must be a UUID or None")

        self._require_run().embedding_call_id = embedding_call_id

    def record_vector(self, candidates: tuple[RetrievalCandidate, ...], *, latency_ms: int) -> None:
        self._validate_candidates(candidates)
        self._validate_latency(latency_ms)
        self._vector_count = len(candidates)
        self._vector_latency_ms = latency_ms
        for rank, candidate in enumerate(candidates, start=1):
            self._candidate(candidate).vector_rank = rank

    def record_lexical(self, candidates: tuple[RetrievalCandidate, ...], *, latency_ms: int) -> None:
        self._validate_candidates(candidates)
        self._validate_latency(latency_ms)
        self._lexical_count = len(candidates)
        self._lexical_latency_ms = latency_ms
        for rank, candidate in enumerate(candidates, start=1):
            self._candidate(candidate).lexical_rank = rank

    def record_fusion(self, candidates: tuple[RetrievalCandidate, ...], *, latency_ms: int) -> None:
        self._validate_candidates(candidates)
        self._validate_latency(latency_ms)
        self._fused_count = len(candidates)
        self._fusion_latency_ms = latency_ms
        for rank, candidate in enumerate(candidates, start=1):
            telemetry = self._candidate(candidate)
            telemetry.candidate = candidate
            telemetry.fusion_rank = rank

    def record_reranking(self, candidates: tuple[RetrievalCandidate, ...], *, latency_ms: int) -> None:
        self._validate_candidates(candidates)
        self._validate_latency(latency_ms)
        self._reranked_count = len(candidates)
        self._reranker_latency_ms = latency_ms
        for rank, candidate in enumerate(candidates, start=1):
            telemetry = self._candidate(candidate)
            telemetry.candidate = candidate
            telemetry.reranker_rank = rank

    def record_final(self, candidates: tuple[RetrievalCandidate, ...]) -> None:
        self._validate_candidates(candidates)

        for rank, candidate in enumerate(candidates, start=1):
            telemetry = self._candidate(candidate)
            telemetry.candidate = candidate
            telemetry.final_rank = rank

    def complete(self, *, context: GroundingContext, completed_at: datetime, total_latency_ms: int, context_build_latency_ms: int) -> None:
        if not isinstance(context, GroundingContext):
            raise TypeError("context must be a GroundingContext")

        self._validate_datetime(completed_at, field_name="completed_at")
        self._validate_latency(total_latency_ms)
        self._validate_latency(context_build_latency_ms)
        run = self._require_run()
        selected_chunk_ids = set(context.chunk_ids)
        candidate_models = tuple(
            self._to_model(run_id=run.id, telemetry=item, selected_chunk_ids=selected_chunk_ids, recorded_at=completed_at)
            for item in self._candidates.values()
        )

        self._repository.add_candidates(candidate_models)
        self._repository.mark_succeeded(
            run,
            completed_at=completed_at,
            total_latency_ms=total_latency_ms,
            vector_candidate_count=self._vector_count,
            lexical_candidate_count=self._lexical_count,
            fused_candidate_count=self._fused_count,
            reranked_candidate_count=self._reranked_count,
            selected_candidate_count=context.block_count,
            context_block_count=context.block_count,
            context_token_count=context.estimated_token_count,
            reranker_used=self._profile.reranking_enabled,
            context_truncated=context.truncated,
            vector_latency_ms=self._vector_latency_ms,
            lexical_latency_ms=self._lexical_latency_ms,
            fusion_latency_ms=self._fusion_latency_ms,
            reranker_latency_ms=self._reranker_latency_ms,
            context_build_latency_ms=context_build_latency_ms,
        )
        self._repository.flush()

    def fail(self, *, completed_at: datetime, total_latency_ms: int, error_code: str, error_message: str, timeout: bool = False) -> None:
        self._validate_datetime(completed_at, field_name="completed_at")
        self._validate_latency(total_latency_ms)
        run = self._require_run()
        self._repository.mark_failed(
            run, completed_at=completed_at, total_latency_ms=total_latency_ms, error_code=error_code, error_message=error_message, timeout=timeout,
        )
        self._repository.flush()

    def _candidate(self, candidate: RetrievalCandidate) -> _CandidateTelemetry:
        existing = self._candidates.get(candidate.chunk_id)
        if existing is not None:
            existing.candidate = candidate
            return existing

        created = _CandidateTelemetry(candidate=candidate)
        self._candidates[candidate.chunk_id] = created
        return created

    @staticmethod
    def _to_model(*, run_id: uuid.UUID, telemetry: _CandidateTelemetry, selected_chunk_ids: set[uuid.UUID], recorded_at: datetime) -> RetrievalCandidateModel:
        candidate = telemetry.candidate
        scores = candidate.scores
        selected = candidate.chunk_id in selected_chunk_ids
        final_score = (
            scores.reranker_score
            if scores.reranker_score is not None
            else scores.fusion_score
            if scores.fusion_score is not None
            else scores.vector_similarity
            if scores.vector_similarity is not None
            and scores.vector_similarity >= 0
            else scores.lexical_score
        )

        return RetrievalCandidateModel(
            id=uuid7(),
            retrieval_run_id=run_id,
            chunk_id=candidate.chunk_id,
            version_id=candidate.version_id,
            document_id=candidate.document_id,
            content_fingerprint=RetrievalTelemetryRecorder._fingerprint(candidate.content),
            vector_rank=telemetry.vector_rank,
            lexical_rank=telemetry.lexical_rank,
            fusion_rank=telemetry.fusion_rank,
            reranker_rank=telemetry.reranker_rank,
            final_rank=telemetry.final_rank,
            vector_similarity=scores.vector_similarity,
            lexical_score=scores.lexical_score,
            fusion_score=scores.fusion_score,
            reranker_score=scores.reranker_score,
            final_score=final_score,
            selected_for_context=selected,
            rejection_reason=None if selected else "not_selected_for_context",
            metadata_={
                "chunk_index": candidate.chunk_index,
                "methods": sorted(method.value for method in candidate.methods),
            },
            recorded_at=recorded_at,
        )

    def _retrieval_mode(self) -> str:
        if self._profile.vector_enabled and self._profile.lexical_enabled:
            return "hybrid"

        if self._profile.vector_enabled:
            return "vector"

        return "lexical"

    def _require_run(self) -> RetrievalRunModel:
        if self._run is None:
            raise RuntimeError("Retrieval telemetry has not been started")

        return self._run

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_candidates(candidates: tuple[RetrievalCandidate, ...]) -> None:
        if not isinstance(candidates, tuple):
            raise TypeError("candidates must be a tuple")

        if not all(isinstance(candidate, RetrievalCandidate) for candidate in candidates):
            raise TypeError("candidates must contain RetrievalCandidate instances")

    @staticmethod
    def _validate_latency(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("latency must be an integer")

        if value < 0:
            raise ValueError("latency cannot be negative")

    @staticmethod
    def _validate_datetime(value: datetime, *, field_name: str) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")