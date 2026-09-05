from __future__ import annotations

from types import MappingProxyType
from uuid import UUID, uuid4

import pytest

from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalFilters,
    RetrievalMethod,
    RetrievalQuery,
    RetrievalResult,
    RetrievalScores,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_candidate(
    *,
    chunk_id: UUID | None = None,
    version_id: UUID | None = None,
    document_id: UUID | None = None,
    chunk_index: int = 0,
    content: str = "Refunds are processed within 5-7 business days.",
    document_title: str = "Refund Policy",
    section_title: str | None = "Processing Time",
    methods: frozenset[RetrievalMethod] | None = None,
    scores: RetrievalScores | None = None,
    metadata: dict[str, object] | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id or uuid4(),
        version_id=version_id or uuid4(),
        document_id=document_id or uuid4(),
        chunk_index=chunk_index,
        content=content,
        document_title=document_title,
        section_title=section_title,
        methods=(
            frozenset({RetrievalMethod.VECTOR})
            if methods is None
            else methods
        ),
        scores=(
            RetrievalScores()
            if scores is None
            else scores
        ),
        metadata=(
            {}
            if metadata is None
            else metadata
        ),
    )


# ===========================================================================
# RetrievalMethod
# ===========================================================================


class TestRetrievalMethod:
    def test_values_are_stable_strings(self) -> None:
        assert RetrievalMethod.VECTOR.value == "vector"
        assert RetrievalMethod.LEXICAL.value == "lexical"
        assert RetrievalMethod.HYBRID.value == "hybrid"

    def test_members_are_string_compatible(self) -> None:
        assert isinstance(RetrievalMethod.VECTOR, str)


# ===========================================================================
# RetrievalFilters
# ===========================================================================


class TestRetrievalFilters:
    def test_default_filters_are_empty(self) -> None:
        filters = RetrievalFilters()

        assert filters.content_types == ()
        assert filters.visibilities == ()
        assert filters.document_ids == ()
        assert dict(filters.metadata) == {}

    def test_normalizes_string_filters(self) -> None:
        filters = RetrievalFilters(
            content_types=(" POLICY ", "FAQ"),
            visibilities=(" CUSTOMER ", "BOTH"),
        )

        assert filters.content_types == ("policy", "faq")
        assert filters.visibilities == ("customer", "both")

    def test_removes_duplicate_string_filters_preserving_order(self) -> None:
        filters = RetrievalFilters(
            content_types=("policy", "POLICY", "faq", "policy"),
        )

        assert filters.content_types == ("policy", "faq")

    def test_removes_duplicate_document_ids_preserving_order(self) -> None:
        first = uuid4()
        second = uuid4()

        filters = RetrievalFilters(
            document_ids=(first, second, first),
        )

        assert filters.document_ids == (first, second)

    def test_metadata_is_copied_and_made_read_only(self) -> None:
        source = {"region": "india"}

        filters = RetrievalFilters(metadata=source)

        source["region"] = "us"

        assert filters.metadata["region"] == "india"
        assert isinstance(filters.metadata, MappingProxyType)

        with pytest.raises(TypeError):
            filters.metadata["region"] = "uk"  # type: ignore[index]

    @pytest.mark.parametrize(
        "field_name",
        ["content_types", "visibilities"],
    )
    def test_string_filter_collection_must_be_tuple(
        self,
        field_name: str,
    ) -> None:
        kwargs = {
            field_name: ["policy"],  # intentionally invalid
        }

        with pytest.raises(
            TypeError,
            match=f"{field_name} must be a tuple",
        ):
            RetrievalFilters(**kwargs)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field_name",
        ["content_types", "visibilities"],
    )
    def test_string_filters_reject_non_string_values(
        self,
        field_name: str,
    ) -> None:
        kwargs = {
            field_name: ("policy", 123),
        }

        with pytest.raises(
            TypeError,
            match=f"{field_name} must contain only strings",
        ):
            RetrievalFilters(**kwargs)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field_name",
        ["content_types", "visibilities"],
    )
    def test_string_filters_reject_blank_values(
        self,
        field_name: str,
    ) -> None:
        kwargs = {
            field_name: ("policy", "   "),
        }

        with pytest.raises(
            ValueError,
            match=f"{field_name} cannot contain blank values",
        ):
            RetrievalFilters(**kwargs)  # type: ignore[arg-type]

    def test_document_ids_must_be_tuple(self) -> None:
        with pytest.raises(
            TypeError,
            match="document_ids must be a tuple",
        ):
            RetrievalFilters(
                document_ids=[uuid4()]  # type: ignore[arg-type]
            )

    def test_document_ids_must_contain_uuid_values(self) -> None:
        with pytest.raises(
            TypeError,
            match="document_ids must contain only UUID values",
        ):
            RetrievalFilters(
                document_ids=("not-a-uuid",)  # type: ignore[arg-type]
            )

    def test_metadata_must_be_mapping(self) -> None:
        with pytest.raises(
            TypeError,
            match="metadata must be a mapping",
        ):
            RetrievalFilters(
                metadata=["invalid"]  # type: ignore[arg-type]
            )

    def test_metadata_keys_must_be_strings(self) -> None:
        with pytest.raises(
            TypeError,
            match="metadata keys must be strings",
        ):
            RetrievalFilters(
                metadata={1: "value"}  # type: ignore[dict-item]
            )

    def test_metadata_rejects_blank_keys(self) -> None:
        with pytest.raises(
            ValueError,
            match="metadata keys cannot be blank",
        ):
            RetrievalFilters(
                metadata={"   ": "value"}
            )

    def test_metadata_rejects_duplicate_keys_after_normalization(self) -> None:
        with pytest.raises(
            ValueError,
            match="duplicate keys after normalization",
        ):
            RetrievalFilters(
                metadata={
                    "region": "india",
                    " region ": "us",
                }
            )


