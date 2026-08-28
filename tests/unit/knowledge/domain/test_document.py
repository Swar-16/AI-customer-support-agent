from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from dataclasses import FrozenInstanceError
import pytest

from packages.knowledge.domain.document import (
    KnowledgeDocument,
    MAX_DOCUMENT_DESCRIPTION_LENGTH,
    MAX_DOCUMENT_METADATA_KEYS,
    MAX_DOCUMENT_TITLE_LENGTH,
    MAX_METADATA_KEY_LENGTH,
)
from packages.knowledge.domain.enums import (
    KnowledgeContentType,
    KnowledgeDocumentStatus,
    KnowledgeVisibility,
)
from packages.knowledge.domain.errors import (
    InvalidKnowledgeDocumentError,
    KnowledgeDocumentAlreadyArchivedError,
    KnowledgeDocumentDeletedError,
    KnowledgeDocumentTitleError,
    KnowledgeStateTransitionError,
)


def make_document(
    **overrides,
) -> KnowledgeDocument:
    now = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)

    defaults = {
        "id": uuid4(),
        "title": "Refund Policy",
        "content_type": KnowledgeContentType.POLICY,
        "visibility": KnowledgeVisibility.CUSTOMER,
        "status": KnowledgeDocumentStatus.ACTIVE,
        "description": "Customer refund rules.",
        "metadata": {
            "language": "en",
            "region": "IN",
        },
        "created_at": now,
        "updated_at": now,
    }

    defaults.update(overrides)

    return KnowledgeDocument(**defaults)


class TestKnowledgeDocumentConstruction:
    def test_creates_valid_document(self) -> None:
        document = make_document()

        assert isinstance(document.id, type(uuid4()))
        assert document.title == "Refund Policy"
        assert document.content_type is KnowledgeContentType.POLICY
        assert document.visibility is KnowledgeVisibility.CUSTOMER
        assert document.status is KnowledgeDocumentStatus.ACTIVE
        assert document.description == "Customer refund rules."
        assert document.is_active is True
        assert document.is_archived is False
        assert document.is_deleted is False

    def test_normalizes_title_description_and_metadata_keys(self) -> None:
        document = make_document(
            title="   Refund Policy   ",
            description="   Customer refund rules.   ",
            metadata={
                "  language  ": "en",
                " region ": "IN",
            },
        )

        assert document.title == "Refund Policy"
        assert document.description == "Customer refund rules."
        assert document.metadata == {
            "language": "en",
            "region": "IN",
        }

    def test_empty_description_is_normalized_to_none(self) -> None:
        document = make_document(
            description="     ",
        )

        assert document.description is None

    def test_copies_metadata_mapping(self) -> None:
        metadata = {
            "language": "en",
        }

        document = make_document(
            metadata=metadata,
        )

        metadata["language"] = "fr"

        assert document.metadata["language"] == "en"


class TestKnowledgeDocumentTitleValidation:
    @pytest.mark.parametrize(
        "title",
        [
            "",
            " ",
            "\t",
            "\n",
        ],
    )
    def test_rejects_empty_title(
        self,
        title: str,
    ) -> None:
        with pytest.raises(KnowledgeDocumentTitleError):
            make_document(title=title)

    def test_rejects_title_over_max_length(self) -> None:
        title = "x" * (MAX_DOCUMENT_TITLE_LENGTH + 1)

        with pytest.raises(KnowledgeDocumentTitleError):
            make_document(title=title)

    def test_rejects_non_string_title(self) -> None:
        with pytest.raises(KnowledgeDocumentTitleError):
            make_document(title=123)


class TestKnowledgeDocumentTypeValidation:
    def test_rejects_non_uuid_id(self) -> None:
        with pytest.raises(TypeError, match="id must be a UUID"):
            make_document(id="not-a-uuid")

    def test_rejects_invalid_content_type(self) -> None:
        with pytest.raises(
            TypeError,
            match="content_type must be a KnowledgeContentType",
        ):
            make_document(content_type="policy")

    def test_rejects_invalid_visibility(self) -> None:
        with pytest.raises(
            TypeError,
            match="visibility must be a KnowledgeVisibility",
        ):
            make_document(visibility="customer")

    def test_rejects_invalid_status(self) -> None:
        with pytest.raises(
            TypeError,
            match="status must be a KnowledgeDocumentStatus",
        ):
            make_document(status="active")

    def test_rejects_non_string_description(self) -> None:
        with pytest.raises(
            TypeError,
            match="description must be a string or None",
        ):
            make_document(description=123)


