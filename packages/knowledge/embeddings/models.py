from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Sequence
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EmbeddingProviderDescriptor:
    """
    Stable identity and capabilities of an embedding model.

    This describes the model that produced an embedding. It is deliberately independent of any provider SDK
    so embedding artifacts remain auditable even if provider implementations change.
    """
    provider: str
    model: str
    revision: str | None
    dimensions: int

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        model = self.model.strip()

        if not provider:
            raise ValueError("Embedding provider must not be blank.")

        if not model:
            raise ValueError("Embedding model must not be blank.")

        if self.dimensions <= 0:
            raise ValueError("Embedding dimensions must be greater than zero.")

        revision = self.revision.strip() if self.revision is not None else None
        if revision == "":
            revision = None

        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "revision", revision)

    @property
    def identity(self) -> str:
        if self.revision is None:
            return f"{self.provider}:{self.model}"

        return f"{self.provider}:{self.model}:{self.revision}"


@dataclass(frozen=True, slots=True)
class EmbeddingInputDescriptor:
    """
    Identifies the strategy used to construct model input from canonical knowledge content.

    The model and the input-construction strategy are intentionally separate. Changing either can require re-embedding.
    """
    strategy_id: str
    version: str
    config_fingerprint: str

    def __post_init__(self) -> None:
        strategy_id = self.strategy_id.strip()
        version = self.version.strip()
        config_fingerprint = self.config_fingerprint.strip()

        if not strategy_id:
            raise ValueError("Embedding input strategy_id must not be blank.")

        if not version:
            raise ValueError("Embedding input strategy version must not be blank.")

        if not config_fingerprint:
            raise ValueError("Embedding input config_fingerprint must not be blank.")

        object.__setattr__(self, "strategy_id", strategy_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "config_fingerprint", config_fingerprint)

    @property
    def identity(self) -> str:
        return (f"{self.strategy_id}:{self.version}:{self.config_fingerprint}")


@dataclass(frozen=True, slots=True)
class PreparedEmbeddingInput:
    """
    Exact text prepared for embedding for one canonical knowledge chunk.

    input_fingerprint must identify the exact prepared representation rather than merely the underlying chunk content.
    """
    chunk_id: UUID
    text: str
    input_fingerprint: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Prepared embedding input text must not be blank.")

        fingerprint = self.input_fingerprint.strip()
        if not fingerprint:
            raise ValueError("Prepared embedding input fingerprint must not be blank.")

        object.__setattr__(self, "input_fingerprint", fingerprint)


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    """
    Immutable numerical embedding returned by an embedding provider.
    """
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("Embedding vector must not be empty.")

        normalized_values: list[float] = []

        for value in self.values:
            numeric_value = float(value)

            if not isfinite(numeric_value):
                raise ValueError("Embedding vector must contain only finite values.")

            normalized_values.append(numeric_value)

        object.__setattr__(self, "values", tuple(normalized_values))

    @classmethod
    def from_sequence(cls, values: Sequence[float]) -> EmbeddingVector:
        return cls(values=tuple(values))

    @property
    def dimensions(self) -> int:
        return len(self.values)


@dataclass(frozen=True, slots=True)
class DocumentEmbedding:
    """
    Embedding produced for one prepared document/chunk input.

    input_index preserves correspondence with the provider request batch.
    """
    input_index: int
    vector: EmbeddingVector

    def __post_init__(self) -> None:
        if self.input_index < 0:
            raise ValueError("Embedding input_index must not be negative.")


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    """
    Result of embedding a batch of document inputs.

    Provider adapters normalize their SDK-specific response into this model.
    """
    embeddings: tuple[DocumentEmbedding, ...]
    provider: EmbeddingProviderDescriptor

    def __post_init__(self) -> None:
        seen_indexes: set[int] = set()

        for embedding in self.embeddings:
            if embedding.input_index in seen_indexes:
                raise ValueError("Embedding batch contains duplicate input indexes.")

            seen_indexes.add(embedding.input_index)
            if embedding.vector.dimensions != self.provider.dimensions:
                raise ValueError(f"Embedding vector dimensions do not match provider descriptor: expected {self.provider.dimensions}, received {embedding.vector.dimensions}.")

    @property
    def size(self) -> int:
        return len(self.embeddings)

    def ordered(self) -> tuple[DocumentEmbedding, ...]:
        return tuple(sorted(self.embeddings, key=lambda embedding: embedding.input_index))