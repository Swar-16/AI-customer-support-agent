from __future__ import annotations

from packages.knowledge.retrieval.query.builder import RetrievalQueryBuilder
from packages.knowledge.retrieval.query.errors import RetrievalQueryPreparationError, RetrievalQueryPreparationUnavailableError, UnexpectedRetrievalQueryPreparationError
from packages.knowledge.retrieval.query.models import PreparedRetrievalQuery, RetrievalQueryContext


class RetrievalQueryPreparationService:
    """
    Stable application-facing boundary for retrieval-query preparation.

    Responsibilities:
        - accept a validated RetrievalQueryContext
        - delegate deterministic preparation to the configured builder
        - preserve expected query-preparation domain failures
        - translate unexpected implementation failures
        - validate the builder's output contract
    """
    def __init__(self, *, builder: RetrievalQueryBuilder) -> None:
        if not isinstance(builder, RetrievalQueryBuilder):
            raise RetrievalQueryPreparationUnavailableError("A valid retrieval query builder is required.")

        self._builder = builder

    def prepare(self, *, context: RetrievalQueryContext) -> PreparedRetrievalQuery:
        if not isinstance(context, RetrievalQueryContext):
            raise TypeError("context must be a RetrievalQueryContext instance")

        try:
            prepared = self._builder.build(context=context)

        except RetrievalQueryPreparationError:
            raise # Expected domain failures already carry meaningful semantics.

        except Exception as exc:
            raise UnexpectedRetrievalQueryPreparationError("Unexpected failure while preparing retrieval query.") from exc

        if not isinstance(prepared, PreparedRetrievalQuery):
            raise UnexpectedRetrievalQueryPreparationError("Retrieval query builder returned an invalid result type.")

        return prepared