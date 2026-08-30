from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from packages.knowledge.application.archive_document import (
    ArchiveKnowledgeDocument,
    ArchiveKnowledgeDocumentCommand,
    KnowledgeArchiveConflictError,
    KnowledgeDocumentDoesNotExistError,
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
    KnowledgeDocumentAlreadyArchivedError,
    KnowledgeDocumentDeletedError,
)
from packages.knowledge.domain.version import KnowledgeDocumentVersion


NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


# ===========================================================================
# Builders
# ===========================================================================


def make_document(
    *,
    document_id=None,
    status=KnowledgeDocumentStatus.ACTIVE,
) -> KnowledgeDocument:
    document_id = document_id or uuid4()

    kwargs = {
        "id": document_id,
        "title": "Refund Policy",
        "content_type": KnowledgeContentType.POLICY,
        "visibility": KnowledgeVisibility.CUSTOMER,
        "status": status,
        "created_at": NOW,
        "updated_at": NOW,
    }

    if status is KnowledgeDocumentStatus.ARCHIVED:
        kwargs["archived_at"] = NOW

    if status is KnowledgeDocumentStatus.DELETED:
        kwargs["deleted_at"] = NOW

    return KnowledgeDocument(**kwargs)


def make_published_version(
    *,
    document_id,
    version_id=None,
) -> KnowledgeDocumentVersion:
    version_id = version_id or uuid4()

    return KnowledgeDocumentVersion(
        id=version_id,
        document_id=document_id,
        version_number=1,
        source_type=KnowledgeSourceType.MARKDOWN,
        source_content="# Refund Policy\nRefunds are available.",
        content_hash="hash-1",
        status=KnowledgeVersionStatus.PUBLISHED,
        ingestion_status=KnowledgeIngestionStatus.COMPLETED,
        created_at=NOW,
        updated_at=NOW,
        processing_started_at=NOW,
        processing_completed_at=NOW,
        ready_at=NOW,
        published_at=NOW,
    )


# ===========================================================================
# Fakes
# ===========================================================================


class FakeDocumentRepository:
    def __init__(self, document=None, events=None):
        self.document = document
        self.events = events if events is not None else []
        self.saved = []

    def get_by_id_for_update(self, document_id):
        self.events.append("document:lock")

        if (
            self.document is not None
            and self.document.id == document_id
        ):
            return self.document

        return None

    def save(self, document):
        self.events.append("document:save")
        self.document = document
        self.saved.append(document)


class FakeVersionRepository:
    def __init__(
        self,
        published=None,
        events=None,
    ):
        self.published = published
        self.events = events if events is not None else []
        self.saved = []

    def get_published_for_document(self, document_id):
        self.events.append("version:get_published")
        return self.published

    def save(self, version):
        self.events.append("version:save")
        self.saved.append(version)
        self.published = version


class FakeKnowledgeUnitOfWork:
    def __init__(
        self,
        *,
        document=None,
        published=None,
        fail_flush_number=None,
    ):
        self.events = []

        self.documents = FakeDocumentRepository(
            document=document,
            events=self.events,
        )

        self.versions = FakeVersionRepository(
            published=published,
            events=self.events,
        )

        self.fail_flush_number = fail_flush_number

        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def __enter__(self):
        self.events.append("uow:enter")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.rollback_count += 1
            self.events.append("uow:rollback")

        self.events.append("uow:exit")
        return False

    def flush(self):
        self.flush_count += 1
        self.events.append(
            f"uow:flush:{self.flush_count}"
        )

        if self.fail_flush_number == self.flush_count:
            raise RuntimeError("simulated flush failure")

    def commit(self):
        self.commit_count += 1
        self.events.append("uow:commit")


def factory_for(uow):
    return lambda: uow


# ===========================================================================
# Construction / command validation
# ===========================================================================


def test_command_rejects_non_uuid_document_id():
    with pytest.raises(TypeError):
        ArchiveKnowledgeDocumentCommand(
            document_id="not-a-uuid"
        )


def test_service_rejects_non_callable_uow_factory():
    with pytest.raises(TypeError):
        ArchiveKnowledgeDocument(
            uow_factory=None
        )


def test_execute_rejects_wrong_command_type():
    service = ArchiveKnowledgeDocument(
        uow_factory=lambda: None
    )

    with pytest.raises(TypeError):
        service.execute(uuid4())


# ===========================================================================
# Basic archival
# ===========================================================================


def test_archives_active_document_without_published_version():
    document = make_document()

    uow = FakeKnowledgeUnitOfWork(
        document=document,
    )

    service = ArchiveKnowledgeDocument(
        uow_factory=factory_for(uow)
    )

    result = service.execute(
        ArchiveKnowledgeDocumentCommand(
            document_id=document.id
        )
    )

    assert (
        result.document_id
        == document.id
    )

    assert (
        result.status
        is KnowledgeDocumentStatus.ARCHIVED
    )

    assert result.archived_at is not None
    assert result.superseded_version_id is None

    assert len(uow.documents.saved) == 1

    archived = uow.documents.saved[0]

    assert archived.is_archived
    assert archived.archived_at is not None

    assert uow.flush_count == 1
    assert uow.commit_count == 1


