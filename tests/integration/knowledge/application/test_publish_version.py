from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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

from packages.knowledge.application.publish_version import (
    KnowledgeDocumentNotPublishableError,
    PublishKnowledgeVersion,
    PublishKnowledgeVersionCommand,
)
from packages.knowledge.domain.enums import (
    KnowledgeDocumentStatus,
    KnowledgeVersionStatus,
)
from packages.knowledge.domain.errors import (
    KnowledgeVersionNotReadyError,
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
    document_id = uuid4()
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
    version_id = uuid4()

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
                    f"{version_number}"
                    * 64
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
                processing_completed_at=(
                    processing_completed_at
                ),
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
    version_id = uuid4()

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
                    f"Published refund policy version {version_number}."
                ),
                content_hash=(
                    f"{version_number + 1}"
                    * 64
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
                processing_completed_at=(
                    processing_completed_at
                ),
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
) -> PublishKnowledgeVersion:
    return PublishKnowledgeVersion(
        uow_factory=lambda: SQLAlchemyKnowledgeUnitOfWork(
            session_factory
        )
    )


# ===========================================================================
# First publication
# ===========================================================================


class TestFirstPublication:

    def test_publishes_ready_version_in_postgresql(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        version_id = seed_ready_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        service = build_service(
            test_session_factory
        )

        result = service.execute(
            PublishKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        assert result.version_id == version_id
        assert result.document_id == document_id
        assert result.version_number == 1

        assert (
            result.status
            is KnowledgeVersionStatus.PUBLISHED
        )

        assert result.published_at is not None
        assert result.superseded_version_id is None

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentVersionModel,
                version_id,
            )

            assert persisted is not None
            assert persisted.status == "published"
            assert (
                persisted.ingestion_status
                == "completed"
            )

            assert persisted.published_at is not None
            assert persisted.superseded_at is None


    def test_published_version_round_trips_through_repository(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        version_id = seed_ready_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        service = build_service(
            test_session_factory
        )

        service.execute(
            PublishKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        with SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        ) as uow:
            persisted = uow.versions.get_by_id(
                version_id
            )

        assert persisted is not None
        assert persisted.is_published
        assert persisted.published_at is not None
        assert persisted.superseded_at is None


# ===========================================================================
# Replacement publication
# ===========================================================================


class TestReplacementPublication:

    def test_supersedes_previous_and_publishes_new_version(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        old_version_id = seed_published_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        new_version_id = seed_ready_version(
            test_session_factory,
            document_id=document_id,
            version_number=2,
        )

        service = build_service(
            test_session_factory
        )

        result = service.execute(
            PublishKnowledgeVersionCommand(
                version_id=new_version_id
            )
        )

        assert result.version_id == new_version_id
        assert (
            result.superseded_version_id
            == old_version_id
        )

        with test_session_factory() as session:
            old_version = session.get(
                KnowledgeDocumentVersionModel,
                old_version_id,
            )

            new_version = session.get(
                KnowledgeDocumentVersionModel,
                new_version_id,
            )

            assert old_version is not None
            assert new_version is not None

            assert old_version.status == "superseded"
            assert old_version.superseded_at is not None

            assert new_version.status == "published"
            assert new_version.published_at is not None

            # Application uses the same occurred_at for both transitions.
            assert (
                old_version.superseded_at
                == new_version.published_at
            )


    def test_only_one_published_version_remains(
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

        new_version_id = seed_ready_version(
            test_session_factory,
            document_id=document_id,
            version_number=2,
        )

        service = build_service(
            test_session_factory
        )

        service.execute(
            PublishKnowledgeVersionCommand(
                version_id=new_version_id
            )
        )

        with test_session_factory() as session:
            published_versions = (
                session.scalars(
                    select(
                        KnowledgeDocumentVersionModel
                    ).where(
                        KnowledgeDocumentVersionModel.document_id
                        == document_id,
                        KnowledgeDocumentVersionModel.status
                        == "published",
                    )
                )
                .all()
            )

            assert len(published_versions) == 1

            assert (
                published_versions[0].id
                == new_version_id
            )


    def test_previous_publication_timestamp_is_preserved(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        old_version_id = seed_published_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        with test_session_factory() as session:
            original = session.get(
                KnowledgeDocumentVersionModel,
                old_version_id,
            )

            assert original is not None
            original_published_at = (
                original.published_at
            )

        new_version_id = seed_ready_version(
            test_session_factory,
            document_id=document_id,
            version_number=2,
        )

        service = build_service(
            test_session_factory
        )

        service.execute(
            PublishKnowledgeVersionCommand(
                version_id=new_version_id
            )
        )

        with test_session_factory() as session:
            superseded = session.get(
                KnowledgeDocumentVersionModel,
                old_version_id,
            )

            assert superseded is not None

            assert (
                superseded.published_at
                == original_published_at
            )

            assert superseded.superseded_at is not None


# ===========================================================================
# Parent document lifecycle
# ===========================================================================


class TestDocumentLifecycle:

    @pytest.mark.parametrize(
        "status",
        [
            "archived",
            "deleted",
        ],
    )
    def test_non_active_document_rejects_publication(
        self,
        test_session_factory: sessionmaker[Session],
        status: str,
    ) -> None:
        document_id = seed_document(
            test_session_factory,
            status=status,
        )

        version_id = seed_ready_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        service = build_service(
            test_session_factory
        )

        with pytest.raises(
            KnowledgeDocumentNotPublishableError
        ):
            service.execute(
                PublishKnowledgeVersionCommand(
                    version_id=version_id
                )
            )

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentVersionModel,
                version_id,
            )

            assert persisted is not None

            # Transaction must leave target untouched.
            assert persisted.status == "ready"
            assert persisted.published_at is None


# ===========================================================================
# Domain rejection + rollback
# ===========================================================================


class TestInvalidTargetLifecycle:

    def test_draft_version_is_not_published(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        version_id = uuid4()
        now = utc_now()

        with test_session_factory() as session:
            session.add(
                KnowledgeDocumentVersionModel(
                    id=version_id,
                    document_id=document_id,
                    version_number=1,
                    source_type="plain_text",
                    source_content="Still a draft.",
                    content_hash="d" * 64,
                    status="draft",
                    ingestion_status="pending",
                    source_name="draft.txt",
                    source_uri=None,
                    metadata_={},
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
            )

            session.commit()

        service = build_service(
            test_session_factory
        )

        with pytest.raises(
            KnowledgeVersionNotReadyError
        ):
            service.execute(
                PublishKnowledgeVersionCommand(
                    version_id=version_id
                )
            )

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentVersionModel,
                version_id,
            )

            assert persisted is not None
            assert persisted.status == "draft"
            assert (
                persisted.ingestion_status
                == "pending"
            )
            assert persisted.published_at is None


# ===========================================================================
# Database invariant
# ===========================================================================


class TestSinglePublishedVersionDatabaseConstraint:

    def test_database_rejects_two_published_versions_for_same_document(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        """
        Directly bypass the application service.

        This test exists specifically to prove PostgreSQL independently
        enforces the "one published version per document" invariant.
        """

        document_id = seed_document(
            test_session_factory
        )

        seed_published_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        now = utc_now()
        second_id = uuid4()

        with pytest.raises(IntegrityError):
            with test_session_factory() as session:
                session.add(
                    KnowledgeDocumentVersionModel(
                        id=second_id,
                        document_id=document_id,
                        version_number=2,
                        source_type="plain_text",
                        source_content=(
                            "Illegal second published version."
                        ),
                        content_hash="e" * 64,
                        status="published",
                        ingestion_status="completed",
                        source_name="illegal-v2.txt",
                        source_uri=None,
                        metadata_={},
                        created_at=(
                            now - timedelta(seconds=5)
                        ),
                        updated_at=now,
                        processing_started_at=(
                            now - timedelta(seconds=4)
                        ),
                        processing_completed_at=(
                            now - timedelta(seconds=3)
                        ),
                        ready_at=(
                            now - timedelta(seconds=3)
                        ),
                        published_at=now,
                        superseded_at=None,
                        archived_at=None,
                        failure_code=None,
                        failure_message=None,
                    )
                )

                session.commit()


    def test_database_allows_multiple_non_published_versions(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        """
        The partial unique index must restrict only status='published'.
        READY/SUPERSEDED/etc. versions for the same document remain valid.
        """

        document_id = seed_document(
            test_session_factory
        )

        first_id = seed_ready_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        second_id = seed_ready_version(
            test_session_factory,
            document_id=document_id,
            version_number=2,
        )

        with test_session_factory() as session:
            versions = (
                session.scalars(
                    select(
                        KnowledgeDocumentVersionModel
                    ).where(
                        KnowledgeDocumentVersionModel.document_id
                        == document_id
                    )
                )
                .all()
            )

            ids = {
                version.id
                for version in versions
            }

            assert first_id in ids
            assert second_id in ids

            assert all(
                version.status != "published"
                for version in versions
            )


# ===========================================================================
# Repository contract
# ===========================================================================


class TestPublishedRepositoryLookup:

    def test_repository_returns_newly_published_version(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        version_id = seed_ready_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        service = build_service(
            test_session_factory
        )

        service.execute(
            PublishKnowledgeVersionCommand(
                version_id=version_id
            )
        )

        with SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        ) as uow:
            published = (
                uow.versions
                .get_published_for_document(
                    document_id
                )
            )

        assert published is not None
        assert published.id == version_id
        assert published.is_published


    def test_repository_returns_replacement_after_supersession(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        old_id = seed_published_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
        )

        new_id = seed_ready_version(
            test_session_factory,
            document_id=document_id,
            version_number=2,
        )

        service = build_service(
            test_session_factory
        )

        service.execute(
            PublishKnowledgeVersionCommand(
                version_id=new_id
            )
        )

        with SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        ) as uow:
            published = (
                uow.versions
                .get_published_for_document(
                    document_id
                )
            )

            old = uow.versions.get_by_id(
                old_id
            )

        assert published is not None
        assert published.id == new_id

        assert old is not None
        assert old.is_superseded