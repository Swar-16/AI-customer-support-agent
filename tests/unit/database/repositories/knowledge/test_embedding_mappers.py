from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from packages.database.models.knowledge.chunk_embedding import (
    KnowledgeChunkEmbeddingModel,
)
from packages.database.repositories.knowledge.mappers import (
    chunk_embedding_to_domain,
    chunk_embedding_to_model,
)
from packages.knowledge.domain.embedding import KnowledgeChunkEmbedding
from packages.knowledge.embeddings.models import (
    EmbeddingInputDescriptor,
    EmbeddingProviderDescriptor,
    EmbeddingVector,
)


def make_embedding(
    *,
    revision: str | None = "revision-1",
    created_at: datetime | None = None,
) -> KnowledgeChunkEmbedding:
    return KnowledgeChunkEmbedding(
        id=uuid4(),
        chunk_id=uuid4(),
        provider=EmbeddingProviderDescriptor(
            provider="test-provider",
            model="test-model",
            revision=revision,
            dimensions=3,
        ),
        input_descriptor=EmbeddingInputDescriptor(
            strategy_id="contextual-chunk",
            version="1",
            config_fingerprint="a" * 64,
        ),
        input_fingerprint="b" * 64,
        vector=EmbeddingVector.from_sequence(
            [0.1, -0.2, 0.3]
        ),
        created_at=created_at,
    )


class TestChunkEmbeddingToModel:
    def test_maps_complete_domain_artifact_to_model(self) -> None:
        created_at = datetime(
            2026,
            9,
            1,
            10,
            30,
            tzinfo=UTC,
        )

        embedding = make_embedding(
            created_at=created_at,
        )

        model = chunk_embedding_to_model(embedding)

        assert isinstance(
            model,
            KnowledgeChunkEmbeddingModel,
        )

        assert model.id == embedding.id
        assert model.chunk_id == embedding.chunk_id

        assert model.provider == "test-provider"
        assert model.model == "test-model"
        assert model.model_revision == "revision-1"
        assert model.dimensions == 3

        assert model.input_strategy_id == "contextual-chunk"
        assert model.input_strategy_version == "1"
        assert model.input_config_fingerprint == "a" * 64
        assert model.input_fingerprint == "b" * 64

        assert model.embedding == [0.1, -0.2, 0.3]
        assert model.created_at == created_at

    def test_maps_nullable_model_revision(self) -> None:
        embedding = make_embedding(
            revision=None,
        )

        model = chunk_embedding_to_model(embedding)

        assert model.model_revision is None

    def test_preserves_none_created_at(self) -> None:
        embedding = make_embedding(
            created_at=None,
        )

        model = chunk_embedding_to_model(embedding)

        assert model.created_at is None


class TestChunkEmbeddingToDomain:
    def test_maps_complete_model_to_domain(self) -> None:
        embedding_id = uuid4()
        chunk_id = uuid4()

        created_at = datetime(
            2026,
            9,
            1,
            10,
            30,
            tzinfo=UTC,
        )

        model = KnowledgeChunkEmbeddingModel(
            id=embedding_id,
            chunk_id=chunk_id,
            provider="test-provider",
            model="test-model",
            model_revision="revision-1",
            dimensions=3,
            embedding=[0.1, -0.2, 0.3],
            input_strategy_id="contextual-chunk",
            input_strategy_version="1",
            input_config_fingerprint="a" * 64,
            input_fingerprint="b" * 64,
            created_at=created_at,
        )

        embedding = chunk_embedding_to_domain(model)

        assert isinstance(
            embedding,
            KnowledgeChunkEmbedding,
        )

        assert embedding.id == embedding_id
        assert embedding.chunk_id == chunk_id

        assert embedding.provider.provider == "test-provider"
        assert embedding.provider.model == "test-model"
        assert embedding.provider.revision == "revision-1"
        assert embedding.provider.dimensions == 3

        assert (
            embedding.input_descriptor.strategy_id
            == "contextual-chunk"
        )
        assert embedding.input_descriptor.version == "1"
        assert (
            embedding.input_descriptor.config_fingerprint
            == "a" * 64
        )

        assert embedding.input_fingerprint == "b" * 64

        assert embedding.vector.values == pytest.approx(
            (0.1, -0.2, 0.3)
        )

        assert embedding.created_at == created_at

    def test_maps_nullable_model_revision_to_domain(self) -> None:
        model = KnowledgeChunkEmbeddingModel(
            id=uuid4(),
            chunk_id=uuid4(),
            provider="test-provider",
            model="test-model",
            model_revision=None,
            dimensions=3,
            embedding=[0.1, 0.2, 0.3],
            input_strategy_id="contextual-chunk",
            input_strategy_version="1",
            input_config_fingerprint="a" * 64,
            input_fingerprint="b" * 64,
        )

        embedding = chunk_embedding_to_domain(model)

        assert embedding.provider.revision is None


class TestChunkEmbeddingRoundTrip:
    def test_domain_model_domain_round_trip_preserves_artifact(
        self,
    ) -> None:
        original = make_embedding(
            created_at=datetime(
                2026,
                9,
                1,
                10,
                30,
                tzinfo=UTC,
            ),
        )

        model = chunk_embedding_to_model(original)
        restored = chunk_embedding_to_domain(model)

        assert restored.id == original.id
        assert restored.chunk_id == original.chunk_id

        assert restored.provider == original.provider
        assert (
            restored.input_descriptor
            == original.input_descriptor
        )

        assert (
            restored.input_fingerprint
            == original.input_fingerprint
        )

        assert restored.vector.values == pytest.approx(
            original.vector.values
        )

        assert restored.created_at == original.created_at