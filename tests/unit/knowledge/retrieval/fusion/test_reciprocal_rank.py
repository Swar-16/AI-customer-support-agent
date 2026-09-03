from __future__ import annotations

from math import isclose
from uuid import UUID, uuid4

import pytest

from packages.knowledge.retrieval.errors import (
    FusionInputError,
)
from packages.knowledge.retrieval.fusion.base import (
    FusionInput,
    FusionResult,
)
from packages.knowledge.retrieval.fusion.reciprocal_rank import (
    ReciprocalRankFusion,
)
from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalMethod,
    RetrievalQuery,
    RetrievalScores,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def make_candidate(
    *,
    chunk_id: UUID | None = None,
    version_id: UUID | None = None,
    document_id: UUID | None = None,
    chunk_index: int = 0,
    content: str = "Refunds are available within thirty days.",
    document_title: str = "Refund Policy",
    section_title: str = "Eligibility",
    methods: frozenset[RetrievalMethod] | None = None,
    scores: RetrievalScores | None = None,
    metadata: dict | None = None,
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
            methods
            if methods is not None
            else frozenset({RetrievalMethod.VECTOR})
        ),
        scores=(
            scores
            if scores is not None
            else RetrievalScores()
        ),
        metadata=(
            metadata
            if metadata is not None
            else {
                "section_path": [
                    "Refund Policy",
                    "Eligibility",
                ]
            }
        ),
    )


def clone_candidate(
    candidate: RetrievalCandidate,
    *,
    methods: frozenset[RetrievalMethod] | None = None,
    scores: RetrievalScores | None = None,
    content: str | None = None,
    document_title: str | None = None,
    section_title: str | None = None,
    metadata: dict | None = None,
    version_id: UUID | None = None,
    document_id: UUID | None = None,
    chunk_index: int | None = None,
) -> RetrievalCandidate:
    """
    Create another representation of the same logical chunk.

    Useful for simulating the same chunk being returned independently by
    vector and lexical retrieval.
    """

    return RetrievalCandidate(
        chunk_id=candidate.chunk_id,
        version_id=(
            version_id
            if version_id is not None
            else candidate.version_id
        ),
        document_id=(
            document_id
            if document_id is not None
            else candidate.document_id
        ),
        chunk_index=(
            chunk_index
            if chunk_index is not None
            else candidate.chunk_index
        ),
        content=(
            content
            if content is not None
            else candidate.content
        ),
        document_title=(
            document_title
            if document_title is not None
            else candidate.document_title
        ),
        section_title=(
            section_title
            if section_title is not None
            else candidate.section_title
        ),
        methods=(
            methods
            if methods is not None
            else candidate.methods
        ),
        scores=(
            scores
            if scores is not None
            else candidate.scores
        ),
        metadata=(
            metadata
            if metadata is not None
            else dict(candidate.metadata)
        ),
    )


