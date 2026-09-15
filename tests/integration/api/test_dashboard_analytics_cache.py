# AI-customer-support-agent\tests\integration\api\test_dashboard_analytics_cache.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from typing import Any
import pytest

from fastapi.testclient import TestClient

from packages.application.composition.application_factory import (
    ApplicationServices,
)
from packages.application.dashboard.analytics_cache import (
    CachingDashboardAnalyticsRepository,
)
from packages.database.repositories.dashboard.sqlalchemy_analytics_repository import (
    SQLAlchemyDashboardAnalyticsRepository,
)


UTC = timezone.utc


def _analytics_params(
    *,
    day_offset: int = 0,
) -> dict[str, str]:
    started_at = datetime(
        2026,
        9,
        1,
        tzinfo=UTC,
    ) + timedelta(days=day_offset)

    ended_at = started_at + timedelta(days=1)

    return {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "bucket": "hour",
    }


class TestDashboardAnalyticsCacheComposition:
    def test_application_services_share_one_cache_instance(
        self,
        application_services: ApplicationServices,
    ) -> None:
        conversation_repository = (
            application_services
            .get_conversation_analytics
            ._repository_factory()
        )
        ai_repository = (
            application_services
            .get_ai_analytics
            ._repository_factory()
        )
        support_repository = (
            application_services
            .get_support_analytics
            ._repository_factory()
        )
        knowledge_repository = (
            application_services
            .get_knowledge_health
            ._repository_factory()
        )

        assert isinstance(
            conversation_repository,
            CachingDashboardAnalyticsRepository,
        )

        assert conversation_repository is ai_repository
        assert conversation_repository is support_repository
        assert conversation_repository is knowledge_repository


