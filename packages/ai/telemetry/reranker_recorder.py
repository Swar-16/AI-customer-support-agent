# AI-customer-support-agent\packages\ai\telemetry\reranker_recorder.py
from __future__ import annotations
import hashlib
import uuid
from datetime import datetime
from collections.abc import Callable
from typing import Any
from uuid6 import uuid7

from packages.database.models.ai.reranker_call import RerankerCallModel
from packages.database.repositories.ai.reranker_call_repository import RerankerCallRepository
from packages.knowledge.retrieval.reranking.models import RerankerDescriptor, RerankingRequest, RerankingResponse

RetrievalRunIdProvider = Callable[[], uuid.UUID | None]

class RerankerTelemetryRecorder:
    """
    Request-scoped transactional recorder for reranker executions.

    It uses the active customer-message Unit of Work and never commits. Query text and candidate content are 
    represented only by fingerprints and counts.
    """
    def __init__(self, *, repository: RerankerCallRepository, retrieval_run_id: uuid.UUID | RetrievalRunIdProvider,
                 trace_id: uuid.UUID | None = None, metadata: dict[str, Any] | None = None
    ) -> None:
        if not isinstance(repository, RerankerCallRepository):
            raise TypeError("repository must be a RerankerCallRepository")

        if not isinstance(retrieval_run_id, uuid.UUID) and not callable(retrieval_run_id):
            raise TypeError("retrieval_run_id must be a UUID or callable")

        if trace_id is not None and not isinstance(trace_id, uuid.UUID):
            raise TypeError("trace_id must be a UUID or None")

        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary or None")

        self._repository = repository
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
        call = RerankerCallModel(
            id=uuid7(),
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

        self._repository.add(call)
        self._repository.flush()
        return call.id
    
    def _resolve_retrieval_run_id(self) -> uuid.UUID:
        source = self._retrieval_run_id
        retrieval_run_id = source() if callable(source) else source
        if retrieval_run_id is None:
            raise RuntimeError("Retrieval run has not been started before reranking")

        if not isinstance(retrieval_run_id, uuid.UUID):
            raise TypeError("retrieval_run_id provider must return a UUID or None")

        return retrieval_run_id

    def complete_call(self, call_id: uuid.UUID, *, response: RerankingResponse, completed_at: datetime, latency_ms: int, provider_request_id: str | None = None) -> None:
        if not isinstance(response, RerankingResponse):
            raise TypeError("response must be a RerankingResponse")

        call = self._get_required(call_id)
        self._repository.mark_succeeded(call, completed_at=completed_at, latency_ms=latency_ms, output_candidate_count=response.count, provider_request_id=provider_request_id)

    def fail_call(self, call_id: uuid.UUID, *, completed_at: datetime, latency_ms: int, error_code: str, error_message: str, provider_request_id: str | None = None) -> None:
        call = self._get_required(call_id)
        self._repository.mark_failed(
            call, completed_at=completed_at, latency_ms=latency_ms, error_code=error_code, error_message=error_message, provider_request_id=provider_request_id,
        )

    def timeout_call(self, call_id: uuid.UUID, *, completed_at: datetime, latency_ms: int, provider_request_id: str | None = None) -> None:
        call = self._get_required(call_id)
        self._repository.mark_timeout(call, completed_at=completed_at, latency_ms=latency_ms, provider_request_id=provider_request_id)

    def _get_required(self, call_id: uuid.UUID) -> RerankerCallModel:
        if not isinstance(call_id, uuid.UUID):
            raise TypeError("call_id must be a UUID")

        call = self._repository.get_by_id(call_id)
        if call is None:
            raise RuntimeError(f"Reranker telemetry call does not exist: {call_id}")

        return call

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _candidate_identity_fingerprint(request: RerankingRequest) -> str:
        """Fingerprint ordered candidate identities without storing content."""
        digest = hashlib.sha256()
        digest.update(b"reranker-candidates-v1\0")
        for candidate in request.candidates:
            payload = candidate.chunk_id.bytes
            digest.update(len(payload).to_bytes(4, "big"))
            digest.update(payload)

        return digest.hexdigest()

    @staticmethod
    def _validate_datetime(value: datetime, *, field_name: str) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")