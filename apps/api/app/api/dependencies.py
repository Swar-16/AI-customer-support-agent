from __future__ import annotations
import uuid
from uuid6 import uuid7
from typing import Annotated
from fastapi import Depends, Header, HTTPException, Request, status

from packages.application.composition.application_factory import ApplicationServices

def get_services(request: Request) -> ApplicationServices:
    """
    Retrieve the process-scoped ApplicationServices container initialized
    during FastAPI lifespan startup.
    """
    services = getattr(request.app.state, "application_services", None)
    if services is None:
        raise RuntimeError("Application services have not been initialized")

    if not isinstance(services, ApplicationServices):
        raise RuntimeError("Invalid application services configured")

    return services

ApplicationServicesDependency = Annotated[ApplicationServices, Depends(get_services)]

# Trace / correlation ID
TRACE_HEADER_NAME = "X-Trace-ID"

def get_trace_id(request: Request, x_trace_id: Annotated[str | None, Header(
            alias=TRACE_HEADER_NAME,
            convert_underscores=False
        ),
    ] = None,
) -> uuid.UUID:
    """
    Resolve a trace ID for the current HTTP request.

    Behavior:
    - valid client-supplied X-Trace-ID → reuse it
    - no X-Trace-ID → generate a new UUID
    - malformed X-Trace-ID → reject with HTTP 400

    The resolved ID is also stored on request.state so middleware,
    exception handlers, routes, and structured logging can reuse the exact
    same correlation identifier without reparsing headers.
    """

    existing = getattr(request.state, "trace_id", None)
    if existing is not None:
        if not isinstance(existing, uuid.UUID):
            raise RuntimeError("request.state.trace_id must be a UUID")

        return existing

    if x_trace_id is None:
        trace_id = uuid7()
    else:
        normalized = x_trace_id.strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_TRACE_ID",
                    "message": (f"{TRACE_HEADER_NAME} cannot be empty."),
                },
            )

        try:
            trace_id = uuid.UUID(normalized)

        except (ValueError, AttributeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_TRACE_ID",
                    "message": (f"{TRACE_HEADER_NAME} must contain a valid UUID."),
                },
            ) from exc

    request.state.trace_id = trace_id
    return trace_id

TraceIdDependency = Annotated[uuid.UUID, Depends(get_trace_id)]

# Request metadata helpers
def get_client_ip(request: Request) -> str | None:
    """
    Return the directly connected client IP.

    Do NOT trust X-Forwarded-For here yet.

    When the API is deployed behind a known reverse proxy/load balancer,
    proxy-header trust should be configured centrally rather than allowing
    arbitrary callers to spoof their source IP.
    """
    if request.client is None:
        return None

    return request.client.host


ClientIpDependency = Annotated[str | None, Depends(get_client_ip)]