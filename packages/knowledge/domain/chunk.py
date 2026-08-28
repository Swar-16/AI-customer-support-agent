from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from packages.knowledge.domain.errors import InvalidKnowledgeChunkError

MAX_CHUNK_CONTENT_LENGTH = 50_000
MAX_CHUNK_METADATA_KEYS = 100
MAX_METADATA_KEY_LENGTH = 100
MAX_SECTION_TITLE_LENGTH = 500

@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """
    Domain representation of one retrieval-oriented chunk derived from a
    KnowledgeDocumentVersion.

    A chunk is not the authoritative source of truth. The original document
    version remains authoritative; chunks are derived representations created
    for retrieval, ranking, grounding, and downstream AI workflows.

    Example:

        KnowledgeDocument
            └── KnowledgeDocumentVersion v3
                    ├── chunk 0
                    ├── chunk 1
                    ├── chunk 2
                    └── chunk 3

    Embeddings are intentionally not stored directly on this domain entity.
    They are infrastructure-specific derived artifacts and will be represented
    separately at the persistence/retrieval boundary.
    """
    id: UUID
    version_id: UUID
    chunk_index: int
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    section_title: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    token_count: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self._validate_ids()
        self._validate_chunk_index()
        self._validate_content()
        self._validate_section_title()
        self._validate_offsets()
        self._validate_token_count()
        self._validate_metadata()
        self._validate_timestamps()

        object.__setattr__(self, "content", self.content.strip())
        if self.section_title is not None:
            normalized_section_title = self.section_title.strip()
            object.__setattr__(self, "section_title", normalized_section_title or None)

        object.__setattr__(self, "metadata", dict(self.metadata))

    # Queries
    @property
    def has_source_offsets(self) -> bool:
        """
        Return whether this chunk has source-position information.

        Offsets are useful for traceability, highlighting retrieved passages,
        and reconstructing where a chunk originated inside normalized source
        content.
        """
        return self.start_offset is not None and self.end_offset is not None

    @property
    def content_length(self) -> int:
        """Return the normalized character length of the chunk."""
        return len(self.content)

    # Controlled mutation
    def replace_metadata(self, metadata: Mapping[str, Any], *, occurred_at: datetime | None = None) -> KnowledgeChunk:
        """
        Return a copy of the chunk with updated derived metadata.

        Chunk content itself is intentionally immutable. If chunking logic or
        source content changes, chunks should be regenerated rather than
        silently mutated.
        """
        normalized_metadata = self._normalize_metadata(metadata)
        if normalized_metadata == dict(self.metadata):
            return self

        changed_at = self._resolve_mutation_time(occurred_at)

        return replace(self, metadata=normalized_metadata, updated_at=changed_at)

    def update_token_count(self, token_count: int | None, *, occurred_at: datetime | None = None) -> KnowledgeChunk:
        """
        Return a copy with an updated token-count estimate.

        Token count is derived information and may vary depending on the
        tokenizer used by the ingestion pipeline.
        """
        self._validate_token_count_value(token_count)
        if token_count == self.token_count:
            return self

        changed_at = self._resolve_mutation_time(occurred_at)

        return replace(self, token_count=token_count, updated_at=changed_at)

    # Validation
    def _validate_ids(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("ID must be a UUID.")

        if not isinstance(self.version_id, UUID):
            raise TypeError("version_id must be a UUID.")

    def _validate_chunk_index(self) -> None:
        if not isinstance(self.chunk_index, int) or isinstance(self.chunk_index, bool) or self.chunk_index < 0:
            raise InvalidKnowledgeChunkError(
                reason="chunk_index must be a non-negative integer.",
                chunk_index=(
                    self.chunk_index
                    if isinstance(self.chunk_index, int)
                    and not isinstance(self.chunk_index, bool)
                    else None
                ),
            )

    def _validate_content(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError("content must be a string.")

        normalized = self.content.strip()
        if not normalized:
            raise InvalidKnowledgeChunkError(reason="Chunk content cannot be empty.", chunk_index=self.chunk_index)

        if len(normalized) > MAX_CHUNK_CONTENT_LENGTH:
            raise InvalidKnowledgeChunkError(
                reason=f"Chunk content cannot exceed {MAX_CHUNK_CONTENT_LENGTH} characters.",
                chunk_index=self.chunk_index,
            )

    def _validate_section_title(self) -> None:
        if self.section_title is None:
            return

        if not isinstance(self.section_title, str):
            raise TypeError("section_title must be a string or None.")

        normalized = self.section_title.strip()
        if len(normalized) > MAX_SECTION_TITLE_LENGTH:
            raise InvalidKnowledgeChunkError(
                reason=f"section_title cannot exceed {MAX_SECTION_TITLE_LENGTH} characters.",
                chunk_index=self.chunk_index,
            )

    def _validate_offsets(self) -> None:
        if self.start_offset is None and self.end_offset is None:
            return

        if self.start_offset is None or self.end_offset is None:
            raise InvalidKnowledgeChunkError(
                reason="start_offset and end_offset must either both be provided or both be omitted.",
                chunk_index=self.chunk_index,
            )

        if not isinstance(self.start_offset, int) or isinstance(self.start_offset, bool):
            raise TypeError("start_offset must be an integer or None.")

        if not isinstance(self.end_offset, int) or isinstance(self.end_offset, bool):
            raise TypeError("end_offset must be an integer or None.")

        if self.start_offset < 0:
            raise InvalidKnowledgeChunkError(
                reason="start_offset cannot be negative.",
                chunk_index=self.chunk_index,
            )

        if self.end_offset <= self.start_offset:
            raise InvalidKnowledgeChunkError(
                reason="end_offset must be greater than start_offset.",
                chunk_index=self.chunk_index,
            )

    def _validate_token_count(self) -> None:
        self._validate_token_count_value(self.token_count)

    def _validate_metadata(self) -> None:
        self._normalize_metadata(self.metadata)

    def _validate_timestamps(self) -> None:
        self._ensure_aware_datetime("created_at", self.created_at)
        self._ensure_aware_datetime("updated_at", self.updated_at)

        if self.updated_at < self.created_at:
            raise InvalidKnowledgeChunkError(
                reason="updated_at cannot be earlier than created_at.",
                chunk_index=self.chunk_index,
            )

    # Normalization helpers
    @staticmethod
    def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        if len(metadata) > MAX_CHUNK_METADATA_KEYS:
            raise InvalidKnowledgeChunkError(reason=f"Chunk metadata cannot contain more than {MAX_CHUNK_METADATA_KEYS} keys.")

        normalized: dict[str, Any] = {}

        for key, value in metadata.items():
            if not isinstance(key, str):
                raise TypeError("metadata keys must be strings.")

            normalized_key = key.strip()
            if not normalized_key:
                raise InvalidKnowledgeChunkError(reason="Chunk metadata keys cannot be empty.")

            if len(normalized_key) > MAX_METADATA_KEY_LENGTH:
                raise InvalidKnowledgeChunkError(reason=f"Chunk metadata keys cannot exceed {MAX_METADATA_KEY_LENGTH} characters.")

            if normalized_key in normalized:
                raise InvalidKnowledgeChunkError(reason="Chunk metadata contains duplicate keys after normalization.")

            normalized[normalized_key] = value

        return normalized

    @staticmethod
    def _validate_token_count_value(token_count: int | None) -> None:
        if token_count is None:
            return

        if not isinstance(token_count, int) or isinstance(token_count, bool):
            raise TypeError("token_count must be an integer or None.")

        if token_count <= 0:
            raise InvalidKnowledgeChunkError(reason="token_count must be greater than zero when provided.")

    # Time handling
    def _resolve_mutation_time(self, occurred_at: datetime | None) -> datetime:
        value = occurred_at or datetime.now(timezone.utc)
        self._ensure_aware_datetime("occurred_at", value)

        if value < self.created_at:
            raise InvalidKnowledgeChunkError(
                reason="Mutation time cannot be earlier than created_at.",
                chunk_index=self.chunk_index,
            )

        if value < self.updated_at:
            raise InvalidKnowledgeChunkError(
                reason="Mutation time cannot be earlier than updated_at.",
                chunk_index=self.chunk_index,
            )

        return value

    @staticmethod
    def _ensure_aware_datetime(field_name: str, value: datetime) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime.")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware.")