# AI-customer-support-agent\packages\knowledge\retrieval\reranking\instrumented.py
from __future__ import annotations
import logging
import time
import uuid
from datetime import datetime, timezone

from packages.ai.telemetry.reranker_recorder import RerankerTelemetryRecorder
from packages.knowledge.retrieval.errors import RerankerProviderError
from packages.knowledge.retrieval.reranking.base import Reranker
from packages.knowledge.retrieval.reranking.models import RerankerDescriptor, RerankingRequest, RerankingResponse

logger = logging.getLogger(__name__)

class InstrumentedReranker(Reranker):
    """
    Telemetry wrapper around any configured Reranker.

    It records execution timing and lifecycle while preserving the wrapped reranker's response and exception behavior.

    Query text and candidate content are never persisted.
    """
    def __init__(self, *, reranker: Reranker, recorder: RerankerTelemetryRecorder) -> None:
        if not isinstance(reranker, Reranker):
            raise TypeError("reranker must implement Reranker")

        if not isinstance(recorder, RerankerTelemetryRecorder):
            raise TypeError("recorder must be a RerankerTelemetryRecorder")

        self._reranker = reranker
        self._recorder = recorder
        self._last_call_id: uuid.UUID | None = None

    @property
    def descriptor(self) -> RerankerDescriptor:
        return self._reranker.descriptor

    @property
    def wrapped_reranker(self) -> Reranker:
        return self._reranker

    @property
    def last_call_id(self) -> uuid.UUID | None:
        return self._last_call_id

    def rerank(self, request: RerankingRequest) -> RerankingResponse:
        if not isinstance(request, RerankingRequest):
            # Preserve the wrapped implementation's validation behavior.
            self._last_call_id = None
            return self._reranker.rerank(request)

        started_at = datetime.now(timezone.utc)
        started_ns = time.monotonic_ns()
        self._last_call_id = None
        call_id = self._start_call_safely(request=request, started_at=started_at)
        self._last_call_id = call_id
        try:
            response = self._reranker.rerank(request)

        except RerankerProviderError as exc:
            if self._is_timeout(exc):
                self._timeout_call_safely(call_id, started_ns=started_ns)
            else:
                self._fail_call_safely(
                    call_id, started_ns=started_ns, error_code=type(exc).__name__, error_message="Reranker provider execution failed."
                )

            raise

        except Exception as exc:
            if self._is_timeout(exc):
                self._timeout_call_safely(call_id, started_ns=started_ns)
            else:
                self._fail_call_safely(
                    call_id, started_ns=started_ns, error_code="unexpected_reranker_error", error_message="Unexpected failure during reranker execution.",
                )

            raise

        self._complete_call_safely(call_id, response=response, started_ns=started_ns)

        return response

    def health_check(self) -> bool:
        return self._reranker.health_check()

    def _start_call_safely(self, *, request: RerankingRequest, started_at: datetime) -> uuid.UUID | None:
        try:
            return self._recorder.start_call(request=request, descriptor=self.descriptor, started_at=started_at)

        except Exception:
            logger.exception(
                "reranker_telemetry_start_failed",
                extra={
                    "reranker_id": self.descriptor.reranker_id,
                    "provider": self.descriptor.provider,
                    "model": self.descriptor.model,
                },
            )
            return None

    def _complete_call_safely(self, call_id: uuid.UUID | None, *, response: RerankingResponse, started_ns: int) -> None:
        if call_id is None:
            return

        try:
            self._recorder.complete_call(call_id, response=response, completed_at=datetime.now(timezone.utc), latency_ms=self._elapsed_ms(started_ns))

        except Exception:
            logger.exception("reranker_telemetry_completion_failed", extra={"reranker_call_id": str(call_id)})

    def _fail_call_safely(self, call_id: uuid.UUID | None, *, started_ns: int, error_code: str, error_message: str) -> None:
        if call_id is None:
            return

        try:
            self._recorder.fail_call(
                call_id, completed_at=datetime.now(timezone.utc), latency_ms=self._elapsed_ms(started_ns), error_code=error_code, error_message=error_message,
            )

        except Exception:
            logger.exception("reranker_telemetry_failure_recording_failed", extra={"reranker_call_id": str(call_id)})

    def _timeout_call_safely(self, call_id: uuid.UUID | None, *, started_ns: int) -> None:
        if call_id is None:
            return

        try:
            self._recorder.timeout_call(call_id, completed_at=datetime.now(timezone.utc), latency_ms=self._elapsed_ms(started_ns))

        except Exception:
            logger.exception("reranker_telemetry_timeout_recording_failed", extra={"reranker_call_id": str(call_id)})

    @staticmethod
    def _is_timeout(exc: BaseException) -> bool:
        """
        Detect native and wrapped timeout failures.

        A dedicated RerankerTimeoutError can replace the class-name fallback when the first external reranker provider is implemented.
        """
        current: BaseException | None = exc
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            if isinstance(current, TimeoutError):
                return True

            if "timeout" in type(current).__name__.casefold():
                return True

            visited.add(id(current))
            current = current.__cause__ or current.__context__

        return False

    @staticmethod
    def _elapsed_ms(started_ns: int) -> int:
        elapsed_ns = time.monotonic_ns() - started_ns
        return max(0, elapsed_ns // 1_000_000)