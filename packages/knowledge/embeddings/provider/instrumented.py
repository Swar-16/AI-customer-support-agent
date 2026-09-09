# AI-customer-support-agent\packages\knowledge\embeddings\provider\instrumented.py
from __future__ import annotations
import hashlib
import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Protocol

from packages.knowledge.embeddings.errors import EmbeddingProviderTimeoutError, KnowledgeEmbeddingError
from packages.knowledge.embeddings.models import EmbeddingBatch, EmbeddingProviderDescriptor, EmbeddingVector
from packages.knowledge.embeddings.provider.base import EmbeddingProvider

logger = logging.getLogger(__name__)

class EmbeddingTelemetryRecorderContract(Protocol):
    def start_call(self, *, purpose: str, provider: str, model: str, input_count: int, total_input_characters: int, started_at: datetime,
                   ai_run_id: uuid.UUID | None = None, trace_id: uuid.UUID | None = None, knowledge_version_id: uuid.UUID | None = None,
                   provider_revision: str | None = None, request_fingerprint: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> uuid.UUID | None:
        ...

    def complete_call(self, call_id: uuid.UUID | None, *, completed_at: datetime, latency_ms: int, dimensions: int, provider_request_id: str | None = None) -> None:
        ...

    def fail_call(self, call_id: uuid.UUID | None, *, completed_at: datetime, latency_ms: int, error_code: str, error_message: str, provider_request_id: str | None = None) -> None:
        ...

    def timeout_call(self, call_id: uuid.UUID | None, *, completed_at: datetime, latency_ms: int, provider_request_id: str | None = None) -> None:
        ...

@dataclass(frozen=True, slots=True)
class EmbeddingCallContext:
    """Immutable context attached to embedding-provider calls."""
    purpose: str
    ai_run_id: uuid.UUID | None = None
    trace_id: uuid.UUID | None = None
    knowledge_version_id: uuid.UUID | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.purpose, str):
            raise TypeError("purpose must be a string")

        normalized_purpose = self.purpose.strip().lower()
        if not normalized_purpose:
            raise ValueError("purpose cannot be blank")

        for field_name, value in (("ai_run_id", self.ai_run_id), ("trace_id", self.trace_id), ("knowledge_version_id", self.knowledge_version_id),):
            if value is not None and not isinstance(value, uuid.UUID):
                raise TypeError(f"{field_name} must be a UUID or None")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")

        object.__setattr__(self, "purpose", normalized_purpose)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

