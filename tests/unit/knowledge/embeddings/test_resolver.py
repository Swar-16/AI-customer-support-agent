from __future__ import annotations

from typing import cast

import pytest

from packages.knowledge.embeddings.errors import (
    EmbeddingProviderResolutionError,
)
from packages.knowledge.embeddings.models import (
    EmbeddingBatch,
    EmbeddingProviderDescriptor,
    EmbeddingVector,
)
from packages.knowledge.embeddings.provider.base import (
    EmbeddingProvider,
)
from packages.knowledge.embeddings.provider.deterministic import (
    DeterministicEmbeddingProvider,
)
from packages.knowledge.embeddings.resolver import (
    EmbeddingProviderResolver,
)


class SecondaryDeterministicProvider(DeterministicEmbeddingProvider):
    """
    Minimal second provider used to verify resolver ordering and lookup.

    It intentionally exposes a different provider identity while reusing the
    deterministic implementation.
    """

    PROVIDER_NAME = "secondary"


class UppercaseProvider(DeterministicEmbeddingProvider):
    """
    Provider whose descriptor uses mixed casing so registration
    normalization can be verified.
    """

    PROVIDER_NAME = "MiXeD-ProViDeR"


class DuplicateDeterministicProvider(DeterministicEmbeddingProvider):
    """
    Another implementation exposing the same provider ID as the default
    deterministic provider but a different model identity.
    """

    MODEL_NAME = "different-model"


class MinimalEmbeddingProvider(EmbeddingProvider):
    """
    Small concrete provider for resolver tests without relying entirely on
    DeterministicEmbeddingProvider behavior.
    """

    def __init__(
        self,
        *,
        provider_id: str,
        model: str = "test-model",
        dimensions: int = 3,
    ) -> None:
        self._descriptor = EmbeddingProviderDescriptor(
            provider=provider_id,
            model=model,
            revision="1",
            dimensions=dimensions,
        )

    @property
    def descriptor(self) -> EmbeddingProviderDescriptor:
        return self._descriptor

    def embed_documents(
        self,
        texts: list[str] | tuple[str, ...],
    ) -> EmbeddingBatch:
        return EmbeddingBatch(
            embeddings=(),
            provider=self.descriptor,
        )

    def embed_query(
        self,
        text: str,
    ) -> EmbeddingVector:
        return EmbeddingVector(
            values=tuple(
                0.0
                for _ in range(self.descriptor.dimensions)
            )
        )


class TestEmbeddingProviderResolverConstruction:
    def test_empty_registry_is_allowed(self) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[],
        )

        assert resolver.provider_ids == ()
        assert resolver.providers == ()

    def test_single_provider_is_registered(self) -> None:
        provider = DeterministicEmbeddingProvider()

        resolver = EmbeddingProviderResolver(
            providers=[provider],
        )

        assert resolver.provider_ids == (
            "deterministic",
        )
        assert resolver.providers == (
            provider,
        )

    def test_multiple_providers_are_registered(self) -> None:
        primary = DeterministicEmbeddingProvider()
        secondary = SecondaryDeterministicProvider()

        resolver = EmbeddingProviderResolver(
            providers=[
                primary,
                secondary,
            ],
        )

        assert set(resolver.provider_ids) == {
            "deterministic",
            "secondary",
        }

    def test_generator_input_is_supported(self) -> None:
        providers = (
            provider
            for provider in [
                DeterministicEmbeddingProvider(),
                SecondaryDeterministicProvider(),
            ]
        )

        resolver = EmbeddingProviderResolver(
            providers=providers,
        )

        assert resolver.provider_ids == (
            "deterministic",
            "secondary",
        )

    def test_provider_ids_are_returned_in_sorted_order(self) -> None:
        first = MinimalEmbeddingProvider(
            provider_id="zeta",
        )
        second = MinimalEmbeddingProvider(
            provider_id="alpha",
        )
        third = MinimalEmbeddingProvider(
            provider_id="middle",
        )

        resolver = EmbeddingProviderResolver(
            providers=[
                first,
                second,
                third,
            ],
        )

        assert resolver.provider_ids == (
            "alpha",
            "middle",
            "zeta",
        )

    def test_providers_are_returned_in_provider_id_order(self) -> None:
        zeta = MinimalEmbeddingProvider(
            provider_id="zeta",
        )
        alpha = MinimalEmbeddingProvider(
            provider_id="alpha",
        )
        middle = MinimalEmbeddingProvider(
            provider_id="middle",
        )

        resolver = EmbeddingProviderResolver(
            providers=[
                zeta,
                alpha,
                middle,
            ],
        )

        assert resolver.providers == (
            alpha,
            middle,
            zeta,
        )


