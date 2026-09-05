from __future__ import annotations

from uuid import uuid4

import pytest

from evaluation.retrieval.models import (
    RetrievalEvaluationCase,
)
from evaluation.retrieval.relevance import (
    DeterministicRelevanceMatcherConfig,
    DeterministicRetrievalRelevanceMatcher,
    RetrievalRelevanceConfigurationError,
    RetrievalRelevanceContractError,
)
from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalMethod,
    RetrievalScores,
)


def make_candidate(
    *,
    document_title: str = "Refund Policy",
    section_title: str | None = "Processing Time",
    content: str = "Refunds may take several business days.",
    metadata: dict[str, object] | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        chunk_index=0,
        content=content,
        document_title=document_title,
        section_title=section_title,
        methods=frozenset(
            {
                RetrievalMethod.VECTOR,
            }
        ),
        scores=RetrievalScores(
            vector_similarity=0.90,
        ),
        metadata=metadata or {},
    )


class TestDocumentRelevance:
    def test_matches_expected_document(self) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_001",
            query="How long does a refund take?",
            expected_document_titles=(
                "Refund Policy",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(),
        )

        assert result == frozenset(
            {
                "document:refund policy",
            }
        )

    def test_document_matching_is_case_insensitive(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_001",
            query="Refund timing",
            expected_document_titles=(
                "REFUND POLICY",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                document_title=" refund   policy ",
            ),
        )

        assert result == frozenset(
            {
                "document:refund policy",
            }
        )

    def test_does_not_fuzzy_match_document_title(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_001",
            query="Refund timing",
            expected_document_titles=(
                "Refund Policy",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                document_title=(
                    "Refund Policy for European Customers"
                ),
            ),
        )

        assert result == frozenset()


class TestSectionRelevance:
    def test_matches_expected_section(self) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_section_001",
            query="How long does refund processing take?",
            expected_section_titles=(
                "Processing Time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(),
        )

        assert result == frozenset(
            {
                "section:processing time",
            }
        )

    def test_section_matching_normalizes_case_and_spacing(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_section_001",
            query="Refund timing",
            expected_section_titles=(
                "PROCESSING TIME",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                section_title=" processing    time ",
            ),
        )

        assert result == frozenset(
            {
                "section:processing time",
            }
        )

    def test_missing_section_does_not_match(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_section_001",
            query="Refund timing",
            expected_section_titles=(
                "Processing Time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                section_title=None,
            ),
        )

        assert result == frozenset()


class TestTopicRelevance:
    def test_matches_topic_from_list_metadata(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_topic_001",
            query="Why is my refund delayed?",
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                metadata={
                    "topics": [
                        "refund eligibility",
                        "Refund Processing Time",
                    ],
                }
            ),
        )

        assert result == frozenset(
            {
                "topic:refund processing time",
            }
        )

    def test_matches_topic_from_comma_separated_metadata(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_topic_001",
            query="Refund timing",
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                metadata={
                    "tags": (
                        "refund eligibility, "
                        "refund processing time"
                    ),
                }
            ),
        )

        assert result == frozenset(
            {
                "topic:refund processing time",
            }
        )

    def test_matches_topic_from_semicolon_separated_metadata(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_topic_001",
            query="Refund timing",
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                metadata={
                    "keywords": (
                        "refund eligibility;"
                        "refund processing time"
                    ),
                }
            ),
        )

        assert result == frozenset(
            {
                "topic:refund processing time",
            }
        )

    def test_does_not_infer_topic_from_chunk_content(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_topic_001",
            query="Refund timing",
            expected_topics=(
                "refund processing time",
            ),
        )

        candidate = make_candidate(
            content=(
                "This chunk repeatedly discusses "
                "refund processing time."
            ),
            metadata={},
        )

        result = matcher.match(
            case=case,
            candidate=candidate,
        )

        assert result == frozenset()

    def test_does_not_fuzzy_match_topic(self) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_topic_001",
            query="Refund timing",
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                metadata={
                    "topics": [
                        "refund processing",
                    ],
                }
            ),
        )

        assert result == frozenset()

    def test_ignores_untrusted_metadata_keys(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_topic_001",
            query="Refund timing",
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                metadata={
                    "description": (
                        "refund processing time"
                    ),
                }
            ),
        )

        assert result == frozenset()