def make_input(
    *rankings: tuple[RetrievalCandidate, ...],
) -> FusionInput:
    return FusionInput(
        query=RetrievalQuery(
            text="What is the refund policy?"
        ),
        rankings=rankings,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestReciprocalRankFusionConstruction:
    def test_uses_default_k(self):
        fusion = ReciprocalRankFusion()

        assert fusion.k == 60

    def test_accepts_custom_k(self):
        fusion = ReciprocalRankFusion(
            k=25
        )

        assert fusion.k == 25

    def test_exposes_stable_strategy_id(self):
        fusion = ReciprocalRankFusion()

        assert (
            fusion.strategy_id
            == "reciprocal_rank_fusion"
        )

    @pytest.mark.parametrize(
        "k",
        [
            0,
            -1,
            -100,
        ],
    )
    def test_rejects_non_positive_k(
        self,
        k,
    ):
        with pytest.raises(
            ValueError,
            match="k must be greater than zero",
        ):
            ReciprocalRankFusion(
                k=k
            )

    @pytest.mark.parametrize(
        "k",
        [
            True,
            False,
            1.0,
            60.0,
            "60",
            None,
        ],
    )
    def test_rejects_non_integer_k(
        self,
        k,
    ):
        with pytest.raises(
            TypeError,
            match="k must be an integer",
        ):
            ReciprocalRankFusion(
                k=k  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Basic RRF behavior
# ---------------------------------------------------------------------------


class TestReciprocalRankFusionScoring:
    def test_single_candidate_receives_expected_rrf_score(
        self,
    ):
        candidate = make_candidate()

        fusion = ReciprocalRankFusion(
            k=60
        )

        result = fusion.fuse(
            fusion_input=make_input(
                (candidate,)
            ),
            limit=10,
        )

        assert result.count == 1

        expected = 1.0 / 61.0

        assert isclose(
            result.candidates[0].scores.fusion_score,
            expected,
        )

    def test_rank_is_one_based(
        self,
    ):
        first = make_candidate()
        second = make_candidate()

        fusion = ReciprocalRankFusion(
            k=60
        )

        result = fusion.fuse(
            fusion_input=make_input(
                (
                    first,
                    second,
                )
            ),
            limit=10,
        )

        scores = {
            candidate.chunk_id:
                candidate.scores.fusion_score
            for candidate in result.candidates
        }

        assert isclose(
            scores[first.chunk_id],
            1.0 / 61.0,
        )

        assert isclose(
            scores[second.chunk_id],
            1.0 / 62.0,
        )

    def test_candidate_appearing_in_multiple_rankings_accumulates_score(
        self,
    ):
        vector_candidate = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                }
            ),
            scores=RetrievalScores(
                vector_distance=0.1,
                vector_similarity=0.9,
            ),
        )

        lexical_candidate = clone_candidate(
            vector_candidate,
            methods=frozenset(
                {
                    RetrievalMethod.LEXICAL,
                }
            ),
            scores=RetrievalScores(
                lexical_score=0.75,
            ),
        )

        fusion = ReciprocalRankFusion(
            k=60
        )

        result = fusion.fuse(
            fusion_input=make_input(
                (vector_candidate,),
                (lexical_candidate,),
            ),
            limit=10,
        )

        fused = result.candidates[0]

        expected = (
            1.0 / 61.0
            + 1.0 / 61.0
        )

        assert isclose(
            fused.scores.fusion_score,
            expected,
        )

    def test_candidate_supported_by_two_rankings_can_outrank_single_source_candidate(
        self,
    ):
        shared_vector = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                }
            )
        )

        shared_lexical = clone_candidate(
            shared_vector,
            methods=frozenset(
                {
                    RetrievalMethod.LEXICAL,
                }
            ),
        )

        vector_only = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                }
            )
        )

        lexical_only = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.LEXICAL,
                }
            )
        )

        fusion = ReciprocalRankFusion(
            k=60
        )

        result = fusion.fuse(
            fusion_input=make_input(
                (
                    vector_only,
                    shared_vector,
                ),
                (
                    lexical_only,
                    shared_lexical,
                ),
            ),
            limit=10,
        )

        assert (
            result.candidates[0].chunk_id
            == shared_vector.chunk_id
        )

    def test_raw_vector_and_lexical_scores_do_not_affect_rrf_formula(
        self,
    ):
        first = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                }
            ),
            scores=RetrievalScores(
                vector_distance=0.99,
                vector_similarity=0.01,
            ),
        )

        second = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                }
            ),
            scores=RetrievalScores(
                vector_distance=0.01,
                vector_similarity=0.99,
            ),
        )

        fusion = ReciprocalRankFusion(
            k=60
        )

        result = fusion.fuse(
            fusion_input=make_input(
                (
                    first,
                    second,
                ),
            ),
            limit=10,
        )

        # RRF respects the ranking supplied to it.
        # It does not inspect the raw vector score.
        assert (
            result.candidates[0].chunk_id
            == first.chunk_id
        )

        assert isclose(
            result.candidates[0].scores.fusion_score,
            1.0 / 61.0,
        )

        assert isclose(
            result.candidates[1].scores.fusion_score,
            1.0 / 62.0,
        )


# ---------------------------------------------------------------------------
# Score/provenance merging
# ---------------------------------------------------------------------------


