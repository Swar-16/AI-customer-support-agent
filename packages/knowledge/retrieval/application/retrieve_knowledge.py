from __future__ import annotations

from packages.knowledge.retrieval.errors import RetrievalPipelineError
from packages.knowledge.retrieval.fusion.base import FusionInput, RetrievalFusionStrategy
from packages.knowledge.retrieval.lexical.service import LexicalRetrievalService
from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalQuery, RetrievalResult
from packages.knowledge.retrieval.profiles import RetrievalProfile
from packages.knowledge.retrieval.reranking.service import RerankingService
from packages.knowledge.retrieval.vector.service import VectorRetrievalService


class RetrieveKnowledge:
    """
    Orchestrates knowledge retrieval across enabled retrieval stages.

    Pipeline:
        
                 +--> vector retrieval  --+ 
        query ---|                        |--> fusion --> reranking --> reranking RetrievalResult
                 +--> lexical retrieval --+

    Responsibilities:
      - execute retrieval branches enabled by the configured profile;
      - apply branch-specific candidate limits;
      - fuse multiple rankings when necessary;
      - optionally invoke the reranking stage;
      - enforce the final result limit;
      - return a canonical RetrievalResult.

    Infrastructure-specific invariants must remain inside the retrieval services/repositories.
    Application-level composition decides which concrete implementations are supplied.
    """
    def __init__(self, *, profile: RetrievalProfile, fusion_strategy: RetrievalFusionStrategy,
                 vector_service: VectorRetrievalService | None = None, lexical_service: LexicalRetrievalService | None = None,
                 reranking_service: RerankingService | None = None,
    ) -> None:
        if not isinstance(profile, RetrievalProfile):
            raise TypeError("profile must be a RetrievalProfile instance.")

        if not isinstance(fusion_strategy, RetrievalFusionStrategy):
            raise TypeError("fusion_strategy must be a RetrievalFusionStrategy instance.")

        if vector_service is not None and not isinstance(vector_service, VectorRetrievalService):
            raise TypeError("vector_service must be a VectorRetrievalService instance or None.")

        if lexical_service is not None and not isinstance(lexical_service, LexicalRetrievalService):
            raise TypeError("lexical_service must be a LexicalRetrievalService instance or None.")

        if reranking_service is not None and not isinstance(reranking_service, RerankingService):
            raise TypeError("reranking_service must be a RerankingService instance or None.")

        self._validate_dependencies(
            profile=profile,
            vector_service=vector_service,
            lexical_service=lexical_service,
            reranking_service=reranking_service,
        )

        self._profile = profile
        self._fusion_strategy = fusion_strategy
        self._vector_service = vector_service
        self._lexical_service = lexical_service
        self._reranking_service = reranking_service

    @property
    def profile(self) -> RetrievalProfile:
        return self._profile

    @property
    def fusion_strategy(self) -> RetrievalFusionStrategy:
        return self._fusion_strategy

    def retrieve(self, *, query: RetrievalQuery) -> RetrievalResult:
        """
        Execute the configured retrieval pipeline.

        Known typed failures from lower layers intentionally propagate.

        This service does not silently degrade from hybrid retrieval to a partial strategy when one branch fails.
        Such degradation is a product/application policy and should be implemented explicitly above or through a dedicated resilience policy.
        """
        if not isinstance(query, RetrievalQuery):
            raise TypeError("query must be a RetrievalQuery instance.")

        rankings = self._retrieve_rankings(query=query)
        if not rankings:
            return RetrievalResult(query=query, candidates=())

        candidates = self._combine_rankings(query=query, rankings=rankings)

        if self._profile.reranking_enabled and candidates:
            candidates = self._rerank(query=query, candidates=candidates)

        candidates = candidates[: self._profile.final_candidate_limit]

        return RetrievalResult(query=query, candidates=candidates)

    def _retrieve_rankings(self, *, query: RetrievalQuery) -> tuple[tuple[RetrievalCandidate, ...], ...,]:
        rankings: list[tuple[RetrievalCandidate, ...]] = []

        if self._profile.vector_enabled:
            vector_service = self._require_vector_service()
            vector_candidates = vector_service.search(query=query, limit=self._profile.vector_candidate_limit)
            if vector_candidates:
                rankings.append(vector_candidates)

        if self._profile.lexical_enabled:
            lexical_service = self._require_lexical_service()
            lexical_candidates = lexical_service.search(query=query, limit=self._profile.lexical_candidate_limit)
            if lexical_candidates:
                rankings.append(lexical_candidates)

        return tuple(rankings)

    def _combine_rankings(self, *, query: RetrievalQuery, rankings: tuple[tuple[RetrievalCandidate, ...], ...,]) -> tuple[RetrievalCandidate, ...]:
        """
        Combine retrieval rankings into one canonical ranking.

        Even a single active ranking is passed through the fusion strategy.
        This keeps score/provenance behavior consistent and avoids creating separate single-source and hybrid result semantics.
        """
        fusion_input = FusionInput(query=query, rankings=rankings)
        result = self._fusion_strategy.fuse(fusion_input=fusion_input, limit=self._profile.fused_candidate_limit)

        if result.query != query:
            raise RetrievalPipelineError("Fusion strategy returned a result for a different retrieval query.")

        return result.candidates

    def _rerank(self, *, query: RetrievalQuery, candidates: tuple[RetrievalCandidate, ...,]) -> tuple[RetrievalCandidate, ...]:
        reranking_service = (self._require_reranking_service())

        return reranking_service.rerank(
            query=query,
            candidates=candidates,
            limit=self._profile.final_candidate_limit,
        )

    def _require_vector_service(self) -> VectorRetrievalService:
        if self._vector_service is None:
            raise RetrievalPipelineError("Vector retrieval is enabled by the retrieval profile, but no vector retrieval service is configured.")

        return self._vector_service

    def _require_lexical_service(self) -> LexicalRetrievalService:
        if self._lexical_service is None:
            raise RetrievalPipelineError("Lexical retrieval is enabled by the retrieval profile, but no lexical retrieval service is configured.")

        return self._lexical_service

    def _require_reranking_service(self) -> RerankingService:
        if self._reranking_service is None:
            raise RetrievalPipelineError("Reranking is enabled by the retrieval profile, but no reranking service is configured.")

        return self._reranking_service

    @staticmethod
    def _validate_dependencies(*, profile: RetrievalProfile, vector_service: VectorRetrievalService | None,
                               lexical_service: LexicalRetrievalService | None, reranking_service: RerankingService | None
    ) -> None:
        """
        Fail fast for invalid application composition.

        Missing dependencies are configuration problems, not runtime retrieval conditions.
        Catching them during object construction makes deployment/configuration errors substantially easier to diagnose.
        """
        if profile.vector_enabled and vector_service is None:
            raise RetrievalPipelineError("Vector retrieval is enabled by the retrieval profile, but no vector retrieval service is configured.")

        if profile.lexical_enabled and lexical_service is None:
            raise RetrievalPipelineError("Lexical retrieval is enabled by the retrieval profile, but no lexical retrieval service is configured.")

        if profile.reranking_enabled and reranking_service is None:
            raise RetrievalPipelineError("Reranking is enabled by the retrieval profile, but no reranking service is configured.")