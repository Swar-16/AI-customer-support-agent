from __future__ import annotations

import pytest

from packages.application.composition.knowledge_embedding_factory import (
    create_embedding_provider,
)
from packages.config.settings import get_settings
from packages.knowledge.embeddings.provider.jina import (
    JinaEmbeddingProvider,
)


pytestmark = pytest.mark.live_embedding


def test_jina_live_query_embedding() -> None:
    settings = get_settings("development")

    print()
    print("app_env:", settings.app_env)
    print(
        "embedding_provider:",
        settings.embedding_provider,
    )
    print(
        "embedding_dimensions:",
        settings.embedding_dimensions,
    )

    key = settings.jina_api_key

    print(
        "jina_key_fingerprint:",
        (
            f"{key[:6]}...{key[-6:]}"
            if key
            else None
        ),
    )

    if settings.embedding_provider != "jina":
        pytest.skip(
            "Live Jina test requires "
            "EMBEDDING_PROVIDER=jina."
        )

    if not settings.jina_api_key:
        pytest.skip(
            "Live Jina test requires JINA_API_KEY."
        )

    provider = create_embedding_provider(
        settings
    )

    print(
        "provider_type:",
        type(provider).__name__,
    )
    print(
        "provider_descriptor:",
        provider.descriptor,
    )

    assert isinstance(
        provider,
        JinaEmbeddingProvider,
    )

    vector = provider.embed_query(
        "Where is my refund?"
    )

    print(
        "returned_dimensions:",
        vector.dimensions,
    )

    assert (
        vector.dimensions
        == settings.embedding_dimensions
    )


def test_jina_live_document_batch_embedding() -> None:
    settings = get_settings("development")

    if settings.embedding_provider != "jina":
        pytest.skip(
            "Live Jina test requires "
            "EMBEDDING_PROVIDER=jina."
        )

    if not settings.jina_api_key:
        pytest.skip(
            "Live Jina test requires JINA_API_KEY."
        )

    provider = create_embedding_provider(
        settings
    )

    batch = provider.embed_documents(
        [
            "Refunds are processed within seven business days.",
            "Orders may be cancelled before shipment.",
        ]
    )

    assert batch.size == 2

    assert (
        batch.provider.provider
        == "jina"
    )

    assert (
        batch.provider.model
        == settings.jina_embedding_model
    )

    assert (
        batch.provider.dimensions
        == settings.embedding_dimensions
    )

    assert all(
        embedding.vector.dimensions
        == settings.embedding_dimensions
        for embedding in batch.embeddings
    )