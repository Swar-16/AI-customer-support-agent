from __future__ import annotations
from typing import Any
from uuid import UUID


class KnowledgeEmbeddingError(RuntimeError):
    """
    Base exception for all embedding-related failures.

    Embedding code should raise one of the more specific subclasses below whenever possible so application services can distinguish between:

    - invalid internal state,
    - invalid embedding input,
    - provider failures,
    - malformed provider responses,
    - configuration problems,
    - persistence/integration failures.

    `details` must contain only safe diagnostic metadata. Do not place secrets, API keys, authorization headers, or full user/knowledge content here.
    """
    def __init__(self, message: str, *, code: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = {key: value for key, value in details.items() if value is not None}

    def __str__(self) -> str:
        return super().__str__()

# Configuration / resolution
class EmbeddingConfigurationError(KnowledgeEmbeddingError):
    """
    Invalid embedding configuration supplied by application composition.

    Examples:
    - invalid batch size,
    - invalid configured dimensions,
    - incompatible distance metric,
    - malformed provider configuration.
    """
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, code="embedding_configuration_error", **details)

class EmbeddingProviderNotConfiguredError(KnowledgeEmbeddingError):
    """
    Raised when an embedding operation is requested but no provider has been configured for the requested profile/use case.
    """
    def __init__(self, *, profile: str | None = None) -> None:
        super().__init__("No embedding provider is configured for the requested operation.", code="embedding_provider_not_configured", profile=profile)

class EmbeddingProviderResolutionError(KnowledgeEmbeddingError):
    """
    A configured provider/model identity could not be resolved to an implementation.
    """
    def __init__(self, message: str = "Unable to resolve embedding provider.", *,
                 provider: str | None = None, model: str | None = None, **details: Any
    ) -> None:
        super().__init__(message, code="embedding_provider_resolution_error", provider=provider, model=model, **details)

class EmbeddingInputStrategyResolutionError(KnowledgeEmbeddingError):
    """
    Requested embedding input strategy is unavailable.
    """
    def __init__(self, message: str = "Unable to resolve embedding input strategy.", *, strategy_id: str | None = None, **details: Any) -> None:
        super().__init__(message, code="embedding_input_strategy_resolution_error", strategy_id=strategy_id, **details)

class UnsupportedEmbeddingModelError(KnowledgeEmbeddingError):
    """
    Provider exists but does not support the configured model.
    """
    def __init__(self, *, provider: str, model: str) -> None:
        super().__init__("Configured embedding model is not supported by the provider.", code="unsupported_embedding_model", provider=provider, model=model)


# Input preparation
class EmbeddingInputError(KnowledgeEmbeddingError):
    """
    Base class for failures while converting canonical knowledge content into model-facing embedding input.
    """
    def __init__(self, message: str, *, code: str = "embedding_input_error", **details: Any) -> None:
        super().__init__(message, code=code, **details)


class EmbeddingInputValidationError(EmbeddingInputError):
    """
    Prepared input violates our own invariants.

    Examples:
    - blank text,
    - missing chunk identity,
    - malformed fingerprint,
    - impossible metadata combination.
    """
    def __init__(self, message: str, *, chunk_id: UUID | None = None, **details: Any) -> None:
        super().__init__(message, code="embedding_input_validation_error", chunk_id=chunk_id, **details)

class EmbeddingInputTooLargeError(EmbeddingInputError):
    """
    Prepared input exceeds the provider/model's accepted input limit.

    The limit may eventually be expressed in tokens rather than characters.
    """
    def __init__(self, *, chunk_id: UUID | None = None, actual_size: int | None = None, maximum_size: int | None = None,
                 size_unit: str | None = None, provider: str | None = None, model: str | None = None
    ) -> None:
        super().__init__(
            "Prepared embedding input exceeds the supported model limit.", code="embedding_input_too_large", chunk_id=chunk_id,
            actual_size=actual_size, maximum_size=maximum_size, size_unit=size_unit, provider=provider, model=model
        )

