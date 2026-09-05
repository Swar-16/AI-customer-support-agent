from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from packages.knowledge.retrieval.context.builder import (
    CharacterTokenEstimator,
    GroundingContextBuilder,
    TokenEstimator,
)
from packages.knowledge.retrieval.context.models import (
    GroundingContextBudget,
)
from packages.knowledge.retrieval.errors import (
    GroundingContextBudgetError,
)
from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalMethod,
    RetrievalQuery,
    RetrievalResult,
    RetrievalScores,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_query(
    text: str = "What is the refund policy?",
) -> RetrievalQuery:
    return RetrievalQuery(
        text=text,
    )


def make_candidate(
    *,
    chunk_id: UUID | None = None,
    version_id: UUID | None = None,
    document_id: UUID | None = None,
    chunk_index: int = 0,
    content: str = "Refunds are available within thirty days.",
    document_title: str = "Refund Policy",
    section_title: str | None = "Eligibility",
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
            else frozenset(
                {
                    RetrievalMethod.VECTOR,
                    RetrievalMethod.LEXICAL,
                }
            )
        ),
        scores=(
            scores
            if scores is not None
            else RetrievalScores(
                vector_distance=0.10,
                vector_similarity=0.90,
                lexical_score=0.75,
                fusion_score=0.032,
            )
        ),
        metadata=(
            metadata
            if metadata is not None
            else {
                "language": "en",
                "section_path": [
                    "Refund Policy",
                    "Eligibility",
                ],
            }
        ),
    )


def make_result(
    *candidates: RetrievalCandidate,
    query: RetrievalQuery | None = None,
) -> RetrievalResult:
    return RetrievalResult(
        query=query or make_query(),
        candidates=tuple(candidates),
    )


def make_budget(
    *,
    max_tokens: int = 1_000,
    max_blocks: int = 10,
) -> GroundingContextBudget:
    return GroundingContextBudget(
        max_tokens=max_tokens,
        max_blocks=max_blocks,
    )


class FixedTokenEstimator(TokenEstimator):
    """
    Test estimator returning a fixed cost for every non-empty block.
    """

    def __init__(
        self,
        tokens: int,
    ) -> None:
        self.tokens = tokens
        self.calls: list[str] = []

    @property
    def estimator_id(self) -> str:
        return "fixed-test"

    def estimate(
        self,
        text: str,
    ) -> int:
        self.calls.append(text)

        if not text:
            return 0

        return self.tokens


