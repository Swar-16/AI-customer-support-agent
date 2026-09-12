# AI-customer-support-agent\apps\api\app\api\v1\users.py
from __future__ import annotations
import uuid
from fastapi import APIRouter, Path, status

from apps.api.app.api.dependencies import AdminPrincipalDependency, ApplicationServicesDependency, TraceIdDependency
from apps.api.app.api.schemas.errors import APIErrorResponse
from apps.api.app.api.v1.schemas.users import UpdateUserAccessRequest, UserAccessResponse
from packages.application.auth.models import AuthRole, AuthUserStatus
from packages.application.users.update_user_access import UpdateUserAccessCommand

router = APIRouter(tags=["users"])

@router.patch(
    "/users/{user_id}/access",
    response_model=UserAccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user access",
    description="Change a user's role or active status. This operation is restricted to authenticated administrators. Relevant active sessions are revoked when access changes.",
    responses={
        401: {
            "model": APIErrorResponse,
            "description": "Authentication required",
        },
        403: {
            "model": APIErrorResponse,
            "description": "Administrator access required",
        },
        404: {
            "model": APIErrorResponse,
            "description": "User not found",
        },
        409: {
            "model": APIErrorResponse,
            "description": "The requested access mutation violates an administrator safety invariant",
        },
        422: {
            "model": APIErrorResponse,
            "description": "Request validation failed",
        },
        500: {
            "model": APIErrorResponse,
            "description": "Unexpected internal failure",
        },
    },
)
def update_user_access(payload: UpdateUserAccessRequest, services: ApplicationServicesDependency, principal: AdminPrincipalDependency,
                       trace_id: TraceIdDependency, user_id: uuid.UUID = Path(..., description="User whose access will be updated."),
) -> UserAccessResponse:
    result = services.update_user_access.execute(
        UpdateUserAccessCommand(
            target_user_id=user_id,
            principal=principal,
            trace_id=trace_id,
            role=AuthRole(payload.role) if payload.role is not None else None,
            status=AuthUserStatus(payload.status) if payload.status is not None else None,
            reason=payload.reason,
        )
    )

    return UserAccessResponse(
        user_id=result.user_id,
        email=result.email,
        display_name=result.display_name,
        role=result.role.value,
        status=result.status.value,
        updated_at=result.updated_at,
        changed=result.changed,
        revoked_session_count=result.revoked_session_count,
    )