class EmbeddingInputBuildError(EmbeddingInputError):
    """
    Unexpected failure inside an EmbeddingInputBuilder implementation.
    """
    def __init__(self, message: str = "Failed to build embedding input.", *, chunk_id: UUID | None = None,
                 strategy_id: str | None = None, **details: Any,
    ) -> None:
        super().__init__(message, code="embedding_input_build_error", chunk_id=chunk_id, strategy_id=strategy_id, **details)


# Provider execution
class EmbeddingProviderError(KnowledgeEmbeddingError):
    """
    Base class for failures originating from an external/local embedding provider.

    Provider adapters should translate SDK-specific exceptions into these exceptions rather than leaking SDK exception types upward.
    """
    def __init__(self, message: str, *, code: str = "embedding_provider_error", provider: str | None = None,
        model: str | None = None, retryable: bool = False, **details: Any,
    ) -> None:
        super().__init__(message, code=code, provider=provider, model=model, retryable=retryable, **details)
        self.retryable = retryable

class EmbeddingProviderAuthenticationError(EmbeddingProviderError):
    """
    Provider rejected authentication credentials.

    Generally not retryable without configuration changes.
    """
    def __init__(self, *, provider: str | None = None, model: str | None = None) -> None:
        super().__init__(
            "Embedding provider authentication failed.", code="embedding_provider_authentication_error",
            provider=provider, model=model, retryable=False
        )

class EmbeddingProviderAuthorizationError(EmbeddingProviderError):
    """
    Credentials are valid but access to the requested resource/model is denied.
    """
    def __init__(self, *, provider: str | None = None, model: str | None = None) -> None:
        super().__init__(
            "Embedding provider denied access to the requested resource.", code="embedding_provider_authorization_error",
            provider=provider, model=model, retryable=False
        )

class EmbeddingProviderRateLimitError(EmbeddingProviderError):
    """
    Provider throttled the request.
    """
    def __init__(self, *, provider: str | None = None, model: str | None = None, retry_after_seconds: float | None = None) -> None:
        super().__init__(
            "Embedding provider rate limit exceeded.", code="embedding_provider_rate_limit_error",
            provider=provider, model=model, retryable=True, retry_after_seconds=retry_after_seconds
        )

class EmbeddingProviderTimeoutError(EmbeddingProviderError):
    """
    Provider request exceeded our configured timeout.
    """
    def __init__(self, *, provider: str | None = None, model: str | None = None, timeout_seconds: float | None = None) -> None:
        super().__init__(
            "Embedding provider request timed out.", code="embedding_provider_timeout_error",
            provider=provider, model=model, retryable=True, timeout_seconds=timeout_seconds,
        )

class EmbeddingProviderUnavailableError(EmbeddingProviderError):
    """
    Provider is temporarily unavailable or returned a transient service error.
    """
    def __init__(self, *, provider: str | None = None, model: str | None = None, provider_status_code: int | None = None) -> None:
        super().__init__(
            "Embedding provider is temporarily unavailable.", code="embedding_provider_unavailable_error",
            provider=provider, model=model, retryable=True, provider_status_code=provider_status_code,
        )

class EmbeddingProviderConnectionError(EmbeddingProviderError):
    """
    Network/DNS/TLS/connectivity failure while contacting a remote provider.
    """
    def __init__(self, *, provider: str | None = None, model: str | None = None) -> None:
        super().__init__(
            "Unable to connect to embedding provider.", code="embedding_provider_connection_error",
            provider=provider, model=model, retryable=True,
        )

class EmbeddingProviderRequestError(EmbeddingProviderError):
    """
    Provider rejected the request itself.

    Examples:
    - invalid model parameters,
    - input rejected by provider,
    - malformed request payload.

    Usually not retryable without changing the request.
    """
    def __init__(self, message: str = "Embedding provider rejected the request.", *, provider: str | None = None, 
                 model: str | None = None, provider_status_code: int | None = None, **details: Any) -> None:
        super().__init__(
            message, code="embedding_provider_request_error", provider=provider, model=model,
            retryable=False, provider_status_code=provider_status_code, **details,
        )

