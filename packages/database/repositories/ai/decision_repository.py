## append-only decision evidence
from __future__ import annotations
import uuid
from collections.abc import Sequence
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.database.models.ai.decision import AIDecisionModel

class AIDecisionRepository:
    """
    Persistence adapter for AI decision records.

    Responsibilities:
    - persist decisions produced during an AI run
    - retrieve decisions by run / LLM call / type / reason
    - expose diagnostic queries for observability
    - preserve historical decision records

    Explicitly NOT responsible for:
    - executing decision logic
    - deciding business policy
    - authorizing actions
    - evaluating escalation eligibility
    - changing historical decisions
    - committing transactions
    """

    def __init__(self, session: Session) -> None:
        if session is None:
            raise TypeError("session cannot be None")

        self._session = session

    # Write operations
    def add(self, decision: AIDecisionModel) -> None:
        """
        Add a decision to the current transaction.
        """
        self._validate_decision_instance(decision)
        self._session.add(decision)

    def flush(self) -> None:
        """
        Flush pending ORM state without committing.
        """
        self._session.flush()

    # Primary lookups
    def get_by_id(self, decision_id: uuid.UUID) -> AIDecisionModel | None:
        statement = (
            select(AIDecisionModel)
            .where(AIDecisionModel.id == decision_id)
        )

        return self._session.scalar(statement)

    def get_by_ai_run(self, ai_run_id: uuid.UUID) -> Sequence[AIDecisionModel]:
        """
        Return all decisions produced during one AI run.

        Multiple decisions are possible. Example:

            retrieve_information -> answer
        or:
            retrieve_information -> escalate
        """
        statement = (
            select(AIDecisionModel)
            .where(AIDecisionModel.ai_run_id == ai_run_id)
            .order_by(
                AIDecisionModel.created_at.asc(),
                AIDecisionModel.id.asc(),
            )
        )

        return tuple(self._session.scalars(statement))

    def get_by_llm_call_id(self, llm_call_id: uuid.UUID) -> Sequence[AIDecisionModel]:
        """
        Return decisions associated with a specific LLM invocation.

        llm_call_id may be NULL for deterministic decisions produced
        entirely by the DecisionEngine.
        """
        statement = (
            select(AIDecisionModel)
            .where(AIDecisionModel.llm_call_id == llm_call_id)
            .order_by(AIDecisionModel.created_at.asc())
        )

        return tuple(self._session.scalars(statement))


    # Diagnostic queries
    def get_by_decision_type(self, decision_type: str, *, limit: int = 100) -> Sequence[AIDecisionModel]:
        """
        Return recent decisions of a particular type.

        Example:
            escalate
            ask_clarification
            retrieve_information
        """
        normalized = decision_type.strip()

        if not normalized:
            raise ValueError("decision_type cannot be empty")

        self._validate_limit(limit)
        statement = (
            select(AIDecisionModel)
            .where(AIDecisionModel.decision_type == normalized)
            .order_by(AIDecisionModel.created_at.desc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def get_by_reason_code(self, reason_code: str, *, limit: int = 100) -> Sequence[AIDecisionModel]:
        """
        Return recent decisions matching a machine-readable reason code.
        This is particularly useful for dashboards and root-cause analysis.
        """
        normalized = reason_code.strip()
        if not normalized:
            raise ValueError("reason_code cannot be empty")

        self._validate_limit(limit)
        statement = (
            select(AIDecisionModel)
            .where(AIDecisionModel.reason_code == normalized)
            .order_by(AIDecisionModel.created_at.desc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def get_low_confidence(self, *, threshold: Decimal | float, limit: int = 100) -> Sequence[AIDecisionModel]:
        """
        Return recent decisions below a caller-supplied confidence threshold.

        The repository does not define what "low confidence" means.
        That belongs to evaluation/business configuration.
        """

        numeric_threshold = Decimal(str(threshold))
        if not Decimal("0") <= numeric_threshold <= Decimal("1"):
            raise ValueError("threshold must be between 0 and 1")

        self._validate_limit(limit)
        statement = (
            select(AIDecisionModel)
            .where(
                AIDecisionModel.confidence.is_not(None),
                AIDecisionModel.confidence
                < numeric_threshold,
            )
            .order_by(AIDecisionModel.created_at.desc())
            .limit(limit)
        )

        return tuple(self._session.scalars(statement))

    def get_escalations(self, *, limit: int = 100) -> Sequence[AIDecisionModel]:
        """
        Return recent escalation decisions.
        """
        return self.get_by_decision_type("escalate", limit=limit)

    def get_clarification_requests(self, *, limit: int = 100) -> Sequence[AIDecisionModel]:
        """
        Return recent clarification decisions.
        """
        return self.get_by_decision_type("ask_clarification", limit=limit)


    # Convenience queries
    def get_latest_for_ai_run(self, ai_run_id: uuid.UUID) -> AIDecisionModel | None:
        """
        Return the newest decision for an AI run.
        Important because an AI run may evolve through multiple decisions.
        """
        statement = (
            select(AIDecisionModel)
            .where(AIDecisionModel.ai_run_id == ai_run_id)
            .order_by(
                AIDecisionModel.created_at.desc(),
                AIDecisionModel.id.desc(),
            )
            .limit(1)
        )

        return self._session.scalar(statement)


    # Internal validation

    @staticmethod
    def _validate_decision_instance(decision: AIDecisionModel) -> None:
        if not isinstance(decision, AIDecisionModel):
            raise TypeError("decision must be an AIDecisionModel")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit <= 0:
            raise ValueError("limit must be greater than zero")