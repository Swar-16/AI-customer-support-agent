from __future__ import annotations

from unittest.mock import create_autospec
from uuid import UUID, uuid4

import pytest

from packages.knowledge.retrieval.application.retrieve_knowledge import (
    RetrieveKnowledge,
)
from packages.knowledge.retrieval.errors import (
    LexicalSearchError,
    RetrievalPipelineError,
    VectorSearchError,
)
from packages.knowledge.retrieval.fusion.base import (
    FusionInput,
    FusionResult,
    RetrievalFusionStrategy,
)
from packages.knowledge.retrieval.fusion.reciprocal_rank import (
    ReciprocalRankFusion,
)
from packages.knowledge.retrieval.lexical.service import (
    LexicalRetrievalService,
)
from packages.knowledge.retrieval.models import (
    RetrievalCandidate,
    RetrievalFilters,
    RetrievalMethod,
    RetrievalQuery,
    RetrievalResult,
    RetrievalScores,
)
from packages.knowledge.retrieval.profiles import (
    RetrievalProfile,
)
from packages.knowledge.retrieval.query.models import (
    PreparedRetrievalQuery,
)
from packages.knowledge.retrieval.reranking.service import (
    RerankingService,
)
from packages.knowledge.retrieval.vector.service import (
    VectorRetrievalService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_prepared_query(
    *,
    original_query: str = "What is the refund policy?",
    semantic_query: str = "What is the refund policy?",
    lexical_query: str = "refund policy",
    filters: RetrievalFilters | None = None,
) -> PreparedRetrievalQuery:
    return PreparedRetrievalQuery(
        original_query=original_query,
        semantic_query=semantic_query,
        lexical_queries=(lexical_query,),
        filters=(
            filters
            if filters is not None
            else RetrievalFilters()
        ),
    )


def make_canonical_query(
    prepared_query: PreparedRetrievalQuery,
) -> RetrievalQuery:
    return RetrievalQuery(
        text=prepared_query.original_query,
        filters=prepared_query.filters,
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
            else frozenset({RetrievalMethod.VECTOR})
        ),
        scores=(
            scores
            if scores is not None
            else RetrievalScores(
                vector_distance=0.10,
                vector_similarity=0.90,
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


def make_profile(
    *,
    vector_enabled: bool = True,
    lexical_enabled: bool = True,
    reranking_enabled: bool = False,
    vector_candidate_limit: int = 20,
    lexical_candidate_limit: int = 20,
    fused_candidate_limit: int = 20,
    final_candidate_limit: int = 8,
    rrf_k: int = 60,
) -> RetrievalProfile:
    return RetrievalProfile(
        profile_id="test",
        vector_enabled=vector_enabled,
        lexical_enabled=lexical_enabled,
        reranking_enabled=reranking_enabled,
        vector_candidate_limit=vector_candidate_limit,
        lexical_candidate_limit=lexical_candidate_limit,
        fused_candidate_limit=fused_candidate_limit,
        final_candidate_limit=final_candidate_limit,
        rrf_k=rrf_k,
    )


def make_vector_service():
    return create_autospec(
        VectorRetrievalService,
        instance=True,
        spec_set=True,
    )


def make_lexical_service():
    return create_autospec(
        LexicalRetrievalService,
        instance=True,
        spec_set=True,
    )


def make_reranking_service():
    return create_autospec(
        RerankingService,
        instance=True,
        spec_set=True,
    )


def make_fusion_strategy():
    return create_autospec(
        RetrievalFusionStrategy,
        instance=True,
        spec_set=True,
    )


def build_service(
    *,
    profile: RetrievalProfile | None = None,
    vector_service=None,
    lexical_service=None,
    fusion_strategy=None,
    reranking_service=None,
) -> RetrieveKnowledge:
    profile = profile or make_profile()

    if vector_service is None and profile.vector_enabled:
        vector_service = make_vector_service()

    if lexical_service is None and profile.lexical_enabled:
        lexical_service = make_lexical_service()

    if fusion_strategy is None:
        fusion_strategy = ReciprocalRankFusion(
            k=profile.rrf_k,
        )

    return RetrieveKnowledge(
        profile=profile,
        fusion_strategy=fusion_strategy,
        vector_service=vector_service,
        lexical_service=lexical_service,
        reranking_service=reranking_service,
    )


# ---------------------------------------------------------------------------
# Construction / composition
# ---------------------------------------------------------------------------


class TestRetrieveKnowledgeConstruction:
    def test_accepts_valid_dependencies(self):
        profile = make_profile()
        vector_service = make_vector_service()
        lexical_service = make_lexical_service()
        fusion_strategy = ReciprocalRankFusion(
            k=profile.rrf_k,
        )

        service = RetrieveKnowledge(
            profile=profile,
            fusion_strategy=fusion_strategy,
            vector_service=vector_service,
            lexical_service=lexical_service,
        )

        assert service.profile is profile
        assert service.fusion_strategy is fusion_strategy

    @pytest.mark.parametrize(
        "profile",
        [
            None,
            object(),
            "profile",
            123,
        ],
    )
    def test_rejects_invalid_profile(
        self,
        profile,
    ):
        with pytest.raises(
            TypeError,
            match="profile must be a RetrievalProfile instance",
        ):
            RetrieveKnowledge(
                profile=profile,  # type: ignore[arg-type]
                fusion_strategy=ReciprocalRankFusion(),
            )

    @pytest.mark.parametrize(
        "fusion_strategy",
        [
            None,
            object(),
            "rrf",
            123,
        ],
    )
    def test_rejects_invalid_fusion_strategy(
        self,
        fusion_strategy,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
        )

        with pytest.raises(
            TypeError,
            match="fusion_strategy must be a RetrievalFusionStrategy instance",
        ):
            RetrieveKnowledge(
                profile=profile,
                fusion_strategy=fusion_strategy,  # type: ignore[arg-type]
                vector_service=make_vector_service(),
            )

    def test_requires_vector_service_when_vector_enabled(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
        )

        with pytest.raises(
            RetrievalPipelineError,
            match="Vector retrieval is enabled",
        ):
            RetrieveKnowledge(
                profile=profile,
                fusion_strategy=ReciprocalRankFusion(),
                vector_service=None,
            )

    def test_requires_lexical_service_when_lexical_enabled(
        self,
    ):
        profile = make_profile(
            vector_enabled=False,
            lexical_enabled=True,
        )

        with pytest.raises(
            RetrievalPipelineError,
            match="Lexical retrieval is enabled",
        ):
            RetrieveKnowledge(
                profile=profile,
                fusion_strategy=ReciprocalRankFusion(),
                lexical_service=None,
            )

    def test_requires_reranking_service_when_reranking_enabled(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
            reranking_enabled=True,
        )

        with pytest.raises(
            RetrievalPipelineError,
            match="Reranking is enabled",
        ):
            RetrieveKnowledge(
                profile=profile,
                fusion_strategy=ReciprocalRankFusion(),
                vector_service=make_vector_service(),
                reranking_service=None,
            )

    def test_does_not_require_reranking_service_when_disabled(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
            reranking_enabled=False,
        )

        service = RetrieveKnowledge(
            profile=profile,
            fusion_strategy=ReciprocalRankFusion(),
            vector_service=make_vector_service(),
        )

        assert service.profile is profile

    def test_rejects_invalid_vector_service_even_when_disabled(
        self,
    ):
        profile = make_profile(
            vector_enabled=False,
            lexical_enabled=True,
        )

        with pytest.raises(
            TypeError,
            match="vector_service must be a VectorRetrievalService",
        ):
            RetrieveKnowledge(
                profile=profile,
                fusion_strategy=ReciprocalRankFusion(),
                vector_service=object(),  # type: ignore[arg-type]
                lexical_service=make_lexical_service(),
            )

    def test_rejects_invalid_lexical_service_even_when_disabled(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
        )

        with pytest.raises(
            TypeError,
            match="lexical_service must be a LexicalRetrievalService",
        ):
            RetrieveKnowledge(
                profile=profile,
                fusion_strategy=ReciprocalRankFusion(),
                vector_service=make_vector_service(),
                lexical_service=object(),  # type: ignore[arg-type]
            )

    def test_rejects_invalid_reranking_service_even_when_disabled(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
            reranking_enabled=False,
        )

        with pytest.raises(
            TypeError,
            match="reranking_service must be a RerankingService",
        ):
            RetrieveKnowledge(
                profile=profile,
                fusion_strategy=ReciprocalRankFusion(),
                vector_service=make_vector_service(),
                reranking_service=object(),  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestRetrieveKnowledgeInput:
    @pytest.mark.parametrize(
        "prepared_query",
        [
            None,
            object(),
            "refund",
            123,
        ],
    )
    def test_rejects_invalid_prepared_query(
        self,
        prepared_query,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
        )

        service = build_service(
            profile=profile,
        )

        with pytest.raises(
            TypeError,
            match=(
                "prepared_query must be a "
                "PreparedRetrievalQuery instance"
            ),
        ):
            service.retrieve(
                prepared_query=prepared_query,  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Branch execution
# ---------------------------------------------------------------------------


class TestRetrieveKnowledgeBranches:
    def test_hybrid_executes_vector_and_lexical_with_profile_limits(
        self,
    ):
        profile = make_profile(
            vector_candidate_limit=17,
            lexical_candidate_limit=13,
        )

        filters = RetrievalFilters(
            visibilities=("customer",),
        )
        prepared_query = make_prepared_query(
            original_query="How long does my refund take?",
            semantic_query="How long does my refund take?",
            lexical_query="refund duration",
            filters=filters,
        )

        vector_candidate = make_candidate(
            methods=frozenset(
                {RetrievalMethod.VECTOR}
            )
        )
        lexical_candidate = make_candidate(
            methods=frozenset(
                {RetrievalMethod.LEXICAL}
            ),
            scores=RetrievalScores(
                lexical_score=0.85,
            ),
        )

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()

        vector_service.search.return_value = (
            vector_candidate,
        )
        lexical_service.search.return_value = (
            lexical_candidate,
        )

        service = build_service(
            profile=profile,
            vector_service=vector_service,
            lexical_service=lexical_service,
        )

        service.retrieve(
            prepared_query=prepared_query,
        )

        vector_service.search.assert_called_once_with(
            query=RetrievalQuery(
                text="How long does my refund take?",
                filters=filters,
            ),
            limit=17,
        )
        lexical_service.search.assert_called_once_with(
            query=RetrievalQuery(
                text="refund duration",
                filters=filters,
            ),
            limit=13,
        )

    def test_both_branches_preserve_same_trusted_filters(
        self,
    ):
        filters = RetrievalFilters(
            content_types=("policy",),
            visibilities=("customer",),
        )
        prepared_query = make_prepared_query(
            semantic_query="Can I get a refund?",
            lexical_query="refund",
            filters=filters,
        )

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()
        vector_service.search.return_value = ()
        lexical_service.search.return_value = ()

        service = build_service(
            vector_service=vector_service,
            lexical_service=lexical_service,
        )

        service.retrieve(
            prepared_query=prepared_query,
        )

        vector_query = (
            vector_service.search.call_args.kwargs["query"]
        )
        lexical_query = (
            lexical_service.search.call_args.kwargs["query"]
        )

        assert vector_query.filters is filters
        assert lexical_query.filters is filters

    def test_vector_only_does_not_execute_lexical(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
        )

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()

        vector_service.search.return_value = (
            make_candidate(),
        )

        service = RetrieveKnowledge(
            profile=profile,
            fusion_strategy=ReciprocalRankFusion(),
            vector_service=vector_service,
            lexical_service=lexical_service,
        )

        service.retrieve(
            prepared_query=make_prepared_query(),
        )

        vector_service.search.assert_called_once()
        lexical_service.search.assert_not_called()

    def test_lexical_only_does_not_execute_vector(
        self,
    ):
        profile = make_profile(
            vector_enabled=False,
            lexical_enabled=True,
        )

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()

        lexical_service.search.return_value = (
            make_candidate(
                methods=frozenset(
                    {RetrievalMethod.LEXICAL}
                ),
                scores=RetrievalScores(
                    lexical_score=0.9,
                ),
            ),
        )

        service = RetrieveKnowledge(
            profile=profile,
            fusion_strategy=ReciprocalRankFusion(),
            vector_service=vector_service,
            lexical_service=lexical_service,
        )

        service.retrieve(
            prepared_query=make_prepared_query(),
        )

        vector_service.search.assert_not_called()
        lexical_service.search.assert_called_once()


# ---------------------------------------------------------------------------
# Empty retrieval
# ---------------------------------------------------------------------------


class TestRetrieveKnowledgeEmptyResults:
    def test_returns_empty_result_when_all_enabled_branches_are_empty(
        self,
    ):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()
        fusion_strategy = make_fusion_strategy()

        vector_service.search.return_value = ()
        lexical_service.search.return_value = ()

        service = build_service(
            vector_service=vector_service,
            lexical_service=lexical_service,
            fusion_strategy=fusion_strategy,
        )

        result = service.retrieve(
            prepared_query=prepared_query,
        )

        assert isinstance(
            result,
            RetrievalResult,
        )
        assert result.query == canonical_query
        assert result.candidates == ()
        assert result.is_empty

        fusion_strategy.fuse.assert_not_called()

    def test_empty_vector_does_not_suppress_lexical_results(
        self,
    ):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)

        lexical_candidate = make_candidate(
            methods=frozenset(
                {RetrievalMethod.LEXICAL}
            ),
            scores=RetrievalScores(
                lexical_score=1.5,
            ),
        )

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()

        vector_service.search.return_value = ()
        lexical_service.search.return_value = (
            lexical_candidate,
        )

        result = build_service(
            vector_service=vector_service,
            lexical_service=lexical_service,
        ).retrieve(
            prepared_query=prepared_query,
        )

        assert result.count == 1
        assert (
            result.candidates[0].chunk_id
            == lexical_candidate.chunk_id
        )

    def test_empty_lexical_does_not_suppress_vector_results(
        self,
    ):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)

        vector_candidate = make_candidate()

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()

        vector_service.search.return_value = (
            vector_candidate,
        )
        lexical_service.search.return_value = ()

        result = build_service(
            vector_service=vector_service,
            lexical_service=lexical_service,
        ).retrieve(
            prepared_query=prepared_query,
        )

        assert result.count == 1
        assert (
            result.candidates[0].chunk_id
            == vector_candidate.chunk_id
        )


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


class TestRetrieveKnowledgeFusion:
    def test_passes_non_empty_rankings_to_fusion_in_stable_branch_order(
        self,
    ):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)

        vector_candidate = make_candidate(
            methods=frozenset(
                {RetrievalMethod.VECTOR}
            )
        )
        lexical_candidate = make_candidate(
            methods=frozenset(
                {RetrievalMethod.LEXICAL}
            ),
            scores=RetrievalScores(
                lexical_score=0.8,
            ),
        )

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()
        fusion_strategy = make_fusion_strategy()

        vector_service.search.return_value = (
            vector_candidate,
        )
        lexical_service.search.return_value = (
            lexical_candidate,
        )

        fusion_strategy.fuse.return_value = (
            FusionResult(
                query=canonical_query,
                candidates=(
                    vector_candidate,
                    lexical_candidate,
                ),
            )
        )

        profile = make_profile(
            fused_candidate_limit=11,
        )

        service = build_service(
            profile=profile,
            vector_service=vector_service,
            lexical_service=lexical_service,
            fusion_strategy=fusion_strategy,
        )

        service.retrieve(
            prepared_query=prepared_query,
        )

        fusion_strategy.fuse.assert_called_once()

        call = fusion_strategy.fuse.call_args

        assert (
            call.kwargs["limit"]
            == 11
        )

        fusion_input = call.kwargs[
            "fusion_input"
        ]

        assert isinstance(
            fusion_input,
            FusionInput,
        )
        assert fusion_input.query == canonical_query
        assert fusion_input.rankings == (
            (vector_candidate,),
            (lexical_candidate,),
        )

    def test_excludes_empty_ranking_from_fusion_input(
        self,
    ):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        lexical_candidate = make_candidate(
            methods=frozenset(
                {RetrievalMethod.LEXICAL}
            ),
            scores=RetrievalScores(
                lexical_score=0.9,
            ),
        )

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()
        fusion_strategy = make_fusion_strategy()

        vector_service.search.return_value = ()
        lexical_service.search.return_value = (
            lexical_candidate,
        )

        fusion_strategy.fuse.return_value = (
            FusionResult(
                query=canonical_query,
                candidates=(
                    lexical_candidate,
                ),
            )
        )

        build_service(
            vector_service=vector_service,
            lexical_service=lexical_service,
            fusion_strategy=fusion_strategy,
        ).retrieve(
            prepared_query=prepared_query,
        )

        fusion_input = (
            fusion_strategy
            .fuse
            .call_args
            .kwargs["fusion_input"]
        )

        assert fusion_input.rankings == (
            (lexical_candidate,),
        )

    def test_single_ranking_still_runs_through_fusion(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
        )

        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        candidate = make_candidate()

        vector_service = make_vector_service()
        fusion_strategy = make_fusion_strategy()

        vector_service.search.return_value = (
            candidate,
        )

        fusion_strategy.fuse.return_value = (
            FusionResult(
                query=canonical_query,
                candidates=(candidate,),
            )
        )

        build_service(
            profile=profile,
            vector_service=vector_service,
            fusion_strategy=fusion_strategy,
        ).retrieve(
            prepared_query=prepared_query,
        )

        fusion_strategy.fuse.assert_called_once()

    def test_rejects_fusion_result_for_different_query(
        self,
    ):
        prepared_query = make_prepared_query(
            original_query="refund policy",
            semantic_query="semantic refund policy query",
            lexical_query="refund policy",
        )
        different_query = RetrievalQuery(
            text="shipping policy",
            filters=prepared_query.filters,
        )

        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
        )

        candidate = make_candidate()

        vector_service = make_vector_service()
        fusion_strategy = make_fusion_strategy()

        vector_service.search.return_value = (
            candidate,
        )

        fusion_strategy.fuse.return_value = (
            FusionResult(
                query=different_query,
                candidates=(candidate,),
            )
        )

        service = build_service(
            profile=profile,
            vector_service=vector_service,
            fusion_strategy=fusion_strategy,
        )

        with pytest.raises(
            RetrievalPipelineError,
            match="different retrieval query",
        ):
            service.retrieve(
                prepared_query=prepared_query,
            )


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------


class TestRetrieveKnowledgeReranking:
    def test_reranking_enabled_invokes_service_after_fusion(
        self,
    ):
        profile = make_profile(
            reranking_enabled=True,
            final_candidate_limit=2,
        )

        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)

        first = make_candidate()
        second = make_candidate()
        third = make_candidate()

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()
        fusion_strategy = make_fusion_strategy()
        reranking_service = (
            make_reranking_service()
        )

        vector_service.search.return_value = (
            first,
            second,
            third,
        )
        lexical_service.search.return_value = ()

        fusion_strategy.fuse.return_value = (
            FusionResult(
                query=canonical_query,
                candidates=(
                    first,
                    second,
                    third,
                ),
            )
        )

        reranking_service.rerank.return_value = (
            second,
            first,
        )

        result = build_service(
            profile=profile,
            vector_service=vector_service,
            lexical_service=lexical_service,
            fusion_strategy=fusion_strategy,
            reranking_service=reranking_service,
        ).retrieve(
            prepared_query=prepared_query,
        )

        reranking_service.rerank.assert_called_once_with(
            query=canonical_query,
            candidates=(
                first,
                second,
                third,
            ),
            limit=2,
        )

        assert result.candidates == (
            second,
            first,
        )

    def test_reranking_disabled_does_not_invoke_service(
        self,
    ):
        profile = make_profile(
            reranking_enabled=False,
        )

        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        candidate = make_candidate()

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()
        reranking_service = (
            make_reranking_service()
        )

        vector_service.search.return_value = (
            candidate,
        )
        lexical_service.search.return_value = ()

        service = RetrieveKnowledge(
            profile=profile,
            fusion_strategy=ReciprocalRankFusion(),
            vector_service=vector_service,
            lexical_service=lexical_service,
            reranking_service=reranking_service,
        )

        service.retrieve(
            prepared_query=prepared_query,
        )

        reranking_service.rerank.assert_not_called()

    def test_does_not_rerank_when_fusion_returns_empty(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
            reranking_enabled=True,
        )

        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)
        retrieved = make_candidate()

        vector_service = make_vector_service()
        fusion_strategy = make_fusion_strategy()
        reranking_service = (
            make_reranking_service()
        )

        vector_service.search.return_value = (
            retrieved,
        )

        fusion_strategy.fuse.return_value = (
            FusionResult(
                query=canonical_query,
                candidates=(),
            )
        )

        result = build_service(
            profile=profile,
            vector_service=vector_service,
            fusion_strategy=fusion_strategy,
            reranking_service=reranking_service,
        ).retrieve(
            prepared_query=prepared_query,
        )

        reranking_service.rerank.assert_not_called()
        assert result.is_empty


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


