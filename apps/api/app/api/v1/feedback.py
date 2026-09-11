# AI-customer-support-agent\apps\api\app\api\v1\feedback.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from fastapi import APIRouter, Path, Query, status

from apps.api.app.api.dependencies import ApplicationServicesDependency
from apps.api.app.api.schemas.errors import APIErrorResponse
from apps.api.app.api.v1.schemas.feedback import FeedbackListResponse, FeedbackReasonCode, FeedbackRequesterRole, FeedbackResponse
from apps.api.app.api.v1.schemas.feedback import FeedbackStatus, ReviewFeedbackRequest, ReviewFeedbackResponse, SubmitFeedbackRequest, SubmitFeedbackResponse
from packages.application.feedback.query_feedback import FeedbackPage, FeedbackView, GetFeedbackQuery, ListFeedbackQuery
from packages.application.feedback.review_feedback import ReviewFeedbackCommand, ReviewFeedbackResult
from packages.application.feedback.submit_feedback import SubmitFeedbackCommand, SubmitFeedbackResult

router = APIRouter(tags=["feedback"])
_COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": APIErrorResponse, "description": "Invalid feedback operation",},
    403: {"model": APIErrorResponse, "description": "Feedback access denied",},
    404: {"model": APIErrorResponse, "description": "Feedback or related resource not found",},
    409: {"model": APIErrorResponse, "description": "Feedback state or concurrency conflict",},
    422: {"model": APIErrorResponse, "description": "Request validation failed",},
    500: {"model": APIErrorResponse, "description": "Unexpected internal failure",},
}

@router.post(
    "/conversations/{conversation_id}/feedback",
    response_model=SubmitFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit response feedback",
    description="Submit customer feedback for one AI-generated assistant response.",
    responses=_COMMON_ERROR_RESPONSES,
)
def submit_feedback(
    payload: SubmitFeedbackRequest,
    services: ApplicationServicesDependency,
    conversation_id: uuid.UUID = Path(..., description="Conversation containing the assistant response."),
) -> SubmitFeedbackResponse:
    command = SubmitFeedbackCommand(
        conversation_id=conversation_id,
        customer_id=payload.customer_id,
        response_message_id=payload.response_message_id,
        ai_run_id=payload.ai_run_id,
        rating=payload.rating,
        helpful=payload.helpful,
        comment=payload.comment,
        reason_codes=tuple(payload.reason_codes),
        metadata=payload.metadata,
    )

    result = services.submit_feedback.execute(command)
    return _submit_feedback_response(result)

