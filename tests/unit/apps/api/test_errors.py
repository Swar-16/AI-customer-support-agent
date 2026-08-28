from __future__ import annotations
import uuid
from uuid6 import uuid7
from types import SimpleNamespace
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from apps.api.app.api.errors import (
    ERROR_CONVERSATION_NOT_FOUND,
    ERROR_CONVERSATION_NOT_PROCESSABLE,
    ERROR_INTERNAL,
    ERROR_INVALID_CUSTOMER_MESSAGE,
    ERROR_INVALID_REQUEST,
    conversation_not_found_handler,
    conversation_not_processable_handler,
    customer_message_validation_handler,
    http_exception_handler,
    request_validation_exception_handler,
    unhandled_exception_handler,
)
from apps.api.app.api.dependencies import TRACE_HEADER_NAME
from packages.application.conversations.process_customer_message import (
    ConversationDoesNotExistError,
    ConversationNotProcessableError,
    CustomerMessageValidationError,
)

# Helpers
def make_request(*, trace_id: uuid.UUID | None = None, method: str = "POST", path: str = "/v1/conversations/example/messages") -> SimpleNamespace:
    """
    Build the smallest Request-shaped object needed by API exception
    handlers.

    These are unit tests for exception translation rather than full HTTP
    integration tests, so a lightweight request double is appropriate.
    """
    state = SimpleNamespace()
    if trace_id is not None:
        state.trace_id = trace_id
        
    return SimpleNamespace(state=state, method=method, url=SimpleNamespace(path=path))

def response_json(response) -> dict:
    """
    Decode JSONResponse content for assertions.
    """
    import json
    return json.loads(response.body.decode("utf-8"))

# Conversation not found
class TestConversationNotFoundHandler:
    @pytest.mark.asyncio
    async def test_maps_to_404(self) -> None:
        trace_id = uuid7()
        request = make_request(trace_id=trace_id)
        exc = ConversationDoesNotExistError("conversation missing")
        response = await conversation_not_found_handler(request, exc)
        body = response_json(response)

        assert response.status_code == 404
        assert body == {
            "error": {
                "code": ERROR_CONVERSATION_NOT_FOUND,
                "message": "The requested conversation does not exist.",
                "trace_id": str(trace_id),
            }
        }
        assert response.headers[TRACE_HEADER_NAME] == str(trace_id)

    @pytest.mark.asyncio
    async def test_does_not_expose_exception_message(self) -> None:
        request = make_request()
        secret_detail = "conversation lookup failed on internal_table_xyz"
        exc = ConversationDoesNotExistError(secret_detail)
        response = await conversation_not_found_handler(request, exc)
        body = response_json(response)

        assert secret_detail not in str(body)

# Conversation not processable
class TestConversationNotProcessableHandler:
    @pytest.mark.asyncio
    async def test_maps_to_409(self) -> None:
        trace_id = uuid7()
        request = make_request(trace_id=trace_id)
        exc = ConversationNotProcessableError("closed conversation")
        response = await conversation_not_processable_handler(request, exc)
        body = response_json(response)

        assert response.status_code == 409
        assert body["error"]["code"] == ERROR_CONVERSATION_NOT_PROCESSABLE
        assert body["error"]["trace_id"] == str(trace_id)

    @pytest.mark.asyncio
    async def test_returns_stable_public_message(self) -> None:
        request = make_request()
        exc = ConversationNotProcessableError("INTERNAL STATUS=ARCHIVED")
        response = await conversation_not_processable_handler(request, exc)
        body = response_json(response)

        assert body["error"]["message"] == "The conversation cannot accept a new customer message in its current state."
        assert "ARCHIVED" not in str(body)

# Customer message validation
class TestCustomerMessageValidationHandler:
    @pytest.mark.asyncio
    async def test_maps_to_400(self) -> None:
        trace_id = uuid7()
        request = make_request(trace_id=trace_id)
        exc = CustomerMessageValidationError("message invalid")
        response = await customer_message_validation_handler(request, exc)
        body = response_json(response)

        assert response.status_code == 400
        assert body["error"]["code"] == ERROR_INVALID_CUSTOMER_MESSAGE
        assert body["error"]["trace_id"] == str(trace_id)

    @pytest.mark.asyncio
    async def test_hides_internal_validation_details(self) -> None:
        request = make_request()
        exc = CustomerMessageValidationError("raw internal validation metadata")
        response = await customer_message_validation_handler(request, exc)
        body = response_json(response)

        assert "raw internal validation metadata" not in str(body)


