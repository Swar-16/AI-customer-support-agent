from __future__ import annotations

from uuid import uuid4

import pytest

from packages.knowledge.embeddings.models import (
    DocumentEmbedding,
    EmbeddingBatch,
    EmbeddingInputDescriptor,
    EmbeddingProviderDescriptor,
    EmbeddingVector,
    PreparedEmbeddingInput,
)


class TestEmbeddingProviderDescriptor:
    def test_valid_descriptor_is_normalized(self) -> None:
        descriptor = EmbeddingProviderDescriptor(
            provider="  provider-x  ",
            model="  model-y  ",
            revision="  rev-1  ",
            dimensions=768,
        )

        assert descriptor.provider == "provider-x"
        assert descriptor.model == "model-y"
        assert descriptor.revision == "rev-1"
        assert descriptor.dimensions == 768
        assert descriptor.identity == "provider-x:model-y:rev-1"

    def test_identity_omits_revision_when_absent(self) -> None:
        descriptor = EmbeddingProviderDescriptor(
            provider="provider-x",
            model="model-y",
            revision=None,
            dimensions=768,
        )

        assert descriptor.identity == "provider-x:model-y"

    def test_blank_revision_is_normalized_to_none(self) -> None:
        descriptor = EmbeddingProviderDescriptor(
            provider="provider-x",
            model="model-y",
            revision="   ",
            dimensions=768,
        )

        assert descriptor.revision is None
        assert descriptor.identity == "provider-x:model-y"

    @pytest.mark.parametrize("provider", ["", " ", "\t", "\n"])
    def test_blank_provider_is_rejected(self, provider: str) -> None:
        with pytest.raises(
            ValueError,
            match="Embedding provider must not be blank",
        ):
            EmbeddingProviderDescriptor(
                provider=provider,
                model="model-y",
                revision=None,
                dimensions=768,
            )

    @pytest.mark.parametrize("model", ["", " ", "\t", "\n"])
    def test_blank_model_is_rejected(self, model: str) -> None:
        with pytest.raises(
            ValueError,
            match="Embedding model must not be blank",
        ):
            EmbeddingProviderDescriptor(
                provider="provider-x",
                model=model,
                revision=None,
                dimensions=768,
            )

    @pytest.mark.parametrize("dimensions", [0, -1, -100])
    def test_non_positive_dimensions_are_rejected(
        self,
        dimensions: int,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="Embedding dimensions must be greater than zero",
        ):
            EmbeddingProviderDescriptor(
                provider="provider-x",
                model="model-y",
                revision=None,
                dimensions=dimensions,
            )


class TestEmbeddingInputDescriptor:
    def test_valid_descriptor_is_normalized(self) -> None:
        descriptor = EmbeddingInputDescriptor(
            strategy_id="  contextual-chunk  ",
            version="  1.0.0  ",
            config_fingerprint="  abc123  ",
        )

        assert descriptor.strategy_id == "contextual-chunk"
        assert descriptor.version == "1.0.0"
        assert descriptor.config_fingerprint == "abc123"
        assert descriptor.identity == "contextual-chunk:1.0.0:abc123"

    @pytest.mark.parametrize(
        ("field_name", "kwargs", "expected_message"),
        [
            (
                "strategy_id",
                {
                    "strategy_id": " ",
                    "version": "1.0.0",
                    "config_fingerprint": "abc123",
                },
                "Embedding input strategy_id must not be blank",
            ),
            (
                "version",
                {
                    "strategy_id": "contextual-chunk",
                    "version": " ",
                    "config_fingerprint": "abc123",
                },
                "Embedding input strategy version must not be blank",
            ),
            (
                "config_fingerprint",
                {
                    "strategy_id": "contextual-chunk",
                    "version": "1.0.0",
                    "config_fingerprint": " ",
                },
                "Embedding input config_fingerprint must not be blank",
            ),
        ],
    )
    def test_blank_fields_are_rejected(
        self,
        field_name: str,
        kwargs: dict[str, str],
        expected_message: str,
    ) -> None:
        del field_name

        with pytest.raises(ValueError, match=expected_message):
            EmbeddingInputDescriptor(**kwargs)


class TestPreparedEmbeddingInput:
    def test_valid_input_is_created(self) -> None:
        chunk_id = uuid4()

        prepared = PreparedEmbeddingInput(
            chunk_id=chunk_id,
            text="Useful knowledge content.",
            input_fingerprint="  deadbeef  ",
        )

        assert prepared.chunk_id == chunk_id
        assert prepared.text == "Useful knowledge content."
        assert prepared.input_fingerprint == "deadbeef"

    @pytest.mark.parametrize("text", ["", " ", "\t", "\n"])
    def test_blank_text_is_rejected(self, text: str) -> None:
        with pytest.raises(
            ValueError,
            match="Prepared embedding input text must not be blank",
        ):
            PreparedEmbeddingInput(
                chunk_id=uuid4(),
                text=text,
                input_fingerprint="abc123",
            )

    @pytest.mark.parametrize("fingerprint", ["", " ", "\t", "\n"])
    def test_blank_fingerprint_is_rejected(
        self,
        fingerprint: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="Prepared embedding input fingerprint must not be blank",
        ):
            PreparedEmbeddingInput(
                chunk_id=uuid4(),
                text="Useful content.",
                input_fingerprint=fingerprint,
            )