# ===========================================================================
# RetrievalQuery
# ===========================================================================


class TestRetrievalQuery:
    def test_normalizes_query_text(self) -> None:
        query = RetrievalQuery(
            text="   where is my refund?   "
        )

        assert query.text == "where is my refund?"

    def test_uses_empty_filters_by_default(self) -> None:
        query = RetrievalQuery(text="refund status")

        assert isinstance(query.filters, RetrievalFilters)
        assert query.filters == RetrievalFilters()

    def test_preserves_explicit_filters(self) -> None:
        filters = RetrievalFilters(
            content_types=("policy",)
        )

        query = RetrievalQuery(
            text="refund",
            filters=filters,
        )

        assert query.filters is filters

    def test_text_must_be_string(self) -> None:
        with pytest.raises(
            TypeError,
            match="text must be a string",
        ):
            RetrievalQuery(text=123)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "text",
        ["", " ", "\n\t"],
    )
    def test_rejects_blank_query_text(
        self,
        text: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="Retrieval query text cannot be blank",
        ):
            RetrievalQuery(text=text)

    def test_filters_must_be_retrieval_filters(self) -> None:
        with pytest.raises(
            TypeError,
            match="filters must be a RetrievalFilters instance",
        ):
            RetrievalQuery(
                text="refund",
                filters={},  # type: ignore[arg-type]
            )


# ===========================================================================
# RetrievalScores
# ===========================================================================


class TestRetrievalScores:
    def test_all_scores_default_to_none(self) -> None:
        scores = RetrievalScores()

        assert scores.vector_distance is None
        assert scores.vector_similarity is None
        assert scores.lexical_score is None
        assert scores.fusion_score is None
        assert scores.reranker_score is None

    def test_numeric_scores_are_normalized_to_float(self) -> None:
        scores = RetrievalScores(
            vector_distance=1,
            vector_similarity=0.8,
            lexical_score=2,
            fusion_score=0.3,
            reranker_score=5,
        )

        assert scores.vector_distance == 1.0
        assert scores.vector_similarity == 0.8
        assert scores.lexical_score == 2.0
        assert scores.fusion_score == 0.3
        assert scores.reranker_score == 5.0

        assert isinstance(scores.vector_distance, float)
        assert isinstance(scores.lexical_score, float)

    @pytest.mark.parametrize(
        "field_name",
        [
            "vector_distance",
            "vector_similarity",
            "lexical_score",
            "fusion_score",
            "reranker_score",
        ],
    )
    def test_scores_reject_boolean_values(
        self,
        field_name: str,
    ) -> None:
        with pytest.raises(
            TypeError,
            match=f"{field_name} must be a number or None",
        ):
            RetrievalScores(
                **{field_name: True}
            )

    @pytest.mark.parametrize(
        "field_name",
        [
            "vector_distance",
            "vector_similarity",
            "lexical_score",
            "fusion_score",
            "reranker_score",
        ],
    )
    def test_scores_reject_non_numeric_values(
        self,
        field_name: str,
    ) -> None:
        with pytest.raises(
            TypeError,
            match=f"{field_name} must be a number or None",
        ):
            RetrievalScores(
                **{field_name: "0.5"}
            )

    @pytest.mark.parametrize(
        "value",
        [
            float("nan"),
            float("inf"),
            float("-inf"),
        ],
    )
    @pytest.mark.parametrize(
        "field_name",
        [
            "vector_distance",
            "vector_similarity",
            "lexical_score",
            "fusion_score",
            "reranker_score",
        ],
    )
    def test_scores_must_be_finite(
        self,
        field_name: str,
        value: float,
    ) -> None:
        with pytest.raises(
            ValueError,
            match=f"{field_name} must be finite",
        ):
            RetrievalScores(
                **{field_name: value}
            )