class TestEmbeddingProviderResolverResolution:
    def test_resolve_returns_registered_provider_instance(self) -> None:
        provider = DeterministicEmbeddingProvider()

        resolver = EmbeddingProviderResolver(
            providers=[provider],
        )

        resolved = resolver.resolve(
            "deterministic",
        )

        assert resolved is provider

    def test_resolution_is_case_insensitive(self) -> None:
        provider = DeterministicEmbeddingProvider()

        resolver = EmbeddingProviderResolver(
            providers=[provider],
        )

        assert resolver.resolve(
            "DETERMINISTIC"
        ) is provider

        assert resolver.resolve(
            "Deterministic"
        ) is provider

    def test_resolution_trims_outer_whitespace(self) -> None:
        provider = DeterministicEmbeddingProvider()

        resolver = EmbeddingProviderResolver(
            providers=[provider],
        )

        resolved = resolver.resolve(
            " \t deterministic \n "
        )

        assert resolved is provider

    def test_registration_normalizes_provider_descriptor_identity(
        self,
    ) -> None:
        provider = UppercaseProvider()

        resolver = EmbeddingProviderResolver(
            providers=[provider],
        )

        assert resolver.provider_ids == (
            "mixed-provider",
        )

        assert resolver.resolve(
            "mixed-provider"
        ) is provider

        assert resolver.resolve(
            "MIXED-PROVIDER"
        ) is provider

    def test_unknown_provider_raises_resolution_error(
        self,
    ) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[
                DeterministicEmbeddingProvider(),
            ],
        )

        with pytest.raises(
            EmbeddingProviderResolutionError,
            match="Embedding provider is not registered",
        ) as exc_info:
            resolver.resolve(
                "missing-provider",
            )

        error = exc_info.value

        assert error.code == (
            "embedding_provider_resolution_error"
        )

        assert error.details["provider"] == (
            "missing-provider"
        )

        assert error.details["available_providers"] == (
            "deterministic",
        )

    def test_unknown_provider_from_empty_registry_reports_empty_options(
        self,
    ) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[],
        )

        with pytest.raises(
            EmbeddingProviderResolutionError,
        ) as exc_info:
            resolver.resolve(
                "missing",
            )

        assert (
            exc_info.value.details[
                "available_providers"
            ]
            == ()
        )


class TestProviderIdValidation:
    @pytest.mark.parametrize(
        "provider_id",
        [
            "",
            " ",
            "\t",
            "\n",
            " \t\n ",
        ],
    )
    def test_blank_provider_id_is_rejected(
        self,
        provider_id: str,
    ) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[],
        )

        with pytest.raises(
            EmbeddingProviderResolutionError,
            match=(
                "Embedding provider ID must not be blank"
            ),
        ) as exc_info:
            resolver.resolve(
                provider_id,
            )

        assert exc_info.value.code == (
            "embedding_provider_resolution_error"
        )

    @pytest.mark.parametrize(
        "provider_id",
        [
            None,
            123,
            1.5,
            b"provider",
            object(),
        ],
    )
    def test_non_string_provider_id_is_rejected(
        self,
        provider_id: object,
    ) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[],
        )

        with pytest.raises(
            EmbeddingProviderResolutionError,
            match=(
                "Embedding provider ID must be a string"
            ),
        ) as exc_info:
            resolver.resolve(
                provider_id,  # type: ignore[arg-type]
            )

        assert (
            exc_info.value.details["actual_type"]
            == type(provider_id).__name__
        )


class TestContains:
    def test_contains_returns_true_for_registered_provider(
        self,
    ) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[
                DeterministicEmbeddingProvider(),
            ],
        )

        assert resolver.contains(
            "deterministic"
        ) is True

    def test_contains_is_case_insensitive(self) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[
                DeterministicEmbeddingProvider(),
            ],
        )

        assert resolver.contains(
            "DETERMINISTIC"
        ) is True

    def test_contains_trims_whitespace(self) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[
                DeterministicEmbeddingProvider(),
            ],
        )

        assert resolver.contains(
            "  deterministic  "
        ) is True

    def test_contains_returns_false_for_unknown_provider(
        self,
    ) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[
                DeterministicEmbeddingProvider(),
            ],
        )

        assert resolver.contains(
            "unknown"
        ) is False

    @pytest.mark.parametrize(
        "provider_id",
        [
            "",
            " ",
            "\t",
        ],
    )
    def test_contains_returns_false_for_blank_id(
        self,
        provider_id: str,
    ) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[],
        )

        assert resolver.contains(
            provider_id
        ) is False

    @pytest.mark.parametrize(
        "provider_id",
        [
            None,
            123,
            b"provider",
            object(),
        ],
    )
    def test_contains_returns_false_for_invalid_type(
        self,
        provider_id: object,
    ) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[],
        )

        assert resolver.contains(
            provider_id,  # type: ignore[arg-type]
        ) is False


