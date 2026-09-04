from __future__ import annotations

from types import MappingProxyType

import pytest

from evaluation.retrieval.models import (
    RetrievalEvaluationCase,
    RetrievalEvaluationHit,
    RetrievalEvaluationResult,
)


class TestRetrievalEvaluationCase:
    def test_creates_valid_case(self) -> None:
        case = RetrievalEvaluationCase(
            case_id="refund_delay_001",
            query="How long does a refund take?",
            intent_key="refund_request",
            expected_document_titles=("Refund Policy",),
            expected_topics=("refund processing time",),
            expected_section_titles=("Processing Time",),
            metadata={
                "category": "refunds",
                "language": "en",
            },
        )

        assert case.case_id == "refund_delay_001"
        assert case.query == "How long does a refund take?"
        assert case.intent_key == "refund_request"

        assert case.expected_document_titles == (
            "Refund Policy",
        )
        assert case.expected_topics == (
            "refund processing time",
        )
        assert case.expected_section_titles == (
            "Processing Time",
        )

        assert case.metadata == {
            "category": "refunds",
            "language": "en",
        }

    def test_normalizes_required_text_fields(self) -> None:
        case = RetrievalEvaluationCase(
            case_id="  refund_delay_001  ",
            query="  How long does a refund take?  ",
            intent_key="  refund_request  ",
            expected_document_titles=("Refund Policy",),
        )

        assert case.case_id == "refund_delay_001"
        assert case.query == "How long does a refund take?"
        assert case.intent_key == "refund_request"

    def test_normalizes_empty_intent_key_to_none(self) -> None:
        case = RetrievalEvaluationCase(
            case_id="general_001",
            query="What payment methods do you accept?",
            intent_key="   ",
            expected_document_titles=("Payment Policy",),
        )

        assert case.intent_key is None

    def test_intent_key_may_be_none(self) -> None:
        case = RetrievalEvaluationCase(
            case_id="general_001",
            query="What payment methods do you accept?",
            expected_document_titles=("Payment Policy",),
        )

        assert case.intent_key is None

    def test_requires_at_least_one_relevance_target(self) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "At least one expected relevance target "
                "must be provided"
            ),
        ):
            RetrievalEvaluationCase(
                case_id="invalid_001",
                query="Some query",
            )

    @pytest.mark.parametrize(
        "invalid_case_id",
        [
            "",
            "   ",
        ],
    )
    def test_rejects_empty_case_id(
        self,
        invalid_case_id: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="case_id must not be empty",
        ):
            RetrievalEvaluationCase(
                case_id=invalid_case_id,
                query="Some query",
                expected_document_titles=("Document",),
            )

    @pytest.mark.parametrize(
        "invalid_case_id",
        [
            None,
            123,
            [],
            {},
        ],
    )
    def test_rejects_non_string_case_id(
        self,
        invalid_case_id: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="case_id must be a string",
        ):
            RetrievalEvaluationCase(
                case_id=invalid_case_id,  # type: ignore[arg-type]
                query="Some query",
                expected_document_titles=("Document",),
            )

    @pytest.mark.parametrize(
        "invalid_query",
        [
            "",
            "   ",
        ],
    )
    def test_rejects_empty_query(
        self,
        invalid_query: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="query must not be empty",
        ):
            RetrievalEvaluationCase(
                case_id="case_001",
                query=invalid_query,
                expected_document_titles=("Document",),
            )

    @pytest.mark.parametrize(
        "invalid_query",
        [
            None,
            123,
            [],
            {},
        ],
    )
    def test_rejects_non_string_query(
        self,
        invalid_query: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="query must be a string",
        ):
            RetrievalEvaluationCase(
                case_id="case_001",
                query=invalid_query,  # type: ignore[arg-type]
                expected_document_titles=("Document",),
            )

    @pytest.mark.parametrize(
        "invalid_intent_key",
        [
            123,
            [],
            {},
            object(),
        ],
    )
    def test_rejects_non_string_intent_key(
        self,
        invalid_intent_key: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="intent_key must be a string or None",
        ):
            RetrievalEvaluationCase(
                case_id="case_001",
                query="Some query",
                intent_key=invalid_intent_key,  # type: ignore[arg-type]
                expected_document_titles=("Document",),
            )

    def test_normalizes_and_deduplicates_document_titles(
        self,
    ) -> None:
        case = RetrievalEvaluationCase(
            case_id="case_001",
            query="Some query",
            expected_document_titles=(
                " Refund Policy ",
                "",
                "Refund Policy",
                "  ",
                "Shipping Policy",
            ),
        )

        assert case.expected_document_titles == (
            "Refund Policy",
            "Shipping Policy",
        )

    def test_normalizes_and_deduplicates_topics(self) -> None:
        case = RetrievalEvaluationCase(
            case_id="case_001",
            query="Some query",
            expected_topics=(
                " refund delay ",
                "refund delay",
                "",
                "refund eligibility",
            ),
        )

        assert case.expected_topics == (
            "refund delay",
            "refund eligibility",
        )

    def test_normalizes_and_deduplicates_section_titles(
        self,
    ) -> None:
        case = RetrievalEvaluationCase(
            case_id="case_001",
            query="Some query",
            expected_section_titles=(
                " Processing Time ",
                "Processing Time",
                "",
                "Eligibility",
            ),
        )

        assert case.expected_section_titles == (
            "Processing Time",
            "Eligibility",
        )

    @pytest.mark.parametrize(
        "field_name",
        [
            "expected_document_titles",
            "expected_topics",
            "expected_section_titles",
        ],
    )
    def test_relevance_target_fields_must_be_tuples(
        self,
        field_name: str,
    ) -> None:
        kwargs = {
            "case_id": "case_001",
            "query": "Some query",
            "expected_document_titles": ("Document",),
        }

        kwargs[field_name] = ["Document"]

        with pytest.raises(
            TypeError,
            match=f"{field_name} must be a tuple",
        ):
            RetrievalEvaluationCase(
                **kwargs,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "field_name",
        [
            "expected_document_titles",
            "expected_topics",
            "expected_section_titles",
        ],
    )
    def test_relevance_target_entries_must_be_strings(
        self,
        field_name: str,
    ) -> None:
        kwargs = {
            "case_id": "case_001",
            "query": "Some query",
            "expected_document_titles": ("Document",),
        }

        kwargs[field_name] = (
            "valid",
            123,
        )

        with pytest.raises(
            TypeError,
            match=f"{field_name} entries must be strings",
        ):
            RetrievalEvaluationCase(
                **kwargs,  # type: ignore[arg-type]
            )

    def test_metadata_is_normalized(self) -> None:
        case = RetrievalEvaluationCase(
            case_id="case_001",
            query="Some query",
            expected_document_titles=("Document",),
            metadata={
                " category ": " refunds ",
                " language ": " en ",
                "empty": "   ",
            },
        )

        assert case.metadata == {
            "category": "refunds",
            "language": "en",
        }

    def test_metadata_is_immutable(self) -> None:
        case = RetrievalEvaluationCase(
            case_id="case_001",
            query="Some query",
            expected_document_titles=("Document",),
            metadata={
                "category": "refunds",
            },
        )

        assert isinstance(case.metadata, MappingProxyType)

        with pytest.raises(TypeError):
            case.metadata["category"] = "shipping"  # type: ignore[index]

    def test_metadata_isolated_from_source_mapping(self) -> None:
        source = {
            "category": "refunds",
        }

        case = RetrievalEvaluationCase(
            case_id="case_001",
            query="Some query",
            expected_document_titles=("Document",),
            metadata=source,
        )

        source["category"] = "shipping"

        assert case.metadata == {
            "category": "refunds",
        }

    @pytest.mark.parametrize(
        "invalid_metadata",
        [
            [],
            "metadata",
            123,
            object(),
        ],
    )
    def test_rejects_non_mapping_metadata(
        self,
        invalid_metadata: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="metadata must be a mapping",
        ):
            RetrievalEvaluationCase(
                case_id="case_001",
                query="Some query",
                expected_document_titles=("Document",),
                metadata=invalid_metadata,  # type: ignore[arg-type]
            )

    def test_rejects_non_string_metadata_key(self) -> None:
        with pytest.raises(
            TypeError,
            match="metadata keys and values must be strings",
        ):
            RetrievalEvaluationCase(
                case_id="case_001",
                query="Some query",
                expected_document_titles=("Document",),
                metadata={
                    123: "refunds",
                },  # type: ignore[dict-item]
            )

    def test_rejects_non_string_metadata_value(self) -> None:
        with pytest.raises(
            TypeError,
            match="metadata keys and values must be strings",
        ):
            RetrievalEvaluationCase(
                case_id="case_001",
                query="Some query",
                expected_document_titles=("Document",),
                metadata={
                    "category": 123,
                },  # type: ignore[dict-item]
            )

    def test_rejects_empty_metadata_key(self) -> None:
        with pytest.raises(
            ValueError,
            match="metadata keys must not be empty",
        ):
            RetrievalEvaluationCase(
                case_id="case_001",
                query="Some query",
                expected_document_titles=("Document",),
                metadata={
                    "   ": "refunds",
                },
            )
    
    def test_builds_stable_relevance_target_ids(self) -> None:
        case = RetrievalEvaluationCase(
            case_id="refund_001",
            query="How long does my refund take?",
            expected_document_titles=(
                "Refund Policy",
            ),
            expected_topics=(
                "Refund Processing Time",
            ),
            expected_section_titles=(
                "Processing Time",
            ),
        )

        assert case.relevance_target_ids == frozenset(
            {
                "document:refund policy",
                "topic:refund processing time",
                "section:processing time",
            }
        )

        assert case.relevance_target_count == 3


    def test_target_ids_are_case_and_whitespace_normalized(
        self,
    ) -> None:
        assert (
            RetrievalEvaluationCase.make_document_target_id(
                "  REFUND   Policy  "
            )
            == "document:refund policy"
        )

        assert (
            RetrievalEvaluationCase.make_topic_target_id(
                " Refund   Processing "
            )
            == "topic:refund processing"
        )

        assert (
            RetrievalEvaluationCase.make_section_target_id(
                " PROCESSING   TIME "
            )
            == "section:processing time"
        )


    def test_relevance_targets_are_deduplicated_case_insensitively(
        self,
    ) -> None:
        case = RetrievalEvaluationCase(
            case_id="refund_001",
            query="Refund question",
            expected_document_titles=(
                "Refund Policy",
                " refund   policy ",
                "REFUND POLICY",
            ),
        )

        assert case.expected_document_titles == (
            "Refund Policy",
        )

        assert case.relevance_target_count == 1


    @pytest.mark.parametrize(
        "factory",
        [
            RetrievalEvaluationCase.make_document_target_id,
            RetrievalEvaluationCase.make_topic_target_id,
            RetrievalEvaluationCase.make_section_target_id,
        ],
    )
    def test_target_id_factory_rejects_empty_values(
        self,
        factory,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="target value must not be empty",
        ):
            factory("   ")


    @pytest.mark.parametrize(
        "factory",
        [
            RetrievalEvaluationCase.make_document_target_id,
            RetrievalEvaluationCase.make_topic_target_id,
            RetrievalEvaluationCase.make_section_target_id,
        ],
    )
    def test_target_id_factory_rejects_non_string_values(
        self,
        factory,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="target value must be a string",
        ):
            factory(123)


