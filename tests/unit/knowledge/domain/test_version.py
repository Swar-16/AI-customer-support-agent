from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from packages.knowledge.domain.enums import (
    KnowledgeIngestionStatus,
    KnowledgeSourceType,
    KnowledgeVersionStatus,
)
from packages.knowledge.domain.errors import (
    InvalidKnowledgeVersionError,
    InvalidKnowledgeVersionNumberError,
    KnowledgeStateTransitionError,
    KnowledgeVersionAlreadyPublishedError,
    KnowledgeVersionContentError,
    KnowledgeVersionNotReadyError,
)
from packages.knowledge.domain.version import (
    MAX_FAILURE_CODE_LENGTH,
    MAX_FAILURE_MESSAGE_LENGTH,
    MAX_METADATA_KEY_LENGTH,
    MAX_SOURCE_NAME_LENGTH,
    MAX_SOURCE_URI_LENGTH,
    MAX_VERSION_METADATA_KEYS,
    KnowledgeDocumentVersion,
)


BASE_TIME = datetime(
    2026,
    8,
    29,
    0,
    0,
    tzinfo=timezone.utc,
)


def make_version(
    **overrides,
) -> KnowledgeDocumentVersion:
    defaults = {
        "id": uuid4(),
        "document_id": uuid4(),
        "version_number": 1,
        "source_type": KnowledgeSourceType.MARKDOWN,
        "source_content": "Customers may request a refund.",
        "content_hash": "abc123",
        "status": KnowledgeVersionStatus.DRAFT,
        "ingestion_status": KnowledgeIngestionStatus.PENDING,
        "source_name": "refund_policy.md",
        "source_uri": None,
        "metadata": {
            "language": "en",
            "region": "IN",
        },
        "created_at": BASE_TIME,
        "updated_at": BASE_TIME,
    }

    defaults.update(overrides)

    return KnowledgeDocumentVersion(**defaults)


def make_processing_version() -> KnowledgeDocumentVersion:
    version = make_version()

    return version.start_processing(
        occurred_at=BASE_TIME + timedelta(minutes=1),
    )


def make_ready_version() -> KnowledgeDocumentVersion:
    version = make_processing_version()

    return version.mark_processing_completed(
        occurred_at=BASE_TIME + timedelta(minutes=2),
    )


def make_published_version() -> KnowledgeDocumentVersion:
    version = make_ready_version()

    return version.publish(
        occurred_at=BASE_TIME + timedelta(minutes=3),
    )


class TestKnowledgeVersionConstruction:
    def test_creates_valid_draft_version(self) -> None:
        version = make_version()

        assert version.version_number == 1
        assert version.status is KnowledgeVersionStatus.DRAFT
        assert (
            version.ingestion_status
            is KnowledgeIngestionStatus.PENDING
        )
        assert version.is_draft is True
        assert version.is_processing is False
        assert version.is_ready is False
        assert version.is_published is False
        assert version.is_failed is False

    def test_normalizes_content_hash_and_source_fields(self) -> None:
        version = make_version(
            source_content="   Refund policy content   ",
            content_hash="   abc123   ",
            source_name="   refund.md   ",
            source_uri="   https://example.com/refund   ",
        )

        assert version.source_content == "Refund policy content"
        assert version.content_hash == "abc123"
        assert version.source_name == "refund.md"
        assert version.source_uri == "https://example.com/refund"

    def test_normalizes_metadata_keys(self) -> None:
        version = make_version(
            metadata={
                " language ": "en",
                "  region  ": "IN",
            }
        )

        assert version.metadata == {
            "language": "en",
            "region": "IN",
        }

    def test_copies_metadata_mapping(self) -> None:
        metadata = {
            "language": "en",
        }

        version = make_version(metadata=metadata)

        metadata["language"] = "fr"

        assert version.metadata["language"] == "en"

    def test_blank_optional_source_fields_become_none(self) -> None:
        version = make_version(
            source_name="   ",
            source_uri="\t",
        )

        assert version.source_name is None
        assert version.source_uri is None


