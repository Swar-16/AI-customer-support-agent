from __future__ import annotations

from uuid import uuid4

import pytest

from packages.knowledge.retrieval.fusion.base import (
    FusionInput,
    FusionResult,
)
from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalMethod,
    RetrievalQuery,
    RetrievalScores,
)


def make_candidate(
    *,
    chunk_id=None,
    methods: frozenset[RetrievalMethod] | None = None,
    scores: RetrievalScores | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id or uuid4(),
        version_id=uuid4(),
        document_id=uuid4(),
        chunk_index=0,
        content="Sample knowledge content.",
        document_title="Sample Document",
        section_title="Sample Section",
        methods=(
            methods
            if methods is not None
            else frozenset({RetrievalMethod.VECTOR})
        ),
        scores=(
            scores
            if scores is not None
            else RetrievalScores()
        ),
        metadata={},
    )


class TestFusionInput:
    def test_accepts_multiple_rankings(self):
        vector_candidate = make_candidate(
            methods=frozenset({RetrievalMethod.VECTOR})
        )

        lexical_candidate = make_candidate(
            methods=frozenset({RetrievalMethod.LEXICAL})
        )

        query = RetrievalQuery(
            text="refund policy"
        )

        fusion_input = FusionInput(
            query=query,
            rankings=(
                (vector_candidate,),
                (lexical_candidate,),
            ),
        )

        assert fusion_input.query == query
        assert fusion_input.rankings == (
            (vector_candidate,),
            (lexical_candidate,),
        )
        assert fusion_input.ranking_count == 2
        assert fusion_input.is_empty is False

    def test_accepts_no_rankings(self):
        fusion_input = FusionInput(
            query=RetrievalQuery(
                text="refund policy"
            ),
            rankings=(),
        )

        assert fusion_input.ranking_count == 0
        assert fusion_input.is_empty is True

    def test_accepts_empty_rankings(self):
        fusion_input = FusionInput(
            query=RetrievalQuery(
                text="refund policy"
            ),
            rankings=(
                (),
                (),
            ),
        )

        assert fusion_input.ranking_count == 2
        assert fusion_input.is_empty is True

    def test_accepts_mix_of_empty_and_non_empty_rankings(self):
        candidate = make_candidate()

        fusion_input = FusionInput(
            query=RetrievalQuery(
                text="refund policy"
            ),
            rankings=(
                (),
                (candidate,),
                (),
            ),
        )

        assert fusion_input.ranking_count == 3
        assert fusion_input.is_empty is False

    def test_allows_same_chunk_across_different_rankings(self):
        chunk_id = uuid4()

        vector_candidate = make_candidate(
            chunk_id=chunk_id,
            methods=frozenset({RetrievalMethod.VECTOR}),
        )

        lexical_candidate = make_candidate(
            chunk_id=chunk_id,
            methods=frozenset({RetrievalMethod.LEXICAL}),
        )

        fusion_input = FusionInput(
            query=RetrievalQuery(
                text="refund policy"
            ),
            rankings=(
                (vector_candidate,),
                (lexical_candidate,),
            ),
        )

        assert fusion_input.rankings[0][0].chunk_id == chunk_id
        assert fusion_input.rankings[1][0].chunk_id == chunk_id

    def test_rejects_duplicate_chunk_within_same_ranking(self):
        chunk_id = uuid4()

        first = make_candidate(
            chunk_id=chunk_id
        )

        second = make_candidate(
            chunk_id=chunk_id
        )

        with pytest.raises(
            ValueError,
            match="ranking must not contain duplicate chunk IDs",
        ):
            FusionInput(
                query=RetrievalQuery(
                    text="refund policy"
                ),
                rankings=(
                    (
                        first,
                        second,
                    ),
                ),
            )

    def test_rejects_invalid_query_type(self):
        with pytest.raises(
            TypeError,
            match="query must be a RetrievalQuery instance",
        ):
            FusionInput(
                query="refund",  # type: ignore[arg-type]
                rankings=(),
            )

    def test_rejects_non_tuple_rankings(self):
        with pytest.raises(
            TypeError,
            match="rankings must be a tuple",
        ):
            FusionInput(
                query=RetrievalQuery(
                    text="refund policy"
                ),
                rankings=[],  # type: ignore[arg-type]
            )

    def test_rejects_non_tuple_inner_ranking(self):
        candidate = make_candidate()

        with pytest.raises(
            TypeError,
            match="each ranking must be a tuple",
        ):
            FusionInput(
                query=RetrievalQuery(
                    text="refund policy"
                ),
                rankings=(
                    [candidate],  # type: ignore[list-item]
                ),
            )

    def test_rejects_non_candidate_item(self):
        with pytest.raises(
            TypeError,
            match="rankings must contain RetrievalCandidate instances",
        ):
            FusionInput(
                query=RetrievalQuery(
                    text="refund policy"
                ),
                rankings=(
                    ("invalid",),  # type: ignore[arg-type]
                ),
            )


class TestFusionResult:
    def test_accepts_ranked_candidates(self):
        first = make_candidate()
        second = make_candidate()

        query = RetrievalQuery(
            text="refund policy"
        )

        result = FusionResult(
            query=query,
            candidates=(
                first,
                second,
            ),
        )

        assert result.query == query
        assert result.candidates == (
            first,
            second,
        )
        assert result.count == 2
        assert result.is_empty is False

    def test_accepts_empty_result(self):
        result = FusionResult(
            query=RetrievalQuery(
                text="refund policy"
            ),
            candidates=(),
        )

        assert result.count == 0
        assert result.is_empty is True

    def test_rejects_duplicate_chunk_ids(self):
        chunk_id = uuid4()

        first = make_candidate(
            chunk_id=chunk_id
        )

        second = make_candidate(
            chunk_id=chunk_id
        )

        with pytest.raises(
            ValueError,
            match="fusion result must not contain duplicate chunk IDs",
        ):
            FusionResult(
                query=RetrievalQuery(
                    text="refund policy"
                ),
                candidates=(
                    first,
                    second,
                ),
            )

    def test_rejects_invalid_query_type(self):
        with pytest.raises(
            TypeError,
            match="query must be a RetrievalQuery instance",
        ):
            FusionResult(
                query="refund",  # type: ignore[arg-type]
                candidates=(),
            )

    def test_rejects_non_tuple_candidates(self):
        candidate = make_candidate()

        with pytest.raises(
            TypeError,
            match="candidates must be a tuple",
        ):
            FusionResult(
                query=RetrievalQuery(
                    text="refund policy"
                ),
                candidates=[candidate],  # type: ignore[arg-type]
            )

    def test_rejects_non_candidate_item(self):
        with pytest.raises(
            TypeError,
            match="candidates must contain RetrievalCandidate instances",
        ):
            FusionResult(
                query=RetrievalQuery(
                    text="refund policy"
                ),
                candidates=("invalid",),  # type: ignore[arg-type]
            )