class TestRetrieveKnowledgeLimits:
    def test_final_result_never_exceeds_final_candidate_limit(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
            final_candidate_limit=2,
        )

        candidates = tuple(
            make_candidate(
                chunk_index=index,
            )
            for index in range(5)
        )

        vector_service = make_vector_service()
        fusion_strategy = make_fusion_strategy()

        vector_service.search.return_value = (
            candidates
        )

        # FusionResult must carry the canonical RetrievalQuery value
        # derived from the PreparedRetrievalQuery used by retrieve().
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)

        fusion_strategy.fuse.return_value = (
            FusionResult(
                query=canonical_query,
                candidates=candidates,
            )
        )

        result = build_service(
            profile=profile,
            vector_service=vector_service,
            fusion_strategy=fusion_strategy,
        ).retrieve(
            prepared_query=prepared_query,
        )

        assert result.count == 2
        assert result.candidates == (
            candidates[0],
            candidates[1],
        )

    def test_final_slice_defensively_limits_reranker_output(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
            reranking_enabled=True,
            fused_candidate_limit=5,
            final_candidate_limit=2,
        )

        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)

        candidates = tuple(
            make_candidate(
                chunk_index=index,
            )
            for index in range(4)
        )

        vector_service = make_vector_service()
        fusion_strategy = make_fusion_strategy()
        reranking_service = (
            make_reranking_service()
        )

        vector_service.search.return_value = (
            candidates
        )

        fusion_strategy.fuse.return_value = (
            FusionResult(
                query=canonical_query,
                candidates=candidates,
            )
        )

        # Simulate a future/broken implementation violating the requested
        # limit. RetrieveKnowledge still owns its public final-limit
        # invariant.
        reranking_service.rerank.return_value = (
            candidates
        )

        result = build_service(
            profile=profile,
            vector_service=vector_service,
            fusion_strategy=fusion_strategy,
            reranking_service=reranking_service,
        ).retrieve(
            prepared_query=prepared_query,
        )

        assert result.candidates == (
            candidates[0],
            candidates[1],
        )