class TestKnowledgeVersionIdentityValidation:
    def test_rejects_non_uuid_id(self) -> None:
        with pytest.raises(
            TypeError,
            match="id must be a UUID",
        ):
            make_version(id="not-a-uuid")

    def test_rejects_non_uuid_document_id(self) -> None:
        with pytest.raises(
            TypeError,
            match="document_id must be a UUID",
        ):
            make_version(document_id="not-a-uuid")


class TestKnowledgeVersionNumberValidation:
    @pytest.mark.parametrize(
        "version_number",
        [
            0,
            -1,
            -100,
            True,
        ],
    )
    def test_rejects_invalid_version_number(
        self,
        version_number,
    ) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionNumberError
        ):
            make_version(
                version_number=version_number,
            )

    def test_rejects_non_integer_version_number(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionNumberError
        ):
            make_version(
                version_number="1",
            )


class TestKnowledgeVersionEnumValidation:
    def test_rejects_invalid_source_type(self) -> None:
        with pytest.raises(
            TypeError,
            match="source_type must be a KnowledgeSourceType",
        ):
            make_version(
                source_type="markdown",
            )

    def test_rejects_invalid_version_status(self) -> None:
        with pytest.raises(
            TypeError,
            match="status must be a KnowledgeVersionStatus",
        ):
            make_version(
                status="draft",
            )

    def test_rejects_invalid_ingestion_status(self) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "ingestion_status must be a "
                "KnowledgeIngestionStatus"
            ),
        ):
            make_version(
                ingestion_status="pending",
            )


class TestKnowledgeVersionContentValidation:
    @pytest.mark.parametrize(
        "content",
        [
            "",
            " ",
            "\n",
            "\t",
        ],
    )
    def test_rejects_empty_source_content(
        self,
        content: str,
    ) -> None:
        with pytest.raises(
            KnowledgeVersionContentError
        ):
            make_version(
                source_content=content,
            )

    def test_rejects_non_string_source_content(self) -> None:
        with pytest.raises(
            TypeError,
            match="source_content must be a string",
        ):
            make_version(
                source_content=123,
            )

    @pytest.mark.parametrize(
        "content_hash",
        [
            "",
            " ",
            "\n",
        ],
    )
    def test_rejects_empty_content_hash(
        self,
        content_hash: str,
    ) -> None:
        with pytest.raises(
            KnowledgeVersionContentError
        ):
            make_version(
                content_hash=content_hash,
            )

    def test_rejects_non_string_content_hash(self) -> None:
        with pytest.raises(
            TypeError,
            match="content_hash must be a string",
        ):
            make_version(
                content_hash=123,
            )


class TestKnowledgeVersionSourceMetadataValidation:
    def test_rejects_source_name_over_max_length(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                source_name="x" * (
                    MAX_SOURCE_NAME_LENGTH + 1
                )
            )

    def test_rejects_source_uri_over_max_length(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                source_uri="x" * (
                    MAX_SOURCE_URI_LENGTH + 1
                )
            )

    def test_rejects_non_string_source_name(self) -> None:
        with pytest.raises(TypeError):
            make_version(
                source_name=123,
            )

    def test_rejects_non_string_source_uri(self) -> None:
        with pytest.raises(TypeError):
            make_version(
                source_uri=123,
            )


class TestKnowledgeVersionMetadataValidation:
    def test_rejects_non_mapping_metadata(self) -> None:
        with pytest.raises(
            TypeError,
            match="metadata must be a mapping",
        ):
            make_version(
                metadata=[],
            )

    def test_rejects_too_many_metadata_keys(self) -> None:
        metadata = {
            f"key_{index}": index
            for index in range(
                MAX_VERSION_METADATA_KEYS + 1
            )
        }

        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                metadata=metadata,
            )

    def test_rejects_non_string_metadata_key(self) -> None:
        with pytest.raises(
            TypeError,
            match="metadata keys must be strings",
        ):
            make_version(
                metadata={
                    1: "value",
                }
            )

    def test_rejects_empty_metadata_key(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                metadata={
                    "   ": "value",
                }
            )

    def test_rejects_long_metadata_key(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                metadata={
                    "x" * (
                        MAX_METADATA_KEY_LENGTH + 1
                    ): "value"
                }
            )

    def test_rejects_duplicate_keys_after_normalization(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                metadata={
                    "language": "en",
                    " language ": "fr",
                }
            )


