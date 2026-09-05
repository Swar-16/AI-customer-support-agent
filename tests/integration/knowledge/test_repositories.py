from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from packages.database.models.knowledge.chunk import KnowledgeChunkModel
from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.document_version import (
    KnowledgeDocumentVersionModel,
)
from packages.database.repositories.knowledge import (
    SQLAlchemyKnowledgeChunkRepository,
    SQLAlchemyKnowledgeDocumentRepository,
    SQLAlchemyKnowledgeVersionRepository,
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


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def make_document() -> KnowledgeDocument:
    now = now_utc()

    return KnowledgeDocument(
        id=uuid4(),
        title="Returns Policy",
        description="Customer-facing returns documentation.",
        content_type=KnowledgeContentType.POLICY,
        visibility=KnowledgeVisibility.CUSTOMER,
        status=KnowledgeDocumentStatus.ACTIVE,
        metadata={"region": "global"},
        created_at=now,
        updated_at=now,
    )


def make_version(
    document_id,
    *,
    version_number: int = 1,
    status: KnowledgeVersionStatus = KnowledgeVersionStatus.DRAFT,
    ingestion_status: KnowledgeIngestionStatus = KnowledgeIngestionStatus.PENDING,
) -> KnowledgeDocumentVersion:
    now = now_utc()

    return KnowledgeDocumentVersion(
        id=uuid4(),
        document_id=document_id,
        version_number=version_number,
        source_type=KnowledgeSourceType.MARKDOWN,
        source_content="# Returns\nCustomers may request a return.",
        content_hash=f"hash-{uuid4()}",
        status=status,
        ingestion_status=ingestion_status,
        source_name="returns.md",
        metadata={"language": "en"},
        created_at=now,
        updated_at=now,
    )


def make_chunk(
    version_id,
    *,
    chunk_index: int,
    content: str,
) -> KnowledgeChunk:
    now = now_utc()

    return KnowledgeChunk(
        id=uuid4(),
        version_id=version_id,
        chunk_index=chunk_index,
        content=content,
        section_title="Returns",
        token_count=10,
        metadata={"section": "returns"},
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def db_session(
    test_session_factory: sessionmaker,
    clean_database,
):
    session: Session = test_session_factory()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


class TestKnowledgeDocumentRepository:
    def test_add_and_get_round_trip(self, db_session: Session):
        repo = SQLAlchemyKnowledgeDocumentRepository(db_session)
        document = make_document()

        repo.add(document)
        db_session.flush()

        loaded = repo.get_by_id(document.id)

        assert loaded == document

    def test_add_does_not_commit(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        writer = test_session_factory()
        reader = test_session_factory()

        try:
            repo = SQLAlchemyKnowledgeDocumentRepository(writer)
            document = make_document()

            repo.add(document)
            writer.flush()

            assert reader.get(
                KnowledgeDocumentModel,
                document.id,
            ) is None

            writer.commit()

            reader.expire_all()

            assert reader.get(
                KnowledgeDocumentModel,
                document.id,
            ) is not None

        finally:
            writer.rollback()
            reader.rollback()
            writer.close()
            reader.close()

    def test_get_missing_returns_none(self, db_session: Session):
        repo = SQLAlchemyKnowledgeDocumentRepository(db_session)

        assert repo.get_by_id(uuid4()) is None

    def test_exists(self, db_session: Session):
        repo = SQLAlchemyKnowledgeDocumentRepository(db_session)
        document = make_document()

        assert repo.exists(document.id) is False

        repo.add(document)
        db_session.flush()

        assert repo.exists(document.id) is True

    def test_save_updates_mutable_state(self, db_session: Session):
        repo = SQLAlchemyKnowledgeDocumentRepository(db_session)
        document = make_document()

        repo.add(document)
        db_session.flush()

        updated = document.rename(
            "Updated Returns Policy"
        )

        repo.save(updated)
        db_session.flush()

        loaded = repo.get_by_id(document.id)

        assert loaded is not None
        assert loaded.title == "Updated Returns Policy"
        assert loaded.id == document.id
        assert loaded.created_at == document.created_at

    def test_save_missing_document_raises(self, db_session: Session):
        repo = SQLAlchemyKnowledgeDocumentRepository(db_session)

        with pytest.raises(LookupError):
            repo.save(make_document())


class TestKnowledgeVersionRepository:
    def test_add_and_get_round_trip(self, db_session: Session):
        document_repo = SQLAlchemyKnowledgeDocumentRepository(db_session)
        version_repo = SQLAlchemyKnowledgeVersionRepository(db_session)

        document = make_document()
        version = make_version(document.id)

        document_repo.add(document)
        version_repo.add(version)
        db_session.flush()

        loaded = version_repo.get_by_id(version.id)

        assert loaded == version

    def test_get_missing_returns_none(self, db_session: Session):
        repo = SQLAlchemyKnowledgeVersionRepository(db_session)

        assert repo.get_by_id(uuid4()) is None

    def test_list_for_document_is_version_ordered(
        self,
        db_session: Session,
    ):
        document_repo = SQLAlchemyKnowledgeDocumentRepository(db_session)
        version_repo = SQLAlchemyKnowledgeVersionRepository(db_session)

        document = make_document()
        document_repo.add(document)

        v2 = make_version(document.id, version_number=2)
        v1 = make_version(document.id, version_number=1)
        v3 = make_version(document.id, version_number=3)

        version_repo.add(v2)
        version_repo.add(v1)
        version_repo.add(v3)

        db_session.flush()

        versions = version_repo.list_for_document(document.id)

        assert [v.version_number for v in versions] == [1, 2, 3]

    def test_next_version_number_starts_at_one(
        self,
        db_session: Session,
    ):
        document_repo = SQLAlchemyKnowledgeDocumentRepository(db_session)
        version_repo = SQLAlchemyKnowledgeVersionRepository(db_session)

        document = make_document()
        document_repo.add(document)
        db_session.flush()

        assert version_repo.next_version_number(document.id) == 1

    def test_next_version_number_uses_current_max(
        self,
        db_session: Session,
    ):
        document_repo = SQLAlchemyKnowledgeDocumentRepository(db_session)
        version_repo = SQLAlchemyKnowledgeVersionRepository(db_session)

        document = make_document()
        document_repo.add(document)

        version_repo.add(
            make_version(document.id, version_number=1)
        )
        version_repo.add(
            make_version(document.id, version_number=3)
        )

        db_session.flush()

        assert version_repo.next_version_number(document.id) == 4

    def test_next_version_number_missing_document_raises(
        self,
        db_session: Session,
    ):
        repo = SQLAlchemyKnowledgeVersionRepository(db_session)

        with pytest.raises(LookupError):
            repo.next_version_number(uuid4())

    def test_get_published_for_document(
        self,
        db_session: Session,
    ):
        document_repo = SQLAlchemyKnowledgeDocumentRepository(db_session)
        version_repo = SQLAlchemyKnowledgeVersionRepository(db_session)

        document = make_document()
        document_repo.add(document)

        draft = make_version(document.id, version_number=1)

        # These timestamps may be required by your domain/DB lifecycle rules.
        published = make_version(
            document.id,
            version_number=2,
        )
        
        t0 = published.created_at
        published = published.start_processing(occurred_at=t0 + timedelta(seconds=1))
        published = published.mark_processing_completed(occurred_at=t0 + timedelta(seconds=2))
        published = published.publish(occurred_at=t0 + timedelta(seconds=3))

        version_repo.add(draft)
        version_repo.add(published)

        db_session.flush()

        loaded = version_repo.get_published_for_document(document.id)

        assert loaded is not None
        assert loaded.id == published.id

    def test_save_missing_version_raises(self, db_session: Session):
        repo = SQLAlchemyKnowledgeVersionRepository(db_session)

        with pytest.raises(LookupError):
            repo.save(
                make_version(uuid4())
            )


class TestKnowledgeChunkRepository:
    def test_add_and_get_round_trip(self, db_session: Session):
        document_repo = SQLAlchemyKnowledgeDocumentRepository(db_session)
        version_repo = SQLAlchemyKnowledgeVersionRepository(db_session)
        chunk_repo = SQLAlchemyKnowledgeChunkRepository(db_session)

        document = make_document()
        version = make_version(document.id)
        chunk = make_chunk(
            version.id,
            chunk_index=0,
            content="Customers may request a return.",
        )

        document_repo.add(document)
        version_repo.add(version)
        chunk_repo.add(chunk)

        db_session.flush()

        loaded = chunk_repo.get_by_id(chunk.id)

        assert loaded == chunk

    def test_add_many_and_list_for_version_are_ordered(
        self,
        db_session: Session,
    ):
        document_repo = SQLAlchemyKnowledgeDocumentRepository(db_session)
        version_repo = SQLAlchemyKnowledgeVersionRepository(db_session)
        chunk_repo = SQLAlchemyKnowledgeChunkRepository(db_session)

        document = make_document()
        version = make_version(document.id)

        document_repo.add(document)
        version_repo.add(version)

        chunks = [
            make_chunk(
                version.id,
                chunk_index=2,
                content="Third chunk",
            ),
            make_chunk(
                version.id,
                chunk_index=0,
                content="First chunk",
            ),
            make_chunk(
                version.id,
                chunk_index=1,
                content="Second chunk",
            ),
        ]

        chunk_repo.add_many(chunks)
        db_session.flush()

        loaded = chunk_repo.list_for_version(version.id)

        assert [chunk.chunk_index for chunk in loaded] == [0, 1, 2]

    def test_add_many_empty_is_noop(self, db_session: Session):
        repo = SQLAlchemyKnowledgeChunkRepository(db_session)

        repo.add_many([])

        db_session.flush()

    def test_get_missing_returns_none(self, db_session: Session):
        repo = SQLAlchemyKnowledgeChunkRepository(db_session)

        assert repo.get_by_id(uuid4()) is None

    def test_delete_for_version(
        self,
        db_session: Session,
    ):
        document_repo = SQLAlchemyKnowledgeDocumentRepository(db_session)
        version_repo = SQLAlchemyKnowledgeVersionRepository(db_session)
        chunk_repo = SQLAlchemyKnowledgeChunkRepository(db_session)

        document = make_document()
        version = make_version(document.id)

        document_repo.add(document)
        version_repo.add(version)

        chunk_repo.add_many(
            [
                make_chunk(
                    version.id,
                    chunk_index=0,
                    content="First",
                ),
                make_chunk(
                    version.id,
                    chunk_index=1,
                    content="Second",
                ),
            ]
        )

        db_session.flush()

        chunk_repo.delete_for_version(version.id)
        db_session.flush()

        assert chunk_repo.list_for_version(version.id) == []