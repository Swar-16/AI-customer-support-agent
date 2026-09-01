from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from packages.knowledge.application.embed_version import (
    EmbedKnowledgeVersion,
    EmbedKnowledgeVersionCommand,
)
from packages.knowledge.domain.chunk import KnowledgeChunk
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.embedding import KnowledgeChunkEmbedding
from packages.knowledge.domain.enums import (
    KnowledgeContentType,
    KnowledgeDocumentStatus,
    KnowledgeIngestionStatus,
    KnowledgeSourceType,
    KnowledgeVersionStatus,
    KnowledgeVisibility,
)
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.embeddings.errors import (
    EmbeddingVersionHasNoChunksError,
    EmbeddingVersionNotFoundError,
    EmbeddingVersionNotReadyError,
)
from packages.knowledge.embeddings.models import (
    DocumentEmbedding,
    EmbeddingBatch,
    EmbeddingInputDescriptor,
    EmbeddingProviderDescriptor,
    EmbeddingVector,
    PreparedEmbeddingInput,
)
from packages.knowledge.embeddings import EmbeddingInputBuilder, EmbeddingProvider


# ============================================================================
# Test doubles
# ============================================================================


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        dimensions: int = 3,
    ) -> None:
        self._descriptor = EmbeddingProviderDescriptor(
            provider="fake",
            model="fake-embedding-model",
            revision="1",
            dimensions=dimensions,
        )

        self.calls: list[list[str]] = []

    @property
    def descriptor(
        self,
    ) -> EmbeddingProviderDescriptor:
        return self._descriptor

    def embed_documents(
        self,
        texts: list[str],
    ) -> EmbeddingBatch:
        self.calls.append(list(texts))

        embeddings = tuple(
            DocumentEmbedding(
                input_index=index,
                vector=EmbeddingVector.from_sequence(
                    [
                        float(index + 1),
                        float(index + 2),
                        float(index + 3),
                    ]
                ),
            )
            for index, _ in enumerate(texts)
        )

        return EmbeddingBatch(
            embeddings=embeddings,
            provider=self._descriptor,
        )

    def embed_query(
        self,
        text: str,
    ) -> EmbeddingVector:
        return EmbeddingVector.from_sequence(
            [1.0, 2.0, 3.0]
        )


class FakeEmbeddingInputBuilder(EmbeddingInputBuilder):
    @property
    def descriptor(
        self,
    ) -> EmbeddingInputDescriptor:
        return EmbeddingInputDescriptor(
            strategy_id="contextual-chunk",
            version="1",
            config_fingerprint="a" * 64,
        )

    def build(
        self,
        *,
        chunk: KnowledgeChunk,
        document_title: str,
    ) -> PreparedEmbeddingInput:
        text = (
            f"Document: {document_title}\n"
            f"Section: {chunk.section_title or ''}\n\n"
            f"{chunk.content}"
        )

        # A deterministic fake fingerprint is sufficient here because
        # fingerprint-generation behavior belongs to the builder's own tests.
        fingerprint = (
            f"{chunk.chunk_index:064x}"
        )

        return PreparedEmbeddingInput(
            chunk_id=chunk.id,
            text=text,
            input_fingerprint=fingerprint,
        )


class FakeVersionRepository:
    def __init__(
        self,
        versions: dict[
            UUID,
            KnowledgeDocumentVersion,
        ],
    ) -> None:
        self._versions = versions

    def get_by_id(
        self,
        version_id: UUID,
    ) -> KnowledgeDocumentVersion | None:
        return self._versions.get(version_id)


class FakeDocumentRepository:
    def __init__(
        self,
        documents: dict[
            UUID,
            KnowledgeDocument,
        ],
    ) -> None:
        self._documents = documents

    def get_by_id(
        self,
        document_id: UUID,
    ) -> KnowledgeDocument | None:
        return self._documents.get(document_id)


class FakeChunkRepository:
    def __init__(
        self,
        chunks_by_version: dict[
            UUID,
            list[KnowledgeChunk],
        ],
    ) -> None:
        self._chunks_by_version = chunks_by_version

    def list_for_version(
        self,
        version_id: UUID,
    ) -> list[KnowledgeChunk]:
        return list(
            self._chunks_by_version.get(
                version_id,
                [],
            )
        )


