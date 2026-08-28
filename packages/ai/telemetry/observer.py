## Responsible for tasks like:
## stage lifecycle events, duration measurement, structured logging
## future fan-out to: OpenTelemetry, metrics, tracing, dashboards

from __future__ import annotations
import logging
import threading
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from packages.ai.orchestration.orchestrator import OrchestrationObserver
from packages.ai.orchestration.state import AIState, PipelineError, PipelineStage

logger = logging.getLogger(__name__)

# Structured telemetry event
@dataclass(frozen=True, slots=True)
class StageTelemetryEvent:
    """
    Immutable representation of one orchestration-stage lifecycle event.

    This is independent of:
    - SQLAlchemy
    - OpenTelemetry
    - Prometheus
    - any specific logging vendor

    Adapters may translate this object into their own telemetry format.
    """

    event_type: str
    ai_run_id: uuid.UUID
    trace_id: uuid.UUID
    conversation_id: uuid.UUID
    trigger_message_id: uuid.UUID
    stage: PipelineStage
    duration_ms: int | None = None
    error_code: str | None = None
    retryable: bool | None = None
    metadata: dict[str, Any] | None = None


# Telemetry sink abstraction
class TelemetrySink(Protocol):
    """
    Destination for structured orchestration telemetry.

    Implementations may later include:
        LoggingTelemetrySink
        OpenTelemetrySink
        MetricsTelemetrySink
        CompositeTelemetrySink
    """
    def emit(self, event: StageTelemetryEvent) -> None:
        ...


# Logging sink
class LoggingTelemetrySink:
    """
    Emit orchestration events through Python structured logging.
    No customer message content or model output is logged here by default.
    This minimizes accidental PII/secrets leakage.
    """

    def __init__(self, *, event_logger: logging.Logger | None = None) -> None:
        self._logger = event_logger or logger

    def emit(self, event: StageTelemetryEvent) -> None:
        payload = {
            "event_type": event.event_type,
            "ai_run_id": str(event.ai_run_id),
            "trace_id": str(event.trace_id),
            "conversation_id": str(event.conversation_id),
            "trigger_message_id": str(event.trigger_message_id),
            "stage": event.stage.value,
            "duration_ms": event.duration_ms,
            "error_code": event.error_code,
            "retryable": event.retryable,
            "metadata": dict(event.metadata or {}),
        }

        if event.event_type == "stage_failed":
            self._logger.error(
                "ai_pipeline_stage_failed",
                extra={
                    "telemetry": payload,
                },
            )

        else:
            self._logger.info(
                "ai_pipeline_stage_event",
                extra={
                    "telemetry": payload,
                },
            )

# Composite sink
class CompositeTelemetrySink:
    """
    Fan out a telemetry event to multiple independent sinks.

    Example:

        CompositeTelemetrySink(
            [
                LoggingTelemetrySink(),
                OpenTelemetrySink(),
                MetricsTelemetrySink(),
            ]
        )

    One broken sink does not prevent other sinks from receiving the event.
    """

    def __init__(self, sinks: Iterable[TelemetrySink]) -> None:
        self._sinks = tuple(sinks)
        if not self._sinks:
            raise ValueError("At least one telemetry sink is required")

    def emit(self, event: StageTelemetryEvent) -> None:
        for sink in self._sinks:
            try:
                sink.emit(event)

            except Exception:
                # Observability failures must generally not take down
                # customer-facing AI execution.
                logger.exception(
                    "telemetry_sink_failure",
                    extra={
                        "sink_type": type(
                            sink
                        ).__name__,
                        "event_type": event.event_type,
                        "stage": event.stage.value,
                        "trace_id": str(
                            event.trace_id
                        ),
                    },
                )


