from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from packages.knowledge.embeddings.models import EmbeddingInputDescriptor, EmbeddingProviderDescriptor, EmbeddingVector


@dataclass(frozen=True, slots=True)
class KnowledgeChunkEmbedding:
    """
    Immutable model-dependent embedding artifact for a knowledge chunk.

    The artifact records enough provenance to determine exactly which provider/model and input-building strategy produced the stored vector.
    """
    id: UUID
    chunk_id: UUID
    provider: EmbeddingProviderDescriptor
    input_descriptor: EmbeddingInputDescriptor
    input_fingerprint: str
    vector: EmbeddingVector
    created_at: datetime | None = None
    
    def __post_init__(self) -> None:
        fingerprint = self.input_fingerprint.strip()
        if not fingerprint:
            raise ValueError("Knowledge chunk embedding input_fingerprint must not be blank.")
        
        if len(fingerprint) != 64:
            raise ValueError("Knowledge chunk embedding input_fingerprint must be a 64-character SHA-256 hexadecimal digest.")

        try:
            bytes.fromhex(fingerprint)
            
        except ValueError as exc:
            raise ValueError("Knowledge chunk embedding input_fingerprint must be a valid hexadecimal SHA-256 digest.") from exc

        if self.vector.dimensions != self.provider.dimensions:
            raise ValueError(f"Embedding vector dimensions must match provider dimensions: expected {self.provider.dimensions}, received {self.vector.dimensions}.")

        object.__setattr__(self, "input_fingerprint", fingerprint)