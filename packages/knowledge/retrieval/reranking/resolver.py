from __future__ import annotations
from collections.abc import Mapping
from types import MappingProxyType

from packages.knowledge.retrieval.errors import RerankerResolutionError
from packages.knowledge.retrieval.reranking.base import Reranker


class RerankerResolver:
    """
    Immutable registry for reranking implementations.

    The resolver maps a stable reranker identifier to a concrete Reranker implementation.

    It is intentionally immutable after construction so runtime code cannot register/unregister implementations unpredictably.
    """
    def __init__(self, *, rerankers: Mapping[str, Reranker]) -> None:
        if not isinstance(rerankers, Mapping):
            raise TypeError("rerankers must be a mapping.")

        normalized: dict[str, Reranker] = {}

        for reranker_id, reranker in rerankers.items():
            normalized_id = self._normalize_id(reranker_id)

            if not isinstance(reranker, Reranker):
                raise TypeError(f"reranker '{normalized_id}' must be a Reranker instance.")

            if normalized_id in normalized:
                raise ValueError(f"duplicate reranker identifier after normalization: '{normalized_id}'.")

            descriptor_id = self._normalize_id(reranker.descriptor.reranker_id)
            if descriptor_id != normalized_id:
                raise ValueError(f"reranker registry key does not match the reranker's descriptor ID: key='{normalized_id}', descriptor='{descriptor_id}'.")

            normalized[normalized_id] = reranker

        self._rerankers: Mapping[str, Reranker] = MappingProxyType(normalized)

    def resolve(self, reranker_id: str) -> Reranker:
        normalized_id = self._normalize_id(reranker_id)
        reranker = self._rerankers.get(normalized_id)

        if reranker is None:
            raise RerankerResolutionError(normalized_id)

        return reranker

    def contains(self, reranker_id: str) -> bool:
        normalized_id = self._normalize_id(reranker_id)

        return normalized_id in self._rerankers

    @property
    def available_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._rerankers.keys()))

    @property
    def count(self) -> int:
        return len(self._rerankers)

    @staticmethod
    def _normalize_id(reranker_id: str) -> str:
        if not isinstance(reranker_id, str):
            raise TypeError("reranker_id must be a string.")

        normalized = reranker_id.strip().lower()
        if not normalized:
            raise ValueError("reranker_id must not be blank.")

        return normalized