# ---------------------------------------------------------------------------
# Failure semantics
# ---------------------------------------------------------------------------


class TestRetrieveKnowledgeFailures:
    def test_vector_failure_is_not_silently_degraded_to_lexical(
        self,
    ):
        vector_service = make_vector_service()
        lexical_service = make_lexical_service()

        vector_service.search.side_effect = (
            VectorSearchError(
                "vector search failed"
            )
        )

        lexical_service.search.return_value = (
            make_candidate(
                methods=frozenset(
                    {RetrievalMethod.LEXICAL}
                )
            ),
        )

        service = build_service(
            vector_service=vector_service,
            lexical_service=lexical_service,
        )

        with pytest.raises(
            VectorSearchError,
            match="vector search failed",
        ):
            service.retrieve(
                prepared_query=make_prepared_query(),
            )

        # Current strict semantics stop immediately. This is deliberate,
        # not an accidental best-effort fallback.
        lexical_service.search.assert_not_called()

    def test_lexical_failure_propagates_after_successful_vector_search(
        self,
    ):
        vector_service = make_vector_service()
        lexical_service = make_lexical_service()

        vector_service.search.return_value = (
            make_candidate(),
        )

        lexical_service.search.side_effect = (
            LexicalSearchError(
                "lexical search failed"
            )
        )

        service = build_service(
            vector_service=vector_service,
            lexical_service=lexical_service,
        )

        with pytest.raises(
            LexicalSearchError,
            match="lexical search failed",
        ):
            service.retrieve(
                prepared_query=make_prepared_query(),
            )

        vector_service.search.assert_called_once()
        lexical_service.search.assert_called_once()

    def test_unexpected_branch_exception_is_not_swallowed(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
        )

        vector_service = make_vector_service()

        vector_service.search.side_effect = RuntimeError(
            "programming defect"
        )

        service = build_service(
            profile=profile,
            vector_service=vector_service,
        )

        with pytest.raises(
            RuntimeError,
            match="programming defect",
        ):
            service.retrieve(
                prepared_query=make_prepared_query(),
            )


