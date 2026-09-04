from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping
from types import MappingProxyType

from evaluation.retrieval.models import RetrievalEvaluationCase
from packages.knowledge.retrieval.models import RetrievalFilters, RetrievalResult
from packages.knowledge.retrieval.query.models import PreparedRetrievalQuery, RetrievalQueryContext
from packages.knowledge.retrieval.query.service import RetrievalQueryPreparationService


class RetrievalRunnerError(Exception):
    """
    Base exception for retrieval evaluation runner failures.
    """

class RetrievalRunnerConfigurationError(RetrievalRunnerError):
    """
    Raised when a runner is constructed with invalid dependencies.
    """

class RetrievalRunnerInputError(RetrievalRunnerError):
    """
    Raised when an evaluation case cannot safely be converted into a retrieval request.
    """

class RetrievalRunnerExecutionError(RetrievalRunnerError):
    """
    Raised when the underlying retrieval pipeline fails.
    """

class RetrievalRunnerContractError(RetrievalRunnerError):
    """
    Raised when a dependency violates the expected runner contract.
    """

@dataclass(frozen=True, slots=True)
class EvaluationRetrievalContext:
    """
    Retrieval-specific context derived from a benchmark case.

    This exists to keep benchmark annotations separate from production retrieval inputs.

    Ground-truth fields such as expected documents/sections/topics are deliberately absent. They must never leak into retrieval.
    """
    customer_message: str
    intent_key: str | None
    entities: Mapping[str, str]
    filters: RetrievalFilters
    conversation_context: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.customer_message, str):
            raise RetrievalRunnerInputError("customer_message must be a string.")

        normalized_message = self.customer_message.strip()
        if not normalized_message:
            raise RetrievalRunnerInputError("customer_message must not be empty.")

        object.__setattr__(self, "customer_message", normalized_message)
        if self.intent_key is not None:
            if not isinstance(self.intent_key, str):
                raise RetrievalRunnerInputError("intent_key must be a string or None.")

            normalized_intent = self.intent_key.strip()
            object.__setattr__(self, "intent_key", normalized_intent or None)

        if not isinstance(self.entities, Mapping):
            raise RetrievalRunnerInputError("entities must be a mapping.")

        normalized_entities: dict[str, str] = {}
        for key, value in self.entities.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise RetrievalRunnerInputError("entities must contain string keys and string values.")

            normalized_key = key.strip()
            normalized_value = value.strip()
            if not normalized_key or not normalized_value:
                continue

            normalized_entities[normalized_key] = normalized_value

        object.__setattr__(self, "entities", MappingProxyType(normalized_entities))
        if not isinstance(self.filters, RetrievalFilters):
            raise RetrievalRunnerInputError("filters must be a RetrievalFilters instance.")

        if self.conversation_context is not None:
            if not isinstance(self.conversation_context, str):
                raise RetrievalRunnerInputError("conversation_context must be a string or None.")

            normalized_context = self.conversation_context.strip()
            object.__setattr__(self, "conversation_context", normalized_context or None)


class BaseRetrievalEvaluationRunner(ABC):
    """
    Shared foundation for real retrieval benchmark runners.

    Concrete implementations execute exactly one retrieval strategy:

        lexical
        vector
        hybrid

    The base class is responsible only for:

        EvaluationCase -> RetrievalQueryContext -> PreparedRetrievalQuery

    Ground-truth annotations are NEVER passed into query preparation or retrieval. This prevents benchmark leakage.
    """
    def __init__(self, *, query_preparation_service: RetrievalQueryPreparationService) -> None:
        if not isinstance(query_preparation_service, RetrievalQueryPreparationService):
            raise RetrievalRunnerConfigurationError("query_preparation_service must be a RetrievalQueryPreparationService instance.")

        self._query_preparation_service = query_preparation_service

    @property
    @abstractmethod
    def method(self) -> str:
        """
        Stable benchmark method identifier.

        Examples:
            lexical
            vector
            hybrid
        """
        
    def retrieve(self, *, case: RetrievalEvaluationCase) -> RetrievalResult:
        """
        Execute retrieval for one benchmark case.

        This is the method consumed by RetrievalEvaluator.
        """
        self._validate_case(case)

        try:
            context = self._build_evaluation_context(case=case)
            prepared_query = self._prepare_query(context=context)
            result = self._execute_retrieval(prepared_query=prepared_query)

        except RetrievalRunnerError:
            raise

        except Exception as exc:
            raise RetrievalRunnerExecutionError(
                f"Retrieval evaluation runner failed for case '{case.case_id}' using method '{self.method}'.") from exc

        if not isinstance(result, RetrievalResult):
            raise RetrievalRunnerContractError("_execute_retrieval must return a RetrievalResult instance.")

        return result

    def _build_evaluation_context(self, *, case: RetrievalEvaluationCase) -> EvaluationRetrievalContext:
        """
        Convert benchmark input into the exact retrieval-facing context.

        Ground-truth annotations are deliberately excluded.
        """
        retrieval_input = case.retrieval_input

        return EvaluationRetrievalContext(
            customer_message=case.query,
            intent_key=case.intent_key,
            entities=retrieval_input.entities,
            filters=retrieval_input.filters,
            conversation_context=retrieval_input.conversation_context,
        )

    def _prepare_query(self, *, context: EvaluationRetrievalContext) -> PreparedRetrievalQuery:
        retrieval_context = RetrievalQueryContext(
            customer_message=context.customer_message,
            intent_key=context.intent_key,
            entities=context.entities,
            filters=context.filters,
            conversation_context=context.conversation_context,
        )

        prepared = self._query_preparation_service.prepare(context=retrieval_context)
        if not isinstance(prepared, PreparedRetrievalQuery):
            raise RetrievalRunnerContractError("query preparation service must return PreparedRetrievalQuery.")

        return prepared

    @abstractmethod
    def _execute_retrieval(self, *, prepared_query: PreparedRetrievalQuery) -> RetrievalResult:
        """
        Execute the strategy-specific retrieval operation.
        """

    @staticmethod
    def _validate_case(case: object) -> None:
        if not isinstance(case, RetrievalEvaluationCase):
            raise RetrievalRunnerInputError("case must be a RetrievalEvaluationCase instance.")