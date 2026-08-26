## Historical intent predictions should be treated as immutable evidence. So, NO UPDATE
## mostly append-only inference artifacts.

from __future__ import annotations
import uuid
from collections.abc import Sequence
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.ai.intent_prediction import IntentPredictionModel


class IntentPredictionRepository:
    """
    Persistence adapter for intent-classification results.

    Responsibilities:
    - persist validated intent predictions
    - retrieve predictions by run / LLM call / intent
    - expose useful diagnostic queries
    - preserve append-only classification history

    Explicitly NOT responsible for:
    - running the classifier
    - interpreting confidence
    - applying routing thresholds
    - deciding clarification/escalation
    - mutating historical predictions
    - committing transactions
    """

    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, prediction: IntentPredictionModel, ) -> None:
        """
        Add one intent prediction to the current transaction.
        """
        self._validate_prediction_instance(prediction)
        self._session.add(prediction)

    def flush(self) -> None:
        """
        Flush pending ORM changes without committing.
        """
        self._session.flush()

    # Primary lookups
    def get_by_id(self, prediction_id: uuid.UUID) -> IntentPredictionModel | None:
        statement = (
            select(IntentPredictionModel)
            .where(IntentPredictionModel.id == prediction_id)
        )

        return self._session.scalar(statement)

    def get_by_ai_run(self, ai_run_id: uuid.UUID) -> Sequence[IntentPredictionModel]:
        """
        Return all intent predictions generated during one AI run.

        Multiple predictions are allowed because:
        - retries may occur
        - fallback classifiers may run
        - reclassification may happen
        """
        statement = (
            select(IntentPredictionModel)
            .where(IntentPredictionModel.ai_run_id == ai_run_id)
            .order_by(
                IntentPredictionModel.created_at.asc(),
                IntentPredictionModel.id.asc(),
            )
        )

        return tuple(self._session.scalars(statement))

    def get_by_llm_call_id(self, llm_call_id: uuid.UUID) -> Sequence[IntentPredictionModel]:
        """
        Return predictions associated with one LLM invocation.
        """
        statement = (
            select(IntentPredictionModel)
            .where(IntentPredictionModel.llm_call_id == llm_call_id)
            .order_by(IntentPredictionModel.created_at.asc())
        )

        return tuple(self._session.scalars(statement))


    # Diagnostic queries
    def get_by_intent(self, intent: str, *, limit: int = 100) -> Sequence[IntentPredictionModel]:
        """
        Return recent predictions for a canonical intent.
        """
        normalized_intent = intent.strip()
        if not normalized_intent:
            raise ValueError("intent cannot be empty")

        self._validate_limit(limit)

        statement = (
            select(IntentPredictionModel)
            .where(IntentPredictionModel.intent == normalized_intent)
            .order_by(IntentPredictionModel.created_at.desc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def get_low_confidence(self, *, threshold: Decimal | float, limit: int = 100) -> Sequence[IntentPredictionModel]:
        """
        Return recent predictions below a confidence threshold.

        The repository does not decide what threshold is "good". The caller supplies it.
        """
        numeric_threshold = Decimal(str(threshold))

        if not Decimal("0") <= numeric_threshold <= Decimal("1"):
            raise ValueError("threshold must be between 0 and 1")

        self._validate_limit(limit)

        statement = (
            select(IntentPredictionModel)
            .where(
                IntentPredictionModel.confidence.is_not(None),
                IntentPredictionModel.confidence
                < numeric_threshold,
            )
            .order_by(IntentPredictionModel.created_at.desc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def get_needing_clarification(self, *, limit: int = 100) -> Sequence[IntentPredictionModel]:
        """
        Return recent predictions that explicitly require clarification.
        """
        self._validate_limit(limit)

        statement = (
            select(IntentPredictionModel)
            .where(IntentPredictionModel.needs_clarification.is_(True))
            .order_by(IntentPredictionModel.created_at.desc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def get_unknown(self, *, limit: int = 100) -> Sequence[IntentPredictionModel]:
        """
        Return recent UNKNOWN intent predictions.
        Useful for taxonomy-gap analysis and prompt-quality evaluation.
        """
        self._validate_limit(limit)

        statement = (
            select(IntentPredictionModel)
            .where(IntentPredictionModel.intent == "unknown")
            .order_by(IntentPredictionModel.created_at.desc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))


    # Convenience queries
    def get_latest_for_ai_run(self, ai_run_id: uuid.UUID) -> IntentPredictionModel | None:
        """
        Return the newest prediction for one AI run.
        """

        statement = (
            select(IntentPredictionModel)
            .where(IntentPredictionModel.ai_run_id == ai_run_id)
            .order_by(
                IntentPredictionModel.created_at.desc(),
                IntentPredictionModel.id.desc(),
            )
            .limit(1)
        )

        return self._session.scalar(statement)


    # Internal validation

    @staticmethod
    def _validate_prediction_instance(prediction: IntentPredictionModel) -> None:
        if not isinstance(prediction, IntentPredictionModel):
            raise TypeError("prediction must be an IntentPredictionModel")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")