class TestKnowledgeDocumentMetadataValidation:
    def test_rejects_non_mapping_metadata(self) -> None:
        with pytest.raises(
            TypeError,
            match="metadata must be a mapping",
        ):
            make_document(metadata=[])

    def test_rejects_too_many_metadata_keys(self) -> None:
        metadata = {
            f"key_{index}": index
            for index in range(MAX_DOCUMENT_METADATA_KEYS + 1)
        }

        with pytest.raises(InvalidKnowledgeDocumentError):
            make_document(metadata=metadata)

    def test_rejects_non_string_metadata_key(self) -> None:
        with pytest.raises(
            TypeError,
            match="metadata keys must be strings",
        ):
            make_document(
                metadata={
                    1: "value",
                }
            )

    def test_rejects_empty_metadata_key(self) -> None:
        with pytest.raises(InvalidKnowledgeDocumentError):
            make_document(
                metadata={
                    "   ": "value",
                }
            )

    def test_rejects_metadata_key_over_max_length(self) -> None:
        with pytest.raises(InvalidKnowledgeDocumentError):
            make_document(
                metadata={
                    "x" * (MAX_METADATA_KEY_LENGTH + 1): "value",
                }
            )

    def test_rejects_duplicate_keys_after_normalization(self) -> None:
        with pytest.raises(InvalidKnowledgeDocumentError):
            make_document(
                metadata={
                    "language": "en",
                    " language ": "fr",
                }
            )


class TestKnowledgeDocumentDescriptionValidation:
    def test_rejects_description_over_max_length(self) -> None:
        description = "x" * (
            MAX_DOCUMENT_DESCRIPTION_LENGTH + 1
        )

        with pytest.raises(InvalidKnowledgeDocumentError):
            make_document(
                description=description,
            )


class TestKnowledgeDocumentVisibility:
    @pytest.mark.parametrize(
        ("visibility", "customer_visible", "internal_visible"),
        [
            (
                KnowledgeVisibility.CUSTOMER,
                True,
                False,
            ),
            (
                KnowledgeVisibility.INTERNAL,
                False,
                True,
            ),
            (
                KnowledgeVisibility.BOTH,
                True,
                True,
            ),
        ],
    )
    def test_visibility_helpers(
        self,
        visibility: KnowledgeVisibility,
        customer_visible: bool,
        internal_visible: bool,
    ) -> None:
        document = make_document(
            visibility=visibility,
        )

        assert document.is_customer_visible is customer_visible
        assert document.is_internal_visible is internal_visible


