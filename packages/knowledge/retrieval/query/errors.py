from __future__ import annotations

from packages.knowledge.retrieval.errors import RetrievalError

# Base
class RetrievalQueryPreparationError(RetrievalError):
    """
    Base exception for retrieval-query preparation failures.

    Everything raised by the query-preparation subsystem should derive from this type so application/orchestration
    code can handle query preparation failures without depending on implementation details.
    """

# Input / context errors
class RetrievalQueryContextError(RetrievalQueryPreparationError):
    """
    Base exception for invalid RetrievalQueryContext input.
    """

class InvalidCustomerMessageError(RetrievalQueryContextError):
    """
    Customer message is missing, empty, malformed, or otherwise unusable for retrieval-query preparation.
    """

class InvalidIntentHintError(RetrievalQueryContextError):
    """
    Optional semantic intent hint is malformed.

    This does NOT mean that the intent is unsupported. New/unknown intent keys may still be valid hints. This error is for structurally invalid values.
    """

class InvalidEntityHintsError(RetrievalQueryContextError):
    """
    Entity hints supplied to query preparation are malformed.
    """

class InvalidConversationContextError(RetrievalQueryContextError):
    """
    Optional conversation context is structurally invalid.
    """

class InvalidTrustedFiltersError(RetrievalQueryContextError):
    """
    Trusted retrieval filters supplied by the application layer are invalid.

    Customer-controlled data and LLM-extracted entities must never be silently promoted into these filters.
    """

# Prepared-query errors
class PreparedRetrievalQueryError(RetrievalQueryPreparationError):
    """
    Base exception for an invalid prepared retrieval-query representation.
    """

class InvalidOriginalQueryError(PreparedRetrievalQueryError):
    """
    The preserved original customer query is invalid.
    """

class InvalidSemanticQueryError(PreparedRetrievalQueryError):
    """
    Query intended for semantic/vector retrieval is invalid.
    """

class InvalidLexicalQueryError(PreparedRetrievalQueryError):
    """
    One lexical query is malformed or unusable.
    """

class MissingLexicalQueriesError(PreparedRetrievalQueryError):
    """
    Query preparation produced no usable lexical query.
    """

# Builder errors
class RetrievalQueryBuilderError(RetrievalQueryPreparationError):
    """
    Base exception for deterministic query-builder failures.
    """

class QueryNormalizationError(RetrievalQueryBuilderError):
    """
    Query text could not be normalized into a safe retrieval representation.
    """

class QueryConstructionError(RetrievalQueryBuilderError):
    """
    A valid RetrievalQueryContext could not be transformed into a valid PreparedRetrievalQuery.
    """

class QueryExpansionError(RetrievalQueryBuilderError):
    """
    Optional deterministic query expansion failed.

    Kept separate from construction so future synonym/subtype/entity expansion can fail explicitly without being confused with malformed input.
    """

class QueryPreparationLimitError(RetrievalQueryBuilderError):
    """
    Query preparation exceeded a configured safety/resource limit.

    Examples:
        - too many entity hints
        - excessive generated lexical variants
        - excessive prepared query length
        - excessive conversation-context contribution
    """

# Strategy / configuration errors
class RetrievalQueryConfigurationError(RetrievalQueryPreparationError):
    """
    Base exception for invalid query-preparation configuration.
    """

class InvalidQueryPreparationConfigError(RetrievalQueryConfigurationError):
    """
    Query-preparation configuration contains invalid values or internally inconsistent limits.
    """

class QueryPreparationStrategyError(RetrievalQueryConfigurationError):
    """
    Base exception for query-preparation strategy resolution/configuration failures.
    """

class QueryPreparationStrategyNotFoundError(QueryPreparationStrategyError):
    """
    Requested query-preparation strategy is not registered.
    """
    def __init__(self, strategy_id: str) -> None:
        self.strategy_id = strategy_id
        super().__init__(f"Query preparation strategy not found: {strategy_id!r}")

# Service / pipeline errors
class RetrievalQueryServiceError(RetrievalQueryPreparationError):
    """
    Base exception for failures at the query-preparation service boundary.
    """

class RetrievalQueryPreparationUnavailableError(RetrievalQueryServiceError):
    """
    Query preparation cannot currently be performed because a required
    dependency or strategy is unavailable.
    """

class UnexpectedRetrievalQueryPreparationError(RetrievalQueryServiceError):
    """
    Unexpected internal failure translated at the service boundary.

    The original exception should always be retained using exception chaining:

        raise UnexpectedRetrievalQueryPreparationError(...) from exc
    """