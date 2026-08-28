## It only translate execution facts into your persistence models and repositories.
from __future__ import annotations
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from packages.ai.decision.schemas import DecisionResult
from packages.ai.intent.schemas import IntentResult
from packages.database.models.ai.decision import AIDecisionModel
from packages.database.models.ai.intent_prediction import IntentPredictionModel
from packages.database.models.ai.llm_call import LLMCallModel
from packages.database.repositories.ai.decision_repository import AIDecisionRepository
from packages.database.repositories.ai.intent_prediction_repository import IntentPredictionRepository
from packages.database.repositories.ai.llm_call_repository import LLMCallRepository


class TelemetryRecorder:
    """
    Persists structured AI execution telemetry.

    This component translates runtime/domain results into database records.

    Responsibilities:
    - create LLM call records
    - finalize LLM calls with usage / latency / failure information
    - persist intent predictions
    - persist AI decisions

    Explicitly NOT responsible for:
    - committing or rolling back transactions
    - invoking providers
    - retry/backoff
    - deciding intent
    - deciding business actions
    - calculating model prices
    - handling HTTP/API concerns

    All repositories are expected to share the same Unit-of-Work session.
    """

    def __init__(self, *, llm_calls: LLMCallRepository, 
                 intent_predictions: IntentPredictionRepository, ai_decisions: AIDecisionRepository
    ) -> None:
        if llm_calls is None:
            raise TypeError("llm_calls repository cannot be None")

        if intent_predictions is None:
            raise TypeError("intent_predictions repository cannot be None")

        if ai_decisions is None:
            raise TypeError("ai_decisions repository cannot be None")

        self._llm_calls = llm_calls
        self._intent_predictions = intent_predictions
        self._ai_decisions = ai_decisions

    # LLM calls
    def start_llm_call(self, *, ai_run_id: uuid.UUID, purpose: str, provider: str, model: str, started_at: datetime,
                       prompt_version_id: uuid.UUID | None = None, temperature: Decimal | None = None
    ) -> LLMCallModel:
        """
        Create an LLM-call telemetry record before invoking the provider.

        Persisting the call before execution allows failures/timeouts to
        still have a corresponding telemetry record.
        """
        normalized_purpose = self._normalize_required_string(purpose, field_name="purpose")
        normalized_provider = self._normalize_required_string(provider, field_name="provider")
        normalized_model = self._normalize_required_string(model, field_name="model")

        if(
            temperature is not None
            and not Decimal("0") <= temperature <= Decimal("2")
        ):
            raise ValueError("temperature must be between 0 and 2")

        call = LLMCallModel(
            ai_run_id=ai_run_id,
            prompt_version_id=prompt_version_id,
            purpose=normalized_purpose,
            provider=normalized_provider,
            model=normalized_model,
            temperature=temperature,
            status="started",
            started_at=started_at,
        )

        self._llm_calls.add(call)
        self._llm_calls.flush()

        return call

    def complete_llm_call(self, call: LLMCallModel, *, completed_at: datetime, latency_ms: int,
                          input_tokens: int, output_tokens: int, cached_input_tokens: int = 0, 
                          estimated_cost_usd: Decimal | None = None, provider_request_id: str | None = None
    ) -> None:
        """
        Finalize an LLM call after a successful provider invocation.
        """
        self._llm_calls.mark_succeeded(
            call,
            completed_at=completed_at,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            estimated_cost_usd=estimated_cost_usd,
            provider_request_id=provider_request_id,
        )

    def fail_llm_call(self, call: LLMCallModel, *, completed_at: datetime, latency_ms: int,
                      error_code: str, error_message: str, provider_request_id: str | None = None
    ) -> None:
        """
        Finalize an LLM call with a provider failure.
        """
        self._llm_calls.mark_failed(
            call,
            completed_at=completed_at,
            latency_ms=latency_ms,
            error_code=error_code,
            error_message=error_message,
            provider_request_id=provider_request_id,
        )

    def timeout_llm_call(self, call: LLMCallModel, *, completed_at: datetime, latency_ms: int,
                         error_message: str = "LLM provider request timed out.",
                         provider_request_id: str | None = None
    ) -> None:
        """
        Finalize an LLM call specifically as a timeout.
        """
        self._llm_calls.mark_timeout(
            call,
            completed_at=completed_at,
            latency_ms=latency_ms,
            error_message=error_message,
            provider_request_id=provider_request_id,
        )


    # Intent prediction
    def record_intent_prediction(self, *, ai_run_id: uuid.UUID, result: IntentResult,
                                 llm_call_id: uuid.UUID | None, created_at: datetime
    ) -> IntentPredictionModel:
        """
        Persist one validated intent-classification result.
        """
        if not isinstance(result, IntentResult):
            raise TypeError("result must be an IntentResult")

        prediction = IntentPredictionModel(
            ai_run_id=ai_run_id,
            llm_call_id=llm_call_id,
            intent=result.intent.value,
            confidence=Decimal(str(result.confidence)),
            entities=result.entities.model_dump(mode="json"),
            needs_clarification=result.needs_clarification,
            reasoning_summary=result.reason_summary,
            created_at=created_at,
        )

        self._intent_predictions.add(prediction)
        self._intent_predictions.flush()

        return prediction

    # AI decision
    def record_decision(self, *, ai_run_id: uuid.UUID, result: DecisionResult, created_at: datetime,
                        llm_call_id: uuid.UUID | None = None, extra_metadata: dict[str, Any] | None = None
    ) -> AIDecisionModel:
        """
        Persist one deterministic/probabilistic AI routing decision.
        """
        if not isinstance(result, DecisionResult):
            raise TypeError("result must be a DecisionResult")

        metadata = dict(result.metadata)
        if extra_metadata:
            metadata.update(extra_metadata)

        if result.required_information:
            metadata["required_information"] = list(result.required_information)

        confidence = Decimal(str(result.confidence)) if result.confidence is not None else None

        decision = AIDecisionModel(
            ai_run_id=ai_run_id,
            llm_call_id=llm_call_id,
            decision_type=result.decision.value,
            confidence=confidence,
            reason_code=result.reason_code.value,
            reason_summary=result.reason_summary,
            metadata_=metadata,
            created_at=created_at,
        )

        self._ai_decisions.add(decision)
        self._ai_decisions.flush()

        return decision

    # Internal helpers

    @staticmethod
    def _normalize_required_string(value: str, *, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be empty")

        return normalized