class LengthTokenEstimator(TokenEstimator):
    """
    Uses text length as the token count.

    Useful when tests need different candidates to consume different
    amounts of budget without relying on a real tokenizer.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def estimator_id(self) -> str:
        return "length-test"

    def estimate(
        self,
        text: str,
    ) -> int:
        self.calls.append(text)
        return len(text)


class InvalidTokenEstimator(TokenEstimator):
    def __init__(
        self,
        value,
    ) -> None:
        self.value = value

    @property
    def estimator_id(self) -> str:
        return "invalid-test"

    def estimate(
        self,
        text: str,
    ):
        return self.value


class RaisingTokenEstimator(TokenEstimator):
    @property
    def estimator_id(self) -> str:
        return "raising-test"

    def estimate(
        self,
        text: str,
    ) -> int:
        raise ValueError(
            "estimation failed"
        )


# ---------------------------------------------------------------------------
# CharacterTokenEstimator
# ---------------------------------------------------------------------------


class TestCharacterTokenEstimator:
    def test_default_estimator_id(self):
        estimator = CharacterTokenEstimator()

        assert (
            estimator.estimator_id
            == "character_estimator"
        )

    def test_estimates_using_ceiling(self):
        estimator = CharacterTokenEstimator(
            characters_per_token=4.0,
        )

        assert estimator.estimate("a") == 1
        assert estimator.estimate("abcd") == 1
        assert estimator.estimate("abcde") == 2
        assert estimator.estimate("abcdefgh") == 2
        assert estimator.estimate("abcdefghi") == 3

    def test_empty_text_costs_zero_tokens(self):
        estimator = CharacterTokenEstimator()

        assert estimator.estimate("") == 0

    @pytest.mark.parametrize(
        "value",
        [
            0,
            -1,
            -0.5,
        ],
    )
    def test_rejects_non_positive_characters_per_token(
        self,
        value,
    ):
        with pytest.raises(
            ValueError,
            match="greater than zero",
        ):
            CharacterTokenEstimator(
                characters_per_token=value,
            )

    @pytest.mark.parametrize(
        "value",
        [
            True,
            False,
            "4",
            None,
        ],
    )
    def test_rejects_invalid_characters_per_token_type(
        self,
        value,
    ):
        with pytest.raises(
            TypeError,
            match="must be numeric",
        ):
            CharacterTokenEstimator(
                characters_per_token=value,  # type: ignore[arg-type]
            )

    def test_rejects_non_string_text(self):
        estimator = CharacterTokenEstimator()

        with pytest.raises(
            TypeError,
            match="text must be a string",
        ):
            estimator.estimate(
                None  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestGroundingContextBuilderConstruction:
    def test_accepts_token_estimator(self):
        estimator = FixedTokenEstimator(
            tokens=10
        )

        builder = GroundingContextBuilder(
            token_estimator=estimator
        )

        assert builder.token_estimator is estimator

    @pytest.mark.parametrize(
        "estimator",
        [
            None,
            object(),
            "estimator",
            123,
        ],
    )
    def test_rejects_invalid_token_estimator(
        self,
        estimator,
    ):
        with pytest.raises(
            TypeError,
            match="token_estimator must be a TokenEstimator instance",
        ):
            GroundingContextBuilder(
                token_estimator=estimator,  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestGroundingContextBuilderInput:
    def test_rejects_invalid_retrieval_result(self):
        builder = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        )

        with pytest.raises(
            TypeError,
            match="retrieval_result must be a RetrievalResult instance",
        ):
            builder.build(
                retrieval_result=object(),  # type: ignore[arg-type]
                budget=make_budget(),
            )

    def test_rejects_invalid_budget(self):
        builder = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        )

        with pytest.raises(
            TypeError,
            match="budget must be a GroundingContextBudget instance",
        ):
            builder.build(
                retrieval_result=make_result(),
                budget=object(),  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Empty retrieval
# ---------------------------------------------------------------------------


class TestGroundingContextBuilderEmpty:
    def test_empty_retrieval_returns_empty_context(
        self,
    ):
        query = make_query()

        estimator = FixedTokenEstimator(
            tokens=10
        )

        builder = GroundingContextBuilder(
            token_estimator=estimator
        )

        context = builder.build(
            retrieval_result=make_result(
                query=query
            ),
            budget=make_budget(),
        )

        assert context.query is query
        assert context.blocks == ()
        assert context.block_count == 0
        assert context.is_empty
        assert context.estimated_token_count == 0
        assert context.truncated is False

    def test_empty_retrieval_does_not_call_estimator(
        self,
    ):
        estimator = FixedTokenEstimator(
            tokens=10
        )

        GroundingContextBuilder(
            token_estimator=estimator
        ).build(
            retrieval_result=make_result(),
            budget=make_budget(),
        )

        assert estimator.calls == []


# ---------------------------------------------------------------------------
# Selection and provenance
# ---------------------------------------------------------------------------


class TestGroundingContextBuilderSelection:
    def test_preserves_retrieval_order(
        self,
    ):
        first = make_candidate(
            chunk_index=1,
            content="First candidate.",
        )
        second = make_candidate(
            chunk_index=2,
            content="Second candidate.",
        )
        third = make_candidate(
            chunk_index=3,
            content="Third candidate.",
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                first,
                second,
                third,
            ),
            budget=make_budget(),
        )

        assert context.chunk_ids == (
            first.chunk_id,
            second.chunk_id,
            third.chunk_id,
        )

    def test_preserves_candidate_provenance(
        self,
    ):
        candidate = make_candidate(
            chunk_index=17,
            content="Canonical policy text.",
            document_title="Returns Policy",
            section_title="Damaged Goods",
            metadata={
                "language": "en",
                "region": "IN",
            },
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                candidate
            ),
            budget=make_budget(),
        )

        block = context.blocks[0]

        assert block.chunk_id == candidate.chunk_id
        assert block.version_id == candidate.version_id
        assert block.document_id == candidate.document_id
        assert block.chunk_index == 17
        assert block.content == "Canonical policy text."
        assert block.document_title == "Returns Policy"
        assert block.section_title == "Damaged Goods"
        assert dict(block.metadata) == {
            "language": "en",
            "region": "IN",
        }

    def test_uses_reranker_score_when_available(
        self,
    ):
        candidate = make_candidate(
            scores=RetrievalScores(
                vector_similarity=0.80,
                lexical_score=0.70,
                fusion_score=0.03,
                reranker_score=9.25,
            )
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                candidate
            ),
            budget=make_budget(),
        )

        assert (
            context.blocks[0].retrieval_score
            == 9.25
        )

    def test_falls_back_to_fusion_score_for_passthrough_reranking(
        self,
    ):
        candidate = make_candidate(
            scores=RetrievalScores(
                vector_similarity=0.90,
                lexical_score=0.80,
                fusion_score=0.035,
                reranker_score=None,
            )
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                candidate
            ),
            budget=make_budget(),
        )

        assert (
            context.blocks[0].retrieval_score
            == 0.035
        )


# ---------------------------------------------------------------------------
# Token accounting
# ---------------------------------------------------------------------------


class TestGroundingContextBuilderTokenAccounting:
    def test_counts_selected_block_tokens(
        self,
    ):
        candidates = tuple(
            make_candidate(
                chunk_index=index,
                content=f"Candidate {index}",
            )
            for index in range(3)
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=7
            )
        ).build(
            retrieval_result=make_result(
                *candidates
            ),
            budget=make_budget(),
        )

        assert (
            context.estimated_token_count
            == 21
        )

    def test_estimation_includes_document_title_section_and_content(
        self,
    ):
        candidate = make_candidate(
            document_title="Refund Policy",
            section_title="Eligibility",
            content="Thirty day refund window.",
        )

        estimator = LengthTokenEstimator()

        GroundingContextBuilder(
            token_estimator=estimator
        ).build(
            retrieval_result=make_result(
                candidate
            ),
            budget=make_budget(
                max_tokens=10_000
            ),
        )

        assert estimator.calls == [
            (
                "Refund Policy\n"
                "Eligibility\n"
                "Thirty day refund window."
            )
        ]

    def test_estimation_omits_missing_section_title(
        self,
    ):
        candidate = make_candidate(
            document_title="Refund Policy",
            section_title=None,
            content="Thirty day refund window.",
        )

        estimator = LengthTokenEstimator()

        GroundingContextBuilder(
            token_estimator=estimator
        ).build(
            retrieval_result=make_result(
                candidate
            ),
            budget=make_budget(
                max_tokens=10_000
            ),
        )

        assert estimator.calls == [
            (
                "Refund Policy\n"
                "Thirty day refund window."
            )
        ]


# ---------------------------------------------------------------------------
# Token budget
# ---------------------------------------------------------------------------


class TestGroundingContextBuilderTokenBudget:
    def test_selects_candidates_within_token_budget(
        self,
    ):
        first = make_candidate(
            content="First."
        )
        second = make_candidate(
            content="Second."
        )
        third = make_candidate(
            content="Third."
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                first,
                second,
                third,
            ),
            budget=make_budget(
                max_tokens=20,
                max_blocks=10,
            ),
        )

        assert context.chunk_ids == (
            first.chunk_id,
            second.chunk_id,
        )
        assert context.estimated_token_count == 20
        assert context.truncated is True

    def test_exact_token_budget_is_allowed(
        self,
    ):
        first = make_candidate()
        second = make_candidate()

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                first,
                second,
            ),
            budget=make_budget(
                max_tokens=20
            ),
        )

        assert context.block_count == 2
        assert context.estimated_token_count == 20
        assert context.truncated is False

    def test_oversized_candidate_is_skipped_whole(
        self,
    ):
        candidate = make_candidate(
            content="Large canonical chunk."
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=101
            )
        ).build(
            retrieval_result=make_result(
                candidate
            ),
            budget=make_budget(
                max_tokens=100
            ),
        )

        assert context.is_empty
        assert context.estimated_token_count == 0
        assert context.truncated is True

    def test_does_not_truncate_canonical_chunk_content(
        self,
    ):
        candidate = make_candidate(
            content="Do not partially truncate me."
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=101
            )
        ).build(
            retrieval_result=make_result(
                candidate
            ),
            budget=make_budget(
                max_tokens=100
            ),
        )

        assert context.blocks == ()

    def test_continues_after_candidate_does_not_fit(
        self,
    ):
        """
        A lower-ranked smaller candidate may still fit after a larger
        candidate is skipped.
        """

        first = make_candidate(
            content="A" * 20,
            document_title="D",
            section_title=None,
        )

        second = make_candidate(
            content="B" * 20,
            document_title="D" * 30,
            section_title=None,
        )

        third = make_candidate(
            content="C" * 5,
            document_title="D",
            section_title=None,
        )

        estimator = LengthTokenEstimator()

        first_cost = len(
            "D\n" + ("A" * 20)
        )
        second_cost = len(
            ("D" * 30)
            + "\n"
            + ("B" * 20)
        )
        third_cost = len(
            "D\n" + ("C" * 5)
        )

        budget = first_cost + third_cost

        assert second_cost > (
            budget - first_cost
        )

        context = GroundingContextBuilder(
            token_estimator=estimator
        ).build(
            retrieval_result=make_result(
                first,
                second,
                third,
            ),
            budget=make_budget(
                max_tokens=budget,
                max_blocks=10,
            ),
        )

        assert context.chunk_ids == (
            first.chunk_id,
            third.chunk_id,
        )
        assert (
            context.estimated_token_count
            == first_cost + third_cost
        )
        assert context.truncated is True


# ---------------------------------------------------------------------------
# Block budget
# ---------------------------------------------------------------------------


class TestGroundingContextBuilderBlockBudget:
    def test_enforces_max_blocks(
        self,
    ):
        candidates = tuple(
            make_candidate(
                chunk_index=index,
                content=f"Candidate {index}",
            )
            for index in range(4)
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=1
            )
        ).build(
            retrieval_result=make_result(
                *candidates
            ),
            budget=make_budget(
                max_tokens=100,
                max_blocks=2,
            ),
        )

        assert context.chunk_ids == (
            candidates[0].chunk_id,
            candidates[1].chunk_id,
        )
        assert context.block_count == 2
        assert context.truncated is True

    def test_max_blocks_without_exclusion_is_not_truncated(
        self,
    ):
        first = make_candidate()
        second = make_candidate()

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=1
            )
        ).build(
            retrieval_result=make_result(
                first,
                second,
            ),
            budget=make_budget(
                max_tokens=100,
                max_blocks=2,
            ),
        )

        assert context.block_count == 2
        assert context.truncated is False


# ---------------------------------------------------------------------------
# Redundancy
# ---------------------------------------------------------------------------


class TestGroundingContextBuilderRedundancy:
    def test_suppresses_exact_duplicate_within_same_document_version(
        self,
    ):
        document_id = uuid4()
        version_id = uuid4()

        first = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content="Refunds are allowed within 30 days.",
        )

        duplicate = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content="Refunds are allowed within 30 days.",
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                first,
                duplicate,
            ),
            budget=make_budget(),
        )

        assert context.chunk_ids == (
            first.chunk_id,
        )

        # Redundancy is not budget truncation.
        assert context.truncated is False

    def test_duplicate_detection_normalizes_whitespace_and_case(
        self,
    ):
        document_id = uuid4()
        version_id = uuid4()

        first = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content=(
                "Refund requests must be submitted "
                "within 30 days."
            ),
        )

        duplicate = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content=(
                "  REFUND   requests must be "
                "submitted within 30 DAYS.  "
            ),
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                first,
                duplicate,
            ),
            budget=make_budget(),
        )

        assert context.chunk_ids == (
            first.chunk_id,
        )

    def test_suppresses_lower_ranked_content_contained_in_selected_chunk(
        self,
    ):
        document_id = uuid4()
        version_id = uuid4()

        first = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content=(
                "Refunds are available within 30 days. "
                "The item must be unused."
            ),
        )

        contained = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content=(
                "The item must be unused."
            ),
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                first,
                contained,
            ),
            budget=make_budget(),
        )

        assert context.chunk_ids == (
            first.chunk_id,
        )

    def test_keeps_lower_ranked_chunk_when_it_contains_more_information(
        self,
    ):
        document_id = uuid4()
        version_id = uuid4()

        first = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content=(
                "Refunds are available within 30 days."
            ),
        )

        richer = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content=(
                "Refunds are available within 30 days. "
                "The item must also be unused."
            ),
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                first,
                richer,
            ),
            budget=make_budget(),
        )

        assert context.chunk_ids == (
            first.chunk_id,
            richer.chunk_id,
        )

    def test_keeps_identical_text_from_different_documents(
        self,
    ):
        first = make_candidate(
            document_id=uuid4(),
            version_id=uuid4(),
            content="Refund window is 30 days.",
        )

        second = make_candidate(
            document_id=uuid4(),
            version_id=uuid4(),
            content="Refund window is 30 days.",
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                first,
                second,
            ),
            budget=make_budget(),
        )

        assert context.chunk_ids == (
            first.chunk_id,
            second.chunk_id,
        )

    def test_keeps_identical_text_from_different_versions(
        self,
    ):
        document_id = uuid4()

        first = make_candidate(
            document_id=document_id,
            version_id=uuid4(),
            content="Refund window is 30 days.",
        )

        second = make_candidate(
            document_id=document_id,
            version_id=uuid4(),
            content="Refund window is 30 days.",
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                first,
                second,
            ),
            budget=make_budget(),
        )

        assert context.chunk_ids == (
            first.chunk_id,
            second.chunk_id,
        )

    def test_redundant_candidate_does_not_consume_token_budget(
        self,
    ):
        document_id = uuid4()
        version_id = uuid4()

        first = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content="Same content.",
        )

        duplicate = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content="Same content.",
        )

        third = make_candidate(
            content="Different content.",
        )

        estimator = FixedTokenEstimator(
            tokens=10
        )

        context = GroundingContextBuilder(
            token_estimator=estimator
        ).build(
            retrieval_result=make_result(
                first,
                duplicate,
                third,
            ),
            budget=make_budget(
                max_tokens=20,
            ),
        )

        assert context.chunk_ids == (
            first.chunk_id,
            third.chunk_id,
        )

        assert context.estimated_token_count == 20

        # Only selected non-redundant candidates need estimation.
        assert len(estimator.calls) == 2


# ---------------------------------------------------------------------------
# Truncation semantics
# ---------------------------------------------------------------------------


class TestGroundingContextBuilderTruncation:
    def test_redundancy_only_does_not_mark_context_truncated(
        self,
    ):
        document_id = uuid4()
        version_id = uuid4()

        first = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content="Same.",
        )
        duplicate = make_candidate(
            document_id=document_id,
            version_id=version_id,
            content="Same.",
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=1
            )
        ).build(
            retrieval_result=make_result(
                first,
                duplicate,
            ),
            budget=make_budget(),
        )

        assert context.block_count == 1
        assert context.truncated is False

    def test_any_budget_exclusion_marks_context_truncated(
        self,
    ):
        candidates = tuple(
            make_candidate(
                content=f"Candidate {index}"
            )
            for index in range(3)
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                *candidates
            ),
            budget=make_budget(
                max_tokens=20,
            ),
        )

        assert context.truncated is True


# ---------------------------------------------------------------------------
# Estimator failures
# ---------------------------------------------------------------------------


class TestGroundingContextBuilderEstimatorFailures:
    def test_translates_estimator_value_error(
        self,
    ):
        builder = GroundingContextBuilder(
            token_estimator=RaisingTokenEstimator()
        )

        with pytest.raises(
            GroundingContextBudgetError,
            match="Token estimation failed",
        ):
            builder.build(
                retrieval_result=make_result(
                    make_candidate()
                ),
                budget=make_budget(),
            )

    @pytest.mark.parametrize(
        "value",
        [
            None,
            1.5,
            "10",
            True,
            False,
        ],
    )
    def test_rejects_non_integer_estimator_result(
        self,
        value,
    ):
        builder = GroundingContextBuilder(
            token_estimator=InvalidTokenEstimator(
                value
            )
        )

        with pytest.raises(
            GroundingContextBudgetError,
            match="non-integer",
        ):
            builder.build(
                retrieval_result=make_result(
                    make_candidate()
                ),
                budget=make_budget(),
            )

    def test_rejects_negative_estimator_result(
        self,
    ):
        builder = GroundingContextBuilder(
            token_estimator=InvalidTokenEstimator(
                -1
            )
        )

        with pytest.raises(
            GroundingContextBudgetError,
            match="negative",
        ):
            builder.build(
                retrieval_result=make_result(
                    make_candidate()
                ),
                budget=make_budget(),
            )

    def test_rejects_zero_for_non_empty_estimation_text(
        self,
    ):
        builder = GroundingContextBuilder(
            token_estimator=InvalidTokenEstimator(
                0
            )
        )

        with pytest.raises(
            GroundingContextBudgetError,
            match="zero for non-empty text",
        ):
            builder.build(
                retrieval_result=make_result(
                    make_candidate()
                ),
                budget=make_budget(),
            )


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestGroundingContextBuilderImmutability:
    def test_does_not_mutate_retrieval_result(
        self,
    ):
        first = make_candidate()
        second = make_candidate()

        result = make_result(
            first,
            second,
        )

        original_candidates = (
            result.candidates
        )

        GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=result,
            budget=make_budget(),
        )

        assert (
            result.candidates
            == original_candidates
        )
        assert result.candidates[0] is first
        assert result.candidates[1] is second

    def test_context_metadata_is_not_same_mutable_mapping(
        self,
    ):
        source_metadata = {
            "language": "en",
            "region": "IN",
        }

        candidate = make_candidate(
            metadata=source_metadata
        )

        context = GroundingContextBuilder(
            token_estimator=FixedTokenEstimator(
                tokens=10
            )
        ).build(
            retrieval_result=make_result(
                candidate
            ),
            budget=make_budget(),
        )

        assert dict(
            context.blocks[0].metadata
        ) == source_metadata

        with pytest.raises(
            TypeError
        ):
            context.blocks[0].metadata[
                "region"
            ] = "US"  # type: ignore[index]