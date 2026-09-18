# AI-customer-support-agent\apps\api\app\api\v1\auth.py
from __future__ import annotations
from fastapi import APIRouter, Request, Response, status, Depends

from apps.api.app.api.dependencies import ApplicationServicesDependency, ClientIpDependency, CurrentPrincipalDependency
from apps.api.app.api.dependencies import TraceIdDependency, UserAgentDependency
from apps.api.app.api.v1.schemas.auth import AuthenticatedUserResponse, LoginRequest, LogoutResponse, RegisterRequest
from packages.application.auth.get_current_user import GetCurrentUserCommand
from packages.application.auth.models import LoginCommand, LogoutCommand, RefreshSessionCommand, RegisterCommand
from apps.api.app.api.browser_auth import clear_refresh_cookie, read_refresh_cookie, set_refresh_cookie
from apps.api.app.api.dependencies import BrowserAuthSettingsDependency, require_empty_refresh_body
from apps.api.app.api.v1.schemas.auth import BrowserAuthenticationResponse

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
)

@router.post(
    "/register",
    response_model=BrowserAuthenticationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a customer account",
    responses={
        400: {"description": "Password policy violation"},
        403: {"description": "Browser origin is not permitted"},
        409: {"description": "Email already registered"},
    },
)
def register(payload: RegisterRequest, response: Response, services: ApplicationServicesDependency, trace_id: TraceIdDependency,
             client_ip: ClientIpDependency, user_agent: UserAgentDependency, request: Request, settings: BrowserAuthSettingsDependency
) -> BrowserAuthenticationResponse:
    """
    Register a new customer using local email/password authentication.

    Public registration always creates a customer. Agent and administrator accounts must later be
    provisioned through an authorized administrative workflow.
    """
    result = services.register_user.execute(
        RegisterCommand(
            email=payload.email,
            password=payload.password.get_secret_value(),
            display_name=payload.display_name,
            client_ip=client_ip,
            user_agent=user_agent,
            trace_id=trace_id,
        )
    )

    set_refresh_cookie(
        response,
        refresh_token=result.tokens.refresh_token,
        expires_at=result.tokens.refresh_token_expires_at,
        settings=settings,
    )

    request.state.actor_user_id = result.user.user_id
    request.state.actor_role = result.user.role.value
    _set_sensitive_response_headers(response)

    return BrowserAuthenticationResponse.from_application(result)

@router.post(
    "/login",
    response_model=BrowserAuthenticationResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in using email and password",
    responses={
        401: {"description": "Invalid credentials"},
        403: {"description": "Browser origin is not permitted"},
    },
)
def login(payload: LoginRequest, response: Response, services: ApplicationServicesDependency, trace_id: TraceIdDependency, 
          client_ip: ClientIpDependency, user_agent: UserAgentDependency, request: Request, settings: BrowserAuthSettingsDependency
) -> BrowserAuthenticationResponse:
    """Authenticate an active local user and create a new refresh-token family."""
    result = services.login_user.execute(
        LoginCommand(
            email=payload.email,
            password=payload.password.get_secret_value(),
            client_ip=client_ip,
            user_agent=user_agent,
            trace_id=trace_id,
        )
    )

    set_refresh_cookie(
        response,
        refresh_token=result.tokens.refresh_token,
        expires_at=result.tokens.refresh_token_expires_at,
        settings=settings,
    )

    request.state.actor_user_id = result.user.user_id
    request.state.actor_role = result.user.role.value
    _set_sensitive_response_headers(response)

    return BrowserAuthenticationResponse.from_application(result)

@router.post(
    "/refresh",
    response_model=BrowserAuthenticationResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate the browser refresh session",
    dependencies=[Depends(require_empty_refresh_body)],
    responses={
        401: {"description": "Invalid or expired refresh cookie"},
        403: {"description": "Browser origin is not permitted"},
        422: {"description": "Request body must be empty"},
    },
)
def refresh(response: Response, services: ApplicationServicesDependency, trace_id: TraceIdDependency, client_ip: ClientIpDependency,
            user_agent: UserAgentDependency, request: Request, settings: BrowserAuthSettingsDependency
) -> BrowserAuthenticationResponse:
    """
    Consume the HTTP-only refresh cookie and issue its replacement.

    No bearer token or request body is required. Reuse detection and the original session expiry remain authoritative.
    """
    result = services.refresh_session.execute(
        RefreshSessionCommand(
            refresh_token=read_refresh_cookie(request),
            client_ip=client_ip,
            user_agent=user_agent,
            trace_id=trace_id,
        )
    )

    request.state.actor_user_id = result.user.user_id
    request.state.actor_role = result.user.role.value
    set_refresh_cookie(
        response,
        refresh_token=result.tokens.refresh_token,
        expires_at=result.tokens.refresh_token_expires_at,
        settings=settings,
    )

    return BrowserAuthenticationResponse.from_application(result)

@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Log out the current session",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Browser origin is not permitted"},
    },
)
def logout(response: Response, services: ApplicationServicesDependency, trace_id: TraceIdDependency, 
           principal: CurrentPrincipalDependency, settings: BrowserAuthSettingsDependency
) -> LogoutResponse:
    """
    Revoke the session referenced by the current bearer access token and delete the browser refresh cookie.

    The service handles already-inactive sessions idempotently, but HTTP authentication rejects an already-revoked bearer token with 401.
    """
    result = services.logout_user.execute(
        LogoutCommand(
            principal=principal,
            trace_id=trace_id,
        )
    )

    clear_refresh_cookie(response, settings=settings)
    _set_sensitive_response_headers(response)

    return LogoutResponse.from_application(result)

@router.get(
    "/me",
    response_model=AuthenticatedUserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the current authenticated user",
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Authentication required",},},
)
def get_me(response: Response, services: ApplicationServicesDependency, principal: CurrentPrincipalDependency) -> AuthenticatedUserResponse:
    """Return the authenticated user's safe public profile."""
    user = services.get_current_user.execute(GetCurrentUserCommand(principal=principal))
    _set_sensitive_response_headers(response)

    return AuthenticatedUserResponse.from_application(user)


def _set_sensitive_response_headers(response: Response) -> None:
    """
    Prevent browsers and intermediary caches from retaining authentication responses containing tokens or identity information.
    """
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"