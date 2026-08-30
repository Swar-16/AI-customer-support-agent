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

from packages.knowledge.application.get_document import (
    GetKnowledgeDocument,
    GetKnowledgeDocumentQuery,
    KnowledgeDocumentDoesNotExistError,
)
from packages.knowledge.domain.enums import (
    KnowledgeDocumentStatus,
    KnowledgeVersionStatus,
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
    title: str = "Refund Policy",
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
                title=title,
                description="Integration-test knowledge document.",
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


def seed_version(
    session_factory: sessionmaker[Session],
    *,
    document_id: UUID,
    version_number: int,
    status: str,
) -> UUID:
    """
    Seed a valid version for the requested lifecycle state.

    This helper deliberately builds lifecycle-consistent rows because the
    repository maps ORM rows back into strict domain entities.
    """
    version_id = uuid7()

    now = utc_now()

    created_at = now - timedelta(
        seconds=20 - version_number
    )

    processing_started_at = None
    processing_completed_at = None
    ready_at = None
    published_at = None
    superseded_at = None
    archived_at = None

    ingestion_status = "pending"

    if status in {
        "ready",
        "published",
        "superseded",
    }:
        processing_started_at = (
            created_at + timedelta(seconds=1)
        )

        processing_completed_at = (
            created_at + timedelta(seconds=2)
        )

        ready_at = processing_completed_at
        ingestion_status = "completed"

    if status in {
        "published",
        "superseded",
    }:
        published_at = (
            created_at + timedelta(seconds=3)
        )

    if status == "superseded":
        superseded_at = (
            created_at + timedelta(seconds=4)
        )

    if status == "archived":
        archived_at = (
            created_at + timedelta(seconds=1)
        )

    # updated_at must not precede lifecycle timestamps.
    updated_candidates = [
        created_at,
        processing_started_at,
        processing_completed_at,
        ready_at,
        published_at,
        superseded_at,
        archived_at,
    ]

    updated_at = max(
        value
        for value in updated_candidates
        if value is not None
    )

    with session_factory() as session:
        session.add(
            KnowledgeDocumentVersionModel(
                id=version_id,
                document_id=document_id,
                version_number=version_number,
                source_type="plain_text",
                source_content=(
                    f"Knowledge version {version_number}."
                ),
                content_hash=(
                    f"{version_number}" * 64
                )[:64],
                status=status,
                ingestion_status=ingestion_status,
                source_name=(
                    f"knowledge-v{version_number}.txt"
                ),
                source_uri=None,
                metadata_={
                    "integration_test": True,
                    "version": version_number,
                },
                created_at=created_at,
                updated_at=updated_at,
                processing_started_at=processing_started_at,
                processing_completed_at=processing_completed_at,
                ready_at=ready_at,
                published_at=published_at,
                superseded_at=superseded_at,
                archived_at=archived_at,
                failure_code=None,
                failure_message=None,
            )
        )

        session.commit()

    return version_id


def build_service(
    session_factory: sessionmaker[Session],
) -> GetKnowledgeDocument:
    return GetKnowledgeDocument(
        uow_factory=lambda: SQLAlchemyKnowledgeUnitOfWork(
            session_factory
        )
    )


# ===========================================================================
# Basic retrieval
# ===========================================================================


class TestGetDocument:

    def test_returns_persisted_document(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory,
            title="Refund Policy",
        )

        service = build_service(
            test_session_factory
        )

        result = service.execute(
            GetKnowledgeDocumentQuery(
                document_id=document_id
            )
        )

        assert result.document.id == document_id
        assert result.document.title == "Refund Policy"

        assert (
            result.document.status
            is KnowledgeDocumentStatus.ACTIVE
        )

        assert result.versions == ()
        assert result.published_version_id is None


    def test_document_round_trips_through_application_service(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        result = build_service(
            test_session_factory
        ).execute(
            GetKnowledgeDocumentQuery(
                document_id=document_id
            )
        )

        assert result.document.id == document_id

        assert (
            result.document.metadata[
                "integration_test"
            ]
            is True
        )


# ===========================================================================
# Version history
# ===========================================================================


class TestVersionHistory:

    def test_returns_all_versions_for_document(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        version_1 = seed_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
            status="superseded",
        )

        version_2 = seed_version(
            test_session_factory,
            document_id=document_id,
            version_number=2,
            status="ready",
        )

        result = build_service(
            test_session_factory
        ).execute(
            GetKnowledgeDocumentQuery(
                document_id=document_id
            )
        )

        ids = {
            version.id
            for version in result.versions
        }

        assert ids == {
            version_1,
            version_2,
        }

        assert len(result.versions) == 2


    def test_versions_from_another_document_are_not_returned(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        first_document_id = seed_document(
            test_session_factory,
            title="Refund Policy",
        )

        second_document_id = seed_document(
            test_session_factory,
            title="Shipping Policy",
        )

        expected_version_id = seed_version(
            test_session_factory,
            document_id=first_document_id,
            version_number=1,
            status="ready",
        )

        other_version_id = seed_version(
            test_session_factory,
            document_id=second_document_id,
            version_number=1,
            status="ready",
        )

        result = build_service(
            test_session_factory
        ).execute(
            GetKnowledgeDocumentQuery(
                document_id=first_document_id
            )
        )

        ids = {
            version.id
            for version in result.versions
        }

        assert expected_version_id in ids
        assert other_version_id not in ids

        assert len(ids) == 1


    def test_preserves_historical_version_states(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        superseded_id = seed_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
            status="superseded",
        )

        ready_id = seed_version(
            test_session_factory,
            document_id=document_id,
            version_number=2,
            status="ready",
        )

        result = build_service(
            test_session_factory
        ).execute(
            GetKnowledgeDocumentQuery(
                document_id=document_id
            )
        )

        by_id = {
            version.id: version
            for version in result.versions
        }

        assert (
            by_id[superseded_id].status
            is KnowledgeVersionStatus.SUPERSEDED
        )

        assert (
            by_id[ready_id].status
            is KnowledgeVersionStatus.READY
        )


# ===========================================================================
# Published-version resolution
# ===========================================================================


class TestPublishedVersionResolution:

    def test_returns_published_version_id(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        published_version_id = seed_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
            status="published",
        )

        result = build_service(
            test_session_factory
        ).execute(
            GetKnowledgeDocumentQuery(
                document_id=document_id
            )
        )

        assert (
            result.published_version_id
            == published_version_id
        )

        assert any(
            version.id == published_version_id
            and version.is_published
            for version in result.versions
        )


    def test_ready_version_is_not_reported_as_published(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        seed_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
            status="ready",
        )

        result = build_service(
            test_session_factory
        ).execute(
            GetKnowledgeDocumentQuery(
                document_id=document_id
            )
        )

        assert result.published_version_id is None


    def test_superseded_version_is_not_reported_as_published(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        seed_version(
            test_session_factory,
            document_id=document_id,
            version_number=1,
            status="superseded",
        )

        result = build_service(
            test_session_factory
        ).execute(
            GetKnowledgeDocumentQuery(
                document_id=document_id
            )
        )

        assert result.published_version_id is None


# ===========================================================================
# Administrative visibility
# ===========================================================================


class TestAdministrativeVisibility:

    def test_archived_document_remains_readable(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory,
            status="archived",
        )

        result = build_service(
            test_session_factory
        ).execute(
            GetKnowledgeDocumentQuery(
                document_id=document_id
            )
        )

        assert result.document.id == document_id

        assert (
            result.document.status
            is KnowledgeDocumentStatus.ARCHIVED
        )

        assert result.document.archived_at is not None


    def test_deleted_document_remains_readable_for_administration(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory,
            status="deleted",
        )

        result = build_service(
            test_session_factory
        ).execute(
            GetKnowledgeDocumentQuery(
                document_id=document_id
            )
        )

        assert result.document.id == document_id

        assert (
            result.document.status
            is KnowledgeDocumentStatus.DELETED
        )

        assert result.document.deleted_at is not None


# ===========================================================================
# Missing document
# ===========================================================================


class TestMissingDocument:

    def test_missing_document_raises_application_error(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        missing_id = uuid7()

        service = build_service(
            test_session_factory
        )

        with pytest.raises(
            KnowledgeDocumentDoesNotExistError
        ) as exc_info:
            service.execute(
                GetKnowledgeDocumentQuery(
                    document_id=missing_id
                )
            )

        assert (
            exc_info.value.document_id
            == missing_id
        )


# ===========================================================================
# Repository/application boundary
# ===========================================================================


class TestReadSidePersistence:

    def test_get_does_not_modify_document(
        self,
        test_session_factory: sessionmaker[Session],
    ) -> None:
        document_id = seed_document(
            test_session_factory
        )

        with test_session_factory() as session:
            before = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            assert before is not None

            original_updated_at = before.updated_at
            original_status = before.status

        build_service(
            test_session_factory
        ).execute(
            GetKnowledgeDocumentQuery(
                document_id=document_id
            )
        )

        with test_session_factory() as session:
            after = session.get(
                KnowledgeDocumentModel,
                document_id,
            )

            assert after is not None

            assert after.status == original_status
            assert after.updated_at == original_updated_at