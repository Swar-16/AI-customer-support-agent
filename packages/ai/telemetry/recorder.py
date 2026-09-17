# AI-customer-support-agent\packages\ai\telemetry\recorder.py
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
from packages.database.repositories.ai.decision_repository import AIDecisionRepository
from packages.database.repositories.ai.intent_prediction_repository import IntentPredictionRepository


class TelemetryRecorder:
    """
    Persist final structured AI pipeline outcomes.

    This recorder belongs to the finalization transaction and stores:

    - validated intent predictions;
    - deterministic AI decisions.

    Provider-call lifecycle telemetry is handled separately by
    LLMCallTelemetryRecorder so external calls do not require a long-lived
    SQLAlchemy transaction.
    """
    def __init__(self, *, intent_predictions: IntentPredictionRepository, ai_decisions: AIDecisionRepository) -> None:
        if not isinstance(intent_predictions, IntentPredictionRepository):
            raise TypeError("intent_predictions must be an IntentPredictionRepository")

        if not isinstance(ai_decisions, AIDecisionRepository):
            raise TypeError("ai_decisions must be an AIDecisionRepository")

        self._intent_predictions = intent_predictions
        self._ai_decisions = ai_decisions

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
            escalation_signals=[signal.value for signal in result.escalation_signals],
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