class TestReciprocalRankFusionMerging:
    def test_merges_vector_and_lexical_methods(
        self,
    ):
        vector_candidate = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                }
            )
        )

        lexical_candidate = clone_candidate(
            vector_candidate,
            methods=frozenset(
                {
                    RetrievalMethod.LEXICAL,
                }
            ),
        )

        result = ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                (vector_candidate,),
                (lexical_candidate,),
            ),
            limit=10,
        )

        assert result.candidates[0].methods == frozenset(
            {
                RetrievalMethod.VECTOR,
                RetrievalMethod.LEXICAL,
            }
        )

    def test_preserves_vector_and_lexical_scores(
        self,
    ):
        vector_candidate = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                }
            ),
            scores=RetrievalScores(
                vector_distance=0.12,
                vector_similarity=0.88,
            ),
        )

        lexical_candidate = clone_candidate(
            vector_candidate,
            methods=frozenset(
                {
                    RetrievalMethod.LEXICAL,
                }
            ),
            scores=RetrievalScores(
                lexical_score=0.54,
            ),
        )

        result = ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                (vector_candidate,),
                (lexical_candidate,),
            ),
            limit=10,
        )

        scores = result.candidates[0].scores

        assert scores.vector_distance == 0.12
        assert scores.vector_similarity == 0.88
        assert scores.lexical_score == 0.54
        assert scores.fusion_score is not None

    def test_preserves_reranker_score_if_already_present(
        self,
    ):
        first = make_candidate(
            scores=RetrievalScores(
                vector_similarity=0.8,
                reranker_score=0.91,
            ),
        )

        second = clone_candidate(
            first,
            methods=frozenset(
                {
                    RetrievalMethod.LEXICAL,
                }
            ),
            scores=RetrievalScores(
                lexical_score=0.7,
                reranker_score=0.91,
            ),
        )

        result = ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                (first,),
                (second,),
            ),
            limit=10,
        )

        assert (
            result.candidates[0]
            .scores
            .reranker_score
            == 0.91
        )

    def test_stale_incoming_fusion_score_is_recomputed(
        self,
    ):
        candidate = make_candidate(
            scores=RetrievalScores(
                vector_similarity=0.9,
                fusion_score=999.0,
            )
        )

        result = ReciprocalRankFusion(
            k=60
        ).fuse(
            fusion_input=make_input(
                (candidate,),
            ),
            limit=10,
        )

        assert isclose(
            result.candidates[0].scores.fusion_score,
            1.0 / 61.0,
        )

    @pytest.mark.parametrize(
        (
            "vector_scores",
            "lexical_scores",
            "field_name",
        ),
        [
            (
                RetrievalScores(
                    vector_distance=0.1
                ),
                RetrievalScores(
                    vector_distance=0.2
                ),
                "vector_distance",
            ),
            (
                RetrievalScores(
                    vector_similarity=0.9
                ),
                RetrievalScores(
                    vector_similarity=0.8
                ),
                "vector_similarity",
            ),
            (
                RetrievalScores(
                    lexical_score=0.3
                ),
                RetrievalScores(
                    lexical_score=0.7
                ),
                "lexical_score",
            ),
            (
                RetrievalScores(
                    reranker_score=0.6
                ),
                RetrievalScores(
                    reranker_score=0.8
                ),
                "reranker_score",
            ),
        ],
    )
    def test_rejects_conflicting_source_specific_scores(
        self,
        vector_scores,
        lexical_scores,
        field_name,
    ):
        first = make_candidate(
            scores=vector_scores
        )

        second = clone_candidate(
            first,
            methods=frozenset(
                {
                    RetrievalMethod.LEXICAL,
                }
            ),
            scores=lexical_scores,
        )

        with pytest.raises(
            FusionInputError,
            match=f"Conflicting {field_name}",
        ):
            ReciprocalRankFusion().fuse(
                fusion_input=make_input(
                    (first,),
                    (second,),
                ),
                limit=10,
            )


# ---------------------------------------------------------------------------
# Provenance integrity
# ---------------------------------------------------------------------------


