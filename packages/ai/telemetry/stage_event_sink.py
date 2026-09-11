# AI-customer-support-agent\packages\ai\telemetry\stage_event_sink.py
from __future__ import annotations
from datetime import datetime, timezone

from packages.ai.telemetry.observer import StageTelemetryEvent, TelemetrySink
from packages.database.models.ai.stage_event import AIStageEventModel
from packages.database.repositories.ai.stage_event_repository import AIStageEventRepository


class DatabaseStageEventSink(TelemetrySink):
    """
    Persists orchestration-stage events using the active request transaction.

    The sink does not commit or flush. Transaction ownership remains with the surrounding Unit of Work.

    No customer message, generated answer, prompt, retrieved content, or conversation context is persisted.
    """
    def __init__(self, *, repository: AIStageEventRepository) -> None:
        if not isinstance(repository, AIStageEventRepository):
            raise TypeError("repository must be an AIStageEventRepository")

        self._repository = repository

    def emit(self, event: StageTelemetryEvent) -> None:
        if not isinstance(event, StageTelemetryEvent):
            raise TypeError("event must be a StageTelemetryEvent")

        record = AIStageEventModel(
            ai_run_id=event.ai_run_id,
            trace_id=event.trace_id,
            conversation_id=event.conversation_id,
            trigger_message_id=event.trigger_message_id,
            event_type=event.event_type,
            stage=event.stage.value,
            duration_ms=event.duration_ms,
            error_code=event.error_code,
            retryable=event.retryable,
            metadata_=dict(event.metadata or {}),
            occurred_at=datetime.now(timezone.utc),
        )

        self._repository.add(record)