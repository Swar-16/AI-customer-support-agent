from __future__ import annotations
import uuid
from uuid6 import uuid7
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import HTTPException

from apps.api.app.api.dependencies import TRACE_HEADER_NAME, get_client_ip, get_services, get_trace_id
from packages.application.composition.application_factory import ApplicationServices

# Helpers
def make_request(*, services: object | None = None, trace_id: object | None = None, client_host: str | None = "127.0.0.1") -> SimpleNamespace:
    """
    Build the smallest request-shaped object required by dependencies.py.

    We intentionally avoid FastAPI TestClient here because these are unit
    tests for dependency functions themselves, not HTTP integration tests.
    """
    app_state = SimpleNamespace()
    if services is not None:
        app_state.application_services = services

    request_state = SimpleNamespace()
    if trace_id is not None:
        request_state.trace_id = trace_id
        
    client = None if client_host is None else SimpleNamespace(host=client_host)
    return SimpleNamespace(
        app=SimpleNamespace(state=app_state),
        state=request_state,
        client=client,
    )


def make_application_services() -> Mock:
    """
    Build a mock satisfying the ApplicationServices runtime shape expected by get_services().

    If ApplicationServices is a dataclass and isinstance() is enforced,
    replace this helper with construction of a real ApplicationServices instance using mocked fields.
    """
    return Mock(spec=ApplicationServices)


# get_services
class TestGetServices:
    def test_returns_application_services_from_app_state(self) -> None:
        services = make_application_services()
        request = make_request(services=services)
        result = get_services(request)

        assert result is services

    def test_raises_when_services_are_missing(self) -> None:
        request = make_request()

        with pytest.raises(RuntimeError, match="Application services have not been initialized"):
            get_services(request)

    def test_raises_when_services_have_invalid_type(self) -> None:
        request = make_request(services=object())

        with pytest.raises(RuntimeError, match="Invalid application services configured"):
            get_services(request)

# get_trace_id
class TestGetTraceId:
    def test_generates_trace_id_when_header_is_missing(self) -> None:
        request = make_request()
        result = get_trace_id(request=request, x_trace_id=None)

        assert isinstance(result, uuid.UUID)
        assert request.state.trace_id == result

    def test_reuses_valid_client_supplied_trace_id(self) -> None:
        supplied = uuid7()
        request = make_request()
        result = get_trace_id(request=request, x_trace_id=str(supplied))

        assert result == supplied
        assert request.state.trace_id == supplied

    def test_strips_whitespace_from_trace_header(self) -> None:
        supplied = uuid7()
        request = make_request()
        result = get_trace_id(request=request, x_trace_id=f"   {supplied}   ")

        assert result == supplied
        assert request.state.trace_id == supplied

    def test_reuses_existing_request_state_trace_id(self) -> None:
        existing = uuid7()
        supplied = uuid7()
        request = make_request(trace_id=existing)
        result = get_trace_id(request=request, x_trace_id=str(supplied))

        assert result == existing

    def test_existing_trace_id_takes_precedence_over_header(self) -> None:
        existing = uuid7()
        request = make_request(trace_id=existing)
        result = get_trace_id(request=request, x_trace_id=None)

        assert result == existing

    def test_rejects_invalid_existing_trace_id_type(self) -> None:
        request = make_request(trace_id="not-a-uuid-object")

        with pytest.raises(RuntimeError, match="request.state.trace_id must be a UUID"):
            get_trace_id(request=request, x_trace_id=None)

    def test_rejects_empty_trace_header(self) -> None:
        request = make_request()

        with pytest.raises(HTTPException) as exc_info:
            get_trace_id(request=request, x_trace_id="   ")

        exc = exc_info.value

        assert exc.status_code == 400
        assert exc.detail == {
            "code": "INVALID_TRACE_ID",
            "message": (f"{TRACE_HEADER_NAME} cannot be empty."),
        }
        assert not hasattr(request.state, "trace_id")

    @pytest.mark.parametrize("invalid_trace_id", ["not-a-uuid", "1234", "abc-def", "550e8400-e29b-41d4-a716", "null"])
    def test_rejects_malformed_trace_header(self, invalid_trace_id: str) -> None:
        request = make_request()

        with pytest.raises(HTTPException) as exc_info:
            get_trace_id(request=request, x_trace_id=invalid_trace_id)

        exc = exc_info.value

        assert exc.status_code == 400
        assert exc.detail == {
            "code": "INVALID_TRACE_ID",
            "message": (f"{TRACE_HEADER_NAME} must contain a valid UUID."),
        }

    @pytest.mark.parametrize("trace_id", [uuid.uuid1(),uuid7()])
    def test_accepts_multiple_valid_uuid_versions(self, trace_id: uuid.UUID) -> None:
        request = make_request()
        result = get_trace_id(request=request, x_trace_id=str(trace_id))

        assert result == trace_id

    def test_generated_trace_ids_are_not_reused_between_requests(self) -> None:
        first_request = make_request()
        second_request = make_request()
        first = get_trace_id(request=first_request, x_trace_id=None)
        second = get_trace_id(request=second_request, x_trace_id=None)

        assert first != second

# get_client_ip
class TestGetClientIp:
    def test_returns_direct_client_ip(self) -> None:
        request = make_request(client_host="192.168.1.10")

        assert get_client_ip(request) == "192.168.1.10"

    def test_returns_none_when_client_is_unavailable(self) -> None:
        request = make_request(client_host=None)

        assert get_client_ip(request) is None

    def test_does_not_depend_on_forwarded_headers(self) -> None:
        """
        Client IP resolution deliberately uses request.client only.

        Trusting X-Forwarded-For directly here would allow arbitrary callers
        to spoof their source IP unless proxy trust is configured centrally.
        """
        request = make_request(client_host="10.0.0.8")

        request.headers = {
            "X-Forwarded-For": "203.0.113.10",
        }

        assert get_client_ip(request) == "10.0.0.8"