from __future__ import annotations
import logging
import uuid
from uuid6 import uuid7
from collections.abc import Mapping
from typing import Any
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from apps.api.app.api.dependencies import TRACE_HEADER_NAME
from packages.application.conversations.process_customer_message import ConversationDoesNotExistError, ConversationNotProcessableError, CustomerMessageValidationError


logger = logging.getLogger(__name__)

# Public error codes
ERROR_INVALID_REQUEST = "INVALID_REQUEST"
ERROR_INVALID_TRACE_ID = "INVALID_TRACE_ID"
ERROR_CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
ERROR_CONVERSATION_NOT_PROCESSABLE = "CONVERSATION_NOT_PROCESSABLE"
ERROR_INVALID_CUSTOMER_MESSAGE = "INVALID_CUSTOMER_MESSAGE"
ERROR_INTERNAL = "INTERNAL_ERROR"

# Registration
def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all API-level exception handlers.

    This is the single boundary where internal/application exceptions are translated into stable HTTP responses.

    Route handlers should generally allow known application exceptions to propagate here rather than duplicating try/except blocks.
    """

    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(ConversationDoesNotExistError, conversation_not_found_handler)
    app.add_exception_handler(ConversationNotProcessableError, conversation_not_processable_handler)
    app.add_exception_handler(CustomerMessageValidationError, customer_message_validation_handler)

    # Must remain last conceptually: this is the safety net for unexpected failures.
    app.add_exception_handler(Exception, unhandled_exception_handler)


# Application exception handlers
async def conversation_not_found_handler(request: Request, exc: ConversationDoesNotExistError) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "conversation_not_found",
        extra={
            "trace_id": str(trace_id),
            "path": request.url.path,
        },
    )

    return _error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        code=ERROR_CONVERSATION_NOT_FOUND,
        message="The requested conversation does not exist.",
        trace_id=trace_id,
    )

async def conversation_not_processable_handler(request: Request, exc: ConversationNotProcessableError) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "conversation_not_processable",
        extra={
            "trace_id": str(trace_id),
            "path": request.url.path,
        },
    )

    return _error_response(
        status_code=status.HTTP_409_CONFLICT,
        code=ERROR_CONVERSATION_NOT_PROCESSABLE,
        message="The conversation cannot accept a new customer message in its current state.",
        trace_id=trace_id,
    )

async def customer_message_validation_handler(request: Request, exc: CustomerMessageValidationError) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "customer_message_validation_failed",
        extra={
            "trace_id": str(trace_id),
            "path": request.url.path,
        },
    )
    # Do not automatically expose str(exc) to external callers.
    # Application exceptions can later contain internal details.
    return _error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=ERROR_INVALID_CUSTOMER_MESSAGE,
        message="The customer message is invalid.",
        trace_id=trace_id,
    )

# FastAPI / HTTP exception handlers
async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Convert FastAPI/Pydantic validation failures into our stable API error format.
    """
    trace_id = _resolve_trace_id(request)
    validation_issues = [
        {
            "location": [str(part) for part in error.get("loc", ())],
            "message": str(error.get("msg", "Invalid value.")),
            "type": str(error.get("type", "validation_error",))
        }
        for error in exc.errors()
    ]

    logger.info(
        "request_validation_failed",
        extra={
            "trace_id": str(trace_id),
            "path": request.url.path,
            "method": request.method,
            "validation_error_count": len(validation_issues)
        },
    )

    return _error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code=ERROR_INVALID_REQUEST,
        message="The request contains invalid data.",
        trace_id=trace_id,
        details=validation_issues,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Normalize FastAPI HTTPException instances into the same error envelope.

    This is particularly useful for dependencies such as trace-ID
    validation.
    """
    trace_id = _resolve_trace_id(request)
    code = ERROR_INVALID_REQUEST
    message = "The request could not be processed."
    detail = exc.detail

    if isinstance(detail, Mapping):
        detail_code = detail.get("code")
        detail_message = detail.get("message")
        if isinstance(detail_code, str) and detail_code:
            code = detail_code

        if isinstance(detail_message, str) and detail_message:
            message = detail_message

    elif isinstance(detail, str) and detail:
        message = detail

    return _error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
        trace_id=trace_id,
        headers=exc.headers,
    )

# Unexpected failures
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Last-resort API safety boundary.

    Full exception information is logged internally, while callers receive
    a stable non-sensitive response.
    """
    trace_id = _resolve_trace_id(request)
    logger.exception(
        "unhandled_api_exception",
        exc_info=exc,
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
        },
    )

    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ERROR_INTERNAL,
        message="An unexpected internal error occurred.",
        trace_id=trace_id,
    )

# Response construction
def _error_response(*, status_code: int, code: str, message: str, trace_id: uuid.UUID,
                    details: list[dict[str, Any]] | None = None, headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """
    Construct the canonical API error response.

    Every error:
    - follows the same JSON structure
    - contains a trace ID
    - exposes the trace ID as an HTTP response header
    """
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "trace_id": str(trace_id),
        }
    }
    if details:
        body["error"]["details"] = details

    response_headers = dict(headers or {})
    response_headers[TRACE_HEADER_NAME] = str(trace_id)
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers=response_headers,
    )

# Trace resolution
def _resolve_trace_id(request: Request) -> uuid.UUID:
    """
    Return the request trace ID when available.

    Exception handlers can run before normal endpoint dependencies have
    executed, for example when path/body validation fails. Therefore they
    cannot assume request.state.trace_id already exists.
    """

    existing = getattr(request.state, "trace_id", None)
    if isinstance(existing, uuid.UUID):
        return existing

    trace_id = uuid7()
    request.state.trace_id = trace_id
    return trace_id