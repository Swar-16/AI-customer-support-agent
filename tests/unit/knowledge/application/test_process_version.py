from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from packages.knowledge.application.process_version import (
    KnowledgeProcessingContractError,
    KnowledgeVersionNotFoundError,
    KnowledgeVersionNotProcessableError,
    KnowledgeVersionProcessingConflictError,
    ProcessKnowledgeVersion,
    ProcessKnowledgeVersionCommand,
)
from packages.knowledge.domain.chunk import KnowledgeChunk
from packages.knowledge.domain.enums import (
    KnowledgeIngestionStatus,
    KnowledgeSourceType,
    KnowledgeVersionStatus,
)
from packages.knowledge.domain.version import KnowledgeDocumentVersion
from packages.knowledge.ingestion.chunking.base import (
    BaseDocumentChunker,
    ChunkerDescriptor,
)
from packages.knowledge.ingestion.chunking.models import (
    ChunkCandidate,
    ChunkedDocument,
    ChunkSourceSpan,
)
from packages.knowledge.ingestion.models import (
    IngestionSource,
    ParsedDocument,
    ParsedSegment,
)
from packages.knowledge.ingestion.normalization.base import (
    BaseDocumentNormalizer,
    NormalizerDescriptor,
)
from packages.knowledge.ingestion.normalization.models import (
    NormalizedDocument,
    NormalizedSegment,
)
from packages.knowledge.ingestion.parser.base import (
    BaseDocumentParser,
    ParserDescriptor,
)


# ---------------------------------------------------------------------------
# Test constants / helpers
# ---------------------------------------------------------------------------


UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_version(
    *,
    version_id: UUID | None = None,
    document_id: UUID | None = None,
    status: KnowledgeVersionStatus = KnowledgeVersionStatus.DRAFT,
    ingestion_status: KnowledgeIngestionStatus = KnowledgeIngestionStatus.PENDING,
) -> KnowledgeDocumentVersion:
    now = utc_now()

    processing_started_at = None
    processing_completed_at = None
    ready_at = None
    published_at = None

    if status is KnowledgeVersionStatus.PROCESSING:
        processing_started_at = now

    elif status is KnowledgeVersionStatus.READY:
        processing_started_at = now
        processing_completed_at = now
        ready_at = now

    elif status is KnowledgeVersionStatus.PUBLISHED:
        processing_started_at = now
        processing_completed_at = now
        ready_at = now
        published_at = now

    elif status is KnowledgeVersionStatus.FAILED:
        processing_started_at = now
        processing_completed_at = now

    return KnowledgeDocumentVersion(
        id=version_id or uuid4(),
        document_id=document_id or uuid4(),
        version_number=1,
        source_type=KnowledgeSourceType.PLAIN_TEXT,
        source_content=(
            "Refund requests are accepted within 30 days.\n\n"
            "Customers must provide the original order number."
        ),
        content_hash="a" * 64,
        status=status,
        ingestion_status=ingestion_status,
        source_name="refund-policy.txt",
        source_uri=None,
        metadata={"category": "refund"},
        created_at=now,
        updated_at=now,
        processing_started_at=processing_started_at,
        processing_completed_at=processing_completed_at,
        ready_at=ready_at,
        published_at=published_at,
        superseded_at=None,
        archived_at=None,
        failure_code=(
            "TEST_FAILURE"
            if status is KnowledgeVersionStatus.FAILED
            else None
        ),
        failure_message=(
            "Test ingestion failure."
            if status is KnowledgeVersionStatus.FAILED
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Fake parser
# ---------------------------------------------------------------------------


class StubParser(BaseDocumentParser):

    def __init__(
        self,
        *,
        fail: Exception | None = None,
    ) -> None:
        self.fail = fail
        self.calls = 0

    @property
    def descriptor(self) -> ParserDescriptor:
        return ParserDescriptor(
            strategy_id="test-parser",
            version="1.0.0",
        )

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset(
            {
                KnowledgeSourceType.PLAIN_TEXT,
            }
        )

    def parse(
        self,
        source: IngestionSource,
    ) -> ParsedDocument:
        self.calls += 1

        if self.fail is not None:
            raise self.fail

        return ParsedDocument(
            version_id=source.version_id,
            source_type=source.source_type,
            segments=(
                ParsedSegment(
                    index=0,
                    text=source.content,
                ),
            ),
            parser_strategy_id=(
                self.descriptor.strategy_id
            ),
            parser_version=(
                self.descriptor.version
            ),
            parser_config_fingerprint=(
                self.descriptor.config_fingerprint
            ),
        )


# ---------------------------------------------------------------------------
# Fake normalizer
# ---------------------------------------------------------------------------


class StubNormalizer(BaseDocumentNormalizer):

    def __init__(
        self,
        *,
        fail: Exception | None = None,
    ) -> None:
        self.fail = fail
        self.calls = 0

    @property
    def descriptor(self) -> NormalizerDescriptor:
        return NormalizerDescriptor(
            strategy_id="test-normalizer",
            version="1.0.0",
        )

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset(
            {
                KnowledgeSourceType.PLAIN_TEXT,
            }
        )

    def normalize(
        self,
        document: ParsedDocument,
    ) -> NormalizedDocument:
        self.calls += 1

        if self.fail is not None:
            raise self.fail

        return NormalizedDocument(
            version_id=document.version_id,
            source_type=document.source_type,
            segments=tuple(
                NormalizedSegment(
                    index=segment.index,
                    source_segment_index=(
                        segment.index
                    ),
                    text=segment.text,
                    section_path=(
                        segment.section_path
                    ),
                )
                for segment in document.segments
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


# ---------------------------------------------------------------------------
# Fake chunker
# ---------------------------------------------------------------------------


class StubChunker(BaseDocumentChunker):

    def __init__(
        self,
        *,
        fail: Exception | None = None,
    ) -> None:
        self.fail = fail
        self.calls = 0

    @property
    def descriptor(self) -> ChunkerDescriptor:
        return ChunkerDescriptor(
            strategy_id="test-chunker",
            version="1.0.0",
        )

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset(
            {
                KnowledgeSourceType.PLAIN_TEXT,
            }
        )

    def chunk(
        self,
        document: NormalizedDocument,
    ) -> ChunkedDocument:
        self.calls += 1

        if self.fail is not None:
            raise self.fail

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
                            end_offset=len(
                                segment.text
                            ),
                        ),
                    ),
                    section_path=(
                        segment.section_path
                    ),
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


# ---------------------------------------------------------------------------
# Simple resolver
# ---------------------------------------------------------------------------


class StubResolver:

    def __init__(self, component: Any) -> None:
        self.component = component
        self.calls: list[KnowledgeSourceType] = []

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return self.component.supported_source_types

    def supports(
        self,
        source_type: KnowledgeSourceType,
    ) -> bool:
        return source_type in self.supported_source_types

    def resolve(
        self,
        source_type: KnowledgeSourceType,
    ) -> Any:
        self.calls.append(source_type)

        if not self.supports(source_type):
            raise ValueError(
                f"Unsupported source type: {source_type}"
            )

        return self.component


# ---------------------------------------------------------------------------
# In-memory repositories
# ---------------------------------------------------------------------------


class FakeVersionRepository:

    def __init__(
        self,
        store: dict[
            UUID,
            KnowledgeDocumentVersion,
        ],
    ) -> None:
        self.store = store
        self.locked_ids: list[UUID] = []
        self.saved: list[
            KnowledgeDocumentVersion
        ] = []

    def add(
        self,
        version: KnowledgeDocumentVersion,
    ) -> None:
        self.store[version.id] = version

    def get_by_id(
        self,
        version_id: UUID,
    ) -> KnowledgeDocumentVersion | None:
        return self.store.get(
            version_id
        )

    def get_by_id_for_update(
        self,
        version_id: UUID,
    ) -> KnowledgeDocumentVersion | None:
        self.locked_ids.append(
            version_id
        )

        return self.store.get(
            version_id
        )

    def save(
        self,
        version: KnowledgeDocumentVersion,
    ) -> None:
        self.store[version.id] = version
        self.saved.append(version)

    def get_published_for_document(
        self,
        document_id: UUID,
    ) -> KnowledgeDocumentVersion | None:
        for version in self.store.values():
            if (
                version.document_id
                == document_id
                and version.status
                is KnowledgeVersionStatus.PUBLISHED
            ):
                return version

        return None

    def list_for_document(
        self,
        document_id: UUID,
    ) -> list[KnowledgeDocumentVersion]:
        return sorted(
            [
                version
                for version
                in self.store.values()
                if version.document_id
                == document_id
            ],
            key=lambda version: (
                version.version_number
            ),
        )

    def next_version_number(
        self,
        document_id: UUID,
    ) -> int:
        versions = self.list_for_document(
            document_id
        )

        if not versions:
            return 1

        return (
            max(
                version.version_number
                for version in versions
            )
            + 1
        )


class FakeChunkRepository:

    def __init__(self) -> None:
        self.store: dict[
            UUID,
            list[KnowledgeChunk],
        ] = {}

        self.deleted_versions: list[
            UUID
        ] = []

        self.add_many_calls = 0

    def add(
        self,
        chunk: KnowledgeChunk,
    ) -> None:
        self.store.setdefault(
            chunk.version_id,
            [],
        ).append(chunk)

    def add_many(
        self,
        chunks: list[KnowledgeChunk],
    ) -> None:
        self.add_many_calls += 1

        for chunk in chunks:
            self.add(chunk)

    def get_by_id(
        self,
        chunk_id: UUID,
    ) -> KnowledgeChunk | None:
        for chunks in self.store.values():
            for chunk in chunks:
                if chunk.id == chunk_id:
                    return chunk

        return None

    def list_for_version(
        self,
        version_id: UUID,
    ) -> list[KnowledgeChunk]:
        return sorted(
            self.store.get(
                version_id,
                [],
            ),
            key=lambda chunk: (
                chunk.chunk_index
            ),
        )

    def delete_for_version(
        self,
        version_id: UUID,
    ) -> None:
        self.deleted_versions.append(
            version_id
        )

        self.store.pop(
            version_id,
            None,
        )


# ---------------------------------------------------------------------------
# Fake UoW
# ---------------------------------------------------------------------------


class FakeKnowledgeUnitOfWork:

    def __init__(
        self,
        *,
        versions: FakeVersionRepository,
        chunks: FakeChunkRepository,
        lifecycle: list[str],
    ) -> None:
        self._versions = versions
        self._chunks = chunks
        self.lifecycle = lifecycle

        self.committed = False
        self.rolled_back = False
        self.flush_count = 0
        self.active = False

    @property
    def versions(
        self,
    ) -> FakeVersionRepository:
        return self._versions

    @property
    def chunks(
        self,
    ) -> FakeChunkRepository:
        return self._chunks

    @property
    def documents(self) -> Any:
        raise AssertionError(
            "ProcessKnowledgeVersion must not "
            "access document repository."
        )

    def __enter__(
        self,
    ) -> FakeKnowledgeUnitOfWork:
        assert not self.active

        self.active = True
        self.lifecycle.append(
            "uow_enter"
        )

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        if exc_type is not None:
            self.rollback()

        elif not self.committed:
            self.rollback()

        self.active = False

        self.lifecycle.append(
            "uow_exit"
        )

    def commit(self) -> None:
        assert self.active

        self.committed = True
        self.lifecycle.append(
            "commit"
        )

    def rollback(self) -> None:
        if self.active:
            self.rolled_back = True
            self.lifecycle.append(
                "rollback"
            )

    def flush(self) -> None:
        assert self.active

        self.flush_count += 1
        self.lifecycle.append(
            "flush"
        )


class FakeUoWFactory:

    def __init__(
        self,
        version: KnowledgeDocumentVersion | None,
    ) -> None:
        self.version_store: dict[
            UUID,
            KnowledgeDocumentVersion,
        ] = {}

        if version is not None:
            self.version_store[
                version.id
            ] = version

        self.versions = FakeVersionRepository(
            self.version_store
        )

        self.chunks = FakeChunkRepository()

        self.lifecycle: list[str] = []

        self.instances: list[
            FakeKnowledgeUnitOfWork
        ] = []

    def __call__(
        self,
    ) -> FakeKnowledgeUnitOfWork:
        uow = FakeKnowledgeUnitOfWork(
            versions=self.versions,
            chunks=self.chunks,
            lifecycle=self.lifecycle,
        )

        self.instances.append(uow)

        return uow


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


@dataclass
class ServiceHarness:
    service: ProcessKnowledgeVersion
    uow_factory: FakeUoWFactory
    parser: StubParser
    normalizer: StubNormalizer
    chunker: StubChunker


def make_service(
    *,
    version: KnowledgeDocumentVersion | None = None,
    parser: StubParser | None = None,
    normalizer: StubNormalizer | None = None,
    chunker: StubChunker | None = None,
) -> ServiceHarness:
    version = (
        version
        if version is not None
        else make_version()
    )

    parser = parser or StubParser()
    normalizer = (
        normalizer or StubNormalizer()
    )
    chunker = chunker or StubChunker()

    uow_factory = FakeUoWFactory(
        version
    )

    service = ProcessKnowledgeVersion(
        uow_factory=uow_factory,
        parser_resolver=StubResolver(
            parser
        ),
        normalizer_resolver=StubResolver(
            normalizer
        ),
        chunker_resolver=StubResolver(
            chunker
        ),
    )

    return ServiceHarness(
        service=service,
        uow_factory=uow_factory,
        parser=parser,
        normalizer=normalizer,
        chunker=chunker,
    )


# ---------------------------------------------------------------------------
# Command validation
# ---------------------------------------------------------------------------


class TestProcessKnowledgeVersionCommand:

    def test_rejects_non_uuid_version_id(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="version_id must be a UUID",
        ):
            ProcessKnowledgeVersionCommand(
                version_id="abc",  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Successful processing
# ---------------------------------------------------------------------------


class TestSuccessfulProcessing:

    def test_processes_draft_version_to_ready(
        self,
    ) -> None:
        harness = make_service()

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        result = harness.service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        persisted = (
            harness.uow_factory.version_store[
                version_id
            ]
        )

        assert (
            persisted.status
            is KnowledgeVersionStatus.READY
        )

        assert (
            persisted.ingestion_status
            is KnowledgeIngestionStatus.COMPLETED
        )

        assert (
            persisted.processing_started_at
            is not None
        )

        assert (
            persisted.processing_completed_at
            is not None
        )

        assert persisted.ready_at is not None

        assert result.version_id == version_id
        assert result.chunk_count == 1

        assert (
            result.version_status
            is KnowledgeVersionStatus.READY
        )

        assert (
            result.ingestion_status
            is KnowledgeIngestionStatus.COMPLETED
        )

    def test_pipeline_executes_each_stage_once(
        self,
    ) -> None:
        harness = make_service()

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        harness.service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        assert harness.parser.calls == 1
        assert harness.normalizer.calls == 1
        assert harness.chunker.calls == 1

    def test_success_uses_two_transactions(
        self,
    ) -> None:
        harness = make_service()

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        harness.service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        assert len(
            harness.uow_factory.instances
        ) == 2

        assert all(
            uow.committed
            for uow
            in harness.uow_factory.instances
        )

    def test_claim_and_completion_use_row_lock(
        self,
    ) -> None:
        harness = make_service()

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        harness.service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        assert (
            harness.uow_factory.versions.locked_ids
            == [
                version_id,
                version_id,
            ]
        )

    def test_persists_chunks(
        self,
    ) -> None:
        harness = make_service()

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        harness.service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        chunks = (
            harness.uow_factory.chunks
            .list_for_version(
                version_id
            )
        )

        assert len(chunks) == 1

        chunk = chunks[0]

        assert chunk.version_id == version_id
        assert chunk.chunk_index == 0
        assert chunk.content
        assert chunk.token_count is None

    def test_persisted_chunk_contains_provenance(
        self,
    ) -> None:
        harness = make_service()

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        harness.service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        chunk = (
            harness.uow_factory.chunks
            .list_for_version(
                version_id
            )[0]
        )

        provenance = chunk.metadata[
            "transformation_provenance"
        ]

        assert (
            provenance["parser"][
                "strategy_id"
            ]
            == "test-parser"
        )

        assert (
            provenance["normalizer"][
                "strategy_id"
            ]
            == "test-normalizer"
        )

        assert (
            provenance["chunker"][
                "strategy_id"
            ]
            == "test-chunker"
        )

    def test_exact_source_spans_are_preserved(
        self,
    ) -> None:
        harness = make_service()

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        harness.service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        chunk = (
            harness.uow_factory.chunks
            .list_for_version(
                version_id
            )[0]
        )

        spans = chunk.metadata[
            "source_spans"
        ]

        assert spans == [
            {
                "source_segment_index": 0,
                "start_offset": 0,
                "end_offset": len(
                    chunk.content
                ),
            }
        ]

        assert chunk.start_offset == 0
        assert (
            chunk.end_offset
            == len(chunk.content)
        )


# ---------------------------------------------------------------------------
# Missing / invalid lifecycle
# ---------------------------------------------------------------------------


class TestClaimValidation:

    def test_missing_version_raises(
        self,
    ) -> None:
        harness = make_service()

        missing_id = uuid4()

        with pytest.raises(
            KnowledgeVersionNotFoundError
        ):
            harness.service.execute(
                ProcessKnowledgeVersionCommand(
                    version_id=missing_id
                )
            )

        assert harness.parser.calls == 0

    @pytest.mark.parametrize(
        (
            "status",
            "ingestion_status",
        ),
        [
            (
                KnowledgeVersionStatus.PROCESSING,
                KnowledgeIngestionStatus.RUNNING,
            ),
            (
                KnowledgeVersionStatus.READY,
                KnowledgeIngestionStatus.COMPLETED,
            ),
            (
                KnowledgeVersionStatus.PUBLISHED,
                KnowledgeIngestionStatus.COMPLETED,
            ),
            (
                KnowledgeVersionStatus.FAILED,
                KnowledgeIngestionStatus.FAILED,
            ),
        ],
    )
    def test_non_draft_pending_version_rejected(
        self,
        status: KnowledgeVersionStatus,
        ingestion_status: KnowledgeIngestionStatus,
    ) -> None:
        version = make_version(
            status=status,
            ingestion_status=ingestion_status,
        )

        harness = make_service(
            version=version
        )

        with pytest.raises(
            KnowledgeVersionNotProcessableError
        ):
            harness.service.execute(
                ProcessKnowledgeVersionCommand(
                    version_id=version.id
                )
            )

        assert harness.parser.calls == 0
        assert harness.normalizer.calls == 0
        assert harness.chunker.calls == 0


# ---------------------------------------------------------------------------
# Processing failures
# ---------------------------------------------------------------------------


class TestProcessingFailures:

    def test_parser_failure_marks_version_failed(
        self,
    ) -> None:
        parser = StubParser(
            fail=ValueError(
                "bad source"
            )
        )

        harness = make_service(
            parser=parser
        )

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        with pytest.raises(
            ValueError,
            match="bad source",
        ):
            harness.service.execute(
                ProcessKnowledgeVersionCommand(
                    version_id=version_id
                )
            )

        version = (
            harness.uow_factory.version_store[
                version_id
            ]
        )

        assert (
            version.status
            is KnowledgeVersionStatus.FAILED
        )

        assert (
            version.ingestion_status
            is KnowledgeIngestionStatus.FAILED
        )

        assert (
            version.processing_completed_at
            is not None
        )

        assert version.failure_code == "ValueError"

        # Generic exception text is deliberately not persisted.
        assert (
            version.failure_message
            == (
                "Knowledge ingestion failed during "
                "ValueError."
            )
        )

        assert harness.normalizer.calls == 0
        assert harness.chunker.calls == 0

    def test_normalizer_failure_marks_failed(
        self,
    ) -> None:
        normalizer = StubNormalizer(
            fail=RuntimeError(
                "normalization failed"
            )
        )

        harness = make_service(
            normalizer=normalizer
        )

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        with pytest.raises(RuntimeError):
            harness.service.execute(
                ProcessKnowledgeVersionCommand(
                    version_id=version_id
                )
            )

        version = (
            harness.uow_factory.version_store[
                version_id
            ]
        )

        assert (
            version.status
            is KnowledgeVersionStatus.FAILED
        )

        assert harness.parser.calls == 1
        assert harness.normalizer.calls == 1
        assert harness.chunker.calls == 0

    def test_chunker_failure_marks_failed(
        self,
    ) -> None:
        chunker = StubChunker(
            fail=RuntimeError(
                "chunk failure"
            )
        )

        harness = make_service(
            chunker=chunker
        )

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        with pytest.raises(RuntimeError):
            harness.service.execute(
                ProcessKnowledgeVersionCommand(
                    version_id=version_id
                )
            )

        version = (
            harness.uow_factory.version_store[
                version_id
            ]
        )

        assert (
            version.status
            is KnowledgeVersionStatus.FAILED
        )

        assert harness.parser.calls == 1
        assert harness.normalizer.calls == 1
        assert harness.chunker.calls == 1

    def test_failure_path_uses_claim_and_failure_transactions(
        self,
    ) -> None:
        parser = StubParser(
            fail=ValueError("bad")
        )

        harness = make_service(
            parser=parser
        )

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        with pytest.raises(ValueError):
            harness.service.execute(
                ProcessKnowledgeVersionCommand(
                    version_id=version_id
                )
            )

        assert len(
            harness.uow_factory.instances
        ) == 2

        assert all(
            uow.committed
            for uow
            in harness.uow_factory.instances
        )


# ---------------------------------------------------------------------------
# Concurrency / stale state
# ---------------------------------------------------------------------------


class TestProcessingConcurrency:

    def test_completion_rejects_version_changed_after_claim(
        self,
    ) -> None:
        harness = make_service()

        version_id = next(
            iter(
                harness.uow_factory.version_store
            )
        )

        original_complete = (
            harness.service._complete
        )

        def conflicting_complete(
            *,
            snapshot: Any,
            artifacts: Any,
        ) -> Any:
            current = (
                harness.uow_factory
                .version_store[
                    version_id
                ]
            )

            now = utc_now()

            # Simulate another actor changing lifecycle state after
            # this worker claimed the version.
            harness.uow_factory.version_store[
                version_id
            ] = KnowledgeDocumentVersion(
                id=current.id,
                document_id=current.document_id,
                version_number=current.version_number,
                source_type=current.source_type,
                source_content=current.source_content,
                content_hash=current.content_hash,
                status=KnowledgeVersionStatus.READY,
                ingestion_status=(
                    KnowledgeIngestionStatus.COMPLETED
                ),
                source_name=current.source_name,
                source_uri=current.source_uri,
                metadata=dict(current.metadata),
                created_at=current.created_at,
                updated_at=now,
                processing_started_at=(
                    current.processing_started_at
                ),
                processing_completed_at=now,
                ready_at=now,
                published_at=None,
                superseded_at=None,
                archived_at=None,
                failure_code=None,
                failure_message=None,
            )

            return original_complete(
                snapshot=snapshot,
                artifacts=artifacts,
            )

        harness.service._complete = (  # type: ignore[method-assign]
            conflicting_complete
        )

        with pytest.raises(
            KnowledgeVersionProcessingConflictError
        ):
            harness.service.execute(
                ProcessKnowledgeVersionCommand(
                    version_id=version_id
                )
            )

        # _fail() must not overwrite the state another actor produced.
        persisted = (
            harness.uow_factory.version_store[
                version_id
            ]
        )

        assert (
            persisted.status
            is KnowledgeVersionStatus.READY
        )


# ---------------------------------------------------------------------------
# Transaction boundary
# ---------------------------------------------------------------------------


class TransactionAwareParser(StubParser):

    def __init__(
        self,
        factory: FakeUoWFactory,
    ) -> None:
        super().__init__()
        self.factory = factory

    def parse(
        self,
        source: IngestionSource,
    ) -> ParsedDocument:
        # Claim transaction must already be closed before parsing.
        assert self.factory.instances

        assert not any(
            uow.active
            for uow
            in self.factory.instances
        )

        return super().parse(
            source
        )


class TestTransactionBoundaries:

    def test_no_uow_is_active_during_parser_execution(
        self,
    ) -> None:
        version = make_version()

        factory = FakeUoWFactory(
            version
        )

        parser = TransactionAwareParser(
            factory
        )

        normalizer = StubNormalizer()
        chunker = StubChunker()

        service = ProcessKnowledgeVersion(
            uow_factory=factory,
            parser_resolver=StubResolver(
                parser
            ),
            normalizer_resolver=StubResolver(
                normalizer
            ),
            chunker_resolver=StubResolver(
                chunker
            ),
        )

        service.execute(
            ProcessKnowledgeVersionCommand(
                version_id=version.id
            )
        )

        assert len(factory.instances) == 2