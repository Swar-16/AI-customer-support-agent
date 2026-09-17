# AI-customer-support-agent\packages\ai\telemetry\reranker_recorder.py
from __future__ import annotations
import hashlib
import uuid
from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self
from uuid6 import uuid7

from packages.database.models.ai.reranker_call import RerankerCallModel
from packages.database.repositories.ai.reranker_call_repository import RerankerCallRepository
from packages.knowledge.retrieval.reranking.models import RerankerDescriptor, RerankingRequest, RerankingResponse

RetrievalRunIdProvider = Callable[[], uuid.UUID | None]

class RerankerTelemetryUnitOfWork(Protocol):
    reranker_calls: RerankerCallRepository | None

    def __enter__(self) -> Self:
        ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        ...

    def commit(self) -> None:
        ...

RerankerTelemetryUnitOfWorkFactory = Callable[[], RerankerTelemetryUnitOfWork]

class RerankerTelemetryRecorder:
    """
    Persist reranker telemetry through short independent transactions.

    The retrieval run must already have been committed before start_call() executes because reranker_calls.retrieval_run_id is a foreign key.

    Query text and candidate content are never persisted. Only bounded fingerprints, counts,
    identifiers, timing, and lifecycle state are recorded.
    """
    def __init__(self, *, uow_factory: RerankerTelemetryUnitOfWorkFactory, retrieval_run_id: uuid.UUID | RetrievalRunIdProvider,
                 trace_id: uuid.UUID | None = None, metadata: dict[str, Any] | None = None
    ) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        if not isinstance(retrieval_run_id, uuid.UUID) and not callable(retrieval_run_id):
            raise TypeError("retrieval_run_id must be a UUID or callable")

        if trace_id is not None and not isinstance(trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID or None")

        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary or None")

        self._uow_factory = uow_factory
        self._retrieval_run_id = retrieval_run_id
        self._trace_id = trace_id
        self._metadata = dict(metadata or {})

    def start_call(self, *, request: RerankingRequest, descriptor: RerankerDescriptor, started_at: datetime) -> uuid.UUID:
        if not isinstance(request, RerankingRequest):
            raise TypeError("request must be a RerankingRequest")

        if not isinstance(descriptor, RerankerDescriptor):
            raise TypeError("descriptor must be a RerankerDescriptor")

        self._validate_datetime(started_at, field_name="started_at")
        retrieval_run_id = self._resolve_retrieval_run_id()
        call_id = uuid7()
        call = RerankerCallModel(
            id=call_id,
            retrieval_run_id=retrieval_run_id,
            trace_id=self._trace_id,
            reranker_id=descriptor.reranker_id,
            provider=descriptor.provider,
            model=descriptor.model,
            revision=descriptor.revision,
            query_fingerprint=self._fingerprint(request.query.text),
            input_candidate_count=request.candidate_count,
            requested_limit=request.limit,
            output_candidate_count=0,
            latency_ms=None,
            status="started",
            provider_request_id=None,
            error_code=None,
            error_message=None,
            metadata_={
                **self._metadata,
                "candidate_identity_fingerprint": self._candidate_identity_fingerprint(request),
            },
            started_at=started_at,
            completed_at=None,
        )

        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            repository.add(call)
            repository.flush()
            uow.commit()

        return call_id

    def complete_call(self, call_id: uuid.UUID, *, response: RerankingResponse, completed_at: datetime, latency_ms: int, provider_request_id: str | None = None) -> None:
        if not isinstance(response, RerankingResponse):
            raise TypeError("response must be a RerankingResponse")

        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            call = self._get_started_call(repository=repository, call_id=call_id)
            repository.mark_succeeded(
                call,
                completed_at=completed_at,
                latency_ms=latency_ms,
                output_candidate_count=response.count,
                provider_request_id=provider_request_id,
            )
            uow.commit()

    def fail_call(self, call_id: uuid.UUID, *, completed_at: datetime, latency_ms: int, error_code: str, error_message: str, provider_request_id: str | None = None) -> None:
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        normalized_code = self._normalize_required_text(error_code, field_name="error_code")
        normalized_message = self._normalize_required_text(error_message, field_name="error_message")
        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            call = self._get_started_call(repository=repository, call_id=call_id)
            repository.mark_failed(
                call,
                completed_at=completed_at,
                latency_ms=latency_ms,
                error_code=normalized_code,
                error_message=normalized_message,
                provider_request_id=provider_request_id,
            )
            uow.commit()

    def timeout_call(self, call_id: uuid.UUID, *, completed_at: datetime, latency_ms: int, provider_request_id: str | None = None) -> None:
        self._validate_completion(completed_at=completed_at, latency_ms=latency_ms)
        with self._uow_factory() as uow:
            repository = self._require_repository(uow)
            call = self._get_started_call(repository=repository, call_id=call_id)
            repository.mark_timeout(
                call,
                completed_at=completed_at,
                latency_ms=latency_ms,
                provider_request_id=provider_request_id,
            )
            uow.commit()

    def _resolve_retrieval_run_id(self) -> uuid.UUID:
        source = self._retrieval_run_id
        retrieval_run_id = source() if callable(source) else source
        if retrieval_run_id is None:
            raise RuntimeError("Retrieval run has not been started before reranking")

        if not isinstance(retrieval_run_id, uuid.UUID):
            raise TypeError("retrieval_run_id provider must return a UUID or None")

        return retrieval_run_id

    @staticmethod
    def _require_repository(uow: RerankerTelemetryUnitOfWork) -> RerankerCallRepository:
        repository = uow.reranker_calls
        if repository is None:
            raise RuntimeError("Reranker-call repository is unavailable in the telemetry Unit of Work")

        if not isinstance(repository, RerankerCallRepository):
            raise TypeError("uow.reranker_calls must be a RerankerCallRepository")

        return repository

    @classmethod
    def _get_started_call(cls, *, repository: RerankerCallRepository, call_id: uuid.UUID) -> RerankerCallModel:
        if not isinstance(call_id, uuid.UUID):
            raise TypeError("call_id must be a UUID")

        call = repository.get_by_id(call_id)
        if call is None:
            raise RuntimeError(f"Reranker telemetry call does not exist: {call_id}")

        if call.status != "started":
            raise RuntimeError(f"Reranker telemetry call is already finalized: {call_id} ({call.status})")

        return call

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _candidate_identity_fingerprint(request: RerankingRequest) -> str:
        digest = hashlib.sha256()
        digest.update(b"reranker-candidates-v1\0")
        for candidate in request.candidates:
            payload = candidate.chunk_id.bytes
            digest.update(len(payload).to_bytes(4, "big"))
            digest.update(payload)

        return digest.hexdigest()

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")

        return normalized

    @staticmethod
    def _validate_datetime(value: datetime, *, field_name: str) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")

    @classmethod
    def _validate_completion(cls, *, completed_at: datetime, latency_ms: int) -> None:
        cls._validate_datetime(completed_at, field_name="completed_at")
        if isinstance(latency_ms, bool) or not isinstance(latency_ms, int):
            raise TypeError("latency_ms must be an integer")

        if latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")