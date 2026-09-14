# AI-customer-support-agent\apps\api\app\api\v1\auth.py
from __future__ import annotations
from fastapi import APIRouter, Request, Response, status

from apps.api.app.api.dependencies import ApplicationServicesDependency, ClientIpDependency, CurrentPrincipalDependency
from apps.api.app.api.dependencies import TraceIdDependency, UserAgentDependency
from apps.api.app.api.v1.schemas.auth import AuthenticatedUserResponse, AuthenticationResponse, LoginRequest, LogoutResponse, RefreshSessionRequest, RegisterRequest
from packages.application.auth.get_current_user import GetCurrentUserCommand
from packages.application.auth.models import LoginCommand, LogoutCommand, RefreshSessionCommand, RegisterCommand

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
)

@router.post(
    "/register",
    response_model=AuthenticationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a customer account",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Password policy violation",},
        status.HTTP_409_CONFLICT: {"description": "Email already registered",},
    },
)
def register(payload: RegisterRequest, response: Response, services: ApplicationServicesDependency, trace_id: TraceIdDependency,
             client_ip: ClientIpDependency, user_agent: UserAgentDependency, request: Request
) -> AuthenticationResponse:
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

    request.state.actor_user_id = result.user.user_id
    request.state.actor_role = result.user.role.value
    _set_sensitive_response_headers(response)

    return AuthenticationResponse.from_application(result)

@router.post(
    "/login",
    response_model=AuthenticationResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in using email and password",
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Invalid credentials",},},
)
def login(payload: LoginRequest, response: Response, services: ApplicationServicesDependency, trace_id: TraceIdDependency, 
          client_ip: ClientIpDependency, user_agent: UserAgentDependency, request: Request
) -> AuthenticationResponse:
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

    request.state.actor_user_id = result.user.user_id
    request.state.actor_role = result.user.role.value
    _set_sensitive_response_headers(response)

    return AuthenticationResponse.from_application(result)

@router.post(
    "/refresh",
    response_model=AuthenticationResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate a refresh token",
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Invalid or expired refresh token",},},
)
def refresh(payload: RefreshSessionRequest, response: Response, services: ApplicationServicesDependency, trace_id: TraceIdDependency,
            client_ip: ClientIpDependency, user_agent: UserAgentDependency, request: Request
) -> AuthenticationResponse:
    """
    Consume a refresh token exactly once and return a replacement token pair.

    Reusing a consumed refresh token revokes its entire token family.
    """
    result = services.refresh_session.execute(
        RefreshSessionCommand(
            refresh_token=payload.refresh_token.get_secret_value(),
            client_ip=client_ip,
            user_agent=user_agent,
            trace_id=trace_id,
        )
    )

    request.state.actor_user_id = result.user.user_id
    request.state.actor_role = result.user.role.value
    _set_sensitive_response_headers(response)

    return AuthenticationResponse.from_application(result)

@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Log out the current session",
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Authentication required",},},
)
def logout(response: Response, services: ApplicationServicesDependency, trace_id: TraceIdDependency, principal: CurrentPrincipalDependency) -> LogoutResponse:
    """
    Revoke the refresh-token session referenced by the current access token.

    The operation is idempotent.
    """
    result = services.logout_user.execute(
        LogoutCommand(
            principal=principal,
            trace_id=trace_id,
        )
    )

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