@router.get(
    "/feedback",
    response_model=FeedbackListResponse,
    status_code=status.HTTP_200_OK,
    summary="List feedback",
    description="Return customer-owned feedback or a filtered support dashboard queue.",
    responses=_COMMON_ERROR_RESPONSES,
)
def list_feedback(
    services: ApplicationServicesDependency,
    requester_id: uuid.UUID = Query(..., description="Authenticated requester identity."),
    requester_role: FeedbackRequesterRole = Query(..., description="Authenticated requester role."),
    feedback_status: FeedbackStatus | None = Query(default=None, alias="status", description="Filter by feedback review status."),
    rating: int | None = Query(default=None, ge=1, le=5, description="Filter by exact rating."),
    helpful: bool | None = Query(default=None, description="Filter by explicit helpful value."),
    reason_code: FeedbackReasonCode | None = Query(default=None, description="Filter by a structured feedback reason."),
    customer_id: uuid.UUID | None = Query(default=None, description="Filter by customer."),
    conversation_id: uuid.UUID | None = Query(default=None, description="Filter by conversation."),
    created_from: datetime | None = Query(default=None, description="Inclusive feedback creation lower bound."),
    created_to: datetime | None = Query(default=None, description="Inclusive feedback creation upper bound."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FeedbackListResponse:
    query = ListFeedbackQuery(
        requester_id=requester_id,
        requester_role=requester_role,
        status=feedback_status,
        rating=rating,
        helpful=helpful,
        reason_code=reason_code,
        customer_id=customer_id,
        conversation_id=conversation_id,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )

    result = services.list_feedback.execute(query)
    return _feedback_list_response(result)

@router.get(
    "/feedback/{feedback_id}",
    response_model=FeedbackResponse,
    status_code=status.HTTP_200_OK,
    summary="Get feedback details",
    description="Return one feedback record when the requester is authorized.",
    responses=_COMMON_ERROR_RESPONSES,
)
def get_feedback(
    services: ApplicationServicesDependency,
    feedback_id: uuid.UUID = Path(..., description="Feedback identifier."),
    requester_id: uuid.UUID = Query(..., description="Authenticated requester identity."),
    requester_role: FeedbackRequesterRole = Query(..., description="Authenticated requester role."),
) -> FeedbackResponse:
    query = GetFeedbackQuery(feedback_id=feedback_id, requester_id=requester_id, requester_role=requester_role)
    result = services.get_feedback.execute(query)
    return _feedback_response(result)

@router.patch(
    "/feedback/{feedback_id}/review",
    response_model=ReviewFeedbackResponse,
    status_code=status.HTTP_200_OK,
    summary="Review customer feedback",
    description="Move feedback through its dashboard review lifecycle using optimistic concurrency control.",
    responses=_COMMON_ERROR_RESPONSES,
)
def review_feedback(
    payload: ReviewFeedbackRequest,
    services: ApplicationServicesDependency,
    feedback_id: uuid.UUID = Path(..., description="Feedback identifier."),
) -> ReviewFeedbackResponse:
    command = ReviewFeedbackCommand(
        feedback_id=feedback_id,
        reviewer_id=payload.reviewer_id,
        expected_row_version=payload.expected_row_version,
        target_status=payload.target_status,
        review_notes=payload.review_notes,
    )

    result = services.review_feedback.execute(command)
    return _review_feedback_response(result)

def _submit_feedback_response(result: SubmitFeedbackResult) -> SubmitFeedbackResponse:
    return SubmitFeedbackResponse(
        feedback_id=result.feedback_id,
        conversation_id=result.conversation_id,
        customer_id=result.customer_id,
        response_message_id=result.response_message_id,
        ai_run_id=result.ai_run_id,
        rating=result.rating,
        helpful=result.helpful,
        comment=result.comment,
        reason_codes=list(result.reason_codes),
        status=result.status,
        row_version=result.row_version,
        created=result.created,
    )

def _review_feedback_response(result: ReviewFeedbackResult) -> ReviewFeedbackResponse:
    return ReviewFeedbackResponse(
        feedback_id=result.feedback_id,
        conversation_id=result.conversation_id,
        customer_id=result.customer_id,
        response_message_id=result.response_message_id,
        ai_run_id=result.ai_run_id,
        previous_status=result.previous_status,
        current_status=result.current_status,
        reviewed_by_user_id=result.reviewed_by_user_id,
        review_notes=result.review_notes,
        reviewed_at=result.reviewed_at,
        row_version=result.row_version,
        updated_at=result.updated_at,
        changed=result.changed,
    )

def _feedback_response(view: FeedbackView) -> FeedbackResponse:
    return FeedbackResponse(
        feedback_id=view.feedback_id,
        conversation_id=view.conversation_id,
        customer_id=view.customer_id,
        response_message_id=view.response_message_id,
        ai_run_id=view.ai_run_id,
        rating=view.rating,
        helpful=view.helpful,
        comment=view.comment,
        reason_codes=list(view.reason_codes),
        status=view.status,
        reviewed_by_user_id=view.reviewed_by_user_id,
        review_notes=view.review_notes,
        metadata=dict(view.metadata),
        row_version=view.row_version,
        created_at=view.created_at,
        updated_at=view.updated_at,
        reviewed_at=view.reviewed_at,
    )

def _feedback_list_response(page: FeedbackPage) -> FeedbackListResponse:
    return FeedbackListResponse(
        items=[_feedback_response(feedback) for feedback in page.items],
        count=page.count,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )