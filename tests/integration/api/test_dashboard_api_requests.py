# AI-customer-support-agent\tests\integration\api\test_dashboard_api_requests.py

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolate_database(clean_database):
    """Keep API-request dashboard assertions isolated."""
    yield


def _record_health_request(
    *,
    client: TestClient,
    trace_id: uuid.UUID,
) -> None:
    response = client.get(
        "/v1/health",
        headers={
            "X-Trace-ID": str(trace_id),
        },
    )

    assert response.status_code == 200


class TestDashboardAPIRequests:
    def test_returns_correlated_api_request(
        self,
        client: TestClient,
    ) -> None:
        trace_id = uuid7()

        _record_health_request(
            client=client,
            trace_id=trace_id,
        )

        response = client.get(
            "/v1/dashboard/api-requests",
            params={
                "trace_id": str(trace_id),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1
        assert body["limit"] == 100
        assert body["offset"] == 0
        assert body["has_more"] is False
        assert body["next_offset"] is None

        request = body["items"][0]

        assert uuid.UUID(request["id"])
        assert request["trace_id"] == str(trace_id)
        assert request["method"] == "GET"
        assert request["route_template"] == "/v1/health"
        assert request["status_code"] == 200
        assert request["outcome"] == "success"
        assert request["error_code"] is None
        assert request["latency_ms"] >= 0
        assert request["started_at"] is not None
        assert request["completed_at"] is not None

    def test_filters_by_request_properties(
        self,
        client: TestClient,
    ) -> None:
        trace_id = uuid7()

        _record_health_request(
            client=client,
            trace_id=trace_id,
        )

        response = client.get(
            "/v1/dashboard/api-requests",
            params={
                "trace_id": str(trace_id),
                "method": "GET",
                "route_template": "/v1/health",
                "status_code": 200,
                "outcome": "success",
                "minimum_latency_ms": 0,
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1
        assert body["count"] == 1

        request = body["items"][0]

        assert request["trace_id"] == str(trace_id)
        assert request["method"] == "GET"
        assert request["route_template"] == "/v1/health"
        assert request["status_code"] == 200
        assert request["outcome"] == "success"

    def test_filters_client_error_request(
        self,
        client: TestClient,
    ) -> None:
        trace_id = uuid7()

        missing_response = client.get(
            "/v1/path-that-does-not-exist",
            headers={
                "X-Trace-ID": str(trace_id),
            },
        )

        assert missing_response.status_code == 404

        response = client.get(
            "/v1/dashboard/api-requests",
            params={
                "trace_id": str(trace_id),
                "status_code": 404,
                "outcome": "client_error",
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["total"] == 1

        request = body["items"][0]

        assert request["trace_id"] == str(trace_id)
        assert request["status_code"] == 404
        assert request["outcome"] == "client_error"

    def test_non_matching_trace_returns_empty_page(
        self,
        client: TestClient,
    ) -> None:
        _record_health_request(
            client=client,
            trace_id=uuid7(),
        )

        response = client.get(
            "/v1/dashboard/api-requests",
            params={
                "trace_id": str(uuid7()),
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["items"] == []
        assert body["total"] == 0
        assert body["count"] == 0
        assert body["has_more"] is False
        assert body["next_offset"] is None

    def test_paginates_filtered_requests_without_duplicates(
        self,
        client: TestClient,
    ) -> None:
        _record_health_request(
            client=client,
            trace_id=uuid7(),
        )
        _record_health_request(
            client=client,
            trace_id=uuid7(),
        )

        shared_parameters = {
            "route_template": "/v1/health",
            "limit": 1,
        }

        first_response = client.get(
            "/v1/dashboard/api-requests",
            params={
                **shared_parameters,
                "offset": 0,
            },
        )
        second_response = client.get(
            "/v1/dashboard/api-requests",
            params={
                **shared_parameters,
                "offset": 1,
            },
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200

        first_body = first_response.json()
        second_body = second_response.json()

        assert first_body["total"] == 2
        assert second_body["total"] == 2
        assert first_body["count"] == 1
        assert second_body["count"] == 1

        assert first_body["has_more"] is True
        assert first_body["next_offset"] == 1
        assert second_body["has_more"] is False
        assert second_body["next_offset"] is None

        assert (
            first_body["items"][0]["id"]
            != second_body["items"][0]["id"]
        )

    def test_rejects_invalid_filters(
        self,
        client: TestClient,
    ) -> None:
        invalid_method = client.get(
            "/v1/dashboard/api-requests",
            params={
                "method": "CONNECT",
            },
        )
        invalid_status_code = client.get(
            "/v1/dashboard/api-requests",
            params={
                "status_code": 999,
            },
        )
        invalid_outcome = client.get(
            "/v1/dashboard/api-requests",
            params={
                "outcome": "maybe",
            },
        )
        invalid_latency = client.get(
            "/v1/dashboard/api-requests",
            params={
                "minimum_latency_ms": -1,
            },
        )

        assert invalid_method.status_code == 422
        assert invalid_status_code.status_code == 422
        assert invalid_outcome.status_code == 422
        assert invalid_latency.status_code == 422

    def test_does_not_expose_sensitive_request_data(
        self,
        client: TestClient,
    ) -> None:
        trace_id = uuid7()

        _record_health_request(
            client=client,
            trace_id=trace_id,
        )

        response = client.get(
            "/v1/dashboard/api-requests",
            params={
                "trace_id": str(trace_id),
            },
        )

        assert response.status_code == 200

        request = response.json()["items"][0]

        prohibited_fields = {
            "request_path",
            "client_ip",
            "user_agent",
            "exception_type",
            "metadata",
            "metadata_",
            "authorization",
            "cookie",
            "headers",
            "request_body",
            "response_body",
        }

        assert set(request).isdisjoint(prohibited_fields)