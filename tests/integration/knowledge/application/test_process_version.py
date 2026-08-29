from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from packages.database.models.knowledge.chunk import KnowledgeChunkModel
from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.document_version import (
    KnowledgeDocumentVersionModel,
)
from packages.database.unit_of_work.knowledge import (
    SQLAlchemyKnowledgeUnitOfWork,
)

from packages.knowledge.application.process_version import (
    ProcessKnowledgeVersion,
    ProcessKnowledgeVersionCommand,
)
from packages.knowledge.domain.enums import (
    KnowledgeIngestionStatus,
    KnowledgeSourceType,
    KnowledgeVersionStatus,
)

from packages.knowledge.ingestion.models import (
    IngestionSource,
    ParsedDocument,
    ParsedSegment,
)
from packages.knowledge.ingestion.parser.base import (
    BaseDocumentParser,
    ParserDescriptor,
)

from packages.knowledge.ingestion.normalization.base import (
    BaseDocumentNormalizer,
    NormalizerDescriptor,
)
from packages.knowledge.ingestion.normalization.models import (
    NormalizedDocument,
    NormalizedSegment,
)

from packages.knowledge.ingestion.chunking.base import (
    BaseDocumentChunker,
    ChunkerDescriptor,
)
from packages.knowledge.ingestion.chunking.models import (
    ChunkCandidate,
    ChunkedDocument,
    ChunkSourceSpan,
)


UTC = timezone.utc


# ===========================================================================
# Deterministic processing stages
# ===========================================================================


class IntegrationParser(BaseDocumentParser):

    @property
    def descriptor(self) -> ParserDescriptor:
        return ParserDescriptor(
            strategy_id="integration-parser",
            version="1.0.0",
        )

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset({
            KnowledgeSourceType.PLAIN_TEXT,
        })

    def parse(
        self,
        source: IngestionSource,
    ) -> ParsedDocument:
        return ParsedDocument(
            version_id=source.version_id,
            source_type=source.source_type,
            segments=(
                ParsedSegment(
                    index=0,
                    text=source.content,
                ),
            ),
            parser_strategy_id=self.descriptor.strategy_id,
            parser_version=self.descriptor.version,
            parser_config_fingerprint=(
                self.descriptor.config_fingerprint
            ),
        )


class IntegrationNormalizer(BaseDocumentNormalizer):

    @property
    def descriptor(self) -> NormalizerDescriptor:
        return NormalizerDescriptor(
            strategy_id="integration-normalizer",
            version="1.0.0",
        )

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset({
            KnowledgeSourceType.PLAIN_TEXT,
        })

    def normalize(
        self,
        document: ParsedDocument,
    ) -> NormalizedDocument:
        return NormalizedDocument(
            version_id=document.version_id,
            source_type=document.source_type,
            segments=tuple(
                NormalizedSegment(
                    index=index,
                    source_segment_index=segment.index,
                    text=segment.text,
                    section_path=segment.section_path,
                )
                for index, segment
                in enumerate(document.segments)
            ),
            source_parser_strategy_id=(
                document.parser_strategy_id
            ),
            source_parser_version=(
                document.parser_version
            ),
            source_parser_config_fingerprint=(
                document.parser_config_fingerprint
            ),
            normalizer_strategy_id=(
                self.descriptor.strategy_id
            ),
            normalizer_version=(
                self.descriptor.version
            ),
            normalizer_config_fingerprint=(
                self.descriptor.config_fingerprint
            ),
        )