class TestReciprocalRankFusionProvenance:
    @pytest.mark.parametrize(
        (
            "field_name",
            "changes",
        ),
        [
            (
                "version_id",
                {
                    "version_id": uuid4(),
                },
            ),
            (
                "document_id",
                {
                    "document_id": uuid4(),
                },
            ),
            (
                "chunk_index",
                {
                    "chunk_index": 999,
                },
            ),
            (
                "content",
                {
                    "content":
                        "Conflicting knowledge content.",
                },
            ),
            (
                "document_title",
                {
                    "document_title":
                        "Different Document",
                },
            ),
            (
                "section_title",
                {
                    "section_title":
                        "Different Section",
                },
            ),
        ],
    )
    def test_rejects_conflicting_candidate_provenance(
        self,
        field_name,
        changes,
    ):
        canonical = make_candidate()

        incoming = clone_candidate(
            canonical,
            **changes,
        )

        with pytest.raises(
            FusionInputError,
            match=field_name,
        ):
            ReciprocalRankFusion().fuse(
                fusion_input=make_input(
                    (canonical,),
                    (incoming,),
                ),
                limit=10,
            )

    def test_rejects_conflicting_metadata(
        self,
    ):
        canonical = make_candidate(
            metadata={
                "language": "en",
                "region": "IN",
            }
        )

        incoming = clone_candidate(
            canonical,
            metadata={
                "language": "en",
                "region": "US",
            },
        )

        with pytest.raises(
            FusionInputError,
            match="metadata differs",
        ):
            ReciprocalRankFusion().fuse(
                fusion_input=make_input(
                    (canonical,),
                    (incoming,),
                ),
                limit=10,
            )

    def test_preserves_canonical_candidate_identity_and_content(
        self,
    ):
        candidate = make_candidate(
            chunk_index=7,
            content="Canonical content.",
            document_title="Canonical Document",
            section_title="Canonical Section",
            metadata={
                "language": "en",
                "region": "IN",
            },
        )

        result = ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                (candidate,),
            ),
            limit=10,
        )

        fused = result.candidates[0]

        assert fused.chunk_id == candidate.chunk_id
        assert fused.version_id == candidate.version_id
        assert fused.document_id == candidate.document_id
        assert fused.chunk_index == 7
        assert fused.content == "Canonical content."
        assert (
            fused.document_title
            == "Canonical Document"
        )
        assert (
            fused.section_title
            == "Canonical Section"
        )
        assert dict(fused.metadata) == {
            "language": "en",
            "region": "IN",
        }


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


class TestReciprocalRankFusionOrdering:
    def test_orders_by_fusion_score_descending(
        self,
    ):
        shared = make_candidate()

        shared_from_second_ranking = clone_candidate(
            shared,
            methods=frozenset(
                {
                    RetrievalMethod.LEXICAL,
                }
            ),
        )

        single = make_candidate()

        result = ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                (
                    single,
                    shared,
                ),
                (
                    shared_from_second_ranking,
                ),
            ),
            limit=10,
        )

        assert (
            result.candidates[0].chunk_id
            == shared.chunk_id
        )

        assert (
            result.candidates[0].scores.fusion_score
            >
            result.candidates[1].scores.fusion_score
        )

    def test_best_rank_breaks_equal_fusion_score_tie(
        self,
    ):
        """
        A:
            rank 1 in one ranking

        B:
            rank 1 in another ranking

        Equal fusion scores and equal best ranks therefore fall through
        to deterministic UUID ordering.

        This primarily documents that equal scores remain deterministic.
        """

        low_id = UUID(
            "00000000-0000-0000-0000-000000000001"
        )
        high_id = UUID(
            "00000000-0000-0000-0000-000000000002"
        )

        low = make_candidate(
            chunk_id=low_id
        )
        high = make_candidate(
            chunk_id=high_id
        )

        result = ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                (high,),
                (low,),
            ),
            limit=10,
        )

        assert [
            item.chunk_id
            for item in result.candidates
        ] == [
            low_id,
            high_id,
        ]

    def test_uuid_provides_stable_final_tie_breaker(
        self,
    ):
        first_id = UUID(
            "00000000-0000-0000-0000-000000000001"
        )

        second_id = UUID(
            "00000000-0000-0000-0000-000000000002"
        )

        first = make_candidate(
            chunk_id=first_id
        )

        second = make_candidate(
            chunk_id=second_id
        )

        result = ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                (second,),
                (first,),
            ),
            limit=10,
        )

        assert [
            candidate.chunk_id
            for candidate in result.candidates
        ] == [
            first_id,
            second_id,
        ]

    def test_output_order_is_reproducible(
        self,
    ):
        ids = [
            UUID(
                "00000000-0000-0000-0000-000000000003"
            ),
            UUID(
                "00000000-0000-0000-0000-000000000001"
            ),
            UUID(
                "00000000-0000-0000-0000-000000000002"
            ),
        ]

        candidates = [
            make_candidate(
                chunk_id=chunk_id
            )
            for chunk_id in ids
        ]

        fusion = ReciprocalRankFusion()

        first_result = fusion.fuse(
            fusion_input=make_input(
                (candidates[0],),
                (candidates[1],),
                (candidates[2],),
            ),
            limit=10,
        )

        second_result = fusion.fuse(
            fusion_input=make_input(
                (candidates[0],),
                (candidates[1],),
                (candidates[2],),
            ),
            limit=10,
        )

        assert [
            candidate.chunk_id
            for candidate in first_result.candidates
        ] == [
            candidate.chunk_id
            for candidate in second_result.candidates
        ]


# ---------------------------------------------------------------------------
# Limits and empty states
# ---------------------------------------------------------------------------


