from __future__ import annotations

from uuid import uuid4

import pytest

from packages.knowledge.domain.embedding import KnowledgeChunkEmbedding
from packages.knowledge.embeddings.models import (
    EmbeddingInputDescriptor,
    EmbeddingProviderDescriptor,
    EmbeddingVector,
)


def make_provider(
    *,
    dimensions: int = 3,
) -> EmbeddingProviderDescriptor:
    return EmbeddingProviderDescriptor(
        provider="test-provider",
        model="test-model",
        revision="v1",
        dimensions=dimensions,
    )


def make_input_descriptor() -> EmbeddingInputDescriptor:
    return EmbeddingInputDescriptor(
        strategy_id="contextual-chunk",
        version="1",
        config_fingerprint="a" * 64,
    )


class TestKnowledgeChunkEmbedding:
    def test_constructs_valid_embedding_artifact(self) -> None:
        embedding_id = uuid4()
        chunk_id = uuid4()

        artifact = KnowledgeChunkEmbedding(
            id=embedding_id,
            chunk_id=chunk_id,
            provider=make_provider(),
            input_descriptor=make_input_descriptor(),
            input_fingerprint="b" * 64,
            vector=EmbeddingVector.from_sequence(
                [0.1, 0.2, 0.3]
            ),
        )

        assert artifact.id == embedding_id
        assert artifact.chunk_id == chunk_id
        assert artifact.provider.provider == "test-provider"
        assert artifact.provider.model == "test-model"
        assert artifact.provider.revision == "v1"
        assert artifact.provider.dimensions == 3

        assert artifact.input_descriptor.strategy_id == "contextual-chunk"
        assert artifact.input_descriptor.version == "1"

        assert artifact.input_fingerprint == "b" * 64
        assert artifact.vector.values == (0.1, 0.2, 0.3)
        assert artifact.created_at is None

    def test_strips_input_fingerprint(self) -> None:
        artifact = KnowledgeChunkEmbedding(
            id=uuid4(),
            chunk_id=uuid4(),
            provider=make_provider(),
            input_descriptor=make_input_descriptor(),
            input_fingerprint=f"  {'b' * 64}  ",
            vector=EmbeddingVector.from_sequence(
                [0.1, 0.2, 0.3]
            ),
        )

        assert artifact.input_fingerprint == "b" * 64

    @pytest.mark.parametrize(
        "input_fingerprint",
        [
            "",
            " ",
            "\t",
            "\n",
            "   \t\n   ",
        ],
    )
    def test_rejects_blank_input_fingerprint(
        self,
        input_fingerprint: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="input_fingerprint must not be blank",
        ):
            KnowledgeChunkEmbedding(
                id=uuid4(),
                chunk_id=uuid4(),
                provider=make_provider(),
                input_descriptor=make_input_descriptor(),
                input_fingerprint=input_fingerprint,
                vector=EmbeddingVector.from_sequence(
                    [0.1, 0.2, 0.3]
                ),
            )

    def test_rejects_vector_dimension_mismatch(self) -> None:
        with pytest.raises(
            ValueError,
            match="Embedding vector dimensions must match provider dimensions",
        ):
            KnowledgeChunkEmbedding(
                id=uuid4(),
                chunk_id=uuid4(),
                provider=make_provider(
                    dimensions=3,
                ),
                input_descriptor=make_input_descriptor(),
                input_fingerprint="b" * 64,
                vector=EmbeddingVector.from_sequence(
                    [0.1, 0.2]
                ),
            )

    def test_artifact_is_immutable(self) -> None:
        artifact = KnowledgeChunkEmbedding(
            id=uuid4(),
            chunk_id=uuid4(),
            provider=make_provider(),
            input_descriptor=make_input_descriptor(),
            input_fingerprint="b" * 64,
            vector=EmbeddingVector.from_sequence(
                [0.1, 0.2, 0.3]
            ),
        )

        with pytest.raises(AttributeError):
            artifact.input_fingerprint = "c" * 64  # type: ignore[misc]
        
    def test_rejects_invalid_fingerprint_length(self) -> None:
        with pytest.raises(
            ValueError,
            match="64-character SHA-256",
        ):
            KnowledgeChunkEmbedding(
                id=uuid4(),
                chunk_id=uuid4(),
                provider=make_provider(),
                input_descriptor=make_input_descriptor(),
                input_fingerprint="abc123",
                vector=EmbeddingVector.from_sequence(
                    [0.1, 0.2, 0.3]
                ),
            )


    def test_rejects_non_hexadecimal_fingerprint(self) -> None:
        with pytest.raises(
            ValueError,
            match="valid hexadecimal SHA-256",
        ):
            KnowledgeChunkEmbedding(
                id=uuid4(),
                chunk_id=uuid4(),
                provider=make_provider(),
                input_descriptor=make_input_descriptor(),
                input_fingerprint="z" * 64,
                vector=EmbeddingVector.from_sequence(
                    [0.1, 0.2, 0.3]
                ),
            )