class TestRetrievalEvaluationHit:
    def test_creates_relevant_hit(self) -> None:
        hit = RetrievalEvaluationHit(
            rank=1,
            document_title=" Refund Policy ",
            section_title=" Processing Time ",
            chunk_id=" chunk-123 ",
            matched_target_ids=frozenset(
                {
                    "document:refund policy",
                    "section:processing time",
                }
            ),
        )

        assert hit.rank == 1
        assert hit.document_title == "Refund Policy"
        assert hit.section_title == "Processing Time"
        assert hit.chunk_id == "chunk-123"

        assert hit.matched_target_ids == frozenset(
            {
                "document:refund policy",
                "section:processing time",
            }
        )

        assert hit.relevant is True

    def test_hit_without_matched_targets_is_not_relevant(
        self,
    ) -> None:
        hit = RetrievalEvaluationHit(
            rank=1,
            document_title="Shipping Policy",
            section_title=None,
            chunk_id="chunk-123",
        )

        assert hit.matched_target_ids == frozenset()
        assert hit.relevant is False

    def test_section_title_may_be_none(self) -> None:
        hit = RetrievalEvaluationHit(
            rank=1,
            document_title="Refund Policy",
            section_title=None,
            chunk_id="chunk-123",
        )

        assert hit.section_title is None

    def test_empty_section_title_normalizes_to_none(
        self,
    ) -> None:
        hit = RetrievalEvaluationHit(
            rank=1,
            document_title="Refund Policy",
            section_title="   ",
            chunk_id="chunk-123",
        )

        assert hit.section_title is None

    @pytest.mark.parametrize(
        "invalid_rank",
        [
            0,
            -1,
            -100,
        ],
    )
    def test_rejects_non_positive_rank(
        self,
        invalid_rank: int,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="rank must be greater than zero",
        ):
            RetrievalEvaluationHit(
                rank=invalid_rank,
                document_title="Refund Policy",
                section_title=None,
                chunk_id="chunk-123",
            )

    @pytest.mark.parametrize(
        "invalid_rank",
        [
            True,
            False,
            1.0,
            "1",
            None,
        ],
    )
    def test_rejects_non_integer_rank(
        self,
        invalid_rank: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="rank must be an integer",
        ):
            RetrievalEvaluationHit(
                rank=invalid_rank,  # type: ignore[arg-type]
                document_title="Refund Policy",
                section_title=None,
                chunk_id="chunk-123",
            )

    @pytest.mark.parametrize(
        "invalid_document_title",
        [
            None,
            123,
            [],
            {},
        ],
    )
    def test_rejects_non_string_document_title(
        self,
        invalid_document_title: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="document_title must be a string",
        ):
            RetrievalEvaluationHit(
                rank=1,
                document_title=invalid_document_title,  # type: ignore[arg-type]
                section_title=None,
                chunk_id="chunk-123",
            )

    @pytest.mark.parametrize(
        "invalid_document_title",
        [
            "",
            "   ",
        ],
    )
    def test_rejects_empty_document_title(
        self,
        invalid_document_title: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="document_title must not be empty",
        ):
            RetrievalEvaluationHit(
                rank=1,
                document_title=invalid_document_title,
                section_title=None,
                chunk_id="chunk-123",
            )

    @pytest.mark.parametrize(
        "invalid_section_title",
        [
            123,
            [],
            {},
            object(),
        ],
    )
    def test_rejects_invalid_section_title(
        self,
        invalid_section_title: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="section_title must be a string or None",
        ):
            RetrievalEvaluationHit(
                rank=1,
                document_title="Refund Policy",
                section_title=invalid_section_title,  # type: ignore[arg-type]
                chunk_id="chunk-123",
            )

    @pytest.mark.parametrize(
        "invalid_chunk_id",
        [
            None,
            123,
            [],
            {},
        ],
    )
    def test_rejects_non_string_chunk_id(
        self,
        invalid_chunk_id: object,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="chunk_id must be a string",
        ):
            RetrievalEvaluationHit(
                rank=1,
                document_title="Refund Policy",
                section_title=None,
                chunk_id=invalid_chunk_id,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "invalid_chunk_id",
        [
            "",
            "   ",
        ],
    )
    def test_rejects_empty_chunk_id(
        self,
        invalid_chunk_id: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="chunk_id must not be empty",
        ):
            RetrievalEvaluationHit(
                rank=1,
                document_title="Refund Policy",
                section_title=None,
                chunk_id=invalid_chunk_id,
            )

    def test_matched_target_ids_must_be_frozenset(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="matched_target_ids must be a frozenset",
        ):
            RetrievalEvaluationHit(
                rank=1,
                document_title="Refund Policy",
                section_title=None,
                chunk_id="chunk-123",
                matched_target_ids={
                    "document:refund policy",
                },  # type: ignore[arg-type]
            )

    def test_rejects_non_string_matched_target(self) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "matched_target_ids entries must be strings"
            ),
        ):
            RetrievalEvaluationHit(
                rank=1,
                document_title="Refund Policy",
                section_title=None,
                chunk_id="chunk-123",
                matched_target_ids=frozenset(
                    {
                        123,
                    }
                ),  # type: ignore[arg-type]
            )

    def test_rejects_empty_matched_target(self) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "matched_target_ids entries must not be empty"
            ),
        ):
            RetrievalEvaluationHit(
                rank=1,
                document_title="Refund Policy",
                section_title=None,
                chunk_id="chunk-123",
                matched_target_ids=frozenset(
                    {
                        "   ",
                    }
                ),
            )