class TestEmbeddingVector:
    def test_valid_vector_is_immutable_tuple(self) -> None:
        vector = EmbeddingVector(
            values=(0.1, 0.2, 0.3),
        )

        assert vector.values == (0.1, 0.2, 0.3)
        assert isinstance(vector.values, tuple)
        assert vector.dimensions == 3

    def test_from_sequence_converts_to_tuple(self) -> None:
        source = [0.1, 0.2, 0.3]

        vector = EmbeddingVector.from_sequence(source)

        assert vector.values == (0.1, 0.2, 0.3)
        assert isinstance(vector.values, tuple)

    def test_numeric_values_are_normalized_to_float(self) -> None:
        vector = EmbeddingVector(
            values=(1, 2, 3),
        )

        assert vector.values == (1.0, 2.0, 3.0)

    def test_empty_vector_is_rejected(self) -> None:
        with pytest.raises(
            ValueError,
            match="Embedding vector must not be empty",
        ):
            EmbeddingVector(values=())

    @pytest.mark.parametrize(
        "invalid_value",
        [
            float("nan"),
            float("inf"),
            float("-inf"),
        ],
    )
    def test_non_finite_values_are_rejected(
        self,
        invalid_value: float,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="Embedding vector must contain only finite values",
        ):
            EmbeddingVector(
                values=(0.1, invalid_value, 0.3),
            )


class TestDocumentEmbedding:
    def test_valid_document_embedding_is_created(self) -> None:
        vector = EmbeddingVector(
            values=(0.1, 0.2),
        )

        embedding = DocumentEmbedding(
            input_index=3,
            vector=vector,
        )

        assert embedding.input_index == 3
        assert embedding.vector == vector

    def test_negative_input_index_is_rejected(self) -> None:
        with pytest.raises(
            ValueError,
            match="Embedding input_index must not be negative",
        ):
            DocumentEmbedding(
                input_index=-1,
                vector=EmbeddingVector(values=(0.1,)),
            )


class TestEmbeddingBatch:
    def test_valid_batch_is_created(self) -> None:
        provider = EmbeddingProviderDescriptor(
            provider="provider-x",
            model="model-y",
            revision=None,
            dimensions=2,
        )

        batch = EmbeddingBatch(
            provider=provider,
            embeddings=(
                DocumentEmbedding(
                    input_index=0,
                    vector=EmbeddingVector(values=(0.1, 0.2)),
                ),
                DocumentEmbedding(
                    input_index=1,
                    vector=EmbeddingVector(values=(0.3, 0.4)),
                ),
            ),
        )

        assert batch.provider == provider
        assert batch.size == 2
        assert len(batch.embeddings) == 2

    def test_empty_batch_is_allowed(self) -> None:
        provider = EmbeddingProviderDescriptor(
            provider="provider-x",
            model="model-y",
            revision=None,
            dimensions=2,
        )

        batch = EmbeddingBatch(
            provider=provider,
            embeddings=(),
        )

        assert batch.size == 0

    def test_dimension_mismatch_is_rejected(self) -> None:
        provider = EmbeddingProviderDescriptor(
            provider="provider-x",
            model="model-y",
            revision=None,
            dimensions=3,
        )

        with pytest.raises(
            ValueError,
            match="Embedding vector dimensions do not match provider descriptor",
        ):
            EmbeddingBatch(
                provider=provider,
                embeddings=(
                    DocumentEmbedding(
                        input_index=0,
                        vector=EmbeddingVector(values=(0.1, 0.2)),
                    ),
                ),
            )

    def test_duplicate_input_indexes_are_rejected(self) -> None:
        provider = EmbeddingProviderDescriptor(
            provider="provider-x",
            model="model-y",
            revision=None,
            dimensions=2,
        )

        with pytest.raises(
            ValueError,
            match="Embedding batch contains duplicate input indexes",
        ):
            EmbeddingBatch(
                provider=provider,
                embeddings=(
                    DocumentEmbedding(
                        input_index=0,
                        vector=EmbeddingVector(values=(0.1, 0.2)),
                    ),
                    DocumentEmbedding(
                        input_index=0,
                        vector=EmbeddingVector(values=(0.3, 0.4)),
                    ),
                ),
            )

    def test_ordered_restores_input_order(self) -> None:
        provider = EmbeddingProviderDescriptor(
            provider="provider-x",
            model="model-y",
            revision=None,
            dimensions=2,
        )

        first = DocumentEmbedding(
            input_index=0,
            vector=EmbeddingVector(values=(0.1, 0.2)),
        )
        second = DocumentEmbedding(
            input_index=1,
            vector=EmbeddingVector(values=(0.3, 0.4)),
        )
        third = DocumentEmbedding(
            input_index=2,
            vector=EmbeddingVector(values=(0.5, 0.6)),
        )

        batch = EmbeddingBatch(
            provider=provider,
            embeddings=(third, first, second),
        )

        assert batch.ordered() == (
            first,
            second,
            third,
        )