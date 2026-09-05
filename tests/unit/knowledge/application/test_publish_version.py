from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest

from packages.knowledge.application.publish_version import (
    KnowledgeDocumentDoesNotExistError,
    KnowledgeDocumentNotPublishableError,
    KnowledgePublicationConflictError,
    KnowledgeVersionDoesNotExistError,
    PublishKnowledgeVersion,
    PublishKnowledgeVersionCommand,
)
from packages.knowledge.domain.document import KnowledgeDocument
from packages.knowledge.domain.enums import (
    KnowledgeContentType,
    KnowledgeDocumentStatus,
    KnowledgeIngestionStatus,
    KnowledgeSourceType,
    KnowledgeVersionStatus,
    KnowledgeVisibility,
)
from packages.knowledge.domain.errors import (
    KnowledgeVersionAlreadyPublishedError,
    KnowledgeVersionNotReadyError,
)
from packages.knowledge.domain.version import KnowledgeDocumentVersion


UTC = timezone.utc


# ===========================================================================
# Domain fixtures / builders
# ===========================================================================


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_document(
    *,
    document_id: UUID | None = None,
    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.ACTIVE,
) -> KnowledgeDocument:
    now = utc_now()

    kwargs = dict(
        id=document_id or uuid4(),
        title="Refund Policy",
        description="Customer refund policy.",
        content_type=KnowledgeContentType.POLICY,
        visibility=KnowledgeVisibility.CUSTOMER,
        status=status,
        metadata={"test": True},
        created_at=now,
        updated_at=now,
    )

    if status is KnowledgeDocumentStatus.ARCHIVED:
        kwargs["archived_at"] = now

    if status is KnowledgeDocumentStatus.DELETED:
        kwargs["deleted_at"] = now

    return KnowledgeDocument(**kwargs)


def make_ready_version(
    *,
    version_id: UUID | None = None,
    document_id: UUID | None = None,
    version_number: int = 1,
) -> KnowledgeDocumentVersion:
    now = utc_now()

    processing_started_at = now - timedelta(seconds=2)
    completed_at = now - timedelta(seconds=1)

    return KnowledgeDocumentVersion(
        id=version_id or uuid4(),
        document_id=document_id or uuid4(),
        version_number=version_number,
        source_type=KnowledgeSourceType.PLAIN_TEXT,
        source_content="Refunds are allowed within 30 days.",
        content_hash="a" * 64,
        status=KnowledgeVersionStatus.READY,
        ingestion_status=KnowledgeIngestionStatus.COMPLETED,
        created_at=processing_started_at - timedelta(seconds=1),
        updated_at=completed_at,
        processing_started_at=processing_started_at,
        processing_completed_at=completed_at,
        ready_at=completed_at,
    )


def make_published_version(
    *,
    version_id: UUID | None = None,
    document_id: UUID | None = None,
    version_number: int = 1,
) -> KnowledgeDocumentVersion:
    ready = make_ready_version(
        version_id=version_id,
        document_id=document_id,
        version_number=version_number,
    )

    return ready.publish(
        occurred_at=ready.updated_at + timedelta(seconds=1)
    )


def make_draft_version(
    *,
    version_id: UUID | None = None,
    document_id: UUID | None = None,
    version_number: int = 1,
) -> KnowledgeDocumentVersion:
    now = utc_now()

    return KnowledgeDocumentVersion(
        id=version_id or uuid4(),
        document_id=document_id or uuid4(),
        version_number=version_number,
        source_type=KnowledgeSourceType.PLAIN_TEXT,
        source_content="Draft policy.",
        content_hash="b" * 64,
        status=KnowledgeVersionStatus.DRAFT,
        ingestion_status=KnowledgeIngestionStatus.PENDING,
        created_at=now,
        updated_at=now,
    )


# ===========================================================================
# Fake repositories
# ===========================================================================


class FakeDocumentRepository:
    def __init__(
        self,
        documents: list[KnowledgeDocument] | None = None,
    ) -> None:
        self._documents = {
            document.id: document
            for document in documents or []
        }

        self.get_by_id_for_update_calls: list[UUID] = []

    def add(self, document: KnowledgeDocument) -> None:
        self._documents[document.id] = document

    def get_by_id(
        self,
        document_id: UUID,
    ) -> KnowledgeDocument | None:
        return self._documents.get(document_id)

    def get_by_id_for_update(
        self,
        document_id: UUID,
    ) -> KnowledgeDocument | None:
        self.get_by_id_for_update_calls.append(
            document_id
        )

        return self._documents.get(document_id)

    def save(
        self,
        document: KnowledgeDocument,
    ) -> None:
        self._documents[document.id] = document

    def exists(
        self,
        document_id: UUID,
    ) -> bool:
        return document_id in self._documents


