from __future__ import annotations
from dataclasses import dataclass

from packages.config.settings import Settings
from packages.knowledge.embeddings.errors import EmbeddingConfigurationError, EmbeddingProviderResolutionError
from packages.knowledge.embeddings.provider.base import EmbeddingProvider
from packages.knowledge.embeddings.provider.deterministic import DeterministicEmbeddingProvider
from packages.knowledge.embeddings.provider.jina import JinaEmbeddingProvider
from packages.knowledge.embeddings.resolver import EmbeddingProviderResolver


@dataclass(frozen=True, slots=True)
class KnowledgeEmbeddingServices:
    """
    Composition result for the embedding subsystem.

    The concrete provider is exposed because application services such as EmbedKnowledgeVersion will usually need the active provider directly.

    The resolver is also exposed for components that resolve providers by configured provider identity.
    """
    provider: EmbeddingProvider
    resolver: EmbeddingProviderResolver

def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """
    Construct the configured embedding provider.

    This is the only composition-layer function that knows how application configuration maps to concrete embedding-provider implementations.

    Provider implementations themselves must remain unaware of environment variables, Settings, or application composition.
    """
    provider_id = _normalize_provider_id(settings.embedding_provider)
    if provider_id == "jina":
        return _create_jina_provider(settings)

    if provider_id == "deterministic":
        return _create_deterministic_provider(settings)

    raise EmbeddingProviderResolutionError(
        "Configured embedding provider is not supported.",
        provider=provider_id,
        configured_provider=provider_id,
        supported_providers=("deterministic", "jina"),
    )

def create_embedding_provider_resolver(settings: Settings) -> EmbeddingProviderResolver:
    """
    Build an immutable resolver containing the configured provider.

    At present the application has one active embedding provider/profile. If multiple simultaneous embedding profiles are required 
    later, that should be introduced above this layer rather than encoding provider:model strings into this resolver.
    """
    provider = create_embedding_provider(settings)

    return EmbeddingProviderResolver([provider])

def create_knowledge_embedding_services(settings: Settings) -> KnowledgeEmbeddingServices:
    """
    Construct the complete embedding composition for application startup.

    The provider is constructed exactly once and the same instance is placed into the resolver. This is important for providers
    that later own reusable HTTP clients, connection pools, metrics, or rate-limit state.
    """
    provider = create_embedding_provider(settings)

    resolver = EmbeddingProviderResolver([provider])

    return KnowledgeEmbeddingServices(provider=provider, resolver=resolver)

def _create_jina_provider(settings: Settings) -> JinaEmbeddingProvider:
    api_key = settings.jina_api_key
    if api_key is None or not api_key.strip():
        raise EmbeddingConfigurationError(
            "Jina API key is required when Jina is the active embedding provider.",
            provider="jina",
            configuration_field="jina_api_key",
        )

    model = settings.jina_embedding_model.strip()
    if not model:
        raise EmbeddingConfigurationError(
            "Jina embedding model must not be blank.",
            provider="jina",
            configuration_field="jina_embedding_model",
        )

    dimensions = settings.embedding_dimensions
    if dimensions <= 0:
        raise EmbeddingConfigurationError(
            "Embedding dimensions must be greater than zero.",
            provider="jina",
            configuration_field="embedding_dimensions",
            configured_value=dimensions,
        )

    timeout_seconds = settings.jina_embedding_timeout_seconds
    if timeout_seconds <= 0:
        raise EmbeddingConfigurationError(
            "Jina embedding timeout must be greater than zero.",
            provider="jina",
            configuration_field="jina_embedding_timeout_seconds",
            configured_value=timeout_seconds,
        )

    return JinaEmbeddingProvider(
        api_key=api_key,
        model=model,
        dimensions=dimensions,
        timeout_seconds=timeout_seconds,
    )

def _create_deterministic_provider(settings: Settings) -> DeterministicEmbeddingProvider:
    dimensions = settings.embedding_dimensions
    if dimensions <= 0:
        raise EmbeddingConfigurationError(
            "Embedding dimensions must be greater than zero.",
            provider="deterministic",
            configuration_field="embedding_dimensions",
            configured_value=dimensions,
        )

    return DeterministicEmbeddingProvider(dimensions=dimensions)

def _normalize_provider_id(provider_id: str) -> str:
    if not isinstance(provider_id, str):
        raise EmbeddingConfigurationError(
            "Embedding provider identifier must be a string.",
            configuration_field="embedding_provider",
            actual_type=type(provider_id).__name__,
        )

    normalized = provider_id.strip().lower()
    if not normalized:
        raise EmbeddingConfigurationError(
            "Embedding provider identifier must not be blank.",
            configuration_field="embedding_provider",
        )

    return normalized