class TestKnowledgeVersionStartProcessing:
    def test_draft_can_start_processing(self) -> None:
        version = make_version()

        occurred_at = BASE_TIME + timedelta(minutes=1)

        processing = version.start_processing(
            occurred_at=occurred_at,
        )

        assert processing.status is KnowledgeVersionStatus.PROCESSING
        assert (
            processing.ingestion_status
            is KnowledgeIngestionStatus.RUNNING
        )
        assert processing.processing_started_at == occurred_at
        assert processing.processing_completed_at is None
        assert processing.ready_at is None
        assert processing.failure_code is None
        assert processing.failure_message is None
        assert processing.updated_at == occurred_at

        assert version.status is KnowledgeVersionStatus.DRAFT

    def test_failed_version_can_retry_processing(self) -> None:
        processing = make_processing_version()

        failed = processing.mark_processing_failed(
            failure_code="PARSE_FAILED",
            failure_message="Unable to parse file.",
            occurred_at=BASE_TIME + timedelta(minutes=2),
        )

        retried = failed.start_processing(
            occurred_at=BASE_TIME + timedelta(minutes=3),
        )

        assert retried.status is KnowledgeVersionStatus.PROCESSING
        assert (
            retried.ingestion_status
            is KnowledgeIngestionStatus.RUNNING
        )
        assert retried.failure_code is None
        assert retried.failure_message is None
        assert (
            retried.processing_started_at
            == BASE_TIME + timedelta(minutes=3)
        )

    @pytest.mark.parametrize(
        "factory",
        [
            make_ready_version,
            make_published_version,
        ],
    )
    def test_non_draft_non_failed_version_cannot_start_processing(
        self,
        factory,
    ) -> None:
        version = factory()

        with pytest.raises(
            KnowledgeStateTransitionError
        ):
            version.start_processing(
                occurred_at=version.updated_at
                + timedelta(minutes=1)
            )


class TestKnowledgeVersionProcessingCompletion:
    def test_processing_version_can_become_ready(self) -> None:
        processing = make_processing_version()

        occurred_at = BASE_TIME + timedelta(minutes=2)

        ready = processing.mark_processing_completed(
            occurred_at=occurred_at,
        )

        assert ready.status is KnowledgeVersionStatus.READY
        assert (
            ready.ingestion_status
            is KnowledgeIngestionStatus.COMPLETED
        )
        assert ready.processing_completed_at == occurred_at
        assert ready.ready_at == occurred_at
        assert ready.updated_at == occurred_at
        assert ready.ingestion_completed is True

    def test_draft_cannot_complete_processing(self) -> None:
        version = make_version()

        with pytest.raises(
            KnowledgeStateTransitionError
        ):
            version.mark_processing_completed(
                occurred_at=BASE_TIME + timedelta(minutes=1),
            )


