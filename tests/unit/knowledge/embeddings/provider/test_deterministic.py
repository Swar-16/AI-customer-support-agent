from __future__ import annotations

import math

import pytest

from packages.knowledge.embeddings.errors import (
    EmbeddingInputValidationError,
)
from packages.knowledge.embeddings.provider.deterministic import (
    DeterministicEmbeddingProvider,
)


class TestDeterministicEmbeddingProviderDescriptor:
    def test_default_descriptor(self) -> None:
        provider = DeterministicEmbeddingProvider()

        descriptor = provider.descriptor

        assert descriptor.provider == "deterministic"
        assert descriptor.model == "sha256-projection"
        assert descriptor.revision == "1"
        assert descriptor.dimensions == 64

    def test_custom_dimensions_are_reflected_in_descriptor(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=128,
        )

        assert provider.descriptor.dimensions == 128

    @pytest.mark.parametrize(
        "dimensions",
        [0, -1, -100],
    )
    def test_non_positive_dimensions_are_rejected(
        self,
        dimensions: int,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="dimensions must be greater than zero",
        ):
            DeterministicEmbeddingProvider(
                dimensions=dimensions,
            )

    def test_normalization_enabled_by_default(self) -> None:
        provider = DeterministicEmbeddingProvider()

        assert provider.normalize is True

    def test_normalization_can_be_disabled(self) -> None:
        provider = DeterministicEmbeddingProvider(
            normalize=False,
        )

        assert provider.normalize is False


class TestDocumentEmbedding:
    def test_single_document_produces_single_embedding(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=16,
        )

        result = provider.embed_documents(
            ["Refunds are available within 30 days."]
        )

        assert result.size == 1
        assert len(result.embeddings) == 1

        embedding = result.embeddings[0]

        assert embedding.input_index == 0
        assert embedding.vector.dimensions == 16

    def test_multiple_documents_preserve_input_indexes(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=8,
        )

        result = provider.embed_documents(
            [
                "First document.",
                "Second document.",
                "Third document.",
            ]
        )

        assert result.size == 3

        assert [
            embedding.input_index
            for embedding in result.embeddings
        ] == [0, 1, 2]

    def test_batch_provider_descriptor_matches_provider(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=8,
        )

        result = provider.embed_documents(
            ["Some document."]
        )

        assert result.provider == provider.descriptor

    def test_empty_document_batch_is_allowed(self) -> None:
        provider = DeterministicEmbeddingProvider()

        result = provider.embed_documents([])

        assert result.size == 0
        assert result.embeddings == ()
        assert result.provider == provider.descriptor

    def test_tuple_input_is_supported(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=8,
        )

        result = provider.embed_documents(
            (
                "Document one.",
                "Document two.",
            )
        )

        assert result.size == 2

    def test_single_string_is_rejected(self) -> None:
        provider = DeterministicEmbeddingProvider()

        with pytest.raises(
            EmbeddingInputValidationError,
            match=(
                "Document embedding input must be a sequence of strings"
            ),
        ):
            provider.embed_documents(
                "This must not be treated as characters."
            )  # type: ignore[arg-type]

    def test_bytes_input_is_rejected(self) -> None:
        provider = DeterministicEmbeddingProvider()

        with pytest.raises(
            EmbeddingInputValidationError,
            match=(
                "Document embedding input must be a sequence of strings"
            ),
        ):
            provider.embed_documents(
                b"invalid"
            )  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "value",
        [
            "",
            " ",
            "\t",
            "\n",
            "   \t\n  ",
        ],
    )
    def test_blank_document_input_is_rejected(
        self,
        value: str,
    ) -> None:
        provider = DeterministicEmbeddingProvider()

        with pytest.raises(
            EmbeddingInputValidationError,
            match=r"texts\[0\] must not be blank",
        ) as exc_info:
            provider.embed_documents([value])

        assert exc_info.value.details["input_index"] == 0

    @pytest.mark.parametrize(
        "value",
        [
            123,
            3.14,
            None,
            object(),
            b"bytes",
        ],
    )
    def test_non_string_document_input_is_rejected(
        self,
        value: object,
    ) -> None:
        provider = DeterministicEmbeddingProvider()

        with pytest.raises(
            EmbeddingInputValidationError,
            match=r"texts\[0\] must be a string",
        ) as exc_info:
            provider.embed_documents(
                [value]  # type: ignore[list-item]
            )

        assert exc_info.value.details["input_index"] == 0
        assert (
            exc_info.value.details["actual_type"]
            == type(value).__name__
        )

    def test_error_reports_correct_failing_input_index(self) -> None:
        provider = DeterministicEmbeddingProvider()

        with pytest.raises(
            EmbeddingInputValidationError,
        ) as exc_info:
            provider.embed_documents(
                [
                    "valid",
                    "still valid",
                    "   ",
                    "never reached",
                ]
            )

        assert exc_info.value.details["input_index"] == 2


