# AI-customer-support-agent\apps\api\app\api\dependencies.py
from __future__ import annotations
import logging
import uuid
from collections.abc import Callable
from typing import Annotated
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from uuid6 import uuid7

from packages.application.auth.authenticate_access_token import AccessAuthenticationRejectedError, AuthenticateAccessTokenCommand
from packages.application.auth.models import AuthenticatedPrincipal, AuthRole
from packages.application.composition.application_factory import ApplicationServices

logger = logging.getLogger(__name__)


# Application services
def get_services(request: Request) -> ApplicationServices:
    """
    Return the process-scoped application-service container initialized during FastAPI lifespan startup.
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

def get_trace_id(request: Request, x_trace_id: Annotated[str | None, Header(alias=TRACE_HEADER_NAME, convert_underscores=False),] = None) -> uuid.UUID:
    """
    Resolve the correlation ID for the current HTTP request.

    - Valid caller-supplied X-Trace-ID: reuse it.
    - Missing X-Trace-ID: generate a UUIDv7.
    - Malformed X-Trace-ID: return HTTP 400.
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
                    "message": f"{TRACE_HEADER_NAME} cannot be empty.",
                },
            )

        try:
            trace_id = uuid.UUID(normalized)
            
        except (ValueError, AttributeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_TRACE_ID",
                    "message": f"{TRACE_HEADER_NAME} must contain a valid UUID.",
                },
            ) from exc

    request.state.trace_id = trace_id
    return trace_id

TraceIdDependency = Annotated[uuid.UUID, Depends(get_trace_id)]


# Request metadata
def get_client_ip(request: Request) -> str | None:
    """
    Return the directly connected client address.

    X-Forwarded-For is intentionally not trusted here. Proxy-header trust should be configured only when deployed behind a known reverse proxy.
    """
    if request.client is None:
        return None

    return request.client.host

ClientIpDependency = Annotated[str | None, Depends(get_client_ip)]

def get_user_agent(user_agent: Annotated[str | None, Header(alias="User-Agent")] = None) -> str | None:
    if user_agent is None:
        return None

    normalized = user_agent.strip()
    if not normalized:
        return None

    # Keep request metadata bounded before it reaches persistence.
    return normalized[:2048]

UserAgentDependency = Annotated[str | None, Depends(get_user_agent)]

# Authentication
_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="JWT access token returned by the authentication API.",
)

def get_current_principal(request: Request, services: ApplicationServicesDependency, trace_id: TraceIdDependency,
                          credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> AuthenticatedPrincipal:
    """
    Authenticate the Bearer access token and validate its session against current PostgreSQL state.
    """
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials.strip():
        logger.info(
            "authentication_credentials_missing",
            extra={
                "trace_id": str(trace_id),
                "method": request.method,
                "path": request.url.path,
            },
        )

        raise _unauthenticated_exception()

    try:
        principal = services.authenticate_access_token.execute(AuthenticateAccessTokenCommand(access_token=credentials.credentials))
        
    except AccessAuthenticationRejectedError as exc:
        logger.info(
            "access_authentication_rejected",
            extra={
                "trace_id": str(trace_id),
                "method": request.method,
                "path": request.url.path,
                "reason_code": exc.reason.value,
            },
        )

        raise _unauthenticated_exception() from exc

    # Middleware and later dependencies may reuse the trusted principal.
    request.state.authenticated_principal = principal
    request.state.actor_user_id = principal.user_id
    request.state.actor_role = principal.role.value

    return principal


CurrentPrincipalDependency = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]

def require_roles(*allowed_roles: AuthRole) -> Callable[..., AuthenticatedPrincipal]:
    """
    Build a reusable FastAPI dependency requiring one of the supplied roles.

    Authentication failure returns 401. An authenticated but unauthorized principal returns 403.
    """
    if not allowed_roles:
        raise ValueError("At least one allowed role is required.")

    normalized_roles = frozenset(allowed_roles)

    if any(not isinstance(role, AuthRole) for role in normalized_roles):
        raise TypeError("allowed_roles must contain only AuthRole values")

    def enforce_roles(request: Request, trace_id: TraceIdDependency, principal: CurrentPrincipalDependency) -> AuthenticatedPrincipal:
        if principal.role not in normalized_roles:
            logger.info(
                "authorization_rejected",
                extra={
                    "trace_id": str(trace_id),
                    "method": request.method,
                    "path": request.url.path,
                    "user_id": str(principal.user_id),
                    "session_id": str(principal.session_id),
                    "actual_role": principal.role.value,
                    "allowed_roles": sorted(role.value for role in normalized_roles),
                },
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to perform this operation.",
                },
            )

        return principal

    return enforce_roles

CustomerPrincipalDependency = Annotated[AuthenticatedPrincipal, Depends(require_roles(AuthRole.CUSTOMER))]

# Administrators inherit support-agent endpoint access.
SupportAgentPrincipalDependency = Annotated[AuthenticatedPrincipal, Depends(require_roles(AuthRole.SUPPORT_AGENT, AuthRole.ADMIN))]
AdminPrincipalDependency = Annotated[AuthenticatedPrincipal, Depends(require_roles(AuthRole.ADMIN))]

def _unauthenticated_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "UNAUTHENTICATED",
            "message": "Valid authentication credentials are required.",
        },
        headers={"WWW-Authenticate": "Bearer",},
    )