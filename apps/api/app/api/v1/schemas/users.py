# AI-customer-support-agent\apps\api\app\api\v1\schemas\users.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

AssignableUserRole = Literal["customer", "support_agent", "admin",]
ManageableUserStatus = Literal["active", "disabled",]

class UserAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class UpdateUserAccessRequest(UserAPIModel):
    """
    Administrative role/status mutation.

    The administrator identity comes exclusively from the verified bearer token and is never accepted in this request body.
    """
    role: AssignableUserRole | None = Field(default=None, description="New user role, if changing the role.")
    status: ManageableUserStatus | None = Field(default=None, description="New account status, if changing the status.")
    reason: str = Field(..., min_length=1, max_length=1_000, 
                        description="Administrative reason recorded in the immutable audit event.",
                        examples=["Provisioning support access for the service desk."],
    )

    @model_validator(mode="after")
    def validate_requested_change(self) -> "UpdateUserAccessRequest":
        if self.role is None and self.status is None:
            raise ValueError("at least one of role or status must be provided")

        if not self.reason:
            raise ValueError("reason cannot be blank")

        return self

class UserAccessResponse(UserAPIModel):
    """
    Sanitized access-management result.

    Credential hashes, authentication sessions and token material are intentionally never included.
    """
    user_id: uuid.UUID
    email: str | None
    display_name: str | None
    role: AssignableUserRole
    status: ManageableUserStatus
    updated_at: datetime
    changed: bool
    revoked_session_count: int = Field(..., ge=0)