class TestKnowledgeDocumentMutation:
    def test_rename_returns_new_document(self) -> None:
        document = make_document()
        occurred_at = document.updated_at + timedelta(minutes=1)

        renamed = document.rename(
            "Returns and Refunds",
            occurred_at=occurred_at,
        )

        assert renamed is not document
        assert renamed.id == document.id
        assert renamed.title == "Returns and Refunds"
        assert renamed.updated_at == occurred_at

        assert document.title == "Refund Policy"

    def test_rename_normalizes_title(self) -> None:
        document = make_document()

        renamed = document.rename(
            "   Returns Policy   ",
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        assert renamed.title == "Returns Policy"

    def test_rename_with_same_normalized_title_returns_same_instance(
        self,
    ) -> None:
        document = make_document()

        result = document.rename(
            "  Refund Policy  ",
        )

        assert result is document

    def test_change_description(self) -> None:
        document = make_document()

        changed = document.change_description(
            "New description",
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        assert changed.description == "New description"
        assert document.description == "Customer refund rules."

    def test_change_description_to_blank_sets_none(self) -> None:
        document = make_document()

        changed = document.change_description(
            "   ",
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        assert changed.description is None

    def test_change_content_type(self) -> None:
        document = make_document()

        changed = document.change_content_type(
            KnowledgeContentType.GUIDE,
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        assert changed.content_type is KnowledgeContentType.GUIDE

    def test_change_same_content_type_returns_same_instance(self) -> None:
        document = make_document()

        result = document.change_content_type(
            document.content_type,
        )

        assert result is document

    def test_change_visibility(self) -> None:
        document = make_document()

        changed = document.change_visibility(
            KnowledgeVisibility.INTERNAL,
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        assert changed.visibility is KnowledgeVisibility.INTERNAL

    def test_replace_metadata(self) -> None:
        document = make_document()

        changed = document.replace_metadata(
            {
                "language": "fr",
                "product": "payments",
            },
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        assert changed.metadata == {
            "language": "fr",
            "product": "payments",
        }

        assert document.metadata == {
            "language": "en",
            "region": "IN",
        }

    def test_replace_identical_metadata_returns_same_instance(self) -> None:
        document = make_document()

        result = document.replace_metadata(
            {
                "language": "en",
                "region": "IN",
            }
        )

        assert result is document


class TestKnowledgeDocumentArchive:
    def test_active_document_can_be_archived(self) -> None:
        document = make_document()
        occurred_at = document.updated_at + timedelta(minutes=1)

        archived = document.archive(
            occurred_at=occurred_at,
        )

        assert archived.status is KnowledgeDocumentStatus.ARCHIVED
        assert archived.archived_at == occurred_at
        assert archived.updated_at == occurred_at
        assert archived.is_archived is True

        assert document.status is KnowledgeDocumentStatus.ACTIVE

    def test_archiving_already_archived_document_fails(self) -> None:
        document = make_document()
        archived = document.archive(
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        with pytest.raises(
            KnowledgeDocumentAlreadyArchivedError
        ):
            archived.archive(
                occurred_at=archived.updated_at + timedelta(seconds=1)
            )

    def test_archived_document_can_be_restored(self) -> None:
        document = make_document()

        archived = document.archive(
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        restored = archived.restore(
            occurred_at=archived.updated_at + timedelta(seconds=1),
        )

        assert restored.status is KnowledgeDocumentStatus.ACTIVE
        assert restored.archived_at is None
        assert restored.is_active is True

    def test_restoring_active_document_is_idempotent(self) -> None:
        document = make_document()

        result = document.restore()

        assert result is document


class TestKnowledgeDocumentDelete:
    @pytest.mark.parametrize(
        "initial_status",
        [
            KnowledgeDocumentStatus.ACTIVE,
            KnowledgeDocumentStatus.ARCHIVED,
        ],
    )
    def test_document_can_be_deleted(
        self,
        initial_status: KnowledgeDocumentStatus,
    ) -> None:
        document = make_document()

        if initial_status is KnowledgeDocumentStatus.ARCHIVED:
            document = document.archive(
                occurred_at=document.updated_at + timedelta(seconds=1)
            )

        occurred_at = document.updated_at + timedelta(seconds=1)

        deleted = document.delete(
            occurred_at=occurred_at,
        )

        assert deleted.status is KnowledgeDocumentStatus.DELETED
        assert deleted.deleted_at == occurred_at
        assert deleted.updated_at == occurred_at
        assert deleted.is_deleted is True

    def test_deleting_deleted_document_fails(self) -> None:
        document = make_document()

        deleted = document.delete(
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        with pytest.raises(KnowledgeDocumentDeletedError):
            deleted.delete(
                occurred_at=deleted.updated_at + timedelta(seconds=1)
            )

    @pytest.mark.parametrize(
        "operation",
        [
            lambda document: document.rename("New title"),
            lambda document: document.change_description("New"),
            lambda document: document.change_content_type(
                KnowledgeContentType.GUIDE
            ),
            lambda document: document.change_visibility(
                KnowledgeVisibility.INTERNAL
            ),
            lambda document: document.replace_metadata(
                {"language": "fr"}
            ),
            lambda document: document.restore(),
        ],
    )
    def test_deleted_document_rejects_mutations(
        self,
        operation,
    ) -> None:
        document = make_document()

        deleted = document.delete(
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        with pytest.raises(KnowledgeDocumentDeletedError):
            operation(deleted)


class TestKnowledgeDocumentLifecycleConsistency:
    def test_archived_document_requires_archived_at(self) -> None:
        with pytest.raises(InvalidKnowledgeDocumentError):
            make_document(
                status=KnowledgeDocumentStatus.ARCHIVED,
                archived_at=None,
            )

    def test_active_document_cannot_have_archived_at(self) -> None:
        now = datetime.now(timezone.utc)

        with pytest.raises(InvalidKnowledgeDocumentError):
            make_document(
                status=KnowledgeDocumentStatus.ACTIVE,
                archived_at=now,
            )

    def test_deleted_document_requires_deleted_at(self) -> None:
        with pytest.raises(InvalidKnowledgeDocumentError):
            make_document(
                status=KnowledgeDocumentStatus.DELETED,
                deleted_at=None,
            )

    def test_non_deleted_document_cannot_have_deleted_at(self) -> None:
        now = datetime.now(timezone.utc)

        with pytest.raises(InvalidKnowledgeDocumentError):
            make_document(
                deleted_at=now,
            )

    def test_deleted_document_cannot_be_restored(self) -> None:
        document = make_document()

        deleted = document.delete(
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        with pytest.raises(KnowledgeDocumentDeletedError):
            deleted.restore()


class TestKnowledgeDocumentTimestampValidation:
    def test_created_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(
            ValueError,
            match="created_at must be timezone-aware",
        ):
            make_document(
                created_at=datetime(2026, 8, 29, 0, 0),
            )

    def test_updated_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(
            ValueError,
            match="updated_at must be timezone-aware",
        ):
            make_document(
                updated_at=datetime(2026, 8, 29, 0, 0),
            )

    def test_updated_at_cannot_precede_created_at(self) -> None:
        now = datetime.now(timezone.utc)

        with pytest.raises(InvalidKnowledgeDocumentError):
            make_document(
                created_at=now,
                updated_at=now - timedelta(seconds=1),
            )

    def test_mutation_time_cannot_precede_updated_at(self) -> None:
        document = make_document()

        with pytest.raises(InvalidKnowledgeDocumentError):
            document.rename(
                "New title",
                occurred_at=document.updated_at - timedelta(seconds=1),
            )

    def test_mutation_time_must_be_timezone_aware(self) -> None:
        document = make_document()

        with pytest.raises(
            ValueError,
            match="occurred_at must be timezone-aware",
        ):
            document.rename(
                "New title",
                occurred_at=datetime(2026, 8, 29, 1, 0),
            )


class TestKnowledgeDocumentImmutability:
    def test_direct_field_assignment_is_rejected(self) -> None:
        document = make_document()

        with pytest.raises(FrozenInstanceError):
            document.title = "Changed"

    def test_document_identity_is_preserved_across_mutation(self) -> None:
        document = make_document()

        changed = document.rename(
            "Updated Refund Policy",
            occurred_at=document.updated_at + timedelta(seconds=1),
        )

        assert changed.id == document.id