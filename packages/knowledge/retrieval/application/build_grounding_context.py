# AI-customer-support-agent\packages\knowledge\retrieval\application\build_grounding_context.py
from __future__ import annotations
from datetime import datetime, timezone
from time import perf_counter

from packages.ai.telemetry.retrieval_recorder import RetrievalTelemetryRecorder
from packages.knowledge.embeddings.errors import EmbeddingProviderTimeoutError
from packages.knowledge.retrieval.application.retrieve_knowledge import RetrieveKnowledge
from packages.knowledge.retrieval.context.builder import GroundingContextBuilder
from packages.knowledge.retrieval.context.models import GroundingContext, GroundingContextBudget
from packages.knowledge.retrieval.query.models import PreparedRetrievalQuery
from packages.knowledge.retrieval.errors import RetrievalPipelineError

class BuildGroundingContext:
    """
    Application service that converts a retrieval query into bounded,
    trusted grounding context.

    Pipeline:

        RetrievalQuery --> RetrieveKnowledge --> RetrievalResult
                                                        ↓
                        GroundingContext <-- GroundingContextBuilder

    Responsibilities:
      - execute the configured retrieval pipeline;
      - apply context-selection and budgeting policy;
      - return structured grounding context.

    This keeps the knowledge subsystem reusable independently of any specific LLM provider or RAG prompt implementation.
    """
    def __init__(self, *, retrieve_knowledge: RetrieveKnowledge, context_builder: GroundingContextBuilder,
        default_budget: GroundingContextBudget, telemetry_recorder: RetrievalTelemetryRecorder | None = None
    ) -> None:
        if not isinstance(retrieve_knowledge, RetrieveKnowledge):
            raise TypeError("retrieve_knowledge must be a RetrieveKnowledge instance.")

        if not isinstance(context_builder, GroundingContextBuilder):
            raise TypeError("context_builder must be a GroundingContextBuilder instance.")

        if not isinstance(default_budget, GroundingContextBudget):
            raise TypeError("default_budget must be a GroundingContextBudget instance.")

        if telemetry_recorder is not None and not isinstance(telemetry_recorder, RetrievalTelemetryRecorder):
            raise TypeError("telemetry_recorder must be a RetrievalTelemetryRecorder instance or None.")

        self._retrieve_knowledge = retrieve_knowledge
        self._context_builder = context_builder
        self._default_budget = default_budget
        self._telemetry_recorder = telemetry_recorder

    @property
    def retrieve_knowledge(self) -> RetrieveKnowledge:
        return self._retrieve_knowledge

    @property
    def context_builder(self) -> GroundingContextBuilder:
        return self._context_builder

    @property
    def default_budget(self) -> GroundingContextBudget:
        return self._default_budget

    def build(self, *, prepared_query: PreparedRetrievalQuery, budget: GroundingContextBudget | None = None) -> GroundingContext:
        if not isinstance(prepared_query, PreparedRetrievalQuery):
            raise TypeError("prepared_query must be a PreparedRetrievalQuery instance.")

        effective_budget = self._resolve_budget(budget)
        overall_started = perf_counter()
        telemetry_started = False
        if self._telemetry_recorder is not None:
            self._telemetry_recorder.start(prepared_query=prepared_query, started_at=datetime.now(timezone.utc))
            telemetry_started = True

        try:
            retrieval_result = self._retrieve_knowledge.retrieve(prepared_query=prepared_query)
            context_started = perf_counter()
            context = self._context_builder.build(retrieval_result=retrieval_result, budget=effective_budget)
            context_latency_ms = self._elapsed_ms(context_started)
            if context.query != retrieval_result.query:
                raise RetrievalPipelineError("Grounding context was produced for a different retrieval query.")

            if self._telemetry_recorder is not None:
                self._telemetry_recorder.complete(
                    context=context,
                    completed_at=datetime.now(timezone.utc),
                    total_latency_ms=self._elapsed_ms(overall_started),
                    context_build_latency_ms=context_latency_ms,
                )

            return context

        except Exception as exc:
            if self._telemetry_recorder is not None and telemetry_started:
                self._telemetry_recorder.fail(
                    completed_at=datetime.now(timezone.utc),
                    total_latency_ms=self._elapsed_ms(overall_started),
                    error_code=type(exc).__name__,
                    error_message="Retrieval pipeline execution failed.",
                    timeout=self._is_timeout(exc),
                )

            raise
        
    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        elapsed = perf_counter() - started_at
        return max(0, int(round(elapsed * 1_000)))

    @staticmethod
    def _is_timeout(exc: BaseException) -> bool:
        current: BaseException | None = exc
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            if isinstance(current, EmbeddingProviderTimeoutError):
                return True

            visited.add(id(current))
            current = current.__cause__ or current.__context__

        return False

    def _resolve_budget(self, budget: GroundingContextBudget | None) -> GroundingContextBudget:
        if budget is None:
            return self._default_budget

        if not isinstance(budget, GroundingContextBudget):
            raise TypeError("budget must be a GroundingContextBudget instance or None.")

        return budget