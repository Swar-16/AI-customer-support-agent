from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID
from uuid6 import uuid7

import pytest
from sqlalchemy.orm import Session, sessionmaker

from packages.database.models.knowledge.document import (
    KnowledgeDocumentModel,
)
from packages.database.models.knowledge.document_version import (
    KnowledgeDocumentVersionModel,
)
from packages.database.unit_of_work.knowledge import (
    SQLAlchemyKnowledgeUnitOfWork,
)

from packages.knowledge.application.archive_document import (
    ArchiveKnowledgeDocument,
    ArchiveKnowledgeDocumentCommand,
    KnowledgeDocumentDoesNotExistError,
)
from packages.knowledge.domain.enums import (
    KnowledgeDocumentStatus,
    KnowledgeVersionStatus,
)
from packages.knowledge.domain.errors import (
    KnowledgeDocumentAlreadyArchivedError,
    KnowledgeDocumentDeletedError,
)


UTC = timezone.utc


# ===========================================================================
# Helpers
# ===========================================================================


def utc_now() -> datetime:
    return datetime.now(UTC)


def seed_document(
    session_factory: sessionmaker[Session],
    *,
    status: str = "active",
) -> UUID:
    document_id = uuid7()
    now = utc_now()

    archived_at = (
        now
        if status == "archived"
        else None
    )

    deleted_at = (
        now
        if status == "deleted"
        else None
    )

    with session_factory() as session:
        session.add(
            KnowledgeDocumentModel(
                id=document_id,
                title="Refund Policy",
                description="Integration-test refund policy.",
                content_type="policy",
                visibility="customer",
                status=status,
                metadata_={
                    "integration_test": True,
                },
                created_at=now,
                updated_at=now,
                archived_at=archived_at,
                deleted_at=deleted_at,
            )
        )

        session.commit()

    return document_id


def seed_ready_version(
    session_factory: sessionmaker[Session],
    *,
    document_id: UUID,
    version_number: int,
) -> UUID:
    """
    A READY version is deliberately useful for archival tests.

    Archiving the parent must NOT automatically archive READY,
    DRAFT, FAILED, or other historical versions.
    """
    version_id = uuid7()

    now = utc_now()
    created_at = now - timedelta(seconds=5)
    processing_started_at = now - timedelta(seconds=4)
    processing_completed_at = now - timedelta(seconds=2)

    with session_factory() as session:
        session.add(
            KnowledgeDocumentVersionModel(
                id=version_id,
                document_id=document_id,
                version_number=version_number,
                source_type="plain_text",
                source_content=(
                    f"Refund policy version {version_number}."
                ),
                content_hash=(
                    f"{version_number}" * 64
                )[:64],
                status="ready",
                ingestion_status="completed",
                source_name=(
                    f"refund-policy-v{version_number}.txt"
                ),
                source_uri=None,
                metadata_={
                    "integration_test": True,
                    "version": version_number,
                },
                created_at=created_at,
                updated_at=processing_completed_at,
                processing_started_at=processing_started_at,
                processing_completed_at=processing_completed_at,
                ready_at=processing_completed_at,
                published_at=None,
                superseded_at=None,
                archived_at=None,
                failure_code=None,
                failure_message=None,
            )
        )

        session.commit()

    return version_id


def seed_published_version(
    session_factory: sessionmaker[Session],
    *,
    document_id: UUID,
    version_number: int,
) -> UUID:
    version_id = uuid7()

    now = utc_now()
    created_at = now - timedelta(seconds=10)
    processing_started_at = now - timedelta(seconds=9)
    processing_completed_at = now - timedelta(seconds=8)
    published_at = now - timedelta(seconds=5)

    with session_factory() as session:
        session.add(
            KnowledgeDocumentVersionModel(
                id=version_id,
                document_id=document_id,
                version_number=version_number,
                source_type="plain_text",
                source_content=(
                    f"Published refund policy version "
                    f"{version_number}."
                ),
                content_hash=(
                    f"{version_number + 1}" * 64
                )[:64],
                status="published",
                ingestion_status="completed",
                source_name=(
                    f"refund-policy-v{version_number}.txt"
                ),
                source_uri=None,
                metadata_={
                    "integration_test": True,
                    "version": version_number,
                },
                created_at=created_at,
                updated_at=published_at,
                processing_started_at=processing_started_at,
                processing_completed_at=processing_completed_at,
                ready_at=processing_completed_at,
                published_at=published_at,
                superseded_at=None,
                archived_at=None,
                failure_code=None,
                failure_message=None,
            )
        )

        session.commit()

    return version_id


def build_service(
    session_factory: sessionmaker[Session],
) -> ArchiveKnowledgeDocument:
    return ArchiveKnowledgeDocument(
        uow_factory=lambda: SQLAlchemyKnowledgeUnitOfWork(
            session_factory
        )
    )


# ===========================================================================
# Basic archival
# ===========================================================================


class TestArchiveDocument:

    def test_archiving_active_document_persists_archived_state(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        service = build_service(
            test_session_factory
        )

        result = service.execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document_id
            )
        )

        assert result.document_id == document_id

        assert (
            result.status
            is KnowledgeDocumentStatus.ARCHIVED
        )

        assert result.archived_at is not None
        assert result.superseded_version_id is None

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            assert persisted is not None
            assert persisted.status == "archived"
            assert persisted.archived_at is not None
            assert persisted.deleted_at is None


    def test_archived_document_round_trips_through_repository(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        build_service(
            test_session_factory
        ).execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document_id
            )
        )

        with SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        ) as uow:
            persisted = uow.documents.get_by_id(
                document_id
            )

        assert persisted is not None
        assert persisted.is_archived
        assert persisted.archived_at is not None


