from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping
from uuid import UUID

from packages.knowledge.embeddings.models import EmbeddingInputDescriptor, PreparedEmbeddingInput


@dataclass(frozen=True, slots=True)
class EmbeddingSourceChunk:
    """
    Provider-independent representation of one canonical knowledge chunk
    together with the contextual metadata that an embedding input strategy may
    use.

    This is intentionally separate from ORM models and persistence entities so
    embedding input builders remain independent of SQLAlchemy and database
    structure.
    """
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    document_title: str
    chunk_text: str
    section_title: str | None = None
    section_path: tuple[str, ...] = ()
    document_metadata: Mapping[str, object] | None = None
    chunk_metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        document_title = self.document_title.strip()
        chunk_text = self.chunk_text.strip()

        if not document_title:
            raise ValueError("Embedding source document title must not be blank.")

        if not chunk_text:
            raise ValueError("Embedding source chunk text must not be blank.")

        section_title = self.section_title.strip() if self.section_title is not None else None
        if section_title == "":
            section_title = None

        normalized_section_path = tuple(part.strip() for part in self.section_path if part.strip())
        object.__setattr__(self, "document_title", document_title)
        object.__setattr__(self, "chunk_text", chunk_text)
        object.__setattr__(self, "section_title", section_title)
        object.__setattr__(self, "section_path", normalized_section_path)

class EmbeddingInputBuilder(ABC):
    """
    Strategy for constructing the exact model-facing text used to embed a
    canonical knowledge chunk.

    Implementations may enrich chunk content with stable contextual information
    such as:
    - document title,
    - section hierarchy,
    - selected retrieval-relevant metadata.

    Implementations must not mutate canonical knowledge content.
    """
    @property
    @abstractmethod
    def descriptor(self) -> EmbeddingInputDescriptor:
        """
        Return the stable identity of this input-construction strategy.

        Any material change to output behavior should change either:
        - descriptor.version, or
        - descriptor.config_fingerprint.

        This enables reliable re-embedding when the model-facing representation changes.
        """
        raise NotImplementedError

    @abstractmethod
    def build(self, source: EmbeddingSourceChunk) -> PreparedEmbeddingInput:
        """
        Construct one deterministic embedding input.

        Contract
        --------
        - The returned chunk_id must equal source.chunk_id.
        - Returned text must be non-blank.
        - The same source + same descriptor/configuration must produce the same output text.
        - input_fingerprint must identify the exact returned text.
        - Builders must not perform network I/O.
        - Builders must not call embedding providers.
        - Builders must not access repositories or databases.
        - Builders must not mutate source content.
        """
        raise NotImplementedError