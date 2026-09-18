# AI-customer-support-agent\packages\application\dashboard\analytics_cache.py
from __future__ import annotations
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, RLock
from typing import TypeVar, cast

from packages.application.dashboard.analytics_contract import AnalyticsWindow
from packages.application.dashboard.analytics_models import AIAnalyticsResult, ConversationAnalyticsResult, KnowledgeHealthResult, SupportAnalyticsResult
from packages.application.dashboard.analytics_repository import DashboardAnalyticsRepository

AnalyticsResult = (ConversationAnalyticsResult | AIAnalyticsResult | SupportAnalyticsResult | KnowledgeHealthResult)
ResultT = TypeVar("ResultT", bound=AnalyticsResult)

@dataclass(frozen=True, slots=True)
class _CacheKey:
    namespace: str
    window: AnalyticsWindow

@dataclass(frozen=True, slots=True)
class _CacheEntry:
    value: AnalyticsResult
    expires_at: float

@dataclass(slots=True)
class _InFlight:
    completed: Event
    error: BaseException | None = None

class CachingDashboardAnalyticsRepository(DashboardAnalyticsRepository):
    """
    Thread-safe, process-local cache for dashboard analytics.

    Successful results are cached for a bounded period. Errors and incomplete results are never cached.

    Concurrent requests for the same analytics window are coalesced so only one underlying database query executes.

    This cache is intentionally process-local. In a multi-worker deployment, each worker maintains its own bounded cache.
    """
    def __init__(self, *, repository: DashboardAnalyticsRepository, ttl_seconds: int = 15, max_entries: int = 256, clock: Callable[[], float] = time.monotonic) -> None:
        self._validate_repository(repository)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
            raise TypeError("ttl_seconds must be an integer.")

        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be greater than or equal to zero.")

        if isinstance(max_entries, bool) or not isinstance(max_entries, int):
            raise TypeError("max_entries must be an integer.")

        if max_entries < 1:
            raise ValueError("max_entries must be greater than or equal to one.")

        if not callable(clock):
            raise TypeError("clock must be callable.")

        self._repository = repository
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[_CacheKey, _CacheEntry] = OrderedDict()
        self._in_flight: dict[_CacheKey, _InFlight] = {}
        self._lock = RLock()

    def get_conversation_analytics(self, *, window: AnalyticsWindow) -> ConversationAnalyticsResult:
        return self._get_or_load(
            namespace="conversation",
            window=window,
            loader=lambda: self._repository.get_conversation_analytics(window=window),
        )

    def get_ai_analytics(self, *, window: AnalyticsWindow) -> AIAnalyticsResult:
        return self._get_or_load(
            namespace="ai",
            window=window,
            loader=lambda: self._repository.get_ai_analytics(window=window),
        )

    def get_support_analytics(self, *, window: AnalyticsWindow) -> SupportAnalyticsResult:
        return self._get_or_load(
            namespace="support",
            window=window,
            loader=lambda: self._repository.get_support_analytics(window=window),
        )

    def get_knowledge_health(self, *, window: AnalyticsWindow) -> KnowledgeHealthResult:
        return self._get_or_load(
            namespace="knowledge",
            window=window,
            loader=lambda: self._repository.get_knowledge_health(window=window),
        )

    def clear(self) -> None:
        """
        Remove all successfully cached analytics results.

        Queries already executing are allowed to finish normally.
        """
        with self._lock:
            self._entries.clear()

    def _get_or_load(self, *, namespace: str, window: AnalyticsWindow, loader: Callable[[], ResultT]) -> ResultT:
        if not isinstance(window, AnalyticsWindow):
            raise TypeError("window must be an AnalyticsWindow.")

        # A zero TTL explicitly disables caching and request coalescing.
        if self._ttl_seconds == 0:
            return loader()

        key = _CacheKey(namespace=namespace, window=window)
        while True:
            now = self._clock()
            with self._lock:
                self._remove_expired_entries(now=now)

                cached = self._entries.get(key)
                if cached is not None:
                    self._entries.move_to_end(key)
                    return cast(ResultT, cached.value)

                in_flight = self._in_flight.get(key)
                if in_flight is None:
                    in_flight = _InFlight(completed=Event())
                    self._in_flight[key] = in_flight
                    is_loader = True
                else:
                    is_loader = False

            if is_loader:
                return self._load_and_publish(key=key, in_flight=in_flight, loader=loader)

            # Do not hold the cache lock while another request queries PostgreSQL.
            in_flight.completed.wait()
            if in_flight.error is not None:
                raise in_flight.error

            # The successful loader inserted the result. Loop once to retrieve it through the normal expiry/LRU path.

    def _load_and_publish(self, *, key: _CacheKey, in_flight: _InFlight, loader: Callable[[], ResultT]) -> ResultT:
        try:
            result = loader()
            
        except BaseException as exc:
            # Wake every waiter, but never store a failed query in the result cache.
            with self._lock:
                in_flight.error = exc
                self._in_flight.pop(key, None)
                in_flight.completed.set()

            raise

        expires_at = self._clock() + self._ttl_seconds
        with self._lock:
            self._entries[key] = _CacheEntry(value=result, expires_at=expires_at)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

            self._in_flight.pop(key, None)
            in_flight.completed.set()

        return result

    def _remove_expired_entries(self, *, now: float) -> None:
        expired_keys = tuple(key for key, entry in self._entries.items() if entry.expires_at <= now)
        for key in expired_keys:
            self._entries.pop(key, None)

    @staticmethod
    def _validate_repository(repository: DashboardAnalyticsRepository) -> None:
        required_methods = ("get_conversation_analytics", "get_ai_analytics", "get_support_analytics", "get_knowledge_health",)
        for method_name in required_methods:
            if not callable(getattr(repository, method_name, None)):
                raise TypeError(f"repository must implement {method_name}().")