class TestQueryEmbedding:
    def test_query_embedding_has_expected_dimensions(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=32,
        )

        vector = provider.embed_query(
            "Where is my refund?"
        )

        assert vector.dimensions == 32

    @pytest.mark.parametrize(
        "value",
        [
            "",
            " ",
            "\t",
            "\n",
        ],
    )
    def test_blank_query_is_rejected(
        self,
        value: str,
    ) -> None:
        provider = DeterministicEmbeddingProvider()

        with pytest.raises(
            EmbeddingInputValidationError,
            match="query must not be blank",
        ):
            provider.embed_query(value)

    @pytest.mark.parametrize(
        "value",
        [
            None,
            42,
            1.5,
            b"bytes",
            object(),
        ],
    )
    def test_non_string_query_is_rejected(
        self,
        value: object,
    ) -> None:
        provider = DeterministicEmbeddingProvider()

        with pytest.raises(
            EmbeddingInputValidationError,
            match="query must be a string",
        ) as exc_info:
            provider.embed_query(
                value  # type: ignore[arg-type]
            )

        assert (
            exc_info.value.details["actual_type"]
            == type(value).__name__
        )


class TestDeterminism:
    def test_same_document_produces_same_vector_repeatedly(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=32,
        )

        first = provider.embed_documents(
            ["Refund requests must be submitted within 30 days."]
        )

        second = provider.embed_documents(
            ["Refund requests must be submitted within 30 days."]
        )

        assert (
            first.embeddings[0].vector
            == second.embeddings[0].vector
        )

    def test_same_document_produces_same_vector_across_instances(
        self,
    ) -> None:
        first_provider = DeterministicEmbeddingProvider(
            dimensions=32,
        )
        second_provider = DeterministicEmbeddingProvider(
            dimensions=32,
        )

        first = first_provider.embed_documents(
            ["Shipping normally takes 3–7 business days."]
        )

        second = second_provider.embed_documents(
            ["Shipping normally takes 3–7 business days."]
        )

        assert (
            first.embeddings[0].vector
            == second.embeddings[0].vector
        )

    def test_same_query_produces_same_vector_across_instances(
        self,
    ) -> None:
        first_provider = DeterministicEmbeddingProvider(
            dimensions=16,
        )
        second_provider = DeterministicEmbeddingProvider(
            dimensions=16,
        )

        first = first_provider.embed_query(
            "How long does shipping take?"
        )

        second = second_provider.embed_query(
            "How long does shipping take?"
        )

        assert first == second

    def test_different_texts_produce_different_vectors(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=32,
        )

        first = provider.embed_documents(
            ["Refund approved."]
        )

        second = provider.embed_documents(
            ["Refund denied."]
        )

        assert (
            first.embeddings[0].vector
            != second.embeddings[0].vector
        )

    def test_same_text_document_and_query_use_different_namespaces(
        self,
    ) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=32,
        )

        text = "How do refunds work?"

        document_vector = provider.embed_documents(
            [text]
        ).embeddings[0].vector

        query_vector = provider.embed_query(text)

        assert document_vector != query_vector

    def test_different_dimensions_change_vector_shape(self) -> None:
        small = DeterministicEmbeddingProvider(
            dimensions=8,
        )
        large = DeterministicEmbeddingProvider(
            dimensions=16,
        )

        text = "Account verification policy."

        small_vector = small.embed_query(text)
        large_vector = large.embed_query(text)

        assert small_vector.dimensions == 8
        assert large_vector.dimensions == 16


