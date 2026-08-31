from __future__ import annotations
from collections.abc import Iterable, Mapping
from types import MappingProxyType

from packages.knowledge.embeddings.errors import EmbeddingProviderResolutionError
from packages.knowledge.embeddings.provider.base import EmbeddingProvider


class EmbeddingProviderResolver:
    """
    Immutable registry for resolving embedding providers by stable provider ID.

    The resolver is constructed during application composition and should not be mutated at runtime.

    Typical composition:

        resolver = EmbeddingProviderResolver(
            providers=[
                deterministic_provider,
                voyage_provider,
            ]
        )

        provider = resolver.resolve("voyage")

    Provider IDs are derived from each provider's descriptor.provider field.
    """
    def __init__(self, providers: Iterable[EmbeddingProvider]) -> None:
        registry: dict[str, EmbeddingProvider] = {}

        for provider in providers:
            self._register(registry=registry, provider=provider)

        self._providers: Mapping[str, EmbeddingProvider] = MappingProxyType(registry)

    @property
    def provider_ids(self) -> tuple[str, ...]:
        """
        Return all registered provider IDs in deterministic sorted order.
        """
        return tuple(sorted(self._providers))

    @property
    def providers(self) -> tuple[EmbeddingProvider, ...]:
        """
        Return registered provider instances in deterministic provider-ID order.

        The returned tuple cannot mutate the resolver registry.
        """
        return tuple(self._providers[provider_id] for provider_id in self.provider_ids)

    def resolve(self, provider_id: str) -> EmbeddingProvider:
        """
        Resolve one configured embedding provider.

        Provider IDs are normalized by trimming outer whitespace and using case-insensitive matching.

        Examples:

            resolve("voyage")
            resolve(" Voyage ")
            resolve("VOYAGE")

        all resolve the same registered provider whose descriptor provider ID is "voyage".
        """
        normalized_id = self._normalize_provider_id(provider_id)
        provider = self._providers.get(normalized_id)
        if provider is None:
            raise EmbeddingProviderResolutionError(
                "Embedding provider is not registered.",
                provider=normalized_id,
                available_providers=self.provider_ids,
            )

        return provider

    def contains(self, provider_id: str) -> bool:
        """
        Return whether a provider ID is registered.

        Invalid or blank provider IDs return False rather than raising because this method is intended as a safe membership check.
        """
        try:
            normalized_id = self._normalize_provider_id(provider_id)
            
        except EmbeddingProviderResolutionError:
            return False

        return normalized_id in self._providers

    def _register(self, *, registry: dict[str, EmbeddingProvider], provider: EmbeddingProvider) -> None:
        if not isinstance(provider, EmbeddingProvider):
            raise EmbeddingProviderResolutionError(
                "Registered embedding provider does not implement "
                "EmbeddingProvider.",
                actual_type=type(provider).__name__,
            )

        descriptor = provider.descriptor
        provider_id = self._normalize_provider_id(descriptor.provider)
        if provider_id in registry:
            existing = registry[provider_id]
            raise EmbeddingProviderResolutionError(
                "Duplicate embedding provider ID.",
                provider=provider_id,
                existing_model=existing.descriptor.model,
                duplicate_model=descriptor.model,
            )
            
        registry[provider_id] = provider

    @staticmethod
    def _normalize_provider_id(provider_id: str) -> str:
        if not isinstance(provider_id, str):
            raise EmbeddingProviderResolutionError("Embedding provider ID must be a string.", actual_type=type(provider_id).__name__)

        normalized = provider_id.strip().lower()
        if not normalized:
            raise EmbeddingProviderResolutionError("Embedding provider ID must not be blank.")

        return normalized