class IntegrationChunker(BaseDocumentChunker):

    @property
    def descriptor(self) -> ChunkerDescriptor:
        return ChunkerDescriptor(
            strategy_id="integration-chunker",
            version="1.0.0",
        )

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset({
            KnowledgeSourceType.PLAIN_TEXT,
        })

    def chunk(
        self,
        document: NormalizedDocument,
    ) -> ChunkedDocument:
        segment = document.segments[0]

        return ChunkedDocument(
            version_id=document.version_id,
            source_type=document.source_type,
            chunks=(
                ChunkCandidate(
                    index=0,
                    text=segment.text,
                    source_spans=(
                        ChunkSourceSpan(
                            source_segment_index=(
                                segment.source_segment_index
                            ),
                            start_offset=0,
                            end_offset=len(segment.text),
                        ),
                    ),
                    section_path=segment.section_path,
                    metadata={
                        "integration_test": True,
                    },
                ),
            ),
            source_parser_strategy_id=(
                document.source_parser_strategy_id
            ),
            source_parser_version=(
                document.source_parser_version
            ),
            source_parser_config_fingerprint=(
                document.source_parser_config_fingerprint
            ),
            source_normalizer_strategy_id=(
                document.normalizer_strategy_id
            ),
            source_normalizer_version=(
                document.normalizer_version
            ),
            source_normalizer_config_fingerprint=(
                document.normalizer_config_fingerprint
            ),
            chunker_strategy_id=(
                self.descriptor.strategy_id
            ),
            chunker_version=(
                self.descriptor.version
            ),
            chunker_config_fingerprint=(
                self.descriptor.config_fingerprint
            ),
        )


# ===========================================================================
# Resolver
# ===========================================================================


class SingleComponentResolver:

    def __init__(self, component: Any) -> None:
        self._component = component

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return self._component.supported_source_types

    def supports(
        self,
        source_type: KnowledgeSourceType,
    ) -> bool:
        return source_type in self.supported_source_types

    def resolve(
        self,
        source_type: KnowledgeSourceType,
    ) -> Any:
        if not self.supports(source_type):
            raise LookupError(
                f"No component registered for {source_type.value}."
            )

        return self._component


# ===========================================================================
# Database seed helpers
# ===========================================================================


def seed_draft_version(
    session_factory: sessionmaker[Session],
) -> tuple[UUID, UUID]:
    """
    Seed the minimum real relational state required by ProcessKnowledgeVersion.

    We deliberately seed ORM rows here rather than going through
    CreateDocument/CreateVersion. Those use cases have their own tests; this
    fixture isolates ProcessKnowledgeVersion's integration boundary.
    """

    document_id = uuid4()
    version_id = uuid4()

    now = datetime.now(UTC)

    source_content = (
        "Refund requests are accepted within 30 days.\n\n"
        "Customers must provide the original order number."
    )

    with session_factory() as session:
        document = KnowledgeDocumentModel(
            id=document_id,
            title="Integration Refund Policy",
            description="Integration-test document.",
            content_type="policy",
            visibility="customer",
            status="active",
            metadata_={
                "test": True,
            },
            created_at=now,
            updated_at=now,
            archived_at=None,
            deleted_at=None,
        )

        version = KnowledgeDocumentVersionModel(
            id=version_id,
            document_id=document_id,
            version_number=1,
            source_type="plain_text",
            source_content=source_content,
            content_hash="a" * 64,
            status="draft",
            ingestion_status="pending",
            source_name="refund-policy.txt",
            source_uri=None,
            metadata_={
                "category": "refund",
                "integration_test": True,
            },
            created_at=now,
            updated_at=now,
            processing_started_at=None,
            processing_completed_at=None,
            ready_at=None,
            published_at=None,
            superseded_at=None,
            archived_at=None,
            failure_code=None,
            failure_message=None,
        )

        # Flush parent before child to make the FK dependency explicit.
        session.add(document)
        session.flush()

        session.add(version)
        session.commit()

    return document_id, version_id


def build_service(
    session_factory: sessionmaker[Session],
) -> ProcessKnowledgeVersion:
    parser = IntegrationParser()
    normalizer = IntegrationNormalizer()
    chunker = IntegrationChunker()

    return ProcessKnowledgeVersion(
        uow_factory=lambda: SQLAlchemyKnowledgeUnitOfWork(
            session_factory
        ),
        parser_resolver=SingleComponentResolver(
            parser
        ),
        normalizer_resolver=SingleComponentResolver(
            normalizer
        ),
        chunker_resolver=SingleComponentResolver(
            chunker
        ),
    )


# ===========================================================================
# Successful persistence
# ===========================================================================