# FastAPI request validation
class TestRequestValidationExceptionHandler:
    @pytest.mark.asyncio
    async def test_maps_request_validation_to_422(self) -> None:
        trace_id = uuid7()
        request = make_request(trace_id=trace_id)
        exc = RequestValidationError([
            {
                "type": "string_too_short",
                "loc": ("body", "message",),
                "msg": "String should have at least 1 character",
                "input": "",
            }]
        )
        response = await request_validation_exception_handler(request, exc)
        body = response_json(response)

        assert response.status_code == 422
        assert body["error"]["code"] == ERROR_INVALID_REQUEST
        assert body["error"]["trace_id"] == str(trace_id)
        assert body["error"]["details"] == [
            {
                "location": ["body", "message"],
                "message": "String should have at least 1 character",
                "type": "string_too_short",
            }
        ]

    @pytest.mark.asyncio
    async def test_does_not_return_rejected_input(self) -> None:
        request = make_request()
        sensitive_input = "customer-secret-input-value"
        exc = RequestValidationError([
            {
                "type": "string_type",
                "loc": ("body", "message",),
                "msg": "Input should be a valid string",
                "input": sensitive_input,
            }]
        )
        response = await request_validation_exception_handler(request, exc)
        body = response_json(response)

        assert sensitive_input not in str(body)

    @pytest.mark.asyncio
    async def test_generates_trace_id_when_dependency_never_ran(self) -> None:
        request = make_request()

        assert not hasattr(request.state, "trace_id")

        response = await request_validation_exception_handler(request,
                                                              RequestValidationError([
                                                                        {
                                                                            "type": "missing",
                                                                            "loc": ("body", "message",),
                                                                            "msg": "Field required",
                                                                            "input": {},
                                                                        }]
                ),
        )
        generated = request.state.trace_id
        assert isinstance(generated, uuid.UUID)

        body = response_json(response)
        assert body["error"]["trace_id"] == str(generated)
        assert response.headers[TRACE_HEADER_NAME] == str(generated)

# HTTPException
class TestHTTPExceptionHandler:
    @pytest.mark.asyncio
    async def test_preserves_structured_code_and_message(self) -> None:
        trace_id = uuid7()
        request = make_request(trace_id=trace_id)
        exc = HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_TRACE_ID",
                "message": "X-Trace-ID must contain a valid UUID.",
            },
        )
        response = await http_exception_handler(request, exc)
        body = response_json(response)

        assert response.status_code == 400
        assert body == {
            "error": {
                "code": "INVALID_TRACE_ID",
                "message": "X-Trace-ID must contain a valid UUID.",
                "trace_id": str(trace_id),
            }
        }

    @pytest.mark.asyncio
    async def test_supports_string_http_exception_detail(self) -> None:
        request = make_request()
        exc = HTTPException(status_code=403, detail="Forbidden")
        response = await http_exception_handler(request, exc)
        body = response_json(response)

        assert response.status_code == 403
        assert body["error"]["code"] == ERROR_INVALID_REQUEST
        assert body["error"]["message"] == "Forbidden"

    @pytest.mark.asyncio
    async def test_preserves_http_exception_headers(self) -> None:
        request = make_request()
        exc = HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={ "Retry-After": "10",},
        )
        response = await http_exception_handler(request, exc)

        assert response.headers["Retry-After"] == "10"
        assert TRACE_HEADER_NAME in response.headers

    @pytest.mark.asyncio
    async def test_uses_default_message_for_unrecognized_detail(self) -> None:
        request = make_request()
        exc = HTTPException(status_code=400, detail=["unexpected", "detail"])
        response = await http_exception_handler(request, exc)
        body = response_json(response)

        assert body["error"]["code"] == ERROR_INVALID_REQUEST
        assert body["error"]["message"] == "The request could not be processed."

# Unexpected failures
class TestUnhandledExceptionHandler:
    @pytest.mark.asyncio
    async def test_maps_to_500(self) -> None:
        trace_id = uuid7()
        request = make_request(trace_id=trace_id)
        exc = RuntimeError("something broke")
        response = await unhandled_exception_handler(request, exc)
        body = response_json(response)

        assert response.status_code == 500
        assert body == {
            "error": {
                "code": ERROR_INTERNAL,
                "message": "An unexpected internal error occurred.",
                "trace_id": str(trace_id),
            }
        }

    @pytest.mark.asyncio
    async def test_does_not_expose_internal_exception(self) -> None:
        request = make_request()
        sensitive = "postgresql://admin:password@localhost/db"
        response = await unhandled_exception_handler(request, RuntimeError(sensitive))
        body = response_json(response)

        assert sensitive not in str(body)

    @pytest.mark.asyncio
    async def test_generates_trace_id_when_missing(self) -> None:
        request = make_request()
        response = await unhandled_exception_handler(request, RuntimeError("boom"))
        generated = request.state.trace_id

        assert isinstance(generated, uuid.UUID)

        body = response_json(response)
        assert body["error"]["trace_id"] == str(generated)

# Trace consistency
class TestTraceIdConsistency:
    @pytest.mark.asyncio
    async def test_existing_trace_id_is_preserved(self) -> None:
        trace_id = uuid7()
        request = make_request(trace_id=trace_id)
        response = await unhandled_exception_handler(request, RuntimeError("failure"))
        
        assert request.state.trace_id == trace_id
        
        body = response_json(response)
        
        assert body["error"]["trace_id"] == str(trace_id)
        assert (response.headers[TRACE_HEADER_NAME] == str(trace_id))

# Handler registration
class TestExceptionHandlerRegistration:
    def test_handlers_can_be_registered_on_fastapi_app(self) -> None:
        from apps.api.app.api.errors import register_exception_handlers

        app = FastAPI()
        register_exception_handlers(app)
        
        assert RequestValidationError in app.exception_handlers
        assert HTTPException in app.exception_handlers
        assert ConversationDoesNotExistError in app.exception_handlers
        assert ConversationNotProcessableError in app.exception_handlers
        assert CustomerMessageValidationError in app.exception_handlers
        assert Exception in app.exception_handlers