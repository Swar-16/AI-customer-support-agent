# AI-customer-support-agent\packages\ai\telemetry\transactional_embedding_recorder.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any

from packages.database.models.ai.embedding_call import EmbeddingCallModel
from packages.database.repositories.ai.embedding_call_repository import EmbeddingCallRepository, VALID_EMBEDDING_PURPOSES


class TransactionalEmbeddingTelemetryRecorder:
    """
    Embedding telemetry recorder using an already-active transaction.

    This is used during ProcessCustomerMessage because the referenced AI run has not yet been committed and is invisible to separate sessions.

    It deliberately does not commit. The surrounding application Unit of Work owns the transaction.
    """
    def __init__(self, *, repository: EmbeddingCallRepository) -> None:
        if not isinstance(repository, EmbeddingCallRepository):
            raise TypeError("repository must be an EmbeddingCallRepository")

        self._repository = repository

    def start_call(self, *, purpose: str, provider: str, model: str, input_count: int, total_input_characters: int, started_at: datetime,
                   ai_run_id: uuid.UUID | None = None, trace_id: uuid.UUID | None = None, knowledge_version_id: uuid.UUID | None = None,
                   provider_revision: str | None = None, request_fingerprint: str | None = None, metadata: dict[str, Any] | None = None
    ) -> uuid.UUID:
        normalized_purpose = purpose.strip().lower()
        if normalized_purpose not in VALID_EMBEDDING_PURPOSES:
            expected = ", ".join(sorted(VALID_EMBEDDING_PURPOSES))
            raise ValueError(f"purpose must be one of: {expected}")

        call = EmbeddingCallModel(
            ai_run_id=ai_run_id,
            trace_id=trace_id,
            knowledge_version_id=knowledge_version_id,
            purpose=normalized_purpose,
            provider=provider.strip(),
            model=model.strip(),
            provider_revision=provider_revision.strip() if provider_revision is not None else None,
            input_count=input_count,
            total_input_characters=total_input_characters,
            request_fingerprint=request_fingerprint,
            dimensions=None,
            latency_ms=None,
            status="started",
            provider_request_id=None,
            error_code=None,
            error_message=None,
            metadata_=dict(metadata or {}),
            started_at=started_at,
            completed_at=None,
        )

        self._repository.add(call)
        self._repository.flush()

        return call.id

    def complete_call(self, call_id: uuid.UUID | None, *, completed_at: datetime, latency_ms: int, dimensions: int, provider_request_id: str | None = None) -> None:
        call = self._get_required(call_id)
        self._repository.mark_succeeded(
            call, completed_at=completed_at, latency_ms=latency_ms, dimensions=dimensions, provider_request_id=provider_request_id
        )

    def fail_call(self, call_id: uuid.UUID | None, *, completed_at: datetime, latency_ms: int, error_code: str, error_message: str, provider_request_id: str | None = None) -> None:
        call = self._get_required(call_id)
        self._repository.mark_failed(
            call,
            completed_at=completed_at,
            latency_ms=latency_ms,
            error_code=error_code,
            error_message=error_message,
            provider_request_id=provider_request_id,
        )

    def timeout_call(self, call_id: uuid.UUID | None, *, completed_at: datetime, latency_ms: int, provider_request_id: str | None = None) -> None:
        call = self._get_required(call_id)
        self._repository.mark_timeout(
            call,
            completed_at=completed_at,
            latency_ms=latency_ms,
            provider_request_id=provider_request_id,
        )

    def _get_required(self, call_id: uuid.UUID | None) -> EmbeddingCallModel:
        if call_id is None:
            raise ValueError("call_id cannot be None")

        call = self._repository.get_by_id(call_id)
        if call is None:
            raise RuntimeError(f"Embedding telemetry call does not exist: {call_id}")

        return call