class TestNormalization:
    def test_document_vectors_are_l2_normalized_by_default(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=64,
        )

        vector = provider.embed_documents(
            ["Refund and return policy."]
        ).embeddings[0].vector

        norm = math.sqrt(
            math.fsum(
                value * value
                for value in vector.values
            )
        )

        assert norm == pytest.approx(
            1.0,
            rel=1e-12,
            abs=1e-12,
        )

    def test_query_vectors_are_l2_normalized_by_default(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=64,
        )

        vector = provider.embed_query(
            "Can I return my order?"
        )

        norm = math.sqrt(
            math.fsum(
                value * value
                for value in vector.values
            )
        )

        assert norm == pytest.approx(
            1.0,
            rel=1e-12,
            abs=1e-12,
        )

    def test_disabling_normalization_changes_vector(self) -> None:
        normalized_provider = DeterministicEmbeddingProvider(
            dimensions=32,
            normalize=True,
        )

        raw_provider = DeterministicEmbeddingProvider(
            dimensions=32,
            normalize=False,
        )

        text = "Payment failed."

        normalized = normalized_provider.embed_query(text)
        raw = raw_provider.embed_query(text)

        assert normalized != raw

        normalized_norm = math.sqrt(
            math.fsum(
                value * value
                for value in normalized.values
            )
        )

        assert normalized_norm == pytest.approx(1.0)


class TestInputNormalization:
    def test_outer_whitespace_does_not_change_document_vector(
        self,
    ) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=32,
        )

        first = provider.embed_documents(
            ["Refund policy"]
        )

        second = provider.embed_documents(
            ["  Refund policy  \n"]
        )

        assert (
            first.embeddings[0].vector
            == second.embeddings[0].vector
        )

    def test_outer_whitespace_does_not_change_query_vector(
        self,
    ) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=32,
        )

        first = provider.embed_query(
            "Where is my order?"
        )

        second = provider.embed_query(
            "\n  Where is my order?  "
        )

        assert first == second

    def test_internal_whitespace_is_semantically_preserved(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=32,
        )

        first = provider.embed_query(
            "refund policy"
        )

        second = provider.embed_query(
            "refund  policy"
        )

        assert first != second

    def test_case_is_preserved(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=32,
        )

        lower = provider.embed_query(
            "refund policy"
        )

        upper = provider.embed_query(
            "Refund Policy"
        )

        assert lower != upper


class TestUnicode:
    def test_unicode_document_input_is_supported(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=16,
        )

        result = provider.embed_documents(
            [
                "Refunds take 3–7 business days.",
                "Customer’s identity must be verified.",
                "Amount − Fee = Refund.",
            ]
        )

        assert result.size == 3

        for embedding in result.embeddings:
            assert embedding.vector.dimensions == 16

    def test_unicode_is_deterministic(self) -> None:
        first_provider = DeterministicEmbeddingProvider(
            dimensions=16,
        )
        second_provider = DeterministicEmbeddingProvider(
            dimensions=16,
        )

        text = "Refunds take 3–7 days — depending on the bank."

        first = first_provider.embed_query(text)
        second = second_provider.embed_query(text)

        assert first == second

    def test_different_unicode_characters_are_not_collapsed(self) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=32,
        )

        en_dash = provider.embed_query(
            "3–7 days"
        )

        hyphen = provider.embed_query(
            "3-7 days"
        )

        minus = provider.embed_query(
            "3−7 days"
        )

        assert en_dash != hyphen
        assert en_dash != minus
        assert hyphen != minus


class TestVectorIntegrity:
    @pytest.mark.parametrize(
        "dimensions",
        [1, 2, 8, 64, 128],
    )
    def test_all_values_are_finite(
        self,
        dimensions: int,
    ) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=dimensions,
        )

        vector = provider.embed_query(
            "Some retrieval query."
        )

        assert len(vector.values) == dimensions
        assert all(
            math.isfinite(value)
            for value in vector.values
        )

    def test_document_vectors_have_exact_configured_dimensions(
        self,
    ) -> None:
        provider = DeterministicEmbeddingProvider(
            dimensions=37,
        )

        batch = provider.embed_documents(
            [
                "One",
                "Two",
                "Three",
            ]
        )

        assert all(
            embedding.vector.dimensions == 37
            for embedding in batch.embeddings
        )


class TestHealthCheck:
    def test_health_check_uses_base_provider_default(self) -> None:
        provider = DeterministicEmbeddingProvider()

        assert provider.health_check() is True