class FakeVersionRepository:
    def __init__(
        self,
        versions: list[KnowledgeDocumentVersion] | None = None,
    ) -> None:
        self._versions = {
            version.id: version
            for version in versions or []
        }

        self.get_by_id_calls: list[UUID] = []
        self.get_by_id_for_update_calls: list[UUID] = []
        self.get_published_calls: list[UUID] = []
        self.saved_versions: list[
            KnowledgeDocumentVersion
        ] = []

        self.override_locked_version: (
            KnowledgeDocumentVersion | None
        ) = None

        self.return_none_on_locked_lookup = False

    def add(
        self,
        version: KnowledgeDocumentVersion,
    ) -> None:
        self._versions[version.id] = version

    def get_by_id(
        self,
        version_id: UUID,
    ) -> KnowledgeDocumentVersion | None:
        self.get_by_id_calls.append(version_id)
        return self._versions.get(version_id)

    def get_by_id_for_update(
        self,
        version_id: UUID,
    ) -> KnowledgeDocumentVersion | None:
        self.get_by_id_for_update_calls.append(
            version_id
        )

        if self.return_none_on_locked_lookup:
            return None

        if self.override_locked_version is not None:
            return self.override_locked_version

        return self._versions.get(version_id)

    def save(
        self,
        version: KnowledgeDocumentVersion,
    ) -> None:
        self.saved_versions.append(version)
        self._versions[version.id] = version

    def get_published_for_document(
        self,
        document_id: UUID,
    ) -> KnowledgeDocumentVersion | None:
        self.get_published_calls.append(document_id)

        for version in self._versions.values():
            if (
                version.document_id == document_id
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
            (
                version
                for version in self._versions.values()
                if version.document_id == document_id
            ),
            key=lambda version: version.version_number,
        )

    def next_version_number(
        self,
        document_id: UUID,
    ) -> int:
        versions = self.list_for_document(document_id)

        if not versions:
            return 1

        return max(
            version.version_number
            for version in versions
        ) + 1


class FakeChunkRepository:
    def add(self, chunk) -> None:
        raise NotImplementedError

    def add_many(self, chunks) -> None:
        raise NotImplementedError

    def get_by_id(self, chunk_id):
        raise NotImplementedError

    def list_for_version(self, version_id):
        return []

    def delete_for_version(self, version_id):
        raise NotImplementedError


# ===========================================================================
# Fake UoW
# ===========================================================================


class FakeKnowledgeUnitOfWork:
    def __init__(
        self,
        *,
        documents: FakeDocumentRepository,
        versions: FakeVersionRepository,
    ) -> None:
        self.documents = documents
        self.versions = versions
        self.chunks = FakeChunkRepository()

        self.entered = False
        self.exited = False

        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0

        self.exit_exception_type: (
            type[BaseException] | None
        ) = None

    def __enter__(self) -> Self:
        self.entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited = True
        self.exit_exception_type = exc_type

        if exc_type is not None:
            self.rollback()

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def flush(self) -> None:
        self.flush_count += 1


class FakeKnowledgeUnitOfWorkFactory:
    def __init__(
        self,
        uow: FakeKnowledgeUnitOfWork,
    ) -> None:
        self.uow = uow
        self.call_count = 0

    def __call__(self) -> FakeKnowledgeUnitOfWork:
        self.call_count += 1
        return self.uow


# ===========================================================================
# Service harness
# ===========================================================================


@dataclass(frozen=True)
class ServiceHarness:
    service: PublishKnowledgeVersion
    uow: FakeKnowledgeUnitOfWork
    documents: FakeDocumentRepository
    versions: FakeVersionRepository
    factory: FakeKnowledgeUnitOfWorkFactory


