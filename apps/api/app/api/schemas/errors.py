from __future__ import annotations
import uuid
from pydantic import BaseModel, ConfigDict, Field

class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ValidationIssue(APIModel):
    """
    One sanitized request-validation failure.
    """
    location: list[str]
    message: str = Field(..., min_length=1, max_length=1000)
    type: str = Field(..., min_length=1, max_length=200)

class APIErrorDetail(APIModel):
    """
    Stable machine-readable API error representation.
    """
    code: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=1000)
    trace_id: uuid.UUID
    details: list[ValidationIssue] | None = None

class APIErrorResponse(APIModel):
    error: APIErrorDetail