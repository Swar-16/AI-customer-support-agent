from __future__ import annotations

from datetime import datetime, timezone
import uuid
from uuid6 import uuid7

import pytest
from sqlalchemy.orm import Session, sessionmaker

from packages.database.models.knowledge.chunk import KnowledgeChunkModel
from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.document_version import (
    KnowledgeDocumentVersionModel,
)
from packages.database.unit_of_work.knowledge import (
    SQLAlchemyKnowledgeUnitOfWork,
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
        id=uuid7(),
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
) -> KnowledgeDocumentVersion:
    now = now_utc()

    return KnowledgeDocumentVersion(
        id=uuid7(),
        document_id=document_id,
        version_number=version_number,
        source_type=KnowledgeSourceType.MARKDOWN,
        source_content="# Returns\nCustomers may request a return.",
        content_hash=f"hash-{uuid7()}",
        status=KnowledgeVersionStatus.DRAFT,
        ingestion_status=KnowledgeIngestionStatus.PENDING,
        source_name="returns.md",
        metadata={"language": "en"},
        created_at=now,
        updated_at=now,
    )


def make_chunk(
    version_id,
    *,
    chunk_index: int = 0,
) -> KnowledgeChunk:
    now = now_utc()

    return KnowledgeChunk(
        id=uuid7(),
        version_id=version_id,
        chunk_index=chunk_index,
        content="Customers may request a return.",
        section_title="Returns",
        token_count=10,
        metadata={"section": "returns"},
        created_at=now,
        updated_at=now,
    )


class TestSQLAlchemyKnowledgeUnitOfWork:
    def test_commit_persists_document(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        document = make_document()

        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with uow:
            uow.documents.add(document)
            uow.commit()

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentModel,
                document.id,
            )

        assert persisted is not None
        assert persisted.id == document.id
        assert persisted.title == document.title

    def test_exit_without_commit_rolls_back(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        document = make_document()

        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with uow:
            uow.documents.add(document)
            uow.flush()

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentModel,
                document.id,
            )

        assert persisted is None

    def test_exception_rolls_back_transaction(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        document = make_document()

        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with pytest.raises(RuntimeError):
            with uow:
                uow.documents.add(document)
                uow.flush()

                raise RuntimeError("simulated failure")

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentModel,
                document.id,
            )

        assert persisted is None

    def test_atomic_commit_across_all_repositories(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        document = make_document()
        version = make_version(document.id)
        chunk = make_chunk(version.id)

        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with uow:
            uow.documents.add(document)
            uow.versions.add(version)
            uow.chunks.add(chunk)

            uow.commit()

        with test_session_factory() as session:
            persisted_document = session.get(
                KnowledgeDocumentModel,
                document.id,
            )
            persisted_version = session.get(
                KnowledgeDocumentVersionModel,
                version.id,
            )
            persisted_chunk = session.get(
                KnowledgeChunkModel,
                chunk.id,
            )

        assert persisted_document is not None
        assert persisted_version is not None
        assert persisted_chunk is not None

    def test_failure_rolls_back_changes_from_all_repositories(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        document = make_document()
        version = make_version(document.id)
        chunk = make_chunk(version.id)

        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with pytest.raises(RuntimeError):
            with uow:
                uow.documents.add(document)
                uow.versions.add(version)
                uow.chunks.add(chunk)

                # Force SQL to PostgreSQL before the simulated failure.
                uow.flush()

                raise RuntimeError(
                    "simulated ingestion failure"
                )

        with test_session_factory() as session:
            assert session.get(
                KnowledgeDocumentModel,
                document.id,
            ) is None

            assert session.get(
                KnowledgeDocumentVersionModel,
                version.id,
            ) is None

            assert session.get(
                KnowledgeChunkModel,
                chunk.id,
            ) is None

    def test_flush_does_not_commit(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        document = make_document()

        writer_uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        reader: Session = test_session_factory()

        try:
            with writer_uow:
                writer_uow.documents.add(document)
                writer_uow.flush()

                assert writer_uow.documents.get_by_id(
                    document.id
                ) is not None

                # Different transaction must not see uncommitted data.
                assert reader.get(
                    KnowledgeDocumentModel,
                    document.id,
                ) is None

        finally:
            reader.rollback()
            reader.close()

    def test_repositories_operate_inside_same_transaction(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        document = make_document()
        version = make_version(document.id)

        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with uow:
            uow.documents.add(document)
            uow.flush()

            next_number = uow.versions.next_version_number(
                document.id
            )

            assert next_number == 1

            uow.versions.add(version)
            uow.flush()

            loaded_document = uow.documents.get_by_id(
                document.id
            )
            loaded_version = uow.versions.get_by_id(
                version.id
            )

            assert loaded_document is not None
            assert loaded_version is not None

            uow.rollback()

    def test_manual_rollback_discards_changes(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        document = make_document()

        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with uow:
            uow.documents.add(document)
            uow.flush()

            assert uow.documents.exists(document.id)

            uow.rollback()

            assert not uow.documents.exists(document.id)

        with test_session_factory() as session:
            assert session.get(
                KnowledgeDocumentModel,
                document.id,
            ) is None

    def test_repository_access_before_enter_raises(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with pytest.raises(RuntimeError):
            _ = uow.documents

        with pytest.raises(RuntimeError):
            _ = uow.versions

        with pytest.raises(RuntimeError):
            _ = uow.chunks

    def test_transaction_operations_before_enter_raise(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with pytest.raises(RuntimeError):
            uow.commit()

        with pytest.raises(RuntimeError):
            uow.rollback()

        with pytest.raises(RuntimeError):
            uow.flush()

    def test_repository_access_after_exit_raises(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with uow:
            pass

        with pytest.raises(RuntimeError):
            _ = uow.documents

        with pytest.raises(RuntimeError):
            _ = uow.versions

        with pytest.raises(RuntimeError):
            _ = uow.chunks

        with pytest.raises(RuntimeError):
            uow.commit()

    def test_reentering_active_uow_raises(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with uow:
            with pytest.raises(RuntimeError):
                uow.__enter__()

    def test_same_uow_instance_can_be_reused_after_exit(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        first = make_document()
        second = make_document()

        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with uow:
            uow.documents.add(first)
            uow.commit()

        with uow:
            uow.documents.add(second)
            uow.commit()

        with test_session_factory() as session:
            assert session.get(
                KnowledgeDocumentModel,
                first.id,
            ) is not None

            assert session.get(
                KnowledgeDocumentModel,
                second.id,
            ) is not None

    def test_commit_then_exception_does_not_undo_committed_work(
        self,
        test_session_factory: sessionmaker,
        clean_database,
    ):
        """
        Once commit succeeds, a later Python exception cannot roll back that
        already-committed transaction. This documents the UoW boundary clearly.
        """
        document = make_document()

        uow = SQLAlchemyKnowledgeUnitOfWork(
            test_session_factory
        )

        with pytest.raises(RuntimeError):
            with uow:
                uow.documents.add(document)
                uow.commit()

                raise RuntimeError(
                    "failure after transaction commit"
                )

        with test_session_factory() as session:
            persisted = session.get(
                KnowledgeDocumentModel,
                document.id,
            )

        assert persisted is not None