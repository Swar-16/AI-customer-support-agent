from __future__ import annotations
import hashlib
import math
from collections.abc import Sequence

from packages.knowledge.embeddings.errors import EmbeddingInputValidationError, EmbeddingResponseCardinalityError, EmbeddingDimensionMismatchError
from packages.knowledge.embeddings.models import DocumentEmbedding, EmbeddingBatch, EmbeddingProviderDescriptor, EmbeddingVector
from packages.knowledge.embeddings.provider.base import EmbeddingProvider


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic embedding provider intended for tests and local development.

    This provider does not call any external API and does not attempt to model real semantic similarity. Its purpose is to provide:

    - repeatable vectors across processes and machines,
    - stable dimensionality,
    - deterministic document/query embeddings,
    - realistic provider contract behavior,
    - fast and dependency-free unit/integration tests.

    It MUST NOT be used as a production retrieval model.
    """
    PROVIDER_NAME = "deterministic"
    MODEL_NAME = "sha256-projection"
    MODEL_REVISION = "1"
    DEFAULT_DIMENSIONS = 64

    def __init__(self, *, dimensions: int = DEFAULT_DIMENSIONS, normalize: bool = True) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be greater than zero.")

        self._normalize = normalize

        self._descriptor = EmbeddingProviderDescriptor(
            provider=self.PROVIDER_NAME,
            model=self.MODEL_NAME,
            revision=self.MODEL_REVISION,
            dimensions=dimensions,
        )

    @property
    def descriptor(self) -> EmbeddingProviderDescriptor:
        return self._descriptor

    @property
    def normalize(self) -> bool:
        return self._normalize

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        """
        Embed document/chunk text while preserving input ordering.

        Empty batches are allowed because EmbeddingBatch itself permits them.
        Application-level workflows may impose stronger non-empty requirements.
        """
        normalized_texts = self._validate_document_inputs(texts)
        embeddings = tuple(
            DocumentEmbedding(
                input_index=index,
                vector=self._embed_text(text=text, task="document"),
            )
            for index, text in enumerate(normalized_texts)
        )

        batch = EmbeddingBatch(embeddings=embeddings, provider=self.descriptor)
        self._validate_batch_contract(batch=batch, expected_count=len(normalized_texts))

        return batch

    def embed_query(self, text: str) -> EmbeddingVector:
        normalized_text = self._validate_single_text(text, field_name="query")
        vector = self._embed_text(text=normalized_text, task="query")
        if vector.dimensions != self.descriptor.dimensions:
            raise EmbeddingDimensionMismatchError(
                expected_dimensions=self.descriptor.dimensions,
                actual_dimensions=vector.dimensions,
                provider=self.descriptor.provider,
                model=self.descriptor.model,
            )

        return vector

    def _validate_document_inputs(self, texts: Sequence[str]) -> tuple[str, ...]:
        """
        Validate one document embedding request.

        Strings themselves are rejected as Sequence inputs because otherwise:

            embed_documents("hello")

        would silently be interpreted as five independent inputs:
        "h", "e", "l", "l", "o".
        """
        if isinstance(texts, (str, bytes)):
            raise EmbeddingInputValidationError("Document embedding input must be a sequence of strings, not a single string.")

        normalized: list[str] = []

        for index, text in enumerate(texts):
            try:
                normalized_text = self._validate_single_text(text, field_name=f"texts[{index}]")
                
            except EmbeddingInputValidationError as exc:
                exc.details.setdefault("input_index", index)
                raise

            normalized.append(normalized_text)

        return tuple(normalized)

    @staticmethod
    def _validate_single_text(text: str, *, field_name: str) -> str:
        if not isinstance(text, str):
            raise EmbeddingInputValidationError(f"{field_name} must be a string.", actual_type=type(text).__name__)

        normalized = text.strip()
        if not normalized:
            raise EmbeddingInputValidationError(f"{field_name} must not be blank.")

        return normalized

    def _embed_text(self, *, text: str, task: str) -> EmbeddingVector:
        """
        Convert text into a deterministic fixed-dimensional vector.

        The construction deliberately includes:
        - model identity,
        - model revision,
        - task type,
        - vector position,
        - exact normalized UTF-8 input text.

        Including task type ensures document and query vectors are generated through distinct deterministic namespaces,
        mirroring real providers that differentiate retrieval-document and retrieval-query tasks.
        """
        values = tuple(
            self._value_for_dimension(text=text, task=task, dimension_index=index)
            for index in range(self.descriptor.dimensions)
        )

        if self._normalize:
            values = self._l2_normalize(values)

        return EmbeddingVector(values=values)

    def _value_for_dimension(self, *, text: str, task: str, dimension_index: int) -> float:
        payload = (
            f"provider={self.descriptor.provider}\nmodel={self.descriptor.model}\nrevision={self.descriptor.revision or ''}\n"
            f"task={task}\ndimension={dimension_index}\ntext={text}").encode("utf-8")

        digest = hashlib.sha256(payload).digest()

        # Read the first 8 bytes as an unsigned 64-bit integer.
        integer = int.from_bytes(digest[:8], byteorder="big", signed=False)
        max_uint64 = (1 << 64) - 1

        # Map [0, 2^64 - 1] approximately into [-1.0, 1.0].
        return (2.0 * (integer / max_uint64) - 1.0)

    @staticmethod
    def _l2_normalize(values: tuple[float, ...]) -> tuple[float, ...]:
        norm_squared = math.fsum(value * value for value in values)

        if norm_squared <= 0.0:
            # Practically impossible with the hash construction, but handling this explicitly protects the provider contract.
            return values

        norm = math.sqrt(norm_squared)

        return tuple(value / norm for value in values)

    def _validate_batch_contract(self, *, batch: EmbeddingBatch, expected_count: int) -> None:
        if batch.size != expected_count:
            raise EmbeddingResponseCardinalityError(
                expected_count=expected_count,
                actual_count=batch.size,
                provider=self.descriptor.provider,
                model=self.descriptor.model,
            )

        for embedding in batch.embeddings:
            if embedding.vector.dimensions != self.descriptor.dimensions:
                raise EmbeddingDimensionMismatchError(
                    expected_dimensions=self.descriptor.dimensions,
                    actual_dimensions=embedding.vector.dimensions,
                    provider=self.descriptor.provider,
                    model=self.descriptor.model,
                    input_index=embedding.input_index,
                )