from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import ceil

from packages.knowledge.retrieval.context.models import GroundingContext, GroundingContextBlock, GroundingContextBudget
from packages.knowledge.retrieval.errors import GroundingContextBudgetError, GroundingContextCandidateError
from packages.knowledge.retrieval.models import RetrievalCandidate, RetrievalResult


class TokenEstimator(ABC):
    """
    Estimates the number of tokens required to represent text.

    Context construction must not depend directly on a particular LLM provider or tokenizer. Exact provider-specific
    token accounting can therefore be introduced later without changing GroundingContextBuilder.
    """
    @property
    @abstractmethod
    def estimator_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def estimate(self, text: str) -> int:
        raise NotImplementedError

@dataclass(frozen=True, slots=True)
class CharacterTokenEstimator(TokenEstimator):
    """
    Lightweight deterministic token estimator.

    ``characters_per_token`` is an approximation rather than a guarantee. It is suitable for provider-independent context budgeting and tests.

    Exact model tokenization should be introduced through another TokenEstimator implementation when required.
    """
    characters_per_token: float = 4.0

    def __post_init__(self) -> None:
        value = self.characters_per_token
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("characters_per_token must be numeric.")

        normalized = float(value)
        if normalized <= 0.0:
            raise ValueError("characters_per_token must be greater than zero.")

        object.__setattr__(self, "characters_per_token", normalized)

    @property
    def estimator_id(self) -> str:
        return "character_estimator"

    def estimate(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("text must be a string.")

        if not text:
            return 0

        return max(1, ceil(len(text) / self.characters_per_token))

class GroundingContextBuilder:
    """
    Builds bounded grounding context from ranked retrieval results.

    The input candidate order is treated as authoritative relevance order.

    Responsibilities:
      - preserve retrieval ordering;
      - suppress duplicate chunk identities defensively;
      - suppress redundant overlapping chunks when safe;
      - enforce block and token budgets;
      - preserve canonical chunk content and provenance;
      - report whether relevant candidates were excluded.

    Candidate text is included whole or excluded whole. This preserves a direct relationship between grounding content and its persisted chunk.
    """

    def __init__(self, *, token_estimator: TokenEstimator) -> None:
        if not isinstance(token_estimator, TokenEstimator):
            raise TypeError("token_estimator must be a TokenEstimator instance.")

        self._token_estimator = token_estimator

    @property
    def token_estimator(self) -> TokenEstimator:
        return self._token_estimator

    def build(self, *, retrieval_result: RetrievalResult, budget: GroundingContextBudget) -> GroundingContext:
        if not isinstance(retrieval_result, RetrievalResult):
            raise TypeError("retrieval_result must be a RetrievalResult instance.")

        if not isinstance(budget, GroundingContextBudget):
            raise TypeError("budget must be a GroundingContextBudget instance.")

        if retrieval_result.is_empty:
            return GroundingContext(
                query=retrieval_result.query,
                blocks=(),
                estimated_token_count=0,
                truncated=False,
            )

        selected: list[GroundingContextBlock] = []
        selected_candidates: list[RetrievalCandidate] = []
        seen_chunk_ids = set()
        total_tokens = 0
        excluded_by_budget = False

        for candidate in retrieval_result.candidates:
            if candidate.chunk_id in seen_chunk_ids:
                continue

            seen_chunk_ids.add(candidate.chunk_id)
            if self._is_redundant(candidate=candidate, selected_candidates=selected_candidates):
                continue

            if len(selected) >= budget.max_blocks:
                excluded_by_budget = True
                continue

            block = self._build_block(candidate)
            block_tokens = self._estimate_block_tokens(block)
            if block_tokens > budget.max_tokens:
                excluded_by_budget = True
                continue

            if total_tokens + block_tokens > budget.max_tokens:
                excluded_by_budget = True
                continue

            selected.append(block)
            selected_candidates.append(candidate)
            total_tokens += block_tokens

        return GroundingContext(
            query=retrieval_result.query,
            blocks=tuple(selected),
            estimated_token_count=total_tokens,
            truncated=excluded_by_budget,
        )

    @staticmethod
    def _build_block(candidate: RetrievalCandidate) -> GroundingContextBlock:
        try:
            return GroundingContextBlock.from_candidate(candidate)
        
        except (TypeError, ValueError) as exc:
            raise GroundingContextCandidateError(f"Failed to construct grounding context block for chunk '{candidate.chunk_id}'.") from exc

    def _estimate_block_tokens(self, block: GroundingContextBlock) -> int:
        """
        Estimate the complete textual footprint of a context block.

        Budgeting only ``content`` would systematically undercount the document/section provenance 
        that will also need to be represented to the generation layer.
        """
        text = self._build_estimation_text(block)
        try:
            estimate = self._token_estimator.estimate(text)
            
        except (TypeError, ValueError) as exc:
            raise GroundingContextBudgetError(f"Token estimation failed for grounding chunk '{block.chunk_id}'.") from exc

        if isinstance(estimate, bool) or not isinstance(estimate, int):
            raise GroundingContextBudgetError("Token estimator returned a non-integer result.")

        if estimate < 0:
            raise GroundingContextBudgetError("Token estimator returned a negative result.")

        if text and estimate == 0:
            raise GroundingContextBudgetError("Token estimator returned zero for non-empty text.")

        return estimate

    @staticmethod
    def _build_estimation_text(block: GroundingContextBlock) -> str:
        """
        Construct a stable provider-neutral approximation of the text footprint that the eventual prompt formatter will represent.

        This is intentionally not the final RAG prompt format.
        """
        parts = [block.document_title,]

        if block.section_title is not None:
            parts.append(block.section_title)

        parts.append(block.content)

        return "\n".join(parts)

    @classmethod
    def _is_redundant(cls, *, candidate: RetrievalCandidate, selected_candidates: list[RetrievalCandidate]) -> bool:
        """
        Suppress obvious same-document textual redundancy.

        We intentionally keep this conservative.

        Two chunks from different documents or versions are never treated as duplicates merely because their text happens to be similar.
        Distinct sources may independently support the same statement and that provenance can be useful during grounded generation.

        For the same document version, exact normalized content duplicates and fully-contained content are considered redundant.
        """
        candidate_content = cls._normalize_for_overlap(candidate.content)
        for selected in selected_candidates:
            if candidate.document_id != selected.document_id:
                continue

            if candidate.version_id != selected.version_id:
                continue

            selected_content = cls._normalize_for_overlap(selected.content)
            if candidate_content == selected_content:
                return True

            if candidate_content and candidate_content in selected_content:
                return True

        return False

    @staticmethod
    def _normalize_for_overlap(text: str) -> str:
        """
        Normalize insignificant whitespace for conservative containment checks without changing the canonical text placed into context.
        """
        return " ".join(text.split()).casefold()