def build_harness(
    *,
    document: KnowledgeDocument,
    target: KnowledgeDocumentVersion,
    current_published: KnowledgeDocumentVersion | None = None,
) -> ServiceHarness:
    documents = FakeDocumentRepository(
        [document]
    )

    versions_to_seed = [target]

    if current_published is not None:
        versions_to_seed.append(
            current_published
        )

    versions = FakeVersionRepository(
        versions_to_seed
    )

    uow = FakeKnowledgeUnitOfWork(
        documents=documents,
        versions=versions,
    )

    factory = FakeKnowledgeUnitOfWorkFactory(
        uow
    )

    service = PublishKnowledgeVersion(
        uow_factory=factory
    )

    return ServiceHarness(
        service=service,
        uow=uow,
        documents=documents,
        versions=versions,
        factory=factory,
    )


# ===========================================================================
# Command / construction
# ===========================================================================


class TestPublishKnowledgeVersionConstruction:

    def test_rejects_non_callable_uow_factory(self) -> None:
        with pytest.raises(
            TypeError,
            match="uow_factory must be callable",
        ):
            PublishKnowledgeVersion(
                uow_factory=object(),  # type: ignore[arg-type]
            )

    def test_command_requires_uuid(self) -> None:
        with pytest.raises(
            TypeError,
            match="version_id must be a UUID",
        ):
            PublishKnowledgeVersionCommand(
                version_id="abc",  # type: ignore[arg-type]
            )

    def test_execute_requires_command_instance(self) -> None:
        document = make_document()

        target = make_ready_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        with pytest.raises(
            TypeError,
            match="PublishKnowledgeVersionCommand",
        ):
            harness.service.execute(
                object()  # type: ignore[arg-type]
            )

        assert harness.factory.call_count == 0


# ===========================================================================
# First publication
# ===========================================================================