# ===========================================================================
# RetrievalCandidate
# ===========================================================================


class TestRetrievalCandidate:
    def test_constructs_valid_candidate(self) -> None:
        candidate = make_candidate()

        assert isinstance(candidate.chunk_id, UUID)
        assert candidate.chunk_index == 0
        assert candidate.content
        assert candidate.document_title
        assert candidate.methods == frozenset(
            {RetrievalMethod.VECTOR}
        )

    def test_normalizes_content_title_and_section(self) -> None:
        candidate = make_candidate(
            content="   refund policy text   ",
            document_title="   Refund Policy   ",
            section_title="   Timing   ",
        )

        assert candidate.content == "refund policy text"
        assert candidate.document_title == "Refund Policy"
        assert candidate.section_title == "Timing"

    def test_blank_section_title_becomes_none(self) -> None:
        candidate = make_candidate(
            section_title="   "
        )

        assert candidate.section_title is None

    @pytest.mark.parametrize(
        "field_name",
        [
            "chunk_id",
            "version_id",
            "document_id",
        ],
    )
    def test_identifier_fields_must_be_uuid(
        self,
        field_name: str,
    ) -> None:
        kwargs = {
            field_name: "bad-id",
        }

        with pytest.raises(
            TypeError,
            match=f"{field_name} must be a UUID",
        ):
            make_candidate(
                **kwargs  # type: ignore[arg-type]
            )

    def test_chunk_index_must_be_integer(self) -> None:
        with pytest.raises(
            TypeError,
            match="chunk_index must be an integer",
        ):
            make_candidate(
                chunk_index=1.5  # type: ignore[arg-type]
            )

    def test_chunk_index_rejects_boolean(self) -> None:
        with pytest.raises(
            TypeError,
            match="chunk_index must be an integer",
        ):
            make_candidate(
                chunk_index=True  # type: ignore[arg-type]
            )

    def test_chunk_index_cannot_be_negative(self) -> None:
        with pytest.raises(
            ValueError,
            match="chunk_index cannot be negative",
        ):
            make_candidate(chunk_index=-1)

    def test_content_must_be_string(self) -> None:
        with pytest.raises(
            TypeError,
            match="content must be a string",
        ):
            make_candidate(
                content=123  # type: ignore[arg-type]
            )

    def test_content_cannot_be_blank(self) -> None:
        with pytest.raises(
            ValueError,
            match="candidate content cannot be blank",
        ):
            make_candidate(content="   ")

    def test_document_title_must_be_string(self) -> None:
        with pytest.raises(
            TypeError,
            match="document_title must be a string",
        ):
            make_candidate(
                document_title=123  # type: ignore[arg-type]
            )

    def test_document_title_cannot_be_blank(self) -> None:
        with pytest.raises(
            ValueError,
            match="document_title cannot be blank",
        ):
            make_candidate(
                document_title="   "
            )

    def test_section_title_must_be_string_or_none(self) -> None:
        with pytest.raises(
            TypeError,
            match="section_title must be a string or None",
        ):
            make_candidate(
                section_title=123  # type: ignore[arg-type]
            )

    def test_methods_must_be_frozenset(self) -> None:
        with pytest.raises(
            TypeError,
            match="methods must be a frozenset",
        ):
            make_candidate(
                methods={RetrievalMethod.VECTOR}  # type: ignore[arg-type]
            )

    def test_methods_cannot_be_empty(self) -> None:
        with pytest.raises(
            ValueError,
            match="candidate must have at least one retrieval method",
        ):
            make_candidate(
                methods=frozenset()
            )

    def test_methods_must_contain_retrieval_method_values(self) -> None:
        with pytest.raises(
            TypeError,
            match="methods must contain only RetrievalMethod values",
        ):
            make_candidate(
                methods=frozenset(
                    {"vector"}  # type: ignore[arg-type]
                )
            )

    def test_candidate_can_preserve_multiple_retrieval_methods(
        self,
    ) -> None:
        candidate = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                    RetrievalMethod.LEXICAL,
                }
            )
        )

        assert RetrievalMethod.VECTOR in candidate.methods
        assert RetrievalMethod.LEXICAL in candidate.methods

    def test_scores_must_be_retrieval_scores(self) -> None:
        with pytest.raises(
            TypeError,
            match="scores must be a RetrievalScores instance",
        ):
            make_candidate(
                scores={}  # type: ignore[arg-type]
            )

    def test_metadata_is_defensively_copied(self) -> None:
        metadata = {
            "language": "en",
        }

        candidate = make_candidate(
            metadata=metadata
        )

        metadata["language"] = "bn"

        assert candidate.metadata["language"] == "en"

    def test_metadata_is_read_only(self) -> None:
        candidate = make_candidate(
            metadata={"region": "india"}
        )

        assert isinstance(
            candidate.metadata,
            MappingProxyType,
        )

        with pytest.raises(TypeError):
            candidate.metadata["region"] = "us"  # type: ignore[index]

    def test_metadata_must_be_mapping(self) -> None:
        with pytest.raises(
            TypeError,
            match="metadata must be a mapping",
        ):
            make_candidate(
                metadata=["bad"]  # type: ignore[arg-type]
            )