# ---------------------------------------------------------------------------
# Result integrity
# ---------------------------------------------------------------------------


class TestRetrieveKnowledgeResult:
    def test_returns_original_customer_query_as_canonical_result_query(
        self,
    ):
        profile = make_profile(
            vector_enabled=True,
            lexical_enabled=False,
        )

        filters = RetrievalFilters(
            document_ids=(uuid4(),),
        )
        prepared_query = make_prepared_query(
            original_query="When will my refund arrive?",
            semantic_query="When will my refund arrive?",
            lexical_query="refund arrive",
            filters=filters,
        )

        candidate = make_candidate()

        vector_service = make_vector_service()
        vector_service.search.return_value = (
            candidate,
        )

        result = build_service(
            profile=profile,
            vector_service=vector_service,
        ).retrieve(
            prepared_query=prepared_query,
        )

        assert result.query.text == prepared_query.original_query
        assert result.query.filters is prepared_query.filters
        assert result.query.text != prepared_query.lexical_queries[0]

    def test_real_rrf_preserves_and_merges_retrieval_provenance(
        self,
    ):
        prepared_query = make_prepared_query()
        canonical_query = make_canonical_query(prepared_query)

        chunk_id = uuid4()
        version_id = uuid4()
        document_id = uuid4()

        vector_candidate = make_candidate(
            chunk_id=chunk_id,
            version_id=version_id,
            document_id=document_id,
            methods=frozenset(
                {RetrievalMethod.VECTOR}
            ),
            scores=RetrievalScores(
                vector_distance=0.10,
                vector_similarity=0.90,
            ),
        )

        lexical_candidate = make_candidate(
            chunk_id=chunk_id,
            version_id=version_id,
            document_id=document_id,
            methods=frozenset(
                {RetrievalMethod.LEXICAL}
            ),
            scores=RetrievalScores(
                lexical_score=0.85,
            ),
        )

        vector_service = make_vector_service()
        lexical_service = make_lexical_service()

        vector_service.search.return_value = (
            vector_candidate,
        )
        lexical_service.search.return_value = (
            lexical_candidate,
        )

        result = build_service(
            vector_service=vector_service,
            lexical_service=lexical_service,
        ).retrieve(
            prepared_query=prepared_query,
        )

        assert result.count == 1

        candidate = result.candidates[0]

        assert candidate.chunk_id == chunk_id

        assert candidate.methods == frozenset(
            {
                RetrievalMethod.VECTOR,
                RetrievalMethod.LEXICAL,
            }
        )

        assert (
            candidate.scores.vector_distance
            == 0.10
        )
        assert (
            candidate.scores.vector_similarity
            == 0.90
        )
        assert (
            candidate.scores.lexical_score
            == 0.85
        )
        assert (
            candidate.scores.fusion_score
            is not None
        )