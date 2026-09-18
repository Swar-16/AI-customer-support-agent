# AI-customer-support-agent\tests\unit\dashboard\test_analytics_cache.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from typing import Any

import pytest

from packages.application.dashboard.analytics_cache import (
    CachingDashboardAnalyticsRepository,
)
from packages.application.dashboard.analytics_contract import (
    AnalyticsBucket,
    AnalyticsWindow,
)


UTC = timezone.utc


class FakeClock:
    def __init__(self) -> None:
        self._value = 1_000.0

    def __call__(self) -> float:
        return self._value

    def advance(self, seconds: float) -> None:
        self._value += seconds


class FakeAnalyticsRepository:
    def __init__(self) -> None:
        self.conversation_result = object()
        self.ai_result = object()
        self.support_result = object()
        self.knowledge_result = object()

        self.conversation_calls = 0
        self.ai_calls = 0
        self.support_calls = 0
        self.knowledge_calls = 0

    def get_conversation_analytics(
        self,
        *,
        window: AnalyticsWindow,
    ) -> Any:
        self.conversation_calls += 1
        return self.conversation_result

    def get_ai_analytics(
        self,
        *,
        window: AnalyticsWindow,
    ) -> Any:
        self.ai_calls += 1
        return self.ai_result

    def get_support_analytics(
        self,
        *,
        window: AnalyticsWindow,
    ) -> Any:
        self.support_calls += 1
        return self.support_result

    def get_knowledge_health(
        self,
        *,
        window: AnalyticsWindow,
    ) -> Any:
        self.knowledge_calls += 1
        return self.knowledge_result


