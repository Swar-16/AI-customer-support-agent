from __future__ import annotations

import pytest

from packages.application.composition.knowledge_embedding_factory import (
    KnowledgeEmbeddingServices,
    create_embedding_provider,
    create_embedding_provider_resolver,
    create_knowledge_embedding_services,
)
from packages.config.settings import Settings
from packages.knowledge.embeddings.errors import (
    EmbeddingConfigurationError,
    EmbeddingProviderResolutionError,
)
from packages.knowledge.embeddings.provider.deterministic import (
    DeterministicEmbeddingProvider,
)
from packages.knowledge.embeddings.provider.jina import (
    JinaEmbeddingProvider,
)


def make_settings(
    *,
    embedding_provider: str = "deterministic",
    embedding_dimensions: int = 64,
    embedding_batch_size: int = 16,
    jina_api_key: str | None = None,
    jina_embedding_model: str = "jina-embeddings-v4",
    jina_embedding_timeout_seconds: float = 30.0,
) -> Settings:
    """
    Build Settings without depending on any developer machine .env file.

    Database values are irrelevant to these tests but Settings requires them.
    """

    return Settings(
        _env_file=None,
        app_env="test",
        database_name="support_ai_test",
        database_password="test-password",
        embedding_provider=embedding_provider,
        embedding_dimensions=embedding_dimensions,
        embedding_batch_size=embedding_batch_size,
        jina_api_key=jina_api_key,
        jina_embedding_model=jina_embedding_model,
        jina_embedding_timeout_seconds=(
            jina_embedding_timeout_seconds
        ),
    )


class TestCreateEmbeddingProvider:
    def test_creates_deterministic_provider(self) -> None:
        settings = make_settings(
            embedding_provider="deterministic",
            embedding_dimensions=64,
        )

        provider = create_embedding_provider(
            settings
        )

        assert isinstance(
            provider,
            DeterministicEmbeddingProvider,
        )

        assert provider.descriptor.provider == "deterministic"
        assert provider.descriptor.dimensions == 64

    def test_creates_jina_provider(self) -> None:
        settings = make_settings(
            embedding_provider="jina",
            embedding_dimensions=1024,
            jina_api_key="test-jina-key",
        )

        provider = create_embedding_provider(
            settings
        )

        assert isinstance(
            provider,
            JinaEmbeddingProvider,
        )

        descriptor = provider.descriptor

        assert descriptor.provider == "jina"
        assert descriptor.model == "jina-embeddings-v4"
        assert descriptor.dimensions == 1024

    def test_jina_provider_uses_configured_model(self) -> None:
        settings = make_settings(
            embedding_provider="jina",
            embedding_dimensions=512,
            jina_api_key="test-jina-key",
            jina_embedding_model="custom-model",
        )

        provider = create_embedding_provider(
            settings
        )

        assert provider.descriptor.model == "custom-model"
        assert provider.descriptor.dimensions == 512

    def test_provider_identifier_is_normalized(self) -> None:
        settings = make_settings(
            embedding_provider="  DeTeRmInIsTiC  ",
            embedding_dimensions=64,
        )

        provider = create_embedding_provider(
            settings
        )

        assert isinstance(
            provider,
            DeterministicEmbeddingProvider,
        )

    def test_unsupported_provider_raises_resolution_error(
        self,
    ) -> None:
        settings = make_settings(
            embedding_provider="unknown-provider",
        )

        with pytest.raises(
            EmbeddingProviderResolutionError
        ) as exc_info:
            create_embedding_provider(
                settings
            )

        error = exc_info.value

        assert (
            error.details["provider"]
            == "unknown-provider"
        )

    def test_jina_requires_api_key(self) -> None:
        #
        # Settings itself validates this invariant.
        #
        # Therefore constructing Settings is expected to fail before the
        # composition function can be invoked.
        #
        with pytest.raises(
            ValueError
        ):
            make_settings(
                embedding_provider="jina",
                jina_api_key=None,
            )


class TestEmbeddingProviderResolverComposition:
    def test_resolver_contains_configured_provider(
        self,
    ) -> None:
        settings = make_settings(
            embedding_provider="deterministic",
            embedding_dimensions=64,
        )

        resolver = create_embedding_provider_resolver(
            settings
        )

        provider = resolver.resolve(
            "deterministic"
        )

        assert isinstance(
            provider,
            DeterministicEmbeddingProvider,
        )

        assert provider.descriptor.dimensions == 64

    def test_resolver_normalizes_provider_identifier(
        self,
    ) -> None:
        settings = make_settings(
            embedding_provider="deterministic",
        )

        resolver = create_embedding_provider_resolver(
            settings
        )

        provider = resolver.resolve(
            "  DETERMINISTIC  "
        )

        assert isinstance(
            provider,
            DeterministicEmbeddingProvider,
        )


class TestKnowledgeEmbeddingServices:
    def test_builds_embedding_services(self) -> None:
        settings = make_settings(
            embedding_provider="deterministic",
            embedding_dimensions=64,
        )

        services = create_knowledge_embedding_services(
            settings
        )

        assert isinstance(
            services,
            KnowledgeEmbeddingServices,
        )

        assert isinstance(
            services.provider,
            DeterministicEmbeddingProvider,
        )

    def test_services_reuse_same_provider_instance(
        self,
    ) -> None:
        settings = make_settings(
            embedding_provider="deterministic",
            embedding_dimensions=64,
        )

        services = create_knowledge_embedding_services(
            settings
        )

        resolved_provider = services.resolver.resolve(
            "deterministic"
        )

        assert (
            resolved_provider
            is services.provider
        )

    def test_jina_services_reuse_same_provider_instance(
        self,
    ) -> None:
        settings = make_settings(
            embedding_provider="jina",
            embedding_dimensions=1024,
            jina_api_key="test-jina-key",
        )

        services = create_knowledge_embedding_services(
            settings
        )

        resolved_provider = services.resolver.resolve(
            "jina"
        )

        assert (
            resolved_provider
            is services.provider
        )

        assert isinstance(
            services.provider,
            JinaEmbeddingProvider,
        )


class TestCompositionDoesNotPerformNetworkIO:
    def test_constructing_jina_services_does_not_call_provider(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        called = False

        def fail_if_called(
            self: JinaEmbeddingProvider,
            text: str,
        ):
            nonlocal called

            called = True

            raise AssertionError(
                "Embedding provider must not be called "
                "during application composition."
            )

        monkeypatch.setattr(
            JinaEmbeddingProvider,
            "embed_query",
            fail_if_called,
        )

        settings = make_settings(
            embedding_provider="jina",
            embedding_dimensions=1024,
            jina_api_key="test-jina-key",
        )

        services = create_knowledge_embedding_services(
            settings
        )

        assert isinstance(
            services.provider,
            JinaEmbeddingProvider,
        )

        assert called is False