class TestKnowledgeVersionProcessingFailure:
    def test_processing_version_can_fail(self) -> None:
        version = make_processing_version()

        occurred_at = BASE_TIME + timedelta(minutes=2)

        failed = version.mark_processing_failed(
            failure_code="PDF_PARSE_FAILED",
            failure_message="Unable to extract content.",
            occurred_at=occurred_at,
        )

        assert failed.status is KnowledgeVersionStatus.FAILED
        assert (
            failed.ingestion_status
            is KnowledgeIngestionStatus.FAILED
        )
        assert failed.processing_completed_at == occurred_at
        assert failed.failure_code == "PDF_PARSE_FAILED"
        assert failed.failure_message == "Unable to extract content."
        assert failed.ingestion_failed is True

    def test_failure_details_are_normalized(self) -> None:
        version = make_processing_version()

        failed = version.mark_processing_failed(
            failure_code="  PARSE_FAILED  ",
            failure_message="  Invalid source.  ",
            occurred_at=BASE_TIME + timedelta(minutes=2),
        )

        assert failed.failure_code == "PARSE_FAILED"
        assert failed.failure_message == "Invalid source."

    def test_failure_code_length_is_limited(self) -> None:
        version = make_processing_version()

        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            version.mark_processing_failed(
                failure_code="x" * (
                    MAX_FAILURE_CODE_LENGTH + 1
                ),
                occurred_at=BASE_TIME + timedelta(minutes=2),
            )

    def test_failure_message_length_is_limited(self) -> None:
        version = make_processing_version()

        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            version.mark_processing_failed(
                failure_message="x" * (
                    MAX_FAILURE_MESSAGE_LENGTH + 1
                ),
                occurred_at=BASE_TIME + timedelta(minutes=2),
            )

    def test_non_processing_version_cannot_fail_processing(self) -> None:
        version = make_version()

        with pytest.raises(
            KnowledgeStateTransitionError
        ):
            version.mark_processing_failed(
                occurred_at=BASE_TIME + timedelta(minutes=1),
            )


class TestKnowledgeVersionPublication:
    def test_ready_version_can_be_published(self) -> None:
        ready = make_ready_version()

        occurred_at = BASE_TIME + timedelta(minutes=3)

        published = ready.publish(
            occurred_at=occurred_at,
        )

        assert published.status is KnowledgeVersionStatus.PUBLISHED
        assert published.published_at == occurred_at
        assert published.updated_at == occurred_at
        assert published.is_published is True
        assert published.ingestion_completed is True

    def test_draft_version_cannot_be_published(self) -> None:
        version = make_version()

        with pytest.raises(
            KnowledgeVersionNotReadyError
        ):
            version.publish(
                occurred_at=BASE_TIME + timedelta(minutes=1),
            )

    def test_processing_version_cannot_be_published(self) -> None:
        version = make_processing_version()

        with pytest.raises(
            KnowledgeVersionNotReadyError
        ):
            version.publish(
                occurred_at=BASE_TIME + timedelta(minutes=2),
            )

    def test_failed_version_cannot_be_published(self) -> None:
        processing = make_processing_version()

        failed = processing.mark_processing_failed(
            occurred_at=BASE_TIME + timedelta(minutes=2),
        )

        with pytest.raises(
            KnowledgeVersionNotReadyError
        ):
            failed.publish(
                occurred_at=BASE_TIME + timedelta(minutes=3),
            )

    def test_publishing_already_published_version_fails(self) -> None:
        version = make_published_version()

        with pytest.raises(
            KnowledgeVersionAlreadyPublishedError
        ):
            version.publish(
                occurred_at=BASE_TIME + timedelta(minutes=4),
            )


class TestKnowledgeVersionSupersession:
    def test_published_version_can_be_superseded(self) -> None:
        version = make_published_version()

        occurred_at = BASE_TIME + timedelta(minutes=4)

        superseded = version.supersede(
            occurred_at=occurred_at,
        )

        assert (
            superseded.status
            is KnowledgeVersionStatus.SUPERSEDED
        )
        assert superseded.superseded_at == occurred_at
        assert superseded.published_at == version.published_at
        assert superseded.updated_at == occurred_at

    @pytest.mark.parametrize(
        "factory",
        [
            make_version,
            make_processing_version,
            make_ready_version,
        ],
    )
    def test_only_published_version_can_be_superseded(
        self,
        factory,
    ) -> None:
        version = factory()

        with pytest.raises(
            KnowledgeStateTransitionError
        ):
            version.supersede(
                occurred_at=version.updated_at
                + timedelta(minutes=1)
            )