class FakeEmbeddingRepository:
    def __init__(
        self,
        artifacts: list[
            KnowledgeChunkEmbedding
        ]
        | None = None,
    ) -> None:
        self.artifacts = list(
            artifacts or []
        )

    def list_for_chunks(
        self,
        chunk_ids: list[UUID],
        *,
        provider: EmbeddingProviderDescriptor,
        input_descriptor: EmbeddingInputDescriptor,
    ) -> list[KnowledgeChunkEmbedding]:
        chunk_id_set = set(chunk_ids)

        return [
            artifact
            for artifact in self.artifacts
            if artifact.chunk_id in chunk_id_set
            and artifact.provider == provider
            and artifact.input_descriptor
            == input_descriptor
        ]

    def add_many(
        self,
        artifacts: list[
            KnowledgeChunkEmbedding
        ],
    ) -> None:
        self.artifacts.extend(
            artifacts
        )
        
    def add_many_if_absent(
        self,
        artifacts: list[KnowledgeChunkEmbedding],
    ) -> int:
        existing_keys = {
            (
                artifact.chunk_id,
                artifact.provider,
                artifact.input_descriptor,
                artifact.input_fingerprint,
            )
            for artifact in self.artifacts
        }

        created = 0

        for artifact in artifacts:
            key = (
                artifact.chunk_id,
                artifact.provider,
                artifact.input_descriptor,
                artifact.input_fingerprint,
            )

            if key in existing_keys:
                continue

            self.artifacts.append(artifact)
            existing_keys.add(key)
            created += 1

        return created


class FakeKnowledgeUnitOfWork:
    def __init__(
        self,
        *,
        versions: FakeVersionRepository,
        documents: FakeDocumentRepository,
        chunks: FakeChunkRepository,
        embeddings: FakeEmbeddingRepository,
    ) -> None:
        self.versions = versions
        self.documents = documents
        self.chunks = chunks
        self.embeddings = embeddings

        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        if exc_type is not None:
            self.rollback_count += 1

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


@dataclass
class FakeUoWFactory:
    versions: FakeVersionRepository
    documents: FakeDocumentRepository
    chunks: FakeChunkRepository
    embeddings: FakeEmbeddingRepository

    def __call__(
        self,
    ) -> FakeKnowledgeUnitOfWork:
        return FakeKnowledgeUnitOfWork(
            versions=self.versions,
            documents=self.documents,
            chunks=self.chunks,
            embeddings=self.embeddings,
        )


# ============================================================================
# Fixtures / factories
# ============================================================================


def make_ready_version(
    *,
    version_id: UUID,
    document_id: UUID,
) -> KnowledgeDocumentVersion:
    now = datetime.now(
        timezone.utc
    )

    return KnowledgeDocumentVersion(
        id=version_id,
        document_id=document_id,
        version_number=1,
        source_type=KnowledgeSourceType.PLAIN_TEXT,
        source_content="Knowledge source.",
        content_hash="f" * 64,
        status=KnowledgeVersionStatus.READY,
        ingestion_status=(
            KnowledgeIngestionStatus.COMPLETED
        ),
        created_at=now,
        updated_at=now,
        processing_started_at=now,
        processing_completed_at=now,
        ready_at=now,
    )


def make_document(
    *,
    document_id: UUID,
) -> KnowledgeDocument:
    now = datetime.now(
        timezone.utc
    )

    return KnowledgeDocument(
        id=document_id,
        title="Refund Policy",
        description=None,
        content_type=KnowledgeContentType.POLICY,
        visibility=KnowledgeVisibility.CUSTOMER,
        status=KnowledgeDocumentStatus.ACTIVE,
        metadata={},
        created_at=now,
        updated_at=now,
    )


def make_chunk(
    *,
    version_id: UUID,
    chunk_index: int,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=uuid4(),
        version_id=version_id,
        chunk_index=chunk_index,
        content=(
            f"Knowledge chunk {chunk_index}."
        ),
        section_title="Refunds",
        metadata={},
    )


def build_service(
    *,
    version: KnowledgeDocumentVersion,
    document: KnowledgeDocument,
    chunks: list[KnowledgeChunk],
    existing_embeddings: list[
        KnowledgeChunkEmbedding
    ]
    | None = None,
    batch_size: int = 32,
):
    embedding_repository = (
        FakeEmbeddingRepository(
            existing_embeddings
        )
    )

    uow_factory = FakeUoWFactory(
        versions=FakeVersionRepository(
            {
                version.id: version,
            }
        ),
        documents=FakeDocumentRepository(
            {
                document.id: document,
            }
        ),
        chunks=FakeChunkRepository(
            {
                version.id: chunks,
            }
        ),
        embeddings=embedding_repository,
    )

    provider = FakeEmbeddingProvider()
    builder = FakeEmbeddingInputBuilder()

    service = EmbedKnowledgeVersion(
        uow_factory=uow_factory,
        provider=provider,
        input_builder=builder,
        batch_size=batch_size,
    )

    return (
        service,
        provider,
        builder,
        embedding_repository,
    )