class TestCombinedRelevance:
    def test_candidate_can_match_multiple_target_types(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_combined_001",
            query="How long does a refund take?",
            expected_document_titles=(
                "Refund Policy",
            ),
            expected_section_titles=(
                "Processing Time",
            ),
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                metadata={
                    "topics": [
                        "refund processing time",
                    ],
                }
            ),
        )

        assert result == frozenset(
            {
                "document:refund policy",
                "section:processing time",
                "topic:refund processing time",
            }
        )

    def test_candidate_matches_only_targets_it_satisfies(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="mixed_001",
            query="Refund timing",
            expected_document_titles=(
                "Refund Policy",
            ),
            expected_section_titles=(
                "Eligibility",
            ),
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                document_title="Refund Policy",
                section_title="Processing Time",
                metadata={},
            ),
        )

        assert result == frozenset(
            {
                "document:refund policy",
            }
        )


class TestMetadataRobustness:
    def test_ignores_non_string_items_in_topic_collection(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="topic_001",
            query="Refund timing",
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                metadata={
                    "topics": [
                        123,
                        None,
                        "refund processing time",
                        {"unexpected": "value"},
                    ],
                }
            ),
        )

        assert result == frozenset(
            {
                "topic:refund processing time",
            }
        )

    def test_ignores_nested_mapping_topic_value(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="topic_001",
            query="Refund timing",
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                metadata={
                    "topics": {
                        "name": (
                            "refund processing time"
                        )
                    }
                }
            ),
        )

        assert result == frozenset()

    def test_empty_topic_metadata_is_safe(self) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="topic_001",
            query="Refund timing",
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                metadata={
                    "topics": [],
                    "tags": "",
                }
            ),
        )

        assert result == frozenset()


class TestConfiguration:
    def test_supports_custom_topic_metadata_keys(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher(
                config=(
                    DeterministicRelevanceMatcherConfig(
                        topic_metadata_keys=(
                            "retrieval_topics",
                        ),
                    )
                )
            )
        )

        case = RetrievalEvaluationCase(
            case_id="topic_001",
            query="Refund timing",
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                metadata={
                    "retrieval_topics": [
                        "refund processing time",
                    ],
                    "topics": [
                        "something else",
                    ],
                }
            ),
        )

        assert result == frozenset(
            {
                "topic:refund processing time",
            }
        )

    def test_can_disable_string_splitting(
        self,
    ) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher(
                config=(
                    DeterministicRelevanceMatcherConfig(
                        split_string_topic_values=False,
                    )
                )
            )
        )

        case = RetrievalEvaluationCase(
            case_id="topic_001",
            query="Refund timing",
            expected_topics=(
                "refund processing time",
            ),
        )

        result = matcher.match(
            case=case,
            candidate=make_candidate(
                metadata={
                    "topics": (
                        "refund eligibility, "
                        "refund processing time"
                    )
                }
            ),
        )

        assert result == frozenset()

    def test_rejects_empty_topic_metadata_keys(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalRelevanceConfigurationError,
            match=(
                "topic_metadata_keys must contain "
                "at least one key"
            ),
        ):
            DeterministicRelevanceMatcherConfig(
                topic_metadata_keys=(),
            )

    def test_rejects_invalid_config_dependency(
        self,
    ) -> None:
        with pytest.raises(
            RetrievalRelevanceConfigurationError,
            match=(
                "config must be a "
                "DeterministicRelevanceMatcherConfig "
                "instance"
            ),
        ):
            DeterministicRetrievalRelevanceMatcher(
                config=object(),  # type: ignore[arg-type]
            )


class TestContractValidation:
    def test_rejects_invalid_case(self) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        with pytest.raises(
            RetrievalRelevanceContractError,
            match=(
                "case must be a "
                "RetrievalEvaluationCase instance"
            ),
        ):
            matcher.match(
                case=object(),  # type: ignore[arg-type]
                candidate=make_candidate(),
            )

    def test_rejects_invalid_candidate(self) -> None:
        matcher = (
            DeterministicRetrievalRelevanceMatcher()
        )

        case = RetrievalEvaluationCase(
            case_id="refund_001",
            query="Refund timing",
            expected_document_titles=(
                "Refund Policy",
            ),
        )

        with pytest.raises(
            RetrievalRelevanceContractError,
            match=(
                "candidate must be a "
                "RetrievalCandidate instance"
            ),
        ):
            matcher.match(
                case=case,
                candidate=object(),  # type: ignore[arg-type]
            )