class InstrumentedEmbeddingProvider(EmbeddingProvider):
    """
    Telemetry wrapper around any EmbeddingProvider.

    The wrapper preserves provider return values and exceptions. Telemetry failures are logged and must not replace provider results or exceptions.

    Raw input text and embedding vectors are never persisted.
    """
    def __init__(self, *, provider: EmbeddingProvider, recorder: EmbeddingTelemetryRecorderContract, context: EmbeddingCallContext) -> None:
        if not isinstance(provider, EmbeddingProvider):
            raise TypeError("provider must implement EmbeddingProvider")

        required_methods = ("start_call", "complete_call", "fail_call", "timeout_call",)
        if not all(callable(getattr(recorder, method_name, None)) for method_name in required_methods):
            raise TypeError("recorder must implement the embedding telemetry contract")

        if not isinstance(context, EmbeddingCallContext):
            raise TypeError("context must be an EmbeddingCallContext")

        self._provider = provider
        self._recorder = recorder
        self._context = context
        self._last_call_id: uuid.UUID | None = None

    @property
    def descriptor(self) -> EmbeddingProviderDescriptor:
        return self._provider.descriptor

    @property
    def wrapped_provider(self) -> EmbeddingProvider:
        return self._provider

    @property
    def context(self) -> EmbeddingCallContext:
        return self._context

    @property
    def last_call_id(self) -> uuid.UUID | None:
        """
        Return the telemetry ID for the most recent provider invocation.

        Request-scoped retrieval uses this to connect RetrievalRunModel to the exact query embedding call.
        """
        return self._last_call_id

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        # Preserve the wrapped provider's validation behavior when callers accidentally provide one string instead of a sequence of strings.
        if isinstance(texts, (str, bytes)):
            self._last_call_id = None
            return self._provider.embed_documents(texts)

        stable_texts = tuple(texts)
        # Existing providers treat an empty batch as a no-op. No provider execution means no embedding-call telemetry record.
        if not stable_texts:
            self._last_call_id = None
            return self._provider.embed_documents(stable_texts)

        return self._execute_documents(stable_texts)

    def embed_query(self, text: str) -> EmbeddingVector:
        return self._execute_query(text)

    def health_check(self) -> bool:
        """
        Keep readiness probes separate from business-call telemetry.

        Dedicated health-check telemetry can be added later with an explicit purpose and sampling policy.
        """
        return self._provider.health_check()

    def _execute_documents(self, texts: tuple[str, ...]) -> EmbeddingBatch:
        started_at = datetime.now(timezone.utc)
        started_ns = time.monotonic_ns()
        self._last_call_id = None
        call_id = self._start_call_safely(operation="documents", texts=texts, started_at=started_at)
        self._last_call_id = call_id
        try:
            result = self._provider.embed_documents(texts)

        except EmbeddingProviderTimeoutError:
            self._timeout_call_safely(call_id, started_ns=started_ns)
            raise

        except KnowledgeEmbeddingError as exc:
            self._fail_call_safely(call_id, started_ns=started_ns, error_code=exc.code, error_message=str(exc))
            raise

        except Exception:
            self._fail_call_safely(call_id, started_ns=started_ns, error_code="unexpected_embedding_error", error_message="Unexpected failure during embedding-provider execution.")
            raise

        self._complete_call_safely(call_id, started_ns=started_ns, dimensions=result.provider.dimensions)
        return result

    def _execute_query(self, text: str) -> EmbeddingVector:
        started_at = datetime.now(timezone.utc)
        started_ns = time.monotonic_ns()
        self._last_call_id = None
        call_id = self._start_call_safely(operation="query", texts=(text,), started_at=started_at)
        self._last_call_id = call_id

        try:
            result = self._provider.embed_query(text)

        except EmbeddingProviderTimeoutError:
            self._timeout_call_safely(call_id, started_ns=started_ns)
            raise

        except KnowledgeEmbeddingError as exc:
            self._fail_call_safely(call_id, started_ns=started_ns, error_code=exc.code, error_message=str(exc))
            raise

        except Exception:
            self._fail_call_safely(call_id, started_ns=started_ns, error_code="unexpected_embedding_error", error_message="Unexpected failure during embedding-provider execution.")
            raise

        self._complete_call_safely(call_id, started_ns=started_ns, dimensions=result.dimensions)
        return result

    def _start_call_safely(self, *, operation: str, texts: Sequence[Any], started_at: datetime) -> uuid.UUID | None:
        try:
            return self._recorder.start_call(
                purpose=self._context.purpose,
                provider=self.descriptor.provider,
                model=self.descriptor.model,
                provider_revision=self.descriptor.revision,
                input_count=len(texts),
                total_input_characters=self._total_characters(texts),
                request_fingerprint=self._fingerprint(operation=operation, texts=texts),
                ai_run_id=self._context.ai_run_id,
                trace_id=self._context.trace_id,
                knowledge_version_id=self._context.knowledge_version_id,
                metadata=self._telemetry_metadata(operation),
                started_at=started_at,
            )

        except Exception:
            logger.exception(
                "embedding_telemetry_start_failed",
                extra={
                    "purpose": self._context.purpose,
                    "provider": self.descriptor.provider,
                    "model": self.descriptor.model,
                    "operation": operation,
                },
            )
            return None

    def _complete_call_safely(self, call_id: uuid.UUID | None, *, started_ns: int, dimensions: int) -> None:
        if call_id is None:
            return

        try:
            self._recorder.complete_call(
                call_id, completed_at=datetime.now(timezone.utc), latency_ms=self._elapsed_ms(started_ns), dimensions=dimensions
            )

        except Exception:
            logger.exception("embedding_telemetry_completion_failed", extra={"embedding_call_id": str(call_id)})

    def _fail_call_safely(self, call_id: uuid.UUID | None, *, started_ns: int, error_code: str, error_message: str) -> None:
        if call_id is None:
            return

        try:
            self._recorder.fail_call(
                call_id,
                completed_at=datetime.now(timezone.utc),
                latency_ms=self._elapsed_ms(started_ns),
                error_code=error_code,
                error_message=error_message,
            )

        except Exception:
            logger.exception("embedding_telemetry_failure_recording_failed", extra={"embedding_call_id": str(call_id)})

    def _timeout_call_safely(self, call_id: uuid.UUID | None, *, started_ns: int) -> None:
        if call_id is None:
            return

        try:
            self._recorder.timeout_call(call_id, completed_at=datetime.now(timezone.utc), latency_ms=self._elapsed_ms(started_ns))

        except Exception:
            logger.exception("embedding_telemetry_timeout_recording_failed", extra={"embedding_call_id": str(call_id)})

    def _telemetry_metadata(self, operation: str) -> dict[str, Any]:
        metadata = dict(self._context.metadata)
        metadata["operation"] = operation
        return metadata

    def _fingerprint(self, *, operation: str, texts: Sequence[Any]) -> str:
        """
        Hash request identity without retaining its content.

        Length-prefixing prevents ambiguous concatenations such as ["ab", "c"] and ["a", "bc"].
        """
        digest = hashlib.sha256()
        digest.update(b"embedding-call-v1\0")
        digest.update(operation.encode("utf-8"))
        digest.update(b"\0")
        digest.update(self.descriptor.identity.encode("utf-8"))
        digest.update(b"\0")
        for value in texts:
            if isinstance(value, str):
                payload = value.encode("utf-8")
            else:
                payload = (f"<invalid:{type(value).__name__}>").encode("utf-8")

            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)

        return digest.hexdigest()

    @staticmethod
    def _total_characters(texts: Sequence[Any]) -> int:
        return sum(len(value) for value in texts if isinstance(value, str))

    @staticmethod
    def _elapsed_ms(started_ns: int) -> int:
        elapsed_ns = time.monotonic_ns() - started_ns
        return max(0, elapsed_ns // 1_000_000)