class TestKnowledgeVersionArchival:
    def test_draft_version_can_be_archived(self) -> None:
        version = make_version()

        occurred_at = BASE_TIME + timedelta(minutes=1)

        archived = version.archive(
            occurred_at=occurred_at,
        )

        assert archived.status is KnowledgeVersionStatus.ARCHIVED
        assert archived.archived_at == occurred_at

    def test_ready_version_can_be_archived(self) -> None:
        version = make_ready_version()

        archived = version.archive(
            occurred_at=BASE_TIME + timedelta(minutes=3),
        )

        assert archived.status is KnowledgeVersionStatus.ARCHIVED

    def test_failed_version_can_be_archived(self) -> None:
        processing = make_processing_version()

        failed = processing.mark_processing_failed(
            occurred_at=BASE_TIME + timedelta(minutes=2),
        )

        archived = failed.archive(
            occurred_at=BASE_TIME + timedelta(minutes=3),
        )

        assert archived.status is KnowledgeVersionStatus.ARCHIVED

    def test_processing_version_cannot_be_archived(self) -> None:
        version = make_processing_version()

        with pytest.raises(
            KnowledgeStateTransitionError
        ):
            version.archive(
                occurred_at=BASE_TIME + timedelta(minutes=2),
            )

    def test_published_version_cannot_be_archived_directly(self) -> None:
        version = make_published_version()

        with pytest.raises(
            KnowledgeStateTransitionError
        ):
            version.archive(
                occurred_at=BASE_TIME + timedelta(minutes=4),
            )

    def test_archiving_archived_version_is_idempotent(self) -> None:
        version = make_version()

        archived = version.archive(
            occurred_at=BASE_TIME + timedelta(minutes=1),
        )

        result = archived.archive(
            occurred_at=BASE_TIME + timedelta(minutes=2),
        )

        assert result is archived


class TestKnowledgeVersionMetadataMutation:
    def test_metadata_can_be_replaced_while_draft(self) -> None:
        version = make_version()

        changed = version.replace_metadata(
            {
                "language": "fr",
                "region": "EU",
            },
            occurred_at=BASE_TIME + timedelta(minutes=1),
        )

        assert changed.metadata == {
            "language": "fr",
            "region": "EU",
        }
        assert version.metadata["language"] == "en"

    def test_identical_metadata_returns_same_instance(self) -> None:
        version = make_version()

        result = version.replace_metadata(
            {
                "language": "en",
                "region": "IN",
            }
        )

        assert result is version

    def test_published_version_metadata_cannot_be_edited(self) -> None:
        version = make_published_version()

        with pytest.raises(
            KnowledgeStateTransitionError
        ):
            version.replace_metadata(
                {
                    "language": "fr",
                }
            )


class TestKnowledgeVersionSourceReferenceMutation:
    def test_source_reference_can_change_while_draft(self) -> None:
        version = make_version()

        changed = version.change_source_reference(
            source_name="new_refund.md",
            source_uri="https://example.com/new-refund",
            occurred_at=BASE_TIME + timedelta(minutes=1),
        )

        assert changed.source_name == "new_refund.md"
        assert (
            changed.source_uri
            == "https://example.com/new-refund"
        )

    def test_source_reference_cannot_change_when_ready(self) -> None:
        version = make_ready_version()

        with pytest.raises(
            KnowledgeStateTransitionError
        ):
            version.change_source_reference(
                source_name="changed.md",
            )


