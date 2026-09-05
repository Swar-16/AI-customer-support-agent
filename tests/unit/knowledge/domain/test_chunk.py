from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from packages.knowledge.domain.chunk import (
    MAX_CHUNK_CONTENT_LENGTH,
    MAX_CHUNK_METADATA_KEYS,
    MAX_METADATA_KEY_LENGTH,
    MAX_SECTION_TITLE_LENGTH,
    KnowledgeChunk,
)
from packages.knowledge.domain.errors import (
    InvalidKnowledgeChunkError,
)


BASE_TIME = datetime(
    2026,
    8,
    29,
    0,
    0,
    tzinfo=timezone.utc,
)


def make_chunk(
    **overrides,
) -> KnowledgeChunk:
    defaults = {
        "id": uuid4(),
        "version_id": uuid4(),
        "chunk_index": 0,
        "content": "Customers may request a refund within the allowed period.",
        "metadata": {
            "language": "en",
            "section": "refunds",
        },
        "section_title": "Refund Eligibility",
        "start_offset": 0,
        "end_offset": 58,
        "token_count": 10,
        "created_at": BASE_TIME,
        "updated_at": BASE_TIME,
    }

    defaults.update(overrides)

    return KnowledgeChunk(**defaults)


class TestKnowledgeChunkConstruction:
    def test_creates_valid_chunk(self) -> None:
        chunk = make_chunk()

        assert chunk.chunk_index == 0
        assert chunk.content
        assert chunk.section_title == "Refund Eligibility"
        assert chunk.start_offset == 0
        assert chunk.end_offset == 58
        assert chunk.token_count == 10

        assert chunk.has_source_offsets is True
        assert chunk.content_length == len(chunk.content)

    def test_normalizes_content_section_title_and_metadata_keys(
        self,
    ) -> None:
        chunk = make_chunk(
            content="   Refund content here.   ",
            section_title="   Refund Rules   ",
            metadata={
                " language ": "en",
                "  region  ": "IN",
            },
        )

        assert chunk.content == "Refund content here."
        assert chunk.section_title == "Refund Rules"
        assert chunk.metadata == {
            "language": "en",
            "region": "IN",
        }

    def test_blank_section_title_becomes_none(self) -> None:
        chunk = make_chunk(
            section_title="   ",
        )

        assert chunk.section_title is None

    def test_copies_metadata_mapping(self) -> None:
        metadata = {
            "language": "en",
        }

        chunk = make_chunk(
            metadata=metadata,
        )

        metadata["language"] = "fr"

        assert chunk.metadata["language"] == "en"

    def test_offsets_may_be_absent(self) -> None:
        chunk = make_chunk(
            start_offset=None,
            end_offset=None,
        )

        assert chunk.has_source_offsets is False


class TestKnowledgeChunkIdentityValidation:
    def test_rejects_non_uuid_id(self) -> None:
        with pytest.raises(
            TypeError,
            match="id must be a UUID",
        ):
            make_chunk(
                id="bad-id",
            )

    def test_rejects_non_uuid_version_id(self) -> None:
        with pytest.raises(
            TypeError,
            match="version_id must be a UUID",
        ):
            make_chunk(
                version_id="bad-version-id",
            )


class TestKnowledgeChunkIndexValidation:
    @pytest.mark.parametrize(
        "chunk_index",
        [
            -1,
            -100,
            True,
        ],
    )
    def test_rejects_invalid_chunk_index(
        self,
        chunk_index,
    ) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                chunk_index=chunk_index,
            )

    def test_rejects_non_integer_chunk_index(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                chunk_index="0",
            )

    def test_zero_chunk_index_is_valid(self) -> None:
        chunk = make_chunk(
            chunk_index=0,
        )

        assert chunk.chunk_index == 0


class TestKnowledgeChunkContentValidation:
    @pytest.mark.parametrize(
        "content",
        [
            "",
            " ",
            "\n",
            "\t",
        ],
    )
    def test_rejects_empty_content(
        self,
        content: str,
    ) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                content=content,
            )

    def test_rejects_non_string_content(self) -> None:
        with pytest.raises(
            TypeError,
            match="content must be a string",
        ):
            make_chunk(
                content=123,
            )

    def test_rejects_content_over_max_length(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                content="x" * (
                    MAX_CHUNK_CONTENT_LENGTH + 1
                )
            )


class TestKnowledgeChunkSectionValidation:
    def test_rejects_non_string_section_title(self) -> None:
        with pytest.raises(
            TypeError,
            match="section_title must be a string or None",
        ):
            make_chunk(
                section_title=123,
            )

    def test_rejects_section_title_over_max_length(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                section_title="x" * (
                    MAX_SECTION_TITLE_LENGTH + 1
                )
            )


class TestKnowledgeChunkOffsetValidation:
    def test_requires_both_offsets_or_neither(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                start_offset=0,
                end_offset=None,
            )

    def test_rejects_missing_start_offset_only(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                start_offset=None,
                end_offset=10,
            )

    def test_rejects_non_integer_start_offset(self) -> None:
        with pytest.raises(TypeError):
            make_chunk(
                start_offset="0",
                end_offset=10,
            )

    def test_rejects_non_integer_end_offset(self) -> None:
        with pytest.raises(TypeError):
            make_chunk(
                start_offset=0,
                end_offset="10",
            )

    def test_rejects_boolean_offsets(self) -> None:
        with pytest.raises(TypeError):
            make_chunk(
                start_offset=True,
                end_offset=10,
            )

    def test_rejects_negative_start_offset(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                start_offset=-1,
                end_offset=10,
            )

    def test_end_offset_must_be_greater_than_start_offset(
        self,
    ) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                start_offset=10,
                end_offset=10,
            )

    def test_end_offset_cannot_precede_start_offset(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                start_offset=10,
                end_offset=5,
            )