class TestDashboardAnalyticsCacheAPI:
    def test_identical_requests_execute_repository_once(
        self,
        admin_client: TestClient,
        monkeypatch,
    ) -> None:
        original = (
            SQLAlchemyDashboardAnalyticsRepository
            .get_conversation_analytics
        )
        call_count = 0
        count_lock = Lock()

        def counted_get_conversation_analytics(
            repository: SQLAlchemyDashboardAnalyticsRepository,
            *,
            window,
        ):
            nonlocal call_count

            with count_lock:
                call_count += 1

            return original(
                repository,
                window=window,
            )

        monkeypatch.setattr(
            SQLAlchemyDashboardAnalyticsRepository,
            "get_conversation_analytics",
            counted_get_conversation_analytics,
        )

        params = _analytics_params()

        first = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=params,
        )
        second = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=params,
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert second.json() == first.json()
        assert call_count == 1

    def test_different_windows_do_not_share_cache_entries(
        self,
        admin_client: TestClient,
        monkeypatch,
    ) -> None:
        original = (
            SQLAlchemyDashboardAnalyticsRepository
            .get_conversation_analytics
        )
        call_count = 0

        def counted_get_conversation_analytics(
            repository: SQLAlchemyDashboardAnalyticsRepository,
            *,
            window,
        ):
            nonlocal call_count
            call_count += 1

            return original(
                repository,
                window=window,
            )

        monkeypatch.setattr(
            SQLAlchemyDashboardAnalyticsRepository,
            "get_conversation_analytics",
            counted_get_conversation_analytics,
        )

        first = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(day_offset=0),
        )
        second = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=_analytics_params(day_offset=1),
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert call_count == 2

    def test_different_endpoints_use_isolated_namespaces(
        self,
        admin_client: TestClient,
        monkeypatch,
    ) -> None:
        original_conversation = (
            SQLAlchemyDashboardAnalyticsRepository
            .get_conversation_analytics
        )
        original_ai = (
            SQLAlchemyDashboardAnalyticsRepository
            .get_ai_analytics
        )

        conversation_calls = 0
        ai_calls = 0

        def counted_conversation(
            repository: SQLAlchemyDashboardAnalyticsRepository,
            *,
            window,
        ):
            nonlocal conversation_calls
            conversation_calls += 1

            return original_conversation(
                repository,
                window=window,
            )

        def counted_ai(
            repository: SQLAlchemyDashboardAnalyticsRepository,
            *,
            window,
        ):
            nonlocal ai_calls
            ai_calls += 1

            return original_ai(
                repository,
                window=window,
            )

        monkeypatch.setattr(
            SQLAlchemyDashboardAnalyticsRepository,
            "get_conversation_analytics",
            counted_conversation,
        )
        monkeypatch.setattr(
            SQLAlchemyDashboardAnalyticsRepository,
            "get_ai_analytics",
            counted_ai,
        )

        params = _analytics_params()

        conversation_first = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=params,
        )
        ai_first = admin_client.get(
            "/v1/dashboard/ai-analytics",
            params=params,
        )
        conversation_second = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=params,
        )
        ai_second = admin_client.get(
            "/v1/dashboard/ai-analytics",
            params=params,
        )

        assert conversation_first.status_code == 200
        assert ai_first.status_code == 200
        assert conversation_second.status_code == 200
        assert ai_second.status_code == 200

        assert conversation_calls == 1
        assert ai_calls == 1

    def test_repository_failure_is_not_cached(
        self,
        admin_client: TestClient,
        monkeypatch,
    ) -> None:
        original = (
            SQLAlchemyDashboardAnalyticsRepository
            .get_conversation_analytics
        )
        call_count = 0

        def fail_once(
            repository: SQLAlchemyDashboardAnalyticsRepository,
            *,
            window,
        ):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                raise RuntimeError(
                    "deterministic analytics failure"
                )

            return original(
                repository,
                window=window,
            )

        monkeypatch.setattr(
            SQLAlchemyDashboardAnalyticsRepository,
            "get_conversation_analytics",
            fail_once,
        )

        params = _analytics_params()

        with pytest.raises(
            RuntimeError,
            match="deterministic analytics failure",
        ):
            admin_client.get(
                "/v1/dashboard/conversation-analytics",
                params=params,
            )

        # The failed result must not have entered the cache.
        second = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=params,
        )

        assert second.status_code == 200, second.text
        assert call_count == 2

        # The successful retry should now be cached.
        third = admin_client.get(
            "/v1/dashboard/conversation-analytics",
            params=params,
        )

        assert third.status_code == 200, third.text
        assert third.json() == second.json()
        assert call_count == 2

    def test_concurrent_identical_requests_are_coalesced(
        self,
        admin_client: TestClient,
        monkeypatch,
    ) -> None:
        original = (
            SQLAlchemyDashboardAnalyticsRepository
            .get_conversation_analytics
        )

        query_started = Event()
        release_query = Event()
        count_lock = Lock()
        call_count = 0

        def blocking_get_conversation_analytics(
            repository: SQLAlchemyDashboardAnalyticsRepository,
            *,
            window,
        ):
            nonlocal call_count

            with count_lock:
                call_count += 1

            query_started.set()

            if not release_query.wait(timeout=5):
                raise TimeoutError(
                    "Test did not release repository query."
                )

            return original(
                repository,
                window=window,
            )

        monkeypatch.setattr(
            SQLAlchemyDashboardAnalyticsRepository,
            "get_conversation_analytics",
            blocking_get_conversation_analytics,
        )

        params = _analytics_params()
        request_count = 6

        def execute_request() -> Any:
            return admin_client.get(
                "/v1/dashboard/conversation-analytics",
                params=params,
            )

        with ThreadPoolExecutor(
            max_workers=request_count
        ) as executor:
            futures = [
                executor.submit(execute_request)
                for _ in range(request_count)
            ]

            assert query_started.wait(timeout=2)
            release_query.set()

            responses = [
                future.result(timeout=10)
                for future in futures
            ]

        assert all(
            response.status_code == 200
            for response in responses
        )
        assert call_count == 1

        expected_body = responses[0].json()
        assert all(
            response.json() == expected_body
            for response in responses
        )