class TestReciprocalRankFusionResultHandling:
    def test_returns_empty_result_for_no_rankings(
        self,
    ):
        fusion_input = make_input()

        result = ReciprocalRankFusion().fuse(
            fusion_input=fusion_input,
            limit=10,
        )

        assert isinstance(
            result,
            FusionResult,
        )
        assert result.query == fusion_input.query
        assert result.candidates == ()
        assert result.is_empty is True

    def test_returns_empty_result_for_only_empty_rankings(
        self,
    ):
        fusion_input = make_input(
            (),
            (),
        )

        result = ReciprocalRankFusion().fuse(
            fusion_input=fusion_input,
            limit=10,
        )

        assert result.candidates == ()
        assert result.is_empty is True

    def test_handles_one_empty_and_one_non_empty_ranking(
        self,
    ):
        candidate = make_candidate()

        result = ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                (),
                (candidate,),
            ),
            limit=10,
        )

        assert result.count == 1
        assert (
            result.candidates[0].chunk_id
            == candidate.chunk_id
        )

    def test_enforces_result_limit(
        self,
    ):
        candidates = tuple(
            make_candidate()
            for _ in range(5)
        )

        result = ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                candidates,
            ),
            limit=3,
        )

        assert result.count == 3

    def test_limit_larger_than_available_candidates_is_allowed(
        self,
    ):
        candidates = (
            make_candidate(),
            make_candidate(),
        )

        result = ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                candidates,
            ),
            limit=100,
        )

        assert result.count == 2

    @pytest.mark.parametrize(
        "limit",
        [
            0,
            -1,
            -100,
        ],
    )
    def test_rejects_non_positive_limit(
        self,
        limit,
    ):
        with pytest.raises(
            ValueError,
            match="limit must be greater than zero",
        ):
            ReciprocalRankFusion().fuse(
                fusion_input=make_input(),
                limit=limit,
            )

    @pytest.mark.parametrize(
        "limit",
        [
            True,
            False,
            1.0,
            "10",
            None,
        ],
    )
    def test_rejects_non_integer_limit(
        self,
        limit,
    ):
        with pytest.raises(
            TypeError,
            match="limit must be an integer",
        ):
            ReciprocalRankFusion().fuse(
                fusion_input=make_input(),
                limit=limit,  # type: ignore[arg-type]
            )

    def test_rejects_invalid_fusion_input_type(
        self,
    ):
        with pytest.raises(
            TypeError,
            match="fusion_input must be a FusionInput instance",
        ):
            ReciprocalRankFusion().fuse(
                fusion_input="invalid",  # type: ignore[arg-type]
                limit=10,
            )


# ---------------------------------------------------------------------------
# Immutability / side-effect safety
# ---------------------------------------------------------------------------


class TestReciprocalRankFusionImmutability:
    def test_does_not_mutate_original_candidate_scores(
        self,
    ):
        original_scores = RetrievalScores(
            vector_distance=0.2,
            vector_similarity=0.8,
        )

        candidate = make_candidate(
            scores=original_scores
        )

        ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                (candidate,),
            ),
            limit=10,
        )

        assert (
            candidate.scores
            == original_scores
        )

        assert (
            candidate.scores.fusion_score
            is None
        )

    def test_does_not_mutate_original_methods(
        self,
    ):
        vector_candidate = make_candidate(
            methods=frozenset(
                {
                    RetrievalMethod.VECTOR,
                }
            )
        )

        lexical_candidate = clone_candidate(
            vector_candidate,
            methods=frozenset(
                {
                    RetrievalMethod.LEXICAL,
                }
            ),
        )

        ReciprocalRankFusion().fuse(
            fusion_input=make_input(
                (vector_candidate,),
                (lexical_candidate,),
            ),
            limit=10,
        )

        assert vector_candidate.methods == frozenset(
            {
                RetrievalMethod.VECTOR,
            }
        )

        assert lexical_candidate.methods == frozenset(
            {
                RetrievalMethod.LEXICAL,
            }
        )

    def test_does_not_mutate_input_rankings(
        self,
    ):
        first = make_candidate()
        second = make_candidate()

        ranking = (
            first,
            second,
        )

        fusion_input = make_input(
            ranking
        )

        original_rankings = fusion_input.rankings

        ReciprocalRankFusion().fuse(
            fusion_input=fusion_input,
            limit=10,
        )

        assert (
            fusion_input.rankings
            == original_rankings
        )