from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from sqlalchemy import delete, select

from packages.database.models.knowledge import (
    KnowledgeChunkEmbeddingModel,
    KnowledgeChunkModel,
    KnowledgeDocumentModel,
    KnowledgeDocumentVersionModel,
)

from packages.config.settings import get_settings
from packages.database.session import create_session_factory
from packages.database.unit_of_work.knowledge import (
    SQLAlchemyKnowledgeUnitOfWork,
)
from packages.knowledge.application.embed_version import (
    EmbedKnowledgeVersion,
    EmbedKnowledgeVersionCommand,
)
from packages.knowledge.domain.chunk import KnowledgeChunk
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import (
    KnowledgeContentType,
    KnowledgeDocumentStatus,
    KnowledgeIngestionStatus,
    KnowledgeSourceType,
    KnowledgeVersionStatus,
    KnowledgeVisibility,
)
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.embeddings import EmbeddingProvider
from packages.knowledge.embeddings.models import (
    DocumentEmbedding,
    EmbeddingBatch,
    EmbeddingInputDescriptor,
    EmbeddingProviderDescriptor,
    EmbeddingVector,
    PreparedEmbeddingInput,
)
from packages.knowledge.repositories.embedding_repository import (
    KnowledgeEmbeddingRepository,
)
from packages.knowledge.embeddings import EmbeddingInputBuilder, EmbeddingProvider


pytestmark = pytest.mark.integration


# ============================================================================
# Deterministic provider
# ============================================================================


class DeterministicEmbeddingProvider(
    EmbeddingProvider
):
    def __init__(
        self,
        *,
        dimensions: int = 3,
    ) -> None:
        self._descriptor = EmbeddingProviderDescriptor(
            provider="integration-test",
            model="deterministic-v1",
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
        texts: Sequence[str],
    ) -> EmbeddingBatch:
        texts = list(texts)

        self.calls.append(
            list(texts)
        )

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


# ============================================================================
# Deterministic input builder
# ============================================================================