class TestKnowledgeChunkTokenCountValidation:
    def test_token_count_may_be_none(self) -> None:
        chunk = make_chunk(
            token_count=None,
        )

        assert chunk.token_count is None

    def test_rejects_zero_token_count(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                token_count=0,
            )

    def test_rejects_negative_token_count(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                token_count=-1,
            )

    def test_rejects_boolean_token_count(self) -> None:
        with pytest.raises(TypeError):
            make_chunk(
                token_count=True,
            )

    def test_rejects_non_integer_token_count(self) -> None:
        with pytest.raises(TypeError):
            make_chunk(
                token_count="10",
            )


class TestKnowledgeChunkMetadataValidation:
    def test_rejects_non_mapping_metadata(self) -> None:
        with pytest.raises(
            TypeError,
            match="metadata must be a mapping",
        ):
            make_chunk(
                metadata=[],
            )

    def test_rejects_too_many_metadata_keys(self) -> None:
        metadata = {
            f"key_{index}": index
            for index in range(
                MAX_CHUNK_METADATA_KEYS + 1
            )
        }

        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                metadata=metadata,
            )

    def test_rejects_non_string_metadata_key(self) -> None:
        with pytest.raises(
            TypeError,
            match="metadata keys must be strings",
        ):
            make_chunk(
                metadata={
                    1: "value",
                }
            )

    def test_rejects_empty_metadata_key(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                metadata={
                    "   ": "value",
                }
            )

    def test_rejects_metadata_key_over_max_length(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                metadata={
                    "x" * (
                        MAX_METADATA_KEY_LENGTH + 1
                    ): "value"
                }
            )

    def test_rejects_duplicate_metadata_keys_after_normalization(
        self,
    ) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                metadata={
                    "language": "en",
                    " language ": "fr",
                }
            )


class TestKnowledgeChunkMetadataMutation:
    def test_can_replace_metadata(self) -> None:
        chunk = make_chunk()

        changed = chunk.replace_metadata(
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

        assert changed.updated_at == (
            BASE_TIME + timedelta(minutes=1)
        )

        assert chunk.metadata == {
            "language": "en",
            "section": "refunds",
        }

    def test_identical_metadata_returns_same_instance(self) -> None:
        chunk = make_chunk()

        result = chunk.replace_metadata(
            {
                "language": "en",
                "section": "refunds",
            }
        )

        assert result is chunk


class TestKnowledgeChunkTokenCountMutation:
    def test_can_update_token_count(self) -> None:
        chunk = make_chunk(
            token_count=10,
        )

        changed = chunk.update_token_count(
            15,
            occurred_at=BASE_TIME + timedelta(minutes=1),
        )

        assert changed.token_count == 15
        assert changed.updated_at == (
            BASE_TIME + timedelta(minutes=1)
        )

        assert chunk.token_count == 10

    def test_can_clear_token_count(self) -> None:
        chunk = make_chunk(
            token_count=10,
        )

        changed = chunk.update_token_count(
            None,
            occurred_at=BASE_TIME + timedelta(minutes=1),
        )

        assert changed.token_count is None

    def test_same_token_count_returns_same_instance(self) -> None:
        chunk = make_chunk(
            token_count=10,
        )

        result = chunk.update_token_count(10)

        assert result is chunk


class TestKnowledgeChunkTimestampValidation:
    def test_created_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(
            ValueError,
            match="created_at must be timezone-aware",
        ):
            make_chunk(
                created_at=datetime(2026, 8, 29, 0, 0),
            )

    def test_updated_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(
            ValueError,
            match="updated_at must be timezone-aware",
        ):
            make_chunk(
                updated_at=datetime(2026, 8, 29, 0, 0),
            )

    def test_updated_at_cannot_precede_created_at(self) -> None:
        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            make_chunk(
                updated_at=BASE_TIME - timedelta(seconds=1),
            )

    def test_mutation_time_cannot_precede_updated_at(self) -> None:
        chunk = make_chunk()

        with pytest.raises(
            InvalidKnowledgeChunkError
        ):
            chunk.update_token_count(
                15,
                occurred_at=BASE_TIME - timedelta(seconds=1),
            )

    def test_mutation_time_must_be_timezone_aware(self) -> None:
        chunk = make_chunk()

        with pytest.raises(
            ValueError,
            match="occurred_at must be timezone-aware",
        ):
            chunk.update_token_count(
                15,
                occurred_at=datetime(2026, 8, 29, 1, 0),
            )


class TestKnowledgeChunkImmutability:
    def test_direct_content_mutation_is_rejected(self) -> None:
        chunk = make_chunk()

        with pytest.raises(FrozenInstanceError):
            chunk.content = "Changed"

    def test_identity_is_preserved_after_metadata_change(self) -> None:
        chunk = make_chunk()

        changed = chunk.replace_metadata(
            {"language": "fr"},
            occurred_at=BASE_TIME + timedelta(minutes=1),
        )

        assert changed.id == chunk.id
        assert changed.version_id == chunk.version_id
        assert changed.chunk_index == chunk.chunk_index

    def test_content_is_preserved_after_derived_metadata_change(
        self,
    ) -> None:
        chunk = make_chunk()

        changed = chunk.update_token_count(
            20,
            occurred_at=BASE_TIME + timedelta(minutes=1),
        )

        assert changed.content == chunk.content