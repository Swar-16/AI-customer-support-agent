from __future__ import annotations

import uuid
from uuid6 import uuid7

import pytest

from packages.ai.orchestration.state import EvidenceSourceType
from packages.application.knowledge.evidence_mapper import KnowledgeEvidenceMapper
from packages.knowledge.retrieval.context.models import (
    GroundingContext,
    GroundingContextBlock,
)
from packages.knowledge.retrieval.models import RetrievalQuery

def make_block(
    *,
    chunk_id: uuid.UUID | None = None,
    version_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    chunk_index: int = 0,
    content: str = "Refunds may take several business days.",
    document_title: str = "Refund Policy",
    section_title: str | None = "Processing Time",
    retrieval_score: float | None = 0.91,
    metadata: dict | None = None,
) -> GroundingContextBlock:
    return GroundingContextBlock(
        chunk_id=chunk_id or uuid7(),
        version_id=version_id or uuid7(),
        document_id=document_id or uuid7(),
        chunk_index=chunk_index,
        content=content,
        document_title=document_title,
        section_title=section_title,
        retrieval_score=retrieval_score,
        metadata=metadata or {},
    )


def make_context(
    *blocks: GroundingContextBlock,
    estimated_token_count: int = 100,
) -> GroundingContext:
    return GroundingContext(
        query=RetrievalQuery(
            text="refund processing time",
        ),
        blocks=tuple(blocks),
        estimated_token_count=estimated_token_count,
    )


class TestKnowledgeEvidenceMapper:
    def test_maps_grounding_block_to_retrieved_evidence(self) -> None:
        chunk_id = uuid7()
        version_id = uuid7()
        document_id = uuid7()

        block = make_block(
            chunk_id=chunk_id,
            version_id=version_id,
            document_id=document_id,
            chunk_index=4,
            content="Approved refunds usually take several business days.",
            document_title="Refund Policy",
            section_title="Processing Time",
            retrieval_score=0.87,
        )

        mapper = KnowledgeEvidenceMapper()

        result = mapper.map(
            context=make_context(block),
        )

        assert len(result) == 1

        evidence = result[0]

        assert evidence.source_type is EvidenceSourceType.KNOWLEDGE
        assert evidence.source_id == str(chunk_id)
        assert (
            evidence.content
            == "Approved refunds usually take several business days."
        )
        assert evidence.title == "Refund Policy"
        assert evidence.section == "Processing Time"
        assert evidence.relevance_score == pytest.approx(0.87)

    def test_preserves_knowledge_provenance_in_metadata(self) -> None:
        chunk_id = uuid7()
        version_id = uuid7()
        document_id = uuid7()

        block = make_block(
            chunk_id=chunk_id,
            version_id=version_id,
            document_id=document_id,
            chunk_index=7,
            metadata={
                "category": "refunds",
                "language": "en",
            },
        )

        mapper = KnowledgeEvidenceMapper()

        result = mapper.map(
            context=make_context(block),
        )

        metadata = result[0].metadata

        assert metadata["chunk_id"] == str(chunk_id)
        assert metadata["version_id"] == str(version_id)
        assert metadata["document_id"] == str(document_id)
        assert metadata["chunk_index"] == 7

        assert metadata["category"] == "refunds"
        assert metadata["language"] == "en"

    def test_maps_multiple_blocks_in_original_order(self) -> None:
        first = make_block(
            chunk_index=0,
            content="First evidence block.",
        )

        second = make_block(
            chunk_index=1,
            content="Second evidence block.",
        )

        mapper = KnowledgeEvidenceMapper()

        result = mapper.map(
            context=make_context(first, second),
        )

        assert len(result) == 2

        assert result[0].content == "First evidence block."
        assert result[1].content == "Second evidence block."

    def test_empty_grounding_context_maps_to_empty_tuple(self) -> None:
        mapper = KnowledgeEvidenceMapper()

        result = mapper.map(
            context=make_context(),
        )

        assert result == ()
        assert isinstance(result, tuple)

    def test_rejects_wrong_context_type(self) -> None:
        mapper = KnowledgeEvidenceMapper()

        with pytest.raises(
            TypeError,
            match="context must be a GroundingContext instance",
        ):
            mapper.map(
                context="not-a-context",  # type: ignore[arg-type]
            )

    def test_source_metadata_is_not_mutated(self) -> None:
        original_metadata = {
            "category": "refund",
            "language": "en",
        }

        block = make_block(
            metadata=original_metadata,
        )

        metadata_before = dict(block.metadata)

        mapper = KnowledgeEvidenceMapper()

        mapper.map(
            context=make_context(block),
        )

        assert block.metadata == metadata_before
        assert "chunk_id" not in block.metadata
        assert "version_id" not in block.metadata
        assert "document_id" not in block.metadata
        assert "chunk_index" not in block.metadata

    def test_metadata_provenance_overrides_conflicting_source_metadata(
        self,
    ) -> None:
        chunk_id = uuid7()
        version_id = uuid7()
        document_id = uuid7()

        block = make_block(
            chunk_id=chunk_id,
            version_id=version_id,
            document_id=document_id,
            chunk_index=3,
            metadata={
                "chunk_id": "fake-chunk",
                "version_id": "fake-version",
                "document_id": "fake-document",
                "chunk_index": 999,
            },
        )

        mapper = KnowledgeEvidenceMapper()

        result = mapper.map(
            context=make_context(block),
        )

        metadata = result[0].metadata

        assert metadata["chunk_id"] == str(chunk_id)
        assert metadata["version_id"] == str(version_id)
        assert metadata["document_id"] == str(document_id)
        assert metadata["chunk_index"] == 3
        
    def test_document_title_is_preserved(self) -> None:
        block = make_block(
            document_title="Returns and Refunds",
        )

        mapper = KnowledgeEvidenceMapper()

        result = mapper.map(
            context=make_context(block),
        )

        assert result[0].title == "Returns and Refunds"

    def test_none_retrieval_score_is_preserved(self) -> None:
        block = make_block(
            retrieval_score=None,
        )

        mapper = KnowledgeEvidenceMapper()

        result = mapper.map(
            context=make_context(block),
        )

        assert result[0].relevance_score is None

    def test_each_mapping_returns_independent_metadata(self) -> None:
        block = make_block(
            metadata={
                "category": "refund",
            },
        )

        mapper = KnowledgeEvidenceMapper()

        first = mapper.map(
            context=make_context(block),
        )

        second = mapper.map(
            context=make_context(block),
        )

        assert first[0].metadata == second[0].metadata
        assert first[0].metadata is not second[0].metadata
        
    def test_context_token_count_does_not_leak_into_evidence(
        self,
    ) -> None:
        block = make_block()

        context = make_context(
            block,
            estimated_token_count=250,
        )

        mapper = KnowledgeEvidenceMapper()

        result = mapper.map(context=context)

        assert "estimated_token_count" not in result[0].metadata