class FailingAnalyticsRepository(FakeAnalyticsRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail = True

    def get_ai_analytics(
        self,
        *,
        window: AnalyticsWindow,
    ) -> Any:
        self.ai_calls += 1

        if self.fail:
            raise RuntimeError("analytics query failed")

        return self.ai_result


class BlockingAnalyticsRepository(FakeAnalyticsRepository):
    def __init__(self) -> None:
        super().__init__()
        self.query_started = Event()
        self.release_query = Event()
        self._counter_lock = Lock()

    def get_ai_analytics(
        self,
        *,
        window: AnalyticsWindow,
    ) -> Any:
        with self._counter_lock:
            self.ai_calls += 1

        self.query_started.set()

        if not self.release_query.wait(timeout=5):
            raise TimeoutError(
                "Test did not release the analytics query."
            )

        return self.ai_result


def analytics_window(
    *,
    day_offset: int = 0,
) -> AnalyticsWindow:
    started_at = datetime(
        2026,
        9,
        1,
        tzinfo=UTC,
    ) + timedelta(days=day_offset)

    return AnalyticsWindow(
        started_at=started_at,
        ended_at=started_at + timedelta(days=1),
        bucket=AnalyticsBucket.HOUR,
    )


class TestCachingDashboardAnalyticsRepository:
    def test_reuses_successful_result_before_expiry(
        self,
    ) -> None:
        repository = FakeAnalyticsRepository()
        clock = FakeClock()

        cached = CachingDashboardAnalyticsRepository(
            repository=repository,
            ttl_seconds=15,
            max_entries=16,
            clock=clock,
        )

        window = analytics_window()

        first = cached.get_ai_analytics(window=window)
        second = cached.get_ai_analytics(window=window)

        assert first is repository.ai_result
        assert second is repository.ai_result
        assert repository.ai_calls == 1

    def test_reloads_result_after_ttl_expiry(
        self,
    ) -> None:
        repository = FakeAnalyticsRepository()
        clock = FakeClock()

        cached = CachingDashboardAnalyticsRepository(
            repository=repository,
            ttl_seconds=15,
            max_entries=16,
            clock=clock,
        )

        window = analytics_window()

        cached.get_ai_analytics(window=window)
        clock.advance(14.999)
        cached.get_ai_analytics(window=window)

        assert repository.ai_calls == 1

        clock.advance(0.001)
        cached.get_ai_analytics(window=window)

        assert repository.ai_calls == 2

    def test_keeps_analytics_namespaces_isolated(
        self,
    ) -> None:
        repository = FakeAnalyticsRepository()

        cached = CachingDashboardAnalyticsRepository(
            repository=repository,
            ttl_seconds=15,
            max_entries=16,
        )

        window = analytics_window()

        conversation = cached.get_conversation_analytics(
            window=window
        )
        ai = cached.get_ai_analytics(window=window)
        support = cached.get_support_analytics(window=window)
        knowledge = cached.get_knowledge_health(window=window)

        # Repeat every request to prove each namespace has its own entry.
        cached.get_conversation_analytics(window=window)
        cached.get_ai_analytics(window=window)
        cached.get_support_analytics(window=window)
        cached.get_knowledge_health(window=window)

        assert conversation is repository.conversation_result
        assert ai is repository.ai_result
        assert support is repository.support_result
        assert knowledge is repository.knowledge_result

        assert repository.conversation_calls == 1
        assert repository.ai_calls == 1
        assert repository.support_calls == 1
        assert repository.knowledge_calls == 1

    def test_evicts_least_recently_used_entry(
        self,
    ) -> None:
        repository = FakeAnalyticsRepository()

        cached = CachingDashboardAnalyticsRepository(
            repository=repository,
            ttl_seconds=60,
            max_entries=2,
        )

        first_window = analytics_window(day_offset=0)
        second_window = analytics_window(day_offset=1)
        third_window = analytics_window(day_offset=2)

        cached.get_ai_analytics(window=first_window)
        cached.get_ai_analytics(window=second_window)

        # Make the first entry most recently used.
        cached.get_ai_analytics(window=first_window)

        # Inserting a third entry must evict the second.
        cached.get_ai_analytics(window=third_window)

        assert repository.ai_calls == 3

        # First remains cached.
        cached.get_ai_analytics(window=first_window)
        assert repository.ai_calls == 3

        # Second was evicted and must be loaded again.
        cached.get_ai_analytics(window=second_window)
        assert repository.ai_calls == 4

    def test_does_not_cache_repository_exceptions(
        self,
    ) -> None:
        repository = FailingAnalyticsRepository()

        cached = CachingDashboardAnalyticsRepository(
            repository=repository,
            ttl_seconds=15,
            max_entries=16,
        )

        window = analytics_window()

        with pytest.raises(
            RuntimeError,
            match="analytics query failed",
        ):
            cached.get_ai_analytics(window=window)

        assert repository.ai_calls == 1

        repository.fail = False

        result = cached.get_ai_analytics(window=window)

        assert result is repository.ai_result
        assert repository.ai_calls == 2

        # The successful retry is now cached.
        repeated = cached.get_ai_analytics(window=window)

        assert repeated is repository.ai_result
        assert repository.ai_calls == 2

    def test_coalesces_concurrent_identical_requests(
        self,
    ) -> None:
        repository = BlockingAnalyticsRepository()

        cached = CachingDashboardAnalyticsRepository(
            repository=repository,
            ttl_seconds=15,
            max_entries=16,
        )

        window = analytics_window()
        request_count = 8

        with ThreadPoolExecutor(
            max_workers=request_count
        ) as executor:
            futures = [
                executor.submit(
                    cached.get_ai_analytics,
                    window=window,
                )
                for _ in range(request_count)
            ]

            assert repository.query_started.wait(timeout=2)

            repository.release_query.set()

            results = [
                future.result(timeout=5)
                for future in futures
            ]

        assert repository.ai_calls == 1
        assert all(
            result is repository.ai_result
            for result in results
        )

    def test_different_windows_are_not_coalesced(
        self,
    ) -> None:
        repository = FakeAnalyticsRepository()

        cached = CachingDashboardAnalyticsRepository(
            repository=repository,
            ttl_seconds=15,
            max_entries=16,
        )

        first_window = analytics_window(day_offset=0)
        second_window = analytics_window(day_offset=1)

        cached.get_ai_analytics(window=first_window)
        cached.get_ai_analytics(window=second_window)

        assert repository.ai_calls == 2

    def test_zero_ttl_disables_caching(
        self,
    ) -> None:
        repository = FakeAnalyticsRepository()

        cached = CachingDashboardAnalyticsRepository(
            repository=repository,
            ttl_seconds=0,
            max_entries=16,
        )

        window = analytics_window()

        cached.get_ai_analytics(window=window)
        cached.get_ai_analytics(window=window)

        assert repository.ai_calls == 2

    def test_clear_removes_cached_results(
        self,
    ) -> None:
        repository = FakeAnalyticsRepository()

        cached = CachingDashboardAnalyticsRepository(
            repository=repository,
            ttl_seconds=15,
            max_entries=16,
        )

        window = analytics_window()

        cached.get_ai_analytics(window=window)
        cached.clear()
        cached.get_ai_analytics(window=window)

        assert repository.ai_calls == 2