class TestProcessKnowledgeVersionPersistence:

    def test_processes_draft_version_to_ready_in_postgresql(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id, version_id = seed_draft_version(
            test_session_factory
        )

        service = build_service(
            test_session_factory
        )

        result = service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id,
            )
        )

        assert result.version_id == version_id
        assert result.document_id == document_id
        assert result.chunk_count == 1
        assert (
            result.version_status
            is KnowledgeVersionStatus.READY
        )
        assert (
            result.ingestion_status
            is KnowledgeIngestionStatus.COMPLETED
        )

        with test_session_factory() as session:
            version = session.get(
                KnowledgeDocumentVersionModel,
                version_id,
            )

            assert version is not None
            assert version.status == "ready"
            assert (
                version.ingestion_status
                == "completed"
            )

            assert version.processing_started_at is not None
            assert (
                version.processing_completed_at
                is not None
            )
            assert version.ready_at is not None

            assert version.failure_code is None
            assert version.failure_message is None


    def test_persists_generated_chunk(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        _, version_id = seed_draft_version(
            test_session_factory
        )

        service = build_service(
            test_session_factory
        )

        service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id,
            )
        )

        with test_session_factory() as session:
            chunks = (
                session.scalars(
                    select(KnowledgeChunkModel)
                    .where(
                        KnowledgeChunkModel.version_id
                        == version_id
                    )
                    .order_by(
                        KnowledgeChunkModel.chunk_index
                    )
                )
                .all()
            )

            assert len(chunks) == 1

            chunk = chunks[0]

            assert chunk.chunk_index == 0

            assert (
                chunk.content
                == (
                    "Refund requests are accepted "
                    "within 30 days.\n\n"
                    "Customers must provide the "
                    "original order number."
                )
            )

            assert chunk.token_count is None


    def test_persists_chunk_provenance_metadata(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        _, version_id = seed_draft_version(
            test_session_factory
        )

        service = build_service(
            test_session_factory
        )

        service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id,
            )
        )

        with test_session_factory() as session:
            chunk = session.scalar(
                select(KnowledgeChunkModel)
                .where(
                    KnowledgeChunkModel.version_id
                    == version_id
                )
            )

            assert chunk is not None

            metadata = chunk.metadata_

            assert metadata[
                "integration_test"
            ] is True

            provenance = metadata[
                "transformation_provenance"
            ]

            assert (
                provenance["parser"]["strategy_id"]
                == "integration-parser"
            )

            assert (
                provenance["normalizer"]["strategy_id"]
                == "integration-normalizer"
            )

            assert (
                provenance["chunker"]["strategy_id"]
                == "integration-chunker"
            )


    def test_source_version_content_is_not_mutated(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        _, version_id = seed_draft_version(
            test_session_factory
        )

        with test_session_factory() as session:
            original = session.get(
                KnowledgeDocumentVersionModel,
                version_id,
            )

            assert original is not None

            original_content = original.source_content
            original_hash = original.content_hash

        service = build_service(
            test_session_factory
        )

        service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id,
            )
        )

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentVersionModel,
                version_id,
            )

            assert persisted is not None
            assert persisted.source_content == original_content
            assert persisted.content_hash == original_hash


    def test_document_is_not_modified_by_processing(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id, version_id = seed_draft_version(
            test_session_factory
        )

        with test_session_factory() as session:
            original = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            assert original is not None
            original_updated_at = original.updated_at

        service = build_service(
            test_session_factory
        )

        service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id,
            )
        )

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            assert persisted is not None
            assert (
                persisted.updated_at
                == original_updated_at
            )
            assert persisted.status == "active"


# ===========================================================================
# Repository / mapper round-trip
# ===========================================================================


class TestKnowledgePersistenceRoundTrip:

    def test_ready_version_round_trips_through_repository(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        _, version_id = seed_draft_version(
            test_session_factory
        )

        service = build_service(
            test_session_factory
        )

        service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id,
            )
        )

        with SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        ) as uow:
            version = uow.versions.get_by_id(
                version_id
            )

            chunks = uow.chunks.list_for_version(
                version_id
            )

        assert version is not None

        assert (
            version.status
            is KnowledgeVersionStatus.READY
        )

        assert (
            version.ingestion_status
            is KnowledgeIngestionStatus.COMPLETED
        )

        assert version.processing_started_at is not None
        assert version.processing_completed_at is not None
        assert version.ready_at is not None

        assert len(chunks) == 1

        chunk = chunks[0]

        assert chunk.version_id == version_id
        assert chunk.chunk_index == 0
        assert chunk.content