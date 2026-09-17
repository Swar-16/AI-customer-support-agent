# AI-customer-support-agent\packages\ai\telemetry\stage_event_sink.py
from __future__ import annotations
from collections.abc import Callable
from datetime import datetime, timezone
from types import TracebackType
from typing import Protocol, Self

from packages.ai.telemetry.observer import StageTelemetryEvent, TelemetrySink
from packages.database.models.ai.stage_event import AIStageEventModel
from packages.database.repositories.ai.stage_event_repository import AIStageEventRepository

class StageEventTelemetryUnitOfWork(Protocol):
    stage_events: AIStageEventRepository | None

    def __enter__(self) -> Self:
        ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        ...

    def commit(self) -> None:
        ...

StageEventTelemetryUnitOfWorkFactory = Callable[[], StageEventTelemetryUnitOfWork]

class DatabaseStageEventSink(TelemetrySink):
    """
    Persist every orchestration-stage event in a short transaction.

    The transaction is opened only while inserting the event and is closed before orchestration continues.
    No provider call executes inside this transaction.

    Customer messages, prompts, generated answers, retrieved content, and conversation context must never be included in event metadata.
    """
    def __init__(self, *, uow_factory: StageEventTelemetryUnitOfWorkFactory) -> None:
        if not callable(uow_factory):
            raise TypeError("uow_factory must be callable")

        self._uow_factory = uow_factory

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

        with self._uow_factory() as uow:
            repository = uow.stage_events
            if repository is None:
                raise RuntimeError("Stage-event repository is unavailable in the telemetry Unit of Work")

            if not isinstance(repository, AIStageEventRepository):
                raise TypeError("uow.stage_events must be an AIStageEventRepository")

            repository.add(record)
            uow.commit()