class TestDuplicateRegistration:
    def test_duplicate_provider_id_is_rejected(self) -> None:
        first = DeterministicEmbeddingProvider()
        duplicate = DuplicateDeterministicProvider()

        with pytest.raises(
            EmbeddingProviderResolutionError,
            match="Duplicate embedding provider ID",
        ) as exc_info:
            EmbeddingProviderResolver(
                providers=[
                    first,
                    duplicate,
                ],
            )

        error = exc_info.value

        assert error.details["provider"] == (
            "deterministic"
        )

        assert error.details["existing_model"] == (
            first.descriptor.model
        )

        assert error.details["duplicate_model"] == (
            duplicate.descriptor.model
        )

    def test_duplicate_provider_id_is_case_insensitive(
        self,
    ) -> None:
        first = MinimalEmbeddingProvider(
            provider_id="Voyage",
            model="model-a",
        )
        duplicate = MinimalEmbeddingProvider(
            provider_id="voyage",
            model="model-b",
        )

        with pytest.raises(
            EmbeddingProviderResolutionError,
            match="Duplicate embedding provider ID",
        ):
            EmbeddingProviderResolver(
                providers=[
                    first,
                    duplicate,
                ],
            )

    def test_duplicate_provider_id_after_whitespace_normalization_is_rejected(
        self,
    ) -> None:
        first = MinimalEmbeddingProvider(
            provider_id="provider-a",
            model="model-a",
        )

        # EmbeddingProviderDescriptor itself trims outer
        # whitespace during construction.
        duplicate = MinimalEmbeddingProvider(
            provider_id="  provider-a  ",
            model="model-b",
        )

        with pytest.raises(
            EmbeddingProviderResolutionError,
            match="Duplicate embedding provider ID",
        ):
            EmbeddingProviderResolver(
                providers=[
                    first,
                    duplicate,
                ],
            )


class TestInvalidProviderRegistration:
    @pytest.mark.parametrize(
        "invalid_provider",
        [
            None,
            42,
            "not-a-provider",
            object(),
        ],
    )
    def test_non_provider_objects_are_rejected(
        self,
        invalid_provider: object,
    ) -> None:
        with pytest.raises(
            EmbeddingProviderResolutionError,
            match=(
                "Registered embedding provider does not "
                "implement EmbeddingProvider"
            ),
        ) as exc_info:
            EmbeddingProviderResolver(
                providers=[
                    cast(
                        EmbeddingProvider,
                        invalid_provider,
                    )
                ],
            )

        assert (
            exc_info.value.details["actual_type"]
            == type(invalid_provider).__name__
        )


class TestResolverExposure:
    def test_provider_ids_returns_tuple_not_mutable_collection(
        self,
    ) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[
                DeterministicEmbeddingProvider(),
            ],
        )

        provider_ids = resolver.provider_ids

        assert isinstance(
            provider_ids,
            tuple,
        )

    def test_providers_returns_tuple_not_registry_mapping(
        self,
    ) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[
                DeterministicEmbeddingProvider(),
            ],
        )

        providers = resolver.providers

        assert isinstance(
            providers,
            tuple,
        )

    def test_modifying_returned_provider_tuple_is_impossible(
        self,
    ) -> None:
        resolver = EmbeddingProviderResolver(
            providers=[
                DeterministicEmbeddingProvider(),
            ],
        )

        providers = resolver.providers

        with pytest.raises(
            TypeError,
        ):
            providers[0] = (
                SecondaryDeterministicProvider()
            )  # type: ignore[index]

    def test_resolver_state_is_unchanged_after_external_collection_changes(
        self,
    ) -> None:
        original = DeterministicEmbeddingProvider()

        source_list: list[EmbeddingProvider] = [
            original,
        ]

        resolver = EmbeddingProviderResolver(
            providers=source_list,
        )

        source_list.clear()
        source_list.append(
            SecondaryDeterministicProvider()
        )

        assert resolver.provider_ids == (
            "deterministic",
        )

        assert resolver.resolve(
            "deterministic"
        ) is original


class TestProviderIdentitySemantics:
    def test_different_models_from_same_provider_are_currently_rejected(
        self,
    ) -> None:
        """
        Current resolver semantics intentionally allow one configured model
        instance per provider ID.

        If we later need multiple models from the same vendor simultaneously,
        that should be introduced through an embedding-profile abstraction
        rather than silently changing this registry contract.
        """
        model_a = MinimalEmbeddingProvider(
            provider_id="voyage",
            model="model-a",
        )
        model_b = MinimalEmbeddingProvider(
            provider_id="voyage",
            model="model-b",
        )

        with pytest.raises(
            EmbeddingProviderResolutionError,
            match="Duplicate embedding provider ID",
        ):
            EmbeddingProviderResolver(
                providers=[
                    model_a,
                    model_b,
                ],
            )