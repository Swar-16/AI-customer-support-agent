from __future__ import annotations

class RetrievalError(Exception):
    """
    Base exception for the entire knowledge-retrieval subsystem.

    Application/orchestration layers may catch this type when they need to
    handle any retrieval failure without depending on implementation details.
    """

# Configuration / profile errors
class RetrievalConfigurationError(RetrievalError):
    """
    Raised when retrieval cannot run because its configuration is invalid, inconsistent, or unsupported.
    """

class RetrievalProfileError(RetrievalConfigurationError):
    """
    Raised when a retrieval profile is invalid or cannot be resolved.
    """

class RetrievalProfileNotFoundError(RetrievalProfileError):
    """
    Raised when a requested retrieval profile does not exist.
    """
    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id

        super().__init__(f"Retrieval profile '{profile_id}' could not be resolved.")


# Query / input errors
class RetrievalInputError(RetrievalError):
    """
    Base class for invalid input supplied to the retrieval subsystem.
    """

class RetrievalQueryError(RetrievalInputError):
    """
    Raised when a retrieval query cannot be processed.
    """

class RetrievalFilterError(RetrievalInputError):
    """
    Raised when retrieval filters are invalid or unsupported.
    """

# Repository / persistence errors
class RetrievalRepositoryError(RetrievalError):
    """
    Base exception for failures while reading retrieval data from persistence.

    Infrastructure implementations should translate SQLAlchemy, database-driver, pgvector, or PostgreSQL-specifi
    exceptions into this hierarchy before allowing them to cross into the retrieval application layer.
    """

class VectorRetrievalRepositoryError(RetrievalRepositoryError):
    """
    Raised when vector candidate retrieval fails at the persistence layer.
    """

class LexicalRetrievalRepositoryError(RetrievalRepositoryError):
    """
    Raised when lexical candidate retrieval fails at the persistence layer.
    """

# Embedding / vector retrieval errors
class VectorRetrievalError(RetrievalError):
    """
    Base exception for semantic/vector retrieval failures.
    """

class QueryEmbeddingError(VectorRetrievalError):
    """
    Raised when the user's query cannot be converted into an embedding.
    """

class QueryEmbeddingDimensionError(VectorRetrievalError):
    """
    Raised when a query embedding does not match the configured retrieval embedding dimensions.
    """
    def __init__(self, *, expected_dimensions: int, actual_dimensions: int) -> None:
        self.expected_dimensions = expected_dimensions
        self.actual_dimensions = actual_dimensions
        super().__init__(f"Query embedding dimension mismatch: expected {expected_dimensions}, got {actual_dimensions}.")

class EmbeddingProfileMismatchError(VectorRetrievalError):
    """
    Raised when persisted embeddings are incompatible with the embedding profile selected for retrieval.
    """

class VectorSearchError(VectorRetrievalError):
    """
    Raised when semantic candidate retrieval cannot be completed.
    """


# Lexical retrieval errors
class LexicalRetrievalError(RetrievalError):
    """
    Base exception for lexical/full-text retrieval failures.
    """

class LexicalQueryPreparationError(LexicalRetrievalError):
    """
    Raised when a query cannot be converted into a valid lexical-search form.
    """

class LexicalSearchError(LexicalRetrievalError):
    """
    Raised when lexical candidate retrieval cannot be completed.
    """

# Candidate / ranking errors
class RetrievalCandidateError(RetrievalError):
    """
    Raised when retrieved candidate data violates retrieval-domain invariants.
    """

class RetrievalCandidateProvenanceError(RetrievalCandidateError):
    """
    Raised when required document/version/chunk provenance is missing or inconsistent.
    """

class RetrievalScoreError(RetrievalCandidateError):
    """
    Raised when a retrieval or ranking score is invalid or inconsistent.
    """

# Fusion errors
class RetrievalFusionError(RetrievalError):
    """
    Base exception for failures while combining candidate rankings.
    """

class UnsupportedFusionMethodError(RetrievalFusionError):
    """
    Raised when composition requests a fusion strategy that is unsupported.
    """

    def __init__(self, method: str) -> None:
        self.method = method
        super().__init__(f"Unsupported retrieval fusion method '{method}'.")

class FusionInputError(RetrievalFusionError):
    """
    Raised when candidate rankings supplied to a fusion strategy are invalid.
    """

# Reranking errors
class RerankingError(RetrievalError):
    """
    Base exception for reranking failures.
    """

class RerankerResolutionError(RerankingError):
    """
    Raised when the requested reranker implementation cannot be resolved.
    """
    def __init__(self, reranker_id: str) -> None:
        self.reranker_id = reranker_id

        super().__init__(f"Reranker '{reranker_id}' could not be resolved.")

class RerankerProviderError(RerankingError):
    """
    Raised when an external or local reranking provider fails.
    """

class RerankerResponseError(RerankingError):
    """
    Raised when a reranker returns malformed, incomplete, or inconsistent output.
    """

class RerankerCardinalityError(RerankerResponseError):
    """
    Raised when the number of reranking outputs does not match the number expected for the supplied candidates.
    """
    def __init__(self, *, expected_count: int, actual_count: int) -> None:
        self.expected_count = expected_count
        self.actual_count = actual_count

        super().__init__(f"Reranker result cardinality mismatch: expected {expected_count}, got {actual_count}.")

# Context-building errors
class GroundingContextError(RetrievalError):
    """
    Base exception for failures while constructing LLM grounding context.
    """

class GroundingContextBudgetError(GroundingContextError):
    """
    Raised when context cannot be assembled within the configured budget while preserving required invariants.
    """

class GroundingContextCandidateError(GroundingContextError):
    """
    Raised when a candidate cannot safely be converted into grounding context.
    """

# Pipeline / orchestration errors
class RetrievalPipelineError(RetrievalError):
    """
    Raised when the overall retrieval pipeline cannot complete.

    Lower-level exceptions should generally be chained as the cause:

        raise RetrievalPipelineError(...) from exc

    so observability retains the original failure.
    """

class RetrievalUnavailableError(RetrievalPipelineError):
    """
    Raised when retrieval is temporarily unavailable due to dependencies such as the embedding provider or database being unavailable.
    """

class RetrievalReadinessError(RetrievalPipelineError):
    """
    Raised when the knowledge base is not ready for the configured retrieval operation.

    Examples include:
      - no compatible embeddings exist;
      - required retrieval artifacts have not been generated;
      - configured embedding profile is absent from the active knowledge base.
    """