class TestKnowledgeVersionLifecycleConsistency:
    def test_draft_requires_pending_ingestion(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                ingestion_status=KnowledgeIngestionStatus.RUNNING,
            )

    def test_processing_requires_running_ingestion(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                status=KnowledgeVersionStatus.PROCESSING,
                ingestion_status=KnowledgeIngestionStatus.PENDING,
                processing_started_at=BASE_TIME,
            )

    def test_processing_requires_processing_started_at(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                status=KnowledgeVersionStatus.PROCESSING,
                ingestion_status=KnowledgeIngestionStatus.RUNNING,
                processing_started_at=None,
            )

    def test_ready_requires_completed_ingestion(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                status=KnowledgeVersionStatus.READY,
                ingestion_status=KnowledgeIngestionStatus.PENDING,
                ready_at=BASE_TIME,
            )

    def test_ready_requires_ready_at(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                status=KnowledgeVersionStatus.READY,
                ingestion_status=KnowledgeIngestionStatus.COMPLETED,
                ready_at=None,
            )

    def test_published_requires_published_at(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                status=KnowledgeVersionStatus.PUBLISHED,
                ingestion_status=KnowledgeIngestionStatus.COMPLETED,
                ready_at=BASE_TIME,
                published_at=None,
            )

    def test_superseded_requires_previous_publication(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                status=KnowledgeVersionStatus.SUPERSEDED,
                ingestion_status=KnowledgeIngestionStatus.COMPLETED,
                ready_at=BASE_TIME,
                published_at=None,
                superseded_at=BASE_TIME,
            )

    def test_superseded_requires_superseded_at(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                status=KnowledgeVersionStatus.SUPERSEDED,
                ingestion_status=KnowledgeIngestionStatus.COMPLETED,
                ready_at=BASE_TIME,
                published_at=BASE_TIME,
                superseded_at=None,
            )

    def test_failed_requires_failed_ingestion(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                status=KnowledgeVersionStatus.FAILED,
                ingestion_status=KnowledgeIngestionStatus.PENDING,
            )

    def test_archived_requires_archived_at(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                status=KnowledgeVersionStatus.ARCHIVED,
                archived_at=None,
            )

    def test_non_archived_version_cannot_have_archived_at(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                archived_at=BASE_TIME,
            )

    def test_non_failed_version_cannot_carry_failure_details(
        self,
    ) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                failure_code="PARSE_FAILED",
            )


class TestKnowledgeVersionTimestampValidation:
    def test_created_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(
            ValueError,
            match="created_at must be timezone-aware",
        ):
            make_version(
                created_at=datetime(2026, 8, 29, 0, 0),
            )

    def test_updated_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(
            ValueError,
            match="updated_at must be timezone-aware",
        ):
            make_version(
                updated_at=datetime(2026, 8, 29, 0, 0),
            )

    def test_updated_at_cannot_precede_created_at(self) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                updated_at=BASE_TIME - timedelta(seconds=1),
            )

    def test_lifecycle_timestamp_cannot_precede_created_at(
        self,
    ) -> None:
        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            make_version(
                status=KnowledgeVersionStatus.PROCESSING,
                ingestion_status=KnowledgeIngestionStatus.RUNNING,
                processing_started_at=BASE_TIME - timedelta(seconds=1),
            )

    def test_mutation_time_cannot_precede_updated_at(self) -> None:
        version = make_version()

        with pytest.raises(
            InvalidKnowledgeVersionError
        ):
            version.start_processing(
                occurred_at=BASE_TIME - timedelta(seconds=1),
            )

    def test_mutation_time_must_be_timezone_aware(self) -> None:
        version = make_version()

        with pytest.raises(
            ValueError,
            match="occurred_at must be timezone-aware",
        ):
            version.start_processing(
                occurred_at=datetime(2026, 8, 29, 1, 0),
            )


class TestKnowledgeVersionImmutability:
    def test_direct_field_assignment_is_rejected(self) -> None:
        version = make_version()

        with pytest.raises(FrozenInstanceError):
            version.source_content = "Modified"

    def test_source_content_survives_lifecycle_transitions(self) -> None:
        version = make_version(
            source_content="Immutable source content.",
        )

        processing = version.start_processing(
            occurred_at=BASE_TIME + timedelta(minutes=1),
        )

        ready = processing.mark_processing_completed(
            occurred_at=BASE_TIME + timedelta(minutes=2),
        )

        published = ready.publish(
            occurred_at=BASE_TIME + timedelta(minutes=3),
        )

        assert (
            published.source_content
            == "Immutable source content."
        )

    def test_identity_is_preserved_across_lifecycle(self) -> None:
        version = make_version()

        processing = version.start_processing(
            occurred_at=BASE_TIME + timedelta(minutes=1),
        )

        ready = processing.mark_processing_completed(
            occurred_at=BASE_TIME + timedelta(minutes=2),
        )

        published = ready.publish(
            occurred_at=BASE_TIME + timedelta(minutes=3),
        )

        assert published.id == version.id
        assert published.document_id == version.document_id
        assert published.version_number == version.version_number