# ============================================================================
# Tests
# ============================================================================


class TestEmbedKnowledgeVersionHappyPath:
    def test_embeds_all_missing_chunks(
        self,
    ) -> None:
        document_id = uuid4()
        version_id = uuid4()

        version = make_ready_version(
            version_id=version_id,
            document_id=document_id,
        )

        document = make_document(
            document_id=document_id,
        )

        chunks = [
            make_chunk(
                version_id=version_id,
                chunk_index=0,
            ),
            make_chunk(
                version_id=version_id,
                chunk_index=1,
            ),
        ]

        (
            service,
            provider,
            builder,
            repository,
        ) = build_service(
            version=version,
            document=document,
            chunks=chunks,
        )

        result = service.execute(
            EmbedKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        assert result.version_id == version_id
        assert result.document_id == document_id

        assert result.total_chunks == 2
        assert result.created_count == 2
        assert result.existing_count == 0

        assert (
            result.provider_identity
            == provider.descriptor.identity
        )

        assert (
            result.input_strategy_identity
            == builder.descriptor.identity
        )

        assert len(repository.artifacts) == 2

        assert {
            artifact.chunk_id
            for artifact in repository.artifacts
        } == {
            chunks[0].id,
            chunks[1].id,
        }

        assert len(provider.calls) == 1
        assert len(provider.calls[0]) == 2


class TestEmbedKnowledgeVersionIdempotency:
    def test_existing_exact_artifacts_are_not_reembedded(
        self,
    ) -> None:
        document_id = uuid4()
        version_id = uuid4()

        version = make_ready_version(
            version_id=version_id,
            document_id=document_id,
        )

        document = make_document(
            document_id=document_id,
        )

        chunk = make_chunk(
            version_id=version_id,
            chunk_index=0,
        )

        provider = FakeEmbeddingProvider()
        builder = FakeEmbeddingInputBuilder()

        prepared = builder.build(
            chunk=chunk,
            document_title=document.title,
        )

        existing = KnowledgeChunkEmbedding(
            id=uuid4(),
            chunk_id=chunk.id,
            provider=provider.descriptor,
            input_descriptor=builder.descriptor,
            input_fingerprint=(
                prepared.input_fingerprint
            ),
            vector=EmbeddingVector.from_sequence(
                [1.0, 2.0, 3.0]
            ),
        )

        repository = FakeEmbeddingRepository(
            [existing]
        )

        factory = FakeUoWFactory(
            versions=FakeVersionRepository(
                {
                    version_id: version,
                }
            ),
            documents=FakeDocumentRepository(
                {
                    document_id: document,
                }
            ),
            chunks=FakeChunkRepository(
                {
                    version_id: [chunk],
                }
            ),
            embeddings=repository,
        )

        service = EmbedKnowledgeVersion(
            uow_factory=factory,
            provider=provider,
            input_builder=builder,
        )

        result = service.execute(
            EmbedKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        assert result.total_chunks == 1
        assert result.existing_count == 1
        assert result.created_count == 0

        assert provider.calls == []

        assert len(
            repository.artifacts
        ) == 1


class TestEmbedKnowledgeVersionPartialReuse:
    def test_only_missing_chunks_are_sent_to_provider(
        self,
    ) -> None:
        document_id = uuid4()
        version_id = uuid4()

        version = make_ready_version(
            version_id=version_id,
            document_id=document_id,
        )

        document = make_document(
            document_id=document_id,
        )

        first = make_chunk(
            version_id=version_id,
            chunk_index=0,
        )

        second = make_chunk(
            version_id=version_id,
            chunk_index=1,
        )

        provider = FakeEmbeddingProvider()
        builder = FakeEmbeddingInputBuilder()

        prepared_first = builder.build(
            chunk=first,
            document_title=document.title,
        )

        existing = KnowledgeChunkEmbedding(
            id=uuid4(),
            chunk_id=first.id,
            provider=provider.descriptor,
            input_descriptor=builder.descriptor,
            input_fingerprint=(
                prepared_first.input_fingerprint
            ),
            vector=EmbeddingVector.from_sequence(
                [1.0, 2.0, 3.0]
            ),
        )

        repository = FakeEmbeddingRepository(
            [existing]
        )

        service = EmbedKnowledgeVersion(
            uow_factory=FakeUoWFactory(
                versions=FakeVersionRepository(
                    {
                        version_id: version,
                    }
                ),
                documents=FakeDocumentRepository(
                    {
                        document_id: document,
                    }
                ),
                chunks=FakeChunkRepository(
                    {
                        version_id: [
                            first,
                            second,
                        ],
                    }
                ),
                embeddings=repository,
            ),
            provider=provider,
            input_builder=builder,
        )

        result = service.execute(
            EmbedKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        assert result.total_chunks == 2
        assert result.existing_count == 1
        assert result.created_count == 1

        assert len(provider.calls) == 1
        assert len(provider.calls[0]) == 1

        assert len(
            repository.artifacts
        ) == 2


class TestEmbedKnowledgeVersionBatching:
    def test_splits_provider_requests_by_batch_size(
        self,
    ) -> None:
        document_id = uuid4()
        version_id = uuid4()

        version = make_ready_version(
            version_id=version_id,
            document_id=document_id,
        )

        document = make_document(
            document_id=document_id,
        )

        chunks = [
            make_chunk(
                version_id=version_id,
                chunk_index=index,
            )
            for index in range(5)
        ]

        (
            service,
            provider,
            _,
            repository,
        ) = build_service(
            version=version,
            document=document,
            chunks=chunks,
            batch_size=2,
        )

        result = service.execute(
            EmbedKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        assert result.created_count == 5
        assert len(repository.artifacts) == 5

        assert [
            len(call)
            for call in provider.calls
        ] == [
            2,
            2,
            1,
        ]


class TestEmbedKnowledgeVersionValidation:
    def test_missing_version_raises(
        self,
    ) -> None:
        provider = FakeEmbeddingProvider()
        builder = FakeEmbeddingInputBuilder()

        service = EmbedKnowledgeVersion(
            uow_factory=FakeUoWFactory(
                versions=FakeVersionRepository(
                    {}
                ),
                documents=FakeDocumentRepository(
                    {}
                ),
                chunks=FakeChunkRepository(
                    {}
                ),
                embeddings=FakeEmbeddingRepository(),
            ),
            provider=provider,
            input_builder=builder,
        )

        version_id = uuid4()

        with pytest.raises(
            EmbeddingVersionNotFoundError
        ):
            service.execute(
                EmbedKnowledgeVersionCommand(
                    version_id=version_id
                )
            )

        assert provider.calls == []

    def test_draft_version_is_rejected(
        self,
    ) -> None:
        document_id = uuid4()
        version_id = uuid4()

        now = datetime.now(
            timezone.utc
        )

        version = KnowledgeDocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=1,
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            source_content="Draft source.",
            content_hash="d" * 64,
            status=KnowledgeVersionStatus.DRAFT,
            ingestion_status=(
                KnowledgeIngestionStatus.PENDING
            ),
            created_at=now,
            updated_at=now,
        )

        document = make_document(
            document_id=document_id,
        )

        (
            service,
            provider,
            _,
            _,
        ) = build_service(
            version=version,
            document=document,
            chunks=[],
        )

        with pytest.raises(
            EmbeddingVersionNotReadyError
        ):
            service.execute(
                EmbedKnowledgeVersionCommand(
                    version_id=version_id
                )
            )

        assert provider.calls == []

    def test_ready_version_without_chunks_is_rejected(
        self,
    ) -> None:
        document_id = uuid4()
        version_id = uuid4()

        version = make_ready_version(
            version_id=version_id,
            document_id=document_id,
        )

        document = make_document(
            document_id=document_id,
        )

        (
            service,
            provider,
            _,
            _,
        ) = build_service(
            version=version,
            document=document,
            chunks=[],
        )

        with pytest.raises(
            EmbeddingVersionHasNoChunksError
        ):
            service.execute(
                EmbedKnowledgeVersionCommand(
                    version_id=version_id
                )
            )

        assert provider.calls == []


class TestEmbedKnowledgeVersionResult:
    def test_result_enforces_accounting_invariant(
        self,
    ) -> None:
        from packages.knowledge.application.embed_version import (
            EmbedKnowledgeVersionResult,
        )

        with pytest.raises(
            ValueError,
            match=(
                "existing_count \\+ created_count "
                "must equal total_chunks"
            ),
        ):
            EmbedKnowledgeVersionResult(
                version_id=uuid4(),
                document_id=uuid4(),
                total_chunks=3,
                existing_count=1,
                created_count=1,
                provider_identity="fake:model",
                input_strategy_identity="strategy:1:abc",
            )