class TestRetrievalEvaluationResult:
    TARGETS = frozenset(
        {
            "document:refund policy",
            "section:processing time",
        }
    )

    def test_creates_valid_result(self) -> None:
        result = RetrievalEvaluationResult(
            case_id="refund_delay_001",
            method="hybrid",
            relevance_target_ids=self.TARGETS,
            hits=(
                RetrievalEvaluationHit(
                    rank=1,
                    document_title="Refund Policy",
                    section_title="Processing Time",
                    chunk_id="chunk-1",
                    matched_target_ids=frozenset(
                        {
                            "document:refund policy",
                            "section:processing time",
                        }
                    ),
                ),
                RetrievalEvaluationHit(
                    rank=2,
                    document_title="Payment Policy",
                    section_title="Refunds",
                    chunk_id="chunk-2",
                ),
            ),
        )

        assert result.case_id == "refund_delay_001"
        assert result.method == "hybrid"
        assert len(result.hits) == 2

        assert result.relevance_target_count == 2

        assert result.matched_target_ids == self.TARGETS

    def test_allows_empty_hits(self) -> None:
        result = RetrievalEvaluationResult(
            case_id="case_001",
            method="lexical",
            relevance_target_ids=self.TARGETS,
            hits=(),
        )

        assert result.hits == ()
        assert result.matched_target_ids == frozenset()

    def test_multiple_chunks_matching_same_target_count_once(
        self,
    ) -> None:
        result = RetrievalEvaluationResult(
            case_id="case_001",
            method="hybrid",
            relevance_target_ids=self.TARGETS,
            hits=(
                RetrievalEvaluationHit(
                    rank=1,
                    document_title="Refund Policy",
                    section_title="Eligibility",
                    chunk_id="chunk-1",
                    matched_target_ids=frozenset(
                        {
                            "document:refund policy",
                        }
                    ),
                ),
                RetrievalEvaluationHit(
                    rank=2,
                    document_title="Refund Policy",
                    section_title="Processing Time",
                    chunk_id="chunk-2",
                    matched_target_ids=frozenset(
                        {
                            "document:refund policy",
                        }
                    ),
                ),
            ),
        )

        assert result.matched_target_ids == frozenset(
            {
                "document:refund policy",
            }
        )

    @pytest.mark.parametrize(
        "invalid_case_id",
        [
            "",
            "   ",
        ],
    )
    def test_rejects_empty_case_id(
        self,
        invalid_case_id: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="case_id must not be empty",
        ):
            RetrievalEvaluationResult(
                case_id=invalid_case_id,
                method="hybrid",
                relevance_target_ids=self.TARGETS,
                hits=(),
            )

    def test_rejects_non_string_case_id(self) -> None:
        with pytest.raises(
            TypeError,
            match="case_id must be a string",
        ):
            RetrievalEvaluationResult(
                case_id=None,  # type: ignore[arg-type]
                method="hybrid",
                relevance_target_ids=self.TARGETS,
                hits=(),
            )

    @pytest.mark.parametrize(
        "invalid_method",
        [
            "",
            "   ",
        ],
    )
    def test_rejects_empty_method(
        self,
        invalid_method: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="method must not be empty",
        ):
            RetrievalEvaluationResult(
                case_id="case_001",
                method=invalid_method,
                relevance_target_ids=self.TARGETS,
                hits=(),
            )

    def test_rejects_non_string_method(self) -> None:
        with pytest.raises(
            TypeError,
            match="method must be a string",
        ):
            RetrievalEvaluationResult(
                case_id="case_001",
                method=None,  # type: ignore[arg-type]
                relevance_target_ids=self.TARGETS,
                hits=(),
            )

    def test_relevance_target_ids_must_be_frozenset(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="relevance_target_ids must be a frozenset",
        ):
            RetrievalEvaluationResult(
                case_id="case_001",
                method="hybrid",
                relevance_target_ids={
                    "document:refund policy",
                },  # type: ignore[arg-type]
                hits=(),
            )

    def test_requires_at_least_one_relevance_target(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "relevance_target_ids must contain at least one target"
            ),
        ):
            RetrievalEvaluationResult(
                case_id="case_001",
                method="hybrid",
                relevance_target_ids=frozenset(),
                hits=(),
            )

    def test_rejects_non_string_relevance_target(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "relevance_target_ids entries must be strings"
            ),
        ):
            RetrievalEvaluationResult(
                case_id="case_001",
                method="hybrid",
                relevance_target_ids=frozenset(
                    {
                        123,
                    }
                ),  # type: ignore[arg-type]
                hits=(),
            )

    def test_hits_must_be_tuple(self) -> None:
        with pytest.raises(
            TypeError,
            match="hits must be a tuple",
        ):
            RetrievalEvaluationResult(
                case_id="case_001",
                method="hybrid",
                relevance_target_ids=self.TARGETS,
                hits=[],  # type: ignore[arg-type]
            )

    def test_hits_must_contain_evaluation_hits(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match=(
                "hits must contain "
                "RetrievalEvaluationHit instances"
            ),
        ):
            RetrievalEvaluationResult(
                case_id="case_001",
                method="hybrid",
                relevance_target_ids=self.TARGETS,
                hits=(
                    "invalid",  # type: ignore[arg-type]
                ),
            )

    def test_ranks_must_start_at_one(self) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "hits must have contiguous ranks starting at 1"
            ),
        ):
            RetrievalEvaluationResult(
                case_id="case_001",
                method="hybrid",
                relevance_target_ids=self.TARGETS,
                hits=(
                    RetrievalEvaluationHit(
                        rank=2,
                        document_title="Refund Policy",
                        section_title=None,
                        chunk_id="chunk-1",
                    ),
                ),
            )

    def test_ranks_must_be_contiguous(self) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "hits must have contiguous ranks starting at 1"
            ),
        ):
            RetrievalEvaluationResult(
                case_id="case_001",
                method="hybrid",
                relevance_target_ids=self.TARGETS,
                hits=(
                    RetrievalEvaluationHit(
                        rank=1,
                        document_title="Refund Policy",
                        section_title=None,
                        chunk_id="chunk-1",
                    ),
                    RetrievalEvaluationHit(
                        rank=3,
                        document_title="Shipping Policy",
                        section_title=None,
                        chunk_id="chunk-2",
                    ),
                ),
            )

    def test_duplicate_chunk_ids_are_rejected(self) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "hits must not contain duplicate chunk IDs"
            ),
        ):
            RetrievalEvaluationResult(
                case_id="case_001",
                method="hybrid",
                relevance_target_ids=self.TARGETS,
                hits=(
                    RetrievalEvaluationHit(
                        rank=1,
                        document_title="Refund Policy",
                        section_title=None,
                        chunk_id="chunk-1",
                    ),
                    RetrievalEvaluationHit(
                        rank=2,
                        document_title="Refund Policy",
                        section_title="Processing Time",
                        chunk_id="chunk-1",
                    ),
                ),
            )

    def test_hit_cannot_reference_unknown_target(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "hit matched_target_ids must be a subset of "
                "result relevance_target_ids"
            ),
        ):
            RetrievalEvaluationResult(
                case_id="case_001",
                method="hybrid",
                relevance_target_ids=self.TARGETS,
                hits=(
                    RetrievalEvaluationHit(
                        rank=1,
                        document_title="Shipping Policy",
                        section_title=None,
                        chunk_id="chunk-1",
                        matched_target_ids=frozenset(
                            {
                                "document:shipping policy",
                            }
                        ),
                    ),
                ),
            )