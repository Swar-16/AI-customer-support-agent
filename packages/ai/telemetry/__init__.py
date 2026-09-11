# AI-customer-support-agent\packages\ai\telemetry\__init__.py
from __future__ import annotations
from importlib import import_module
from typing import Any

__all__ = [
    "CompositeTelemetrySink",
    "LoggingTelemetrySink",
    "StageTelemetryEvent",
    "TelemetryOrchestrationObserver",
    "TelemetryRecorder",
    "TelemetrySink",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "CompositeTelemetrySink": ("packages.ai.telemetry.observer", "CompositeTelemetrySink",),
    "LoggingTelemetrySink": ("packages.ai.telemetry.observer", "LoggingTelemetrySink",),
    "StageTelemetryEvent": ("packages.ai.telemetry.observer", "StageTelemetryEvent",),
    "TelemetryOrchestrationObserver": ("packages.ai.telemetry.observer", "TelemetryOrchestrationObserver",),
    "TelemetrySink": ("packages.ai.telemetry.observer", "TelemetrySink",),
    "TelemetryRecorder": ("packages.ai.telemetry.recorder", "TelemetryRecorder",),
}

def __getattr__(name: str) -> Any:
    """
    Resolve public telemetry exports lazily.

    Eagerly importing observer.py here creates a cycle because the observer depends on orchestration while
    orchestration reaches retrieval telemetry through AnswerService.
    """
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value

def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})