# ===========================================================================
# RetrievalResult
# ===========================================================================


class TestRetrievalResult:
    def test_constructs_empty_result(self) -> None:
        query = RetrievalQuery(
            text="some unknown question"
        )

        result = RetrievalResult(
            query=query,
            candidates=(),
        )

        assert result.count == 0
        assert result.is_empty is True

    def test_constructs_non_empty_result(self) -> None:
        query = RetrievalQuery(
            text="refund policy"
        )

        first = make_candidate(
            chunk_index=0
        )

        second = make_candidate(
            chunk_index=1
        )

        result = RetrievalResult(
            query=query,
            candidates=(first, second),
        )

        assert result.count == 2
        assert result.is_empty is False
        assert result.candidates == (
            first,
            second,
        )

    def test_query_must_be_retrieval_query(self) -> None:
        with pytest.raises(
            TypeError,
            match="query must be a RetrievalQuery instance",
        ):
            RetrievalResult(
                query="refund",  # type: ignore[arg-type]
                candidates=(),
            )

    def test_candidates_must_be_tuple(self) -> None:
        query = RetrievalQuery(
            text="refund"
        )

        with pytest.raises(
            TypeError,
            match="candidates must be a tuple",
        ):
            RetrievalResult(
                query=query,
                candidates=[],  # type: ignore[arg-type]
            )

    def test_candidates_must_contain_candidate_objects(self) -> None:
        query = RetrievalQuery(
            text="refund"
        )

        with pytest.raises(
            TypeError,
            match="candidates must contain only RetrievalCandidate instances",
        ):
            RetrievalResult(
                query=query,
                candidates=("invalid",),  # type: ignore[arg-type]
            )

    def test_duplicate_chunk_ids_are_rejected(self) -> None:
        query = RetrievalQuery(
            text="refund"
        )

        shared_chunk_id = uuid4()

        first = make_candidate(
            chunk_id=shared_chunk_id,
            chunk_index=0,
        )

        second = make_candidate(
            chunk_id=shared_chunk_id,
            chunk_index=1,
        )

        with pytest.raises(
            ValueError,
            match="RetrievalResult cannot contain duplicate chunk_id",
        ):
            RetrievalResult(
                query=query,
                candidates=(first, second),
            )

    def test_different_chunks_from_same_document_are_allowed(self) -> None:
        query = RetrievalQuery(
            text="refund"
        )

        document_id = uuid4()
        version_id = uuid4()

        first = make_candidate(
            document_id=document_id,
            version_id=version_id,
            chunk_index=0,
        )

        second = make_candidate(
            document_id=document_id,
            version_id=version_id,
            chunk_index=1,
        )

        result = RetrievalResult(
            query=query,
            candidates=(first, second),
        )

        assert result.count == 2