class EmbeddingProviderExecutionError(EmbeddingProviderError):
    """
    Unexpected provider/SDK failure that does not map cleanly onto one of the known failure categories.
    """
    def __init__(self, message: str = "Unexpected embedding provider execution failure.", *, provider: str | None = None,
                 model: str | None = None, retryable: bool = False, **details: Any
    ) -> None:
        super().__init__(message, code="embedding_provider_execution_error", provider=provider, model=model, retryable=retryable, **details)


# Provider response validation
class EmbeddingResponseError(KnowledgeEmbeddingError):
    """
    Base class for provider responses that violate our embedding contract.
    """
    def __init__(self, message: str, *, code: str = "embedding_response_error", provider: str | None = None,
                 model: str | None = None, **details: Any,
    ) -> None:
        super().__init__(message, code=code, provider=provider, model=model, **details)

class EmbeddingResponseCardinalityError(EmbeddingResponseError):
    """
    Provider returned a different number of embeddings than requested.
    """
    def __init__(self, *, expected_count: int, actual_count: int, provider: str | None = None, model: str | None = None) -> None:
        super().__init__(
            "Embedding provider returned an unexpected number of vectors.", code="embedding_response_cardinality_error",
            provider=provider, model=model, expected_count=expected_count, actual_count=actual_count,
        )

class EmbeddingDimensionMismatchError(EmbeddingResponseError):
    """
    Returned vector dimensionality disagrees with the configured/model descriptor.
    """
    def __init__(self, *, expected_dimensions: int, actual_dimensions: int, provider: str | None = None,
                 model: str | None = None, input_index: int | None = None
    ) -> None:
        super().__init__(
            "Embedding vector dimensionality does not match the expected model dimensionality.", code="embedding_dimension_mismatch",
            provider=provider, model=model, expected_dimensions=expected_dimensions, actual_dimensions=actual_dimensions, input_index=input_index,
        )

class InvalidEmbeddingVectorError(EmbeddingResponseError):
    """
    Provider returned a malformed numerical vector.

    Examples:
    - empty vector,
    - NaN,
    - infinity,
    - non-numeric values.
    """
    def __init__(self, message: str = "Embedding provider returned an invalid vector.", *, provider: str | None = None,
                 model: str | None = None, input_index: int | None = None, **details: Any) -> None:
        super().__init__(message, code="invalid_embedding_vector", provider=provider, model=model, input_index=input_index, **details)

class EmbeddingResponseOrderingError(EmbeddingResponseError):
    """
    Provider response cannot be safely mapped back to the original inputs.

    Useful for providers returning explicit indices/IDs or unordered results.
    """
    def __init__(self, message: str = "Embedding response cannot be mapped safely to request inputs.", *,
                 provider: str | None = None, model: str | None = None, **details: Any
    ) -> None:
        super().__init__(message, code="embedding_response_ordering_error", provider=provider, model=model, **details)

class EmbeddingProviderIdentityMismatchError(EmbeddingResponseError):
    """
    Returned provider/model metadata disagrees with the provider configuration.

    This protects against accidentally persisting vectors under the wrong model provenance.
    """
    def __init__(self, message: str = "Embedding response model identity does not match the configured provider.", *, expected_provider: str | None = None,
                 expected_model: str | None = None, actual_provider: str | None = None, actual_model: str | None = None,
    ) -> None:
        super().__init__(
            message, code="embedding_provider_identity_mismatch", provider=expected_provider,
            model=expected_model, actual_provider=actual_provider, actual_model=actual_model
        )


