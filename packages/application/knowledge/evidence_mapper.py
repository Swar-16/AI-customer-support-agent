from __future__ import annotations

from packages.ai.orchestration.state import EvidenceSourceType, RetrievedEvidence
from packages.knowledge.retrieval.context.models import GroundingContext, GroundingContextBlock


class KnowledgeEvidenceMapper:
    """
    Translate knowledge-subsystem grounding context into provider-neutral
    orchestration evidence.

    This class is deliberately an application-layer adapter.

    Dependency direction:

        packages.knowledge --> packages.application --> packages.ai orchestration contracts

    Responsibilities:
    - preserve customer-facing evidence content;
    - preserve primary source identity;
    - preserve provenance required for debugging/auditability;
    - hide knowledge-retrieval implementation details from AI orchestration.
    """
    def map(self, *, context: GroundingContext) -> tuple[RetrievedEvidence, ...]:
        if not isinstance(context, GroundingContext):
            raise TypeError("context must be a GroundingContext instance.")

        return tuple(self._map_block(block) for block in context.blocks)

    @staticmethod
    def _map_block(block: GroundingContextBlock) -> RetrievedEvidence:
        """
        Convert one GroundingContextBlock into neutral RetrievedEvidence.
        """
        metadata = dict(block.metadata)
        # Preserve stable knowledge provenance without forcing the generic orchestration model to understand knowledge-specific identifiers.
        metadata.update(
            {
                "document_id": str(block.document_id),
                "version_id": str(block.version_id),
                "chunk_id": str(block.chunk_id),
                "chunk_index": block.chunk_index,
            }
        )

        return RetrievedEvidence(
            source_type=EvidenceSourceType.KNOWLEDGE,
            source_id=str(block.chunk_id),
            title=block.document_title,
            section=block.section_title,
            content=block.content,
            relevance_score=block.retrieval_score,
            metadata=metadata,
        )