def test_document_is_locked_before_publication_lookup():
    document = make_document()

    uow = FakeKnowledgeUnitOfWork(
        document=document,
    )

    service = ArchiveKnowledgeDocument(
        uow_factory=factory_for(uow)
    )

    service.execute(
        ArchiveKnowledgeDocumentCommand(
            document_id=document.id
        )
    )

    assert (
        uow.events.index("document:lock")
        <
        uow.events.index("version:get_published")
    )


# ===========================================================================
# Published-version coordination
# ===========================================================================


def test_supersedes_published_version_before_archiving_document():
    document = make_document()

    published = make_published_version(
        document_id=document.id
    )

    uow = FakeKnowledgeUnitOfWork(
        document=document,
        published=published,
    )

    service = ArchiveKnowledgeDocument(
        uow_factory=factory_for(uow)
    )

    result = service.execute(
        ArchiveKnowledgeDocumentCommand(
            document_id=document.id
        )
    )

    assert (
        result.superseded_version_id
        == published.id
    )

    assert len(uow.versions.saved) == 1

    superseded = uow.versions.saved[0]

    assert (
        superseded.status
        is KnowledgeVersionStatus.SUPERSEDED
    )

    assert superseded.superseded_at is not None

    archived = uow.documents.saved[0]

    assert archived.is_archived

    # One flush after supersession and another after
    # parent archival.
    assert uow.flush_count == 2
    assert uow.commit_count == 1


def test_supersession_is_flushed_before_document_is_archived():
    document = make_document()

    published = make_published_version(
        document_id=document.id
    )

    uow = FakeKnowledgeUnitOfWork(
        document=document,
        published=published,
    )

    service = ArchiveKnowledgeDocument(
        uow_factory=factory_for(uow)
    )

    service.execute(
        ArchiveKnowledgeDocumentCommand(
            document_id=document.id
        )
    )

    assert uow.events == [
        "uow:enter",
        "document:lock",
        "version:get_published",
        "version:save",
        "uow:flush:1",
        "document:save",
        "uow:flush:2",
        "uow:commit",
        "uow:exit",
    ]


def test_superseded_and_archived_entities_share_same_transition_time():
    document = make_document()

    published = make_published_version(
        document_id=document.id
    )

    uow = FakeKnowledgeUnitOfWork(
        document=document,
        published=published,
    )

    service = ArchiveKnowledgeDocument(
        uow_factory=factory_for(uow)
    )

    service.execute(
        ArchiveKnowledgeDocumentCommand(
            document_id=document.id
        )
    )

    superseded = uow.versions.saved[0]
    archived = uow.documents.saved[0]

    assert (
        superseded.superseded_at
        == archived.archived_at
    )


# ===========================================================================
# Missing / invalid state
# ===========================================================================


def test_missing_document_raises_and_does_not_commit():
    uow = FakeKnowledgeUnitOfWork(
        document=None
    )

    service = ArchiveKnowledgeDocument(
        uow_factory=factory_for(uow)
    )

    document_id = uuid4()

    with pytest.raises(
        KnowledgeDocumentDoesNotExistError
    ) as exc_info:
        service.execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document_id
            )
        )

    assert (
        exc_info.value.document_id
        == document_id
    )

    assert uow.flush_count == 0
    assert uow.commit_count == 0
    assert uow.rollback_count == 1


def test_already_archived_document_uses_domain_rejection():
    document = make_document(
        status=KnowledgeDocumentStatus.ARCHIVED
    )

    uow = FakeKnowledgeUnitOfWork(
        document=document,
    )

    service = ArchiveKnowledgeDocument(
        uow_factory=factory_for(uow)
    )

    with pytest.raises(
        KnowledgeDocumentAlreadyArchivedError
    ):
        service.execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document.id
            )
        )

    assert uow.commit_count == 0
    assert uow.rollback_count == 1


def test_deleted_document_uses_domain_rejection():
    document = make_document(
        status=KnowledgeDocumentStatus.DELETED
    )

    uow = FakeKnowledgeUnitOfWork(
        document=document,
    )

    service = ArchiveKnowledgeDocument(
        uow_factory=factory_for(uow)
    )

    with pytest.raises(
        KnowledgeDocumentDeletedError
    ):
        service.execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document.id
            )
        )

    assert uow.commit_count == 0
    assert uow.rollback_count == 1


def test_rejects_published_version_belonging_to_another_document():
    document = make_document()

    published = make_published_version(
        document_id=uuid4()
    )

    uow = FakeKnowledgeUnitOfWork(
        document=document,
        published=published,
    )

    service = ArchiveKnowledgeDocument(
        uow_factory=factory_for(uow)
    )

    with pytest.raises(
        KnowledgeArchiveConflictError
    ):
        service.execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document.id
            )
        )

    assert uow.flush_count == 0
    assert uow.commit_count == 0
    assert uow.rollback_count == 1


# ===========================================================================
# Transaction failure
# ===========================================================================


def test_second_flush_failure_rolls_back_entire_archival_transaction():
    document = make_document()

    published = make_published_version(
        document_id=document.id
    )

    uow = FakeKnowledgeUnitOfWork(
        document=document,
        published=published,
        fail_flush_number=2,
    )

    service = ArchiveKnowledgeDocument(
        uow_factory=factory_for(uow)
    )

    with pytest.raises(
        RuntimeError,
        match="simulated flush failure",
    ):
        service.execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document.id
            )
        )

    assert uow.flush_count == 2
    assert uow.commit_count == 0
    assert uow.rollback_count == 1