# AI-customer-support-agent\tests\integration\api\test_dashboard_analytics_timeout.py
from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from uuid6 import uuid7

from apps.api.app.main import create_api_app
from packages.application.composition.application_factory import (
    create_application,
)
from packages.application.dashboard.analytics_contract import (
    AnalyticsWindow,
)
from packages.database.repositories.dashboard.sqlalchemy_analytics_repository import (
    SQLAlchemyDashboardAnalyticsRepository,
)


_ENDPOINT = "/v1/dashboard/conversation-analytics"


@pytest.fixture()
def analytics_timeout_client(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
    test_session_factory,
    mock_llm_provider,
) -> Generator[TestClient, None, None]:
    # model_copy prevents this test from mutating the shared Settings
    # fixture used by other integration tests.
    timeout_settings = test_settings.model_copy(
        update={
            "dashboard_analytics_statement_timeout_ms": 10,
        }
    )

    services = create_application(
        settings=timeout_settings,
        session_factory=test_session_factory,
        base_provider=mock_llm_provider,
    )

    def deliberately_slow_count(
        *,
        session: Session,
        window: AnalyticsWindow,
    ) -> int:
        del window

        # This statement executes inside _analytics_session(), after its
        # transaction-local 10 ms statement timeout has been configured.
        session.execute(text("SELECT pg_sleep(0.1)"))
        return 0

    monkeypatch.setattr(
        SQLAlchemyDashboardAnalyticsRepository,
        "_count_conversations_created",
        staticmethod(deliberately_slow_count),
    )

    monkeypatch.setattr(
        "apps.api.app.main.get_application_services",
        lambda: services,
    )

    app = create_api_app()

    # If the generic safety-net handler is ever reached unexpectedly,
    # return its HTTP response instead of re-raising into this test.
    with TestClient(
        app,
        raise_server_exceptions=False,
    ) as client:
        yield client


class TestDashboardAnalyticsStatementTimeout:
    def test_returns_safe_503_instead_of_false_200(
        self,
        analytics_timeout_client: TestClient,
        admin_auth_headers: dict[str, str],
    ) -> None:
        trace_id = uuid7()
        ended_at = datetime.now(UTC)
        started_at = ended_at - timedelta(days=1)

        response = analytics_timeout_client.get(
            _ENDPOINT,
            headers={
                **admin_auth_headers,
                "X-Trace-ID": str(trace_id),
            },
            params={
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "bucket": "hour",
            },
        )

        assert response.status_code == 503
        assert response.status_code != 200
        assert response.headers["Retry-After"] == "5"

        body = response.json()

        assert body["error"]["code"] == (
            "DASHBOARD_ANALYTICS_UNAVAILABLE"
        )
        assert body["error"]["message"] == (
            "Dashboard analytics are temporarily unavailable."
        )
        assert UUID(body["error"]["trace_id"]) == trace_id

        serialized = response.text.lower()

        for forbidden in (
            "pg_sleep",
            "statement_timeout",
            "57014",
            "querycanceled",
            "canceling statement",
            "sqlalchemy",
            "psycopg",
            "select ",
        ):
            assert forbidden not in serialized