# Observer
class TelemetryOrchestrationObserver(OrchestrationObserver):
    """
    Production-oriented implementation of OrchestrationObserver.

    Responsibilities:
    - track stage start times
    - calculate stage latency
    - emit structured lifecycle telemetry
    - preserve trace/run correlation
    - expose failures without leaking sensitive payloads

    This observer does NOT:
    - commit database transactions
    - persist LLM calls
    - persist intent predictions
    - persist AI decisions
    - decide retry behaviour
    - execute pipeline stages
    """

    def __init__(self, *, sink: TelemetrySink | None = None, ) -> None:
        self._sink = sink if sink is not None else LoggingTelemetrySink()

        # Key:
        #   (ai_run_id, stage)
        #
        # Value:
        #   monotonic start timestamp
        self._stage_started_at: dict[
            tuple[uuid.UUID, PipelineStage],
            float,
        ] = {}

        # Observer may be shared across multiple simultaneous requests.
        self._lock = threading.Lock()


    # OrchestrationObserver implementation
    def stage_started(self, *, state: AIState, stage: PipelineStage) -> None:
        self._validate_state_and_stage(state=state, stage=stage)

        key = (state.ai_run_id, stage,)

        started_at = time.perf_counter() ## for elapsed duration measurement better to have monotonic clock

        with self._lock:
            # Duplicate start indicates either:
            # - orchestration bug
            # - retry that forgot to complete/reset its prior span
            #
            # Overwrite instead of crashing customer execution,
            # but surface the anomaly.
            duplicate = key in self._stage_started_at

            self._stage_started_at[key] = started_at

        if duplicate:
            logger.warning(
                "duplicate_pipeline_stage_start",
                extra={
                    "ai_run_id": str(
                        state.ai_run_id
                    ),
                    "trace_id": str(
                        state.trace_id
                    ),
                    "stage": stage.value,
                },
            )

        self._safe_emit(
            StageTelemetryEvent(
                event_type="stage_started",
                ai_run_id=state.ai_run_id,
                trace_id=state.trace_id,
                conversation_id=state.conversation_id,
                trigger_message_id=state.trigger_message_id,
                stage=stage,
                metadata=self._base_metadata(state)
            )
        )

    def stage_completed(self, *, state: AIState, stage: PipelineStage) -> None:
        self._validate_state_and_stage(state=state, stage=stage)

        duration_ms = self._finish_stage(ai_run_id=state.ai_run_id, stage=stage)

        self._safe_emit(
            StageTelemetryEvent(
                event_type="stage_completed",
                ai_run_id=state.ai_run_id,
                trace_id=state.trace_id,
                conversation_id=state.conversation_id,
                trigger_message_id=state.trigger_message_id,
                stage=stage,
                duration_ms=duration_ms,
                metadata=self._base_metadata(state)
            )
        )

    def stage_failed(self, *, state: AIState, stage: PipelineStage, error: PipelineError) -> None:
        self._validate_state_and_stage(state=state, stage=stage)
        if not isinstance(error, PipelineError):
            raise TypeError("error must be a PipelineError")

        duration_ms = self._finish_stage(ai_run_id=state.ai_run_id, stage=stage)

        metadata = self._base_metadata(state)

        # PipelineError.metadata has already passed through our structured
        # domain boundary, but still avoid copying arbitrary exception text.
        metadata.update(dict(error.metadata))

        self._safe_emit(
            StageTelemetryEvent(
                event_type="stage_failed",
                ai_run_id=state.ai_run_id,
                trace_id=state.trace_id,
                conversation_id=state.conversation_id,
                trigger_message_id=state.trigger_message_id,
                stage=stage,
                duration_ms=duration_ms,
                error_code=error.code,
                retryable=error.retryable,
                metadata=metadata,
            )
        )


    # Timing
    def _finish_stage(self, *, ai_run_id: uuid.UUID, stage: PipelineStage) -> int | None:
        """
        Remove a stage timer and return elapsed milliseconds.

        Returns None if no matching start event exists.

        Missing timers are observable anomalies, but should not cause
        customer-facing execution to fail.
        """

        key = (ai_run_id, stage,)

        with self._lock:
            started_at = (
                self._stage_started_at.pop(
                    key,
                    None,
                )
            )

        if started_at is None:
            logger.warning(
                "pipeline_stage_finished_without_start",
                extra={
                    "ai_run_id": str(
                        ai_run_id
                    ),
                    "stage": stage.value,
                },
            )

            return None

        elapsed_seconds = (time.perf_counter() - started_at)
        # perf_counter() is monotonic, but defensive clamping protects
        # against unexpected platform/runtime behaviour.
        elapsed_seconds = max(elapsed_seconds, 0.0)

        return int(round(elapsed_seconds * 1000))


    # Emission safety
    def _safe_emit(self, event: StageTelemetryEvent) -> None:
        """
        Observability must not become a customer-facing availability risk.

        Logging/metrics/tracing failures are captured and surfaced through
        the fallback logger instead of propagating into orchestration.
        """
        try:
            self._sink.emit(event)

        except Exception:
            logger.exception(
                "orchestration_telemetry_emit_failed",
                extra={
                    "event_type": (
                        event.event_type
                    ),
                    "ai_run_id": str(
                        event.ai_run_id
                    ),
                    "trace_id": str(
                        event.trace_id
                    ),
                    "stage": event.stage.value,
                    "sink_type": type(
                        self._sink
                    ).__name__,
                },
            )

    # Metadata
    @staticmethod
    def _base_metadata(state: AIState, ) -> dict[str, Any]:
        """
        Return safe low-cardinality orchestration metadata.

        Do NOT automatically emit:
        - customer_message
        - conversation_context
        - generated_response
        - retrieved document content

        Those may contain PII, credentials, or sensitive customer data.
        """

        metadata: dict[str, Any] = {}

        pipeline_version = state.metadata.get("pipeline_version")

        if pipeline_version is not None:
            metadata["pipeline_version"] = pipeline_version

        if state.intent_result is not None:
            metadata["intent"] = state.intent_result.intent.value
            metadata["intent_confidence"] = state.intent_result.confidence

        if state.decision_result is not None:
            metadata["decision"] = state.decision_result.decision.value
            metadata["decision_reason_code"] = state.decision_result.reason_code.value

        return metadata

    
    # Validation
    @staticmethod
    def _validate_state_and_stage(*, state: AIState, stage: PipelineStage) -> None:
        if not isinstance(state, AIState):
            raise TypeError("state must be an AIState")

        if not isinstance(stage, PipelineStage):
            raise TypeError("stage must be a PipelineStage")