# Batch orchestration
class EmbeddingBatchError(KnowledgeEmbeddingError):
    """
    Base exception for failures involving batching/orchestration.
    """
    def __init__(self, message: str, *, code: str = "embedding_batch_error", **details: Any) -> None:
        super().__init__(message, code=code, **details)

class EmbeddingBatchConfigurationError(EmbeddingBatchError):
    """
    Invalid batching configuration such as batch_size <= 0.
    """
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, code="embedding_batch_configuration_error", **details)

class EmbeddingBatchExecutionError(EmbeddingBatchError):
    """
    One embedding batch failed while processing a larger version/job.
    """
    def __init__(self, message: str = "Failed to execute embedding batch.", *, batch_index: int | None = None,
                 batch_size: int | None = None, **details: Any
    ) -> None:
        super().__init__(message, code="embedding_batch_execution_error", batch_index=batch_index, batch_size=batch_size, **details)


# Knowledge/version coordination
class EmbeddingVersionError(KnowledgeEmbeddingError):
    """
    Base error for version-level embedding operations.
    """
    def __init__(self, message: str, *, code: str = "embedding_version_error", version_id: UUID | None = None, **details: Any) -> None:
        super().__init__(message, code=code, version_id=version_id, **details)

class EmbeddingVersionNotFoundError(EmbeddingVersionError):
    def __init__(self, *, version_id: UUID) -> None:
        super().__init__("Knowledge document version does not exist.", code="embedding_version_not_found", version_id=version_id)

class EmbeddingVersionNotReadyError(EmbeddingVersionError):
    """
    Version exists but canonical ingestion is not sufficiently complete for embedding.
    """
    def __init__(self, *, version_id: UUID, version_status: str | None = None, ingestion_status: str | None = None) -> None:
        super().__init__(
            "Knowledge document version is not ready for embedding.", code="embedding_version_not_ready",
            version_id=version_id, version_status=version_status, ingestion_status=ingestion_status,
        )

class EmbeddingVersionHasNoChunksError(EmbeddingVersionError):
    """
    A supposedly ready version contains no canonical chunks.
    """
    def __init__(self, *, version_id: UUID) -> None:
        super().__init__("Knowledge document version contains no chunks to embed.", code="embedding_version_has_no_chunks", version_id=version_id)

class EmbeddingArtifactConflictError(EmbeddingVersionError):
    """
    Existing embedding artifact conflicts with the artifact we are attempting to persist.

    This is stronger than normal idempotency: same logical identity but incompatible immutable provenance/vector metadata.
    """
    def __init__(self, message: str = "Existing embedding artifact conflicts with the requested embedding.", *,
                 version_id: UUID | None = None, chunk_id: UUID | None = None, **details: Any
    ) -> None:
        super().__init__(message, code="embedding_artifact_conflict", version_id=version_id, chunk_id=chunk_id, **details)

class EmbeddingReadinessError(EmbeddingVersionError):
    """
    Version does not satisfy the embedding artifacts required for retrieval or publication.

    This will be useful when we later enforce:
        process -> embed -> retrieval-ready -> publish
    """
    def __init__(self, message: str = "Knowledge version is not embedding-ready.", *, version_id: UUID,
                 expected_count: int | None = None, actual_count: int | None = None, **details: Any
    ) -> None:
        super().__init__(message, code="embedding_readiness_error", version_id=version_id,
                         expected_count=expected_count, actual_count=actual_count, **details
        )


# Persistence boundary
class EmbeddingPersistenceError(KnowledgeEmbeddingError):
    """
    Repository/storage-level embedding failure after infrastructure exceptions have been translated into a knowledge embedding error.

    SQLAlchemy/psycopg exceptions should generally not leak above the infrastructure/application boundary.
    """
    def __init__(self, message: str = "Failed to persist embedding artifact.", *,
                 chunk_id: UUID | None = None, version_id: UUID | None = None, **details: Any
    ) -> None:
        super().__init__(message, code="embedding_persistence_error", chunk_id=chunk_id, version_id=version_id, **details,)