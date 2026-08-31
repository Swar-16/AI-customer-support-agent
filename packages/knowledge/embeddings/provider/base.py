from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Sequence

from packages.knowledge.embeddings.models import EmbeddingBatch, EmbeddingProviderDescriptor, EmbeddingVector


class EmbeddingProvider(ABC):
    """
    Provider-neutral contract for generating embeddings.

    Implementations may call:
    - a hosted embedding API,
    - a local embedding model,
    - an in-process deterministic test provider,
    - or another embedding backend.

    Higher application layers must depend on this abstraction rather than on any provider SDK.

    Document and query embedding are intentionally separate operations because some embedding models apply different prompting,
    prefixes, pooling behavior, or task configuration depending on whether the text represents indexed content or a search query.
    """
    @property
    @abstractmethod
    def descriptor(self) -> EmbeddingProviderDescriptor:
        """
        Return the stable identity and vector dimensionality of this provider.

        The descriptor must describe the actual model used by this provider instance.
        Persisted embedding artifacts rely on this metadata for provenance, compatibility checks, and re-embedding decisions.
        """
        raise NotImplementedError

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        """
        Generate embeddings for document/chunk inputs.

        Contract
        --------
        - Input order is significant.
        - Every input is expected to correspond to exactly one returned DocumentEmbedding.
        - Returned DocumentEmbedding.input_index values identify the corresponding input positions.
        - All returned vectors must match descriptor.dimensions.
        - Implementations must translate provider/SDK-specific exceptions into exceptions from packages.knowledge.embeddings.errors.
        - Implementations must not silently discard failed inputs.
        - Implementations must not reorder inputs without preserving their input_index mapping.

        The caller remains responsible for higher-level batching across a large knowledge version. A provider implementation may stil
        internally split one request if required by a provider API, provided that the externally visible contract remains unchanged.
        """
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, text: str) -> EmbeddingVector:
        """
        Generate an embedding for a retrieval query.

        Query embedding is a separate method because some embedding models distinguish between document and query representations.

        The returned vector must match descriptor.dimensions.

        Implementations must translate provider/SDK-specific failures into the embedding exception hierarchy.
        """
        raise NotImplementedError

    def health_check(self) -> bool:
        """
        Return whether the provider appears usable.

        The base implementation performs no external I/O and simply reports healthy. Remote providers may
        override this when a meaningful, inexpensive health check exists.

        Application startup should not necessarily call this method eagerly; health/readiness behavior belongs to the composition/API layer.
        """
        return True