class DeterministicEmbeddingInputBuilder(EmbeddingInputBuilder):
    @property
    def descriptor(
        self,
    ) -> EmbeddingInputDescriptor:
        return EmbeddingInputDescriptor(
            strategy_id="integration-contextual",
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

        return PreparedEmbeddingInput(
            chunk_id=chunk.id,
            text=text,
            input_fingerprint=(
                f"{chunk.chunk_index + 1:064x}"
            ),
        )


# ============================================================================
# Database fixture
# ============================================================================


@pytest.fixture
def test_session_factory():
    settings = get_settings(
        "test"
    )

    return create_session_factory(
        database_url=settings.database_url,
        echo=False,
    )


@pytest.fixture
def uow_factory(
    test_session_factory,
):
    def factory():
        return SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

    return factory


# ============================================================================
# Helpers
# ============================================================================


def seed_ready_version(
    *,
    uow_factory,
    chunk_count: int = 2,
):
    document_id = uuid4()
    version_id = uuid4()

    now = datetime.now(
        timezone.utc
    )

    document = KnowledgeDocument(
        id=document_id,
        title="Integration Refund Policy",
        description=(
            "Knowledge document used by embedding integration tests."
        ),
        content_type=KnowledgeContentType.POLICY,
        visibility=KnowledgeVisibility.CUSTOMER,
        status=KnowledgeDocumentStatus.ACTIVE,
        metadata={
            "test": True,
        },
        created_at=now,
        updated_at=now,
    )

    version = KnowledgeDocumentVersion(
        id=version_id,
        document_id=document_id,
        version_number=1,
        source_type=KnowledgeSourceType.PLAIN_TEXT,
        source_content=(
            "Customers may request refunds according to "
            "the applicable refund policy."
        ),
        content_hash="f" * 64,
        status=KnowledgeVersionStatus.READY,
        ingestion_status=(
            KnowledgeIngestionStatus.COMPLETED
        ),
        metadata={
            "test": True,
        },
        created_at=now,
        updated_at=now,
        processing_started_at=now,
        processing_completed_at=now,
        ready_at=now,
    )

    chunks = [
        KnowledgeChunk(
            id=uuid4(),
            version_id=version_id,
            chunk_index=index,
            content=(
                f"Refund policy integration chunk {index}."
            ),
            section_title="Refund Policy",
            metadata={
                "test": True,
            },
            created_at=now,
            updated_at=now,
        )
        for index in range(
            chunk_count
        )
    ]

    with uow_factory() as uow:
        uow.documents.add(
            document
        )

        uow.versions.add(
            version
        )

        uow.chunks.add_many(
            chunks
        )

        uow.flush()
        uow.commit()

    return (
        document,
        version,
        chunks,
    )


def cleanup_document(
    *,
    test_session_factory,
    document_id,
) -> None:
    with test_session_factory() as session:
        version_ids = (
            session.execute(
                select(
                    KnowledgeDocumentVersionModel.id
                ).where(
                    KnowledgeDocumentVersionModel.document_id
                    == document_id
                )
            )
            .scalars()
            .all()
        )

        if version_ids:
            chunk_ids = (
                session.execute(
                    select(
                        KnowledgeChunkModel.id
                    ).where(
                        KnowledgeChunkModel.version_id.in_(
                            version_ids
                        )
                    )
                )
                .scalars()
                .all()
            )

            if chunk_ids:
                session.execute(
                    delete(
                        KnowledgeChunkEmbeddingModel
                    ).where(
                        KnowledgeChunkEmbeddingModel.chunk_id.in_(
                            chunk_ids
                        )
                    )
                )

            session.execute(
                delete(
                    KnowledgeChunkModel
                ).where(
                    KnowledgeChunkModel.version_id.in_(
                        version_ids
                    )
                )
            )

            session.execute(
                delete(
                    KnowledgeDocumentVersionModel
                ).where(
                    KnowledgeDocumentVersionModel.id.in_(
                        version_ids
                    )
                )
            )

        session.execute(
            delete(
                KnowledgeDocumentModel
            ).where(
                KnowledgeDocumentModel.id
                == document_id
            )
        )

        session.commit()

# ============================================================================
# Integration tests
# ============================================================================


class TestEmbedKnowledgeVersionIntegration:
    def test_persists_embedding_artifacts_in_postgresql(
        self,
        uow_factory,
        test_session_factory,
    ) -> None:
        (
            document,
            version,
            chunks,
        ) = seed_ready_version(
            uow_factory=uow_factory,
            chunk_count=2,
        )

        try:
            provider = (
                DeterministicEmbeddingProvider()
            )

            builder = (
                DeterministicEmbeddingInputBuilder()
            )

            service = EmbedKnowledgeVersion(
                uow_factory=uow_factory,
                provider=provider,
                input_builder=builder,
                batch_size=32,
            )

            result = service.execute(
                EmbedKnowledgeVersionCommand(
                    version_id=version.id
                )
            )

            assert (
                result.version_id
                == version.id
            )

            assert (
                result.document_id
                == document.id
            )

            assert (
                result.total_chunks
                == 2
            )

            assert (
                result.created_count
                == 2
            )

            assert (
                result.existing_count
                == 0
            )

            assert (
                len(provider.calls)
                == 1
            )

            with uow_factory() as uow:
                persisted = (
                    uow.embeddings.list_for_chunks(
                        [
                            chunk.id
                            for chunk in chunks
                        ],
                        provider=provider.descriptor,
                        input_descriptor=(
                            builder.descriptor
                        ),
                    )
                )

            assert len(
                persisted
            ) == 2

            persisted_by_chunk = {
                artifact.chunk_id: artifact
                for artifact in persisted
            }

            for chunk in chunks:
                assert (
                    chunk.id
                    in persisted_by_chunk
                )

                artifact = (
                    persisted_by_chunk[
                        chunk.id
                    ]
                )

                assert (
                    artifact.provider
                    == provider.descriptor
                )

                assert (
                    artifact.input_descriptor
                    == builder.descriptor
                )

                assert (
                    artifact.vector.dimensions
                    == 3
                )

        finally:
            cleanup_document(
                test_session_factory=test_session_factory,
                document_id=document.id,
            )

    def test_second_execution_is_idempotent(
        self,
        uow_factory,
        test_session_factory,
    ) -> None:
        (
            document,
            version,
            chunks,
        ) = seed_ready_version(
            uow_factory=uow_factory,
            chunk_count=2,
        )

        try:
            provider = (
                DeterministicEmbeddingProvider()
            )

            builder = (
                DeterministicEmbeddingInputBuilder()
            )

            service = EmbedKnowledgeVersion(
                uow_factory=uow_factory,
                provider=provider,
                input_builder=builder,
            )

            first = service.execute(
                EmbedKnowledgeVersionCommand(
                    version_id=version.id
                )
            )

            second = service.execute(
                EmbedKnowledgeVersionCommand(
                    version_id=version.id
                )
            )

            assert (
                first.created_count
                == 2
            )

            assert (
                first.existing_count
                == 0
            )

            assert (
                second.created_count
                == 0
            )

            assert (
                second.existing_count
                == 2
            )

            # Second execution should not call the provider again.
            assert (
                len(provider.calls)
                == 1
            )

            with uow_factory() as uow:
                persisted = (
                    uow.embeddings.list_for_chunks(
                        [
                            chunk.id
                            for chunk in chunks
                        ],
                        provider=provider.descriptor,
                        input_descriptor=(
                            builder.descriptor
                        ),
                    )
                )

            assert len(
                persisted
            ) == 2

        finally:
            cleanup_document(
                test_session_factory=test_session_factory,
                document_id=document.id,
            )

    def test_different_input_fingerprint_creates_new_artifact(
        self,
        uow_factory,
        test_session_factory,
    ) -> None:
        (
            document,
            version,
            chunks,
        ) = seed_ready_version(
            uow_factory=uow_factory,
            chunk_count=1,
        )

        class SecondBuilder(
            DeterministicEmbeddingInputBuilder
        ):
            @property
            def descriptor(
                self,
            ) -> EmbeddingInputDescriptor:
                return EmbeddingInputDescriptor(
                    strategy_id="integration-contextual",
                    version="2",
                    config_fingerprint="b" * 64,
                )

            def build(
                self,
                *,
                chunk: KnowledgeChunk,
                document_title: str,
            ) -> PreparedEmbeddingInput:
                return PreparedEmbeddingInput(
                    chunk_id=chunk.id,
                    text=(
                        f"Title: {document_title}\n\n"
                        f"{chunk.content}"
                    ),
                    input_fingerprint="c" * 64,
                )

        try:
            provider = (
                DeterministicEmbeddingProvider()
            )

            first_builder = (
                DeterministicEmbeddingInputBuilder()
            )

            second_builder = (
                SecondBuilder()
            )

            first_service = (
                EmbedKnowledgeVersion(
                    uow_factory=uow_factory,
                    provider=provider,
                    input_builder=first_builder,
                )
            )

            second_service = (
                EmbedKnowledgeVersion(
                    uow_factory=uow_factory,
                    provider=provider,
                    input_builder=second_builder,
                )
            )

            first_result = (
                first_service.execute(
                    EmbedKnowledgeVersionCommand(
                        version_id=version.id
                    )
                )
            )

            second_result = (
                second_service.execute(
                    EmbedKnowledgeVersionCommand(
                        version_id=version.id
                    )
                )
            )

            assert (
                first_result.created_count
                == 1
            )

            assert (
                second_result.created_count
                == 1
            )

            with uow_factory() as uow:
                first_artifacts = (
                    uow.embeddings.list_for_chunks(
                        [chunks[0].id],
                        provider=provider.descriptor,
                        input_descriptor=(
                            first_builder.descriptor
                        ),
                    )
                )

                second_artifacts = (
                    uow.embeddings.list_for_chunks(
                        [chunks[0].id],
                        provider=provider.descriptor,
                        input_descriptor=(
                            second_builder.descriptor
                        ),
                    )
                )

            assert len(
                first_artifacts
            ) == 1

            assert len(
                second_artifacts
            ) == 1

            assert (
                first_artifacts[0].id
                != second_artifacts[0].id
            )

        finally:
            cleanup_document(
                test_session_factory=test_session_factory,
                document_id=document.id,
            )