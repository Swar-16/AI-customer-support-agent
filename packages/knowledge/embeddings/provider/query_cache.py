# AI-customer-support-agent\packages\knowledge\embeddings\provider\query_cache.py
from __future__ import annotations
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from threading import Event, RLock
from time import monotonic

from packages.knowledge.embeddings.models import EmbeddingProviderDescriptor, EmbeddingVector

@dataclass(frozen=True, slots=True)
class QueryEmbeddingCacheResult:
    vector: EmbeddingVector
    cache_hit: bool
    waited_for_inflight: bool

@dataclass(frozen=True, slots=True)
class _CacheEntry:
    vector: EmbeddingVector
    expires_at: float

class QueryEmbeddingCache:
    """
    Process-local bounded TTL cache for retrieval-query embeddings.

    Security and correctness properties:
    - raw query text is never retained as a cache key;
    - cache keys include the complete provider descriptor identity;
    - document embeddings are not supported;
    - failed computations are never cached;
    - simultaneous identical misses are collapsed into one computation;
    - storage is bounded using LRU eviction.
    """
    CACHE_KEY_VERSION = "query-embedding-cache-v1"

    def __init__(self, *, max_entries: int = 512, ttl_seconds: float = 3_600.0) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int):
            raise TypeError("max_entries must be an integer")

        if max_entries <= 0:
            raise ValueError("max_entries must be greater than zero")

        if max_entries > 100_000:
            raise ValueError("max_entries cannot exceed 100000")

        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise TypeError("ttl_seconds must be numeric")

        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")

        if ttl_seconds > 86_400:
            raise ValueError("ttl_seconds cannot exceed 86400 seconds")

        self._max_entries = max_entries
        self._ttl_seconds = float(ttl_seconds)
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._inflight: dict[str, Event] = {}
        self._lock = RLock()
        self._hits = 0
        self._misses = 0
        self._inflight_waits = 0
        self._evictions = 0

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    @property
    def size(self) -> int:
        with self._lock:
            self._remove_expired_entries(now=monotonic())
            return len(self._entries)

    @property
    def hits(self) -> int:
        with self._lock:
            return self._hits

    @property
    def misses(self) -> int:
        with self._lock:
            return self._misses

    @property
    def inflight_waits(self) -> int:
        with self._lock:
            return self._inflight_waits

    @property
    def evictions(self) -> int:
        with self._lock:
            return self._evictions

    def get_or_compute(self, *, text: str, descriptor: EmbeddingProviderDescriptor, loader: Callable[[], EmbeddingVector]) -> QueryEmbeddingCacheResult:
        """
        Return a cached vector or compute it exactly once.

        Waiting callers receive the result produced by the request currently responsible for the same cache key.
        """
        if not isinstance(text, str):
            # Preserve the wrapped provider's validation and exception type.
            return QueryEmbeddingCacheResult(vector=loader(), cache_hit=False, waited_for_inflight=False)

        if not isinstance(descriptor, EmbeddingProviderDescriptor):
            raise TypeError("descriptor must be an EmbeddingProviderDescriptor instance")

        if not callable(loader):
            raise TypeError("loader must be callable")

        key = self._build_key(text=text, descriptor=descriptor)
        waited_for_inflight = False

        while True:
            now = monotonic()
            with self._lock:
                cached = self._entries.get(key)
                if cached is not None:
                    if cached.expires_at > now:
                        self._entries.move_to_end(key)
                        self._hits += 1

                        return QueryEmbeddingCacheResult(vector=cached.vector, cache_hit=True, waited_for_inflight=waited_for_inflight)

                    del self._entries[key]

                inflight_event = self._inflight.get(key)
                if inflight_event is None:
                    inflight_event = Event()
                    self._inflight[key] = inflight_event
                    self._misses += 1
                    break

                self._inflight_waits += 1
                waited_for_inflight = True

            # Never hold the cache lock while waiting for provider execution.
            inflight_event.wait()

        try:
            vector = loader()
            if not isinstance(vector, EmbeddingVector):
                raise TypeError("query embedding loader must return an EmbeddingVector")

        except BaseException:
            self._release_inflight(key)
            raise

        with self._lock:
            self._entries[key] = _CacheEntry(
                vector=vector,
                expires_at=monotonic() + self._ttl_seconds,
            )
            self._entries.move_to_end(key)
            self._evict_if_required()
            completed_event = self._inflight.pop(key, None)
            if completed_event is not None:
                completed_event.set()

        return QueryEmbeddingCacheResult(vector=vector, cache_hit=False, waited_for_inflight=False)

    def clear(self) -> None:
        """
        Remove completed cache entries.

        In-flight computations are deliberately not interrupted.
        """
        with self._lock:
            self._entries.clear()

    def _release_inflight(self, key: str) -> None:
        with self._lock:
            completed_event = self._inflight.pop(key, None)
            if completed_event is not None:
                completed_event.set()

    def _evict_if_required(self) -> None:
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
            self._evictions += 1

    def _remove_expired_entries(self, *, now: float) -> None:
        expired_keys = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired_keys:
            del self._entries[key]

    @classmethod
    def _build_key(cls, *, text: str, descriptor: EmbeddingProviderDescriptor) -> str:
        """
        Build a non-reversible key without retaining customer query text.

        Exact text is hashed rather than normalized so cache behavior never changes provider-input semantics.
        """
        digest = sha256()
        digest.update(cls.CACHE_KEY_VERSION.encode("utf-8"))
        digest.update(b"\0")
        digest.update(descriptor.identity.encode("utf-8"))
        digest.update(b"\0")
        payload = text.encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)

        return digest.hexdigest()