class TestFirstPublication:

    def test_publishes_ready_version(self) -> None:
        document = make_document()

        target = make_ready_version(
            document_id=document.id,
            version_number=1,
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        result = harness.service.execute(
            PublishKnowledgeVersionCommand(
                version_id=target.id
            )
        )

        assert result.version_id == target.id
        assert result.document_id == document.id
        assert result.version_number == 1

        assert (
            result.status
            is KnowledgeVersionStatus.PUBLISHED
        )

        assert result.published_at is not None
        assert result.superseded_version_id is None

    def test_persists_published_target(self) -> None:
        document = make_document()

        target = make_ready_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        harness.service.execute(
            PublishKnowledgeVersionCommand(
                version_id=target.id
            )
        )

        assert len(
            harness.versions.saved_versions
        ) == 1

        persisted = (
            harness.versions.saved_versions[0]
        )

        assert persisted.id == target.id
        assert persisted.is_published
        assert persisted.published_at is not None

    def test_flushes_then_commits_once(self) -> None:
        document = make_document()

        target = make_ready_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        harness.service.execute(
            PublishKnowledgeVersionCommand(
                version_id=target.id
            )
        )

        assert harness.uow.flush_count == 1
        assert harness.uow.commit_count == 1
        assert harness.uow.rollback_count == 0

    def test_uses_single_uow(self) -> None:
        document = make_document()

        target = make_ready_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        harness.service.execute(
            PublishKnowledgeVersionCommand(
                version_id=target.id
            )
        )

        assert harness.factory.call_count == 1
        assert harness.uow.entered
        assert harness.uow.exited


# ===========================================================================
# Aggregate locking
# ===========================================================================


class TestPublicationLocking:

    def test_locks_parent_document(self) -> None:
        document = make_document()

        target = make_ready_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        harness.service.execute(
            PublishKnowledgeVersionCommand(
                version_id=target.id
            )
        )

        assert (
            harness.documents
            .get_by_id_for_update_calls
            == [document.id]
        )

    def test_reloads_target_with_lock_after_document_lock(
        self,
    ) -> None:
        document = make_document()

        target = make_ready_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        harness.service.execute(
            PublishKnowledgeVersionCommand(
                version_id=target.id
            )
        )

        assert (
            harness.versions.get_by_id_calls
            == [target.id]
        )

        assert (
            harness.versions
            .get_by_id_for_update_calls
            == [target.id]
        )

    def test_queries_current_published_after_locking(
        self,
    ) -> None:
        document = make_document()

        target = make_ready_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        harness.service.execute(
            PublishKnowledgeVersionCommand(
                version_id=target.id
            )
        )

        assert (
            harness.versions.get_published_calls
            == [document.id]
        )


# ===========================================================================
# Replacement publication
# ===========================================================================


class TestReplacementPublication:

    def test_supersedes_previous_published_version(
        self,
    ) -> None:
        document = make_document()

        previous = make_published_version(
            document_id=document.id,
            version_number=1,
        )

        target = make_ready_version(
            document_id=document.id,
            version_number=2,
        )

        harness = build_harness(
            document=document,
            target=target,
            current_published=previous,
        )

        result = harness.service.execute(
            PublishKnowledgeVersionCommand(
                version_id=target.id
            )
        )

        assert (
            result.superseded_version_id
            == previous.id
        )

        saved = {
            version.id: version
            for version
            in harness.versions.saved_versions
        }

        assert saved[previous.id].is_superseded
        assert (
            saved[previous.id].superseded_at
            is not None
        )

        assert saved[target.id].is_published
        assert (
            saved[target.id].published_at
            is not None
        )

    def test_supersede_and_publish_use_same_timestamp(
        self,
    ) -> None:
        document = make_document()

        previous = make_published_version(
            document_id=document.id,
            version_number=1,
        )

        target = make_ready_version(
            document_id=document.id,
            version_number=2,
        )

        harness = build_harness(
            document=document,
            target=target,
            current_published=previous,
        )

        harness.service.execute(
            PublishKnowledgeVersionCommand(
                version_id=target.id
            )
        )

        saved = {
            version.id: version
            for version
            in harness.versions.saved_versions
        }

        superseded = saved[previous.id]
        published = saved[target.id]

        assert (
            superseded.superseded_at
            == published.published_at
        )

    def test_saves_old_version_before_target(
        self,
    ) -> None:
        document = make_document()

        previous = make_published_version(
            document_id=document.id,
            version_number=1,
        )

        target = make_ready_version(
            document_id=document.id,
            version_number=2,
        )

        harness = build_harness(
            document=document,
            target=target,
            current_published=previous,
        )

        harness.service.execute(
            PublishKnowledgeVersionCommand(
                version_id=target.id
            )
        )

        assert [
            version.id
            for version
            in harness.versions.saved_versions
        ] == [
            previous.id,
            target.id,
        ]

    def test_flushes_supersession_before_publishing_and_commits_once(
        self,
    ) -> None:
        document = make_document()

        previous = make_published_version(
            document_id=document.id
        )

        target = make_ready_version(
            document_id=document.id,
            version_number=2,
        )

        harness = build_harness(
            document=document,
            target=target,
            current_published=previous,
        )

        harness.service.execute(
            PublishKnowledgeVersionCommand(
                version_id=target.id
            )
        )

        assert harness.uow.flush_count == 2
        assert harness.uow.commit_count == 1
        assert harness.uow.rollback_count == 0


# ===========================================================================
# Missing records
# ===========================================================================


class TestMissingPersistenceState:

    def test_missing_target_version_raises(self) -> None:
        document = make_document()

        missing_id = uuid4()

        versions = FakeVersionRepository()
        documents = FakeDocumentRepository(
            [document]
        )

        uow = FakeKnowledgeUnitOfWork(
            documents=documents,
            versions=versions,
        )

        service = PublishKnowledgeVersion(
            uow_factory=FakeKnowledgeUnitOfWorkFactory(
                uow
            )
        )

        with pytest.raises(
            KnowledgeVersionDoesNotExistError
        ) as exc_info:
            service.execute(
                PublishKnowledgeVersionCommand(
                    version_id=missing_id
                )
            )

        assert (
            exc_info.value.version_id
            == missing_id
        )

        assert uow.commit_count == 0

    def test_missing_parent_document_raises(
        self,
    ) -> None:
        document_id = uuid4()

        target = make_ready_version(
            document_id=document_id
        )

        versions = FakeVersionRepository(
            [target]
        )

        documents = FakeDocumentRepository()

        uow = FakeKnowledgeUnitOfWork(
            documents=documents,
            versions=versions,
        )

        service = PublishKnowledgeVersion(
            uow_factory=FakeKnowledgeUnitOfWorkFactory(
                uow
            )
        )

        with pytest.raises(
            KnowledgeDocumentDoesNotExistError
        ) as exc_info:
            service.execute(
                PublishKnowledgeVersionCommand(
                    version_id=target.id
                )
            )

        assert (
            exc_info.value.document_id
            == document_id
        )

        assert uow.commit_count == 0

    def test_target_disappearing_after_lock_raises(
        self,
    ) -> None:
        document = make_document()

        target = make_ready_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        harness.versions.return_none_on_locked_lookup = True

        with pytest.raises(
            KnowledgeVersionDoesNotExistError
        ):
            harness.service.execute(
                PublishKnowledgeVersionCommand(
                    version_id=target.id
                )
            )

        assert harness.uow.commit_count == 0


# ===========================================================================
# Document lifecycle
# ===========================================================================


class TestDocumentLifecycle:

    @pytest.mark.parametrize(
        "status",
        [
            KnowledgeDocumentStatus.ARCHIVED,
            KnowledgeDocumentStatus.DELETED,
        ],
    )
    def test_non_active_document_cannot_publish(
        self,
        status: KnowledgeDocumentStatus,
    ) -> None:
        document = make_document(
            status=status
        )

        target = make_ready_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        with pytest.raises(
            KnowledgeDocumentNotPublishableError
        ) as exc_info:
            harness.service.execute(
                PublishKnowledgeVersionCommand(
                    version_id=target.id
                )
            )

        assert (
            exc_info.value.document_id
            == document.id
        )

        assert exc_info.value.status is status

        assert harness.uow.commit_count == 0
        assert (
            harness.versions.saved_versions
            == []
        )


# ===========================================================================
# Target version domain validation
# ===========================================================================


class TestTargetVersionValidation:

    def test_draft_version_domain_error_propagates(
        self,
    ) -> None:
        document = make_document()

        target = make_draft_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        with pytest.raises(
            KnowledgeVersionNotReadyError
        ):
            harness.service.execute(
                PublishKnowledgeVersionCommand(
                    version_id=target.id
                )
            )

        assert harness.uow.commit_count == 0

    def test_already_published_target_is_rejected(
        self,
    ) -> None:
        document = make_document()

        target = make_published_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        # The repository sees target itself as the current publication.
        # The application detects this cross-version conflict before
        # target.publish() is invoked again.
        with pytest.raises(
            KnowledgePublicationConflictError,
            match="already the published version",
        ):
            harness.service.execute(
                PublishKnowledgeVersionCommand(
                    version_id=target.id
                )
            )

        assert harness.uow.commit_count == 0


# ===========================================================================
# Stale / conflicting aggregate state
# ===========================================================================


class TestPublicationConflicts:

    def test_locked_target_changing_document_is_rejected(
        self,
    ) -> None:
        document = make_document()

        target = make_ready_version(
            document_id=document.id
        )

        harness = build_harness(
            document=document,
            target=target,
        )

        changed_target = make_ready_version(
            version_id=target.id,
            document_id=uuid4(),
        )

        harness.versions.override_locked_version = (
            changed_target
        )

        with pytest.raises(
            KnowledgePublicationConflictError,
            match="no longer belongs",
        ):
            harness.service.execute(
                PublishKnowledgeVersionCommand(
                    version_id=target.id
                )
            )

        assert harness.uow.commit_count == 0


# ===========================================================================
# Transaction rollback
# ===========================================================================


class ExplodingFlushKnowledgeUnitOfWork(
    FakeKnowledgeUnitOfWork
):
    def flush(self) -> None:
        self.flush_count += 1
        raise RuntimeError(
            "simulated database constraint failure"
        )


class TestTransactionFailure:

    def test_flush_failure_prevents_commit_and_rolls_back(
        self,
    ) -> None:
        document = make_document()

        previous = make_published_version(
            document_id=document.id,
            version_number=1,
        )

        target = make_ready_version(
            document_id=document.id,
            version_number=2,
        )

        documents = FakeDocumentRepository(
            [document]
        )

        versions = FakeVersionRepository(
            [previous, target]
        )

        uow = ExplodingFlushKnowledgeUnitOfWork(
            documents=documents,
            versions=versions,
        )

        service = PublishKnowledgeVersion(
            uow_factory=FakeKnowledgeUnitOfWorkFactory(
                uow
            )
        )

        with pytest.raises(
            RuntimeError,
            match="simulated database constraint failure",
        ):
            service.execute(
                PublishKnowledgeVersionCommand(
                    version_id=target.id
                )
            )

        assert uow.flush_count == 1
        assert uow.commit_count == 0
        assert uow.rollback_count == 1

        assert (
            uow.exit_exception_type
            is RuntimeError
        )