# ===========================================================================
# Published-version coordination
# ===========================================================================


class TestArchivePublishedDocument:

    def test_archiving_document_supersedes_current_publication(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        published_version_id = seed_published_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        service = build_service(
            test_session_factory
        )

        result = service.execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document_id
            )
        )

        assert (
            result.superseded_version_id
            == published_version_id
        )

        with test_session_factory() as session:
            document = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            version = session.get(
                KnowledgeDocumentVersionModel,
                published_version_id,
            )

            assert document is not None
            assert version is not None

            assert document.status == "archived"
            assert document.archived_at is not None

            assert version.status == "superseded"
            assert version.superseded_at is not None

            # Publishing history must remain preserved.
            assert version.published_at is not None


    def test_archived_document_has_no_published_version(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        seed_published_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        build_service(
            test_session_factory
        ).execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document_id
            )
        )

        with SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        ) as uow:
            document = uow.documents.get_by_id(
                document_id
            )

            published = (
                uow.versions.get_published_for_document(
                    document_id
                )
            )

        assert document is not None
        assert document.is_archived

        # Main cross-aggregate invariant.
        assert published is None


    def test_document_and_superseded_version_share_transition_time(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        published_version_id = seed_published_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        build_service(
            test_session_factory
        ).execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document_id
            )
        )

        with test_session_factory() as session:
            document = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            version = session.get(
                KnowledgeDocumentVersionModel,
                published_version_id,
            )

            assert document is not None
            assert version is not None

            # ArchiveKnowledgeDocument intentionally uses
            # one occurred_at for the coordinated transition.
            assert (
                document.archived_at
                == version.superseded_at
            )


    def test_previous_publication_timestamp_is_preserved(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        published_version_id = seed_published_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        with test_session_factory() as session:
            original = session.get(
                KnowledgeDocumentVersionModel,
                published_version_id,
            )

            assert original is not None
            original_published_at = original.published_at

        build_service(
            test_session_factory
        ).execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document_id
            )
        )

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentVersionModel,
                published_version_id,
            )

            assert persisted is not None

            assert (
                persisted.published_at
                == original_published_at
            )

            assert persisted.superseded_at is not None


# ===========================================================================
# Historical versions
# ===========================================================================


class TestArchivePreservesHistoricalVersions:

    def test_ready_version_is_not_archived_when_document_is_archived(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        """
        Parent archival should deactivate the logical document but should
        not destroy the historical lifecycle state of non-published versions.
        """
        document_id = seed_document(
            test_session_factory
        )

        ready_version_id = seed_ready_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        build_service(
            test_session_factory
        ).execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document_id
            )
        )

        with test_session_factory() as session:
            document = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            version = session.get(
                KnowledgeDocumentVersionModel,
                ready_version_id,
            )

            assert document is not None
            assert version is not None

            assert document.status == "archived"

            # Version retains its historical lifecycle.
            assert version.status == "ready"
            assert version.archived_at is None


# ===========================================================================
# Invalid parent lifecycle
# ===========================================================================


class TestInvalidDocumentLifecycle:

    def test_already_archived_document_is_rejected(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory,
            status="archived",
        )

        service = build_service(
            test_session_factory
        )

        with pytest.raises(
            KnowledgeDocumentAlreadyArchivedError
        ):
            service.execute(
                ArchiveKnowledgeDocumentCommand(
                    document_id=document_id
                )
            )

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            assert persisted is not None
            assert persisted.status == "archived"
            assert persisted.archived_at is not None


    def test_deleted_document_is_rejected(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory,
            status="deleted",
        )

        service = build_service(
            test_session_factory
        )

        with pytest.raises(
            KnowledgeDocumentDeletedError
        ):
            service.execute(
                ArchiveKnowledgeDocumentCommand(
                    document_id=document_id
                )
            )

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            assert persisted is not None
            assert persisted.status == "deleted"
            assert persisted.deleted_at is not None


# ===========================================================================
# Missing document
# ===========================================================================


class TestMissingDocument:

    def test_missing_document_is_rejected(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = uuid7()

        service = build_service(
            test_session_factory
        )

        with pytest.raises(
            KnowledgeDocumentDoesNotExistError
        ):
            service.execute(
                ArchiveKnowledgeDocumentCommand(
                    document_id=document_id
                )
            )


# ===========================================================================
# Repository contract
# ===========================================================================


class TestRepositoryStateAfterArchive:

    def test_published_lookup_returns_none_after_archival(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        version_id = seed_published_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        build_service(
            test_session_factory
        ).execute(
            ArchiveKnowledgeDocumentCommand(
                document_id=document_id
            )
        )

        with SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        ) as uow:
            published = (
                uow.versions.get_published_for_document(
                    document_id
                )
            )

            historical = uow.versions.get_by_id(
                version_id
            )

        assert published is None

        assert historical is not None
        assert historical.is_superseded
        assert historical.published_at is not None
        assert historical.superseded_at is not None