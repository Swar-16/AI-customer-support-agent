from __future__ import annotations
import uuid
from fastapi import APIRouter, Path, status

from apps.api.app.api.dependencies import ApplicationServicesDependency, TraceIdDependency
from apps.api.app.api.schemas.errors import APIErrorResponse
from apps.api.app.api.v1.schemas.conversations import SendMessageRequest, SendMessageResponse
from packages.application.conversations.process_customer_message import ProcessCustomerMessageCommand

router = APIRouter(tags=["conversations"])

@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SendMessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Send a customer message",
    description="Persist a customer message and execute the configured AI support pipeline for the conversation.",
    responses={
        400: {
            "model": APIErrorResponse,
            "description": "Invalid customer message",
        },
        404: {
            "model": APIErrorResponse,
            "description": "Conversation not found",
        },
        409: {
            "model": APIErrorResponse,
            "description": (
                "Conversation cannot currently accept messages"
            ),
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
def send_message(
    payload: SendMessageRequest,
    services: ApplicationServicesDependency,
    trace_id: TraceIdDependency,
    conversation_id: uuid.UUID = Path(..., description="Conversation receiving the customer message.")
) -> SendMessageResponse:
    """
    Process one customer-authored conversation message.

    Application/domain failures deliberately propagate to the centralized
    API exception handlers.
    """

    command = ProcessCustomerMessageCommand(
        conversation_id=conversation_id,
        customer_message=payload.message,
        trace_id=trace_id,
    )

    result = services.process_customer_message.execute(command)
    return SendMessageResponse(
        conversation_id=result.conversation_id,
        customer_message_id=result.customer_message_id,
        ai_run_id=result.ai_run_id,
        trace_id=result.trace_id,
        pipeline_stage=result.pipeline_stage.value,
        intent=(result.intent.value if hasattr(result.intent, "value") else result.intent),
        decision=(result.decision.value if hasattr(result.decision, "value") else result.decision),
        succeeded=result.succeeded,
    )