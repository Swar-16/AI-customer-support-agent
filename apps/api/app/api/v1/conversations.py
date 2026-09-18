# AI-customer-support-agent\apps\api\app\api\v1\conversations.py
from __future__ import annotations
import uuid
from fastapi import APIRouter, Header, Path, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from typing import NoReturn

from packages.application.conversations.process_customer_message import CustomerMessagePipelineFailedError, CustomerMessagePipelineTimeoutError
from packages.application.conversations.process_customer_message import CustomerMessagePipelineUnavailableError, ProcessCustomerMessageCommand
from packages.application.conversations.process_customer_message import ProcessCustomerMessageResult
from apps.api.app.api.dependencies import ApplicationServicesDependency, CurrentPrincipalDependency, CustomerPrincipalDependency, TraceIdDependency
from apps.api.app.api.schemas.errors import APIErrorResponse
from apps.api.app.api.v1.schemas.conversations import ConversationChannel, ConversationListResponse, ConversationResponse, ConversationStatus
from apps.api.app.api.v1.schemas.conversations import CreateConversationRequest, CreateConversationResponse, SendMessageRequest
from apps.api.app.api.v1.schemas.conversations import ConversationMessageListResponse, ConversationMessageResponse, CloseConversationResponse
from apps.api.app.api.v1.schemas.conversations import StartConversationProcessingResponse, StartConversationRequest, StartConversationResponse
from apps.api.app.api.v1.schemas.conversations import ConversationMessageFeedbackResponse, SendMessageResponse
from packages.application.conversations.process_customer_message import ProcessCustomerMessageCommand
from packages.application.conversations.create_conversation import CreateConversationCommand, CreateConversationResult
from packages.application.conversations.query_conversations import ConversationPage, ConversationView, GetConversationQuery, ListConversationsQuery
from packages.application.conversations.get_conversation_messages import GetConversationMessagesQuery, ConversationMessageView
from packages.application.conversations.close_conversation import CloseConversationCommand
from packages.application.conversations.start_conversation import StartConversationCommand, StartConversationResult
from packages.application.conversations.start_conversation_errors import ConversationStartProcessingInProgressError

router = APIRouter(tags=["conversations"])

def _raise_for_pipeline_failure(result: ProcessCustomerMessageResult) -> NoReturn:
    """
    Translate an already-committed pipeline failure into a safe application exception.

    This function must only run after ProcessCustomerMessage.execute() has committed its telemetry transaction.
    """
    if result.succeeded:
        raise ValueError("A successful result cannot be raised as a failure.")

    failure_code = result.failure_code
    if failure_code is None:
        raise CustomerMessagePipelineFailedError(failure_code="AI_PIPELINE_FAILED")

    normalized_code = failure_code.strip().upper()
    if normalized_code == "TIMEOUT" or normalized_code.endswith("_TIMEOUT"):
        raise CustomerMessagePipelineTimeoutError(failure_code=normalized_code)

    if normalized_code.endswith("_UNAVAILABLE") or normalized_code.endswith("_RATE_LIMITED") or result.failure_retryable is True:
        raise CustomerMessagePipelineUnavailableError(failure_code=normalized_code)

    raise CustomerMessagePipelineFailedError(failure_code=normalized_code)

@router.post(
    "/conversations",
    response_model=CreateConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer conversation",
    description="Create a new conversation owned by the authenticated customer.",
    responses={
        401: {
            "model": APIErrorResponse,
            "description": "Authentication required",
        },
        403: {
            "model": APIErrorResponse,
            "description": "Customer access required",
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
def create_conversation(payload: CreateConversationRequest, services: ApplicationServicesDependency,
                        principal: CustomerPrincipalDependency, trace_id: TraceIdDependency,
) -> CreateConversationResponse:
    result = services.create_conversation.execute(
        CreateConversationCommand(
            principal=principal,
            trace_id=trace_id,
            channel=payload.channel,
            title=payload.title,
        )
    )

    return _create_conversation_response(result)

@router.post(
    "/conversations/start",
    response_model=StartConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a conversation with its first message",
    description="Atomically create a customer conversation and its first message using a customer-scoped idempotency key, then run the AI support pipeline.",
    responses={
        200: {
            "model": StartConversationResponse,
            "description": "Existing terminal result replayed",
        },
        202: {
            "model": StartConversationProcessingResponse,
            "description": "An identical request is still processing",
        },
        400: {
            "model": APIErrorResponse,
            "description": "Invalid first message or idempotency key",
        },
        401: {
            "model": APIErrorResponse,
            "description": "Authentication required",
        },
        403: {
            "model": APIErrorResponse,
            "description": "Customer access required",
        },
        409: {
            "model": APIErrorResponse,
            "description": "Idempotency key reused with conflicting input or its replay period expired",
        },
        422: {
            "model": APIErrorResponse,
            "description": "Request validation failed",
        },
        500: {
            "model": APIErrorResponse,
            "description": "Unexpected internal failure",
        },
        503: {
            "model": APIErrorResponse,
            "description": "The conversation was accepted but processing ownership could not be confirmed",
        },
    },
)
def start_conversation(payload: StartConversationRequest, response: Response, services: ApplicationServicesDependency, 
                       trace_id: TraceIdDependency, principal: CustomerPrincipalDependency,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=16,
        max_length=255,
        description="High-entropy client-generated key scoped to the authenticated customer.",
    ),
) -> StartConversationResponse | JSONResponse:
    try:
        result = services.start_conversation.execute(
            StartConversationCommand(
                principal=principal,
                idempotency_key=idempotency_key,
                customer_message=payload.message,
                trace_id=trace_id,
                channel=payload.channel,
                title=payload.title,
            )
        )
    except (ConversationStartProcessingInProgressError) as exc:
        processing_response = StartConversationProcessingResponse(
            start_request_id=exc.request_id,
            conversation_id=exc.conversation_id,
            retry_after_seconds=exc.retry_after_seconds,
        )

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=jsonable_encoder(processing_response),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    # A newly persisted conversation returns 201. An identical request that resumes or replays existing state returns 200.
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK

    return _start_conversation_response(result)

@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List conversations",
    description="List conversations visible to the authenticated principal. Customers receive only their own conversations.",
)
def list_conversations(services: ApplicationServicesDependency, principal: CurrentPrincipalDependency, 
                       conversation_status: ConversationStatus | None = Query(default=None, alias="status", description="Filter by conversation status."),
                       channel: ConversationChannel | None = Query(default=None, description="Filter by conversation channel."),
                       customer_id: uuid.UUID | None = Query(default=None, description="Administrative customer filter. Customers cannot use this to access another user's conversations."),
                       limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
) -> ConversationListResponse:
    page = services.list_conversations.execute(
        ListConversationsQuery(
            principal=principal,
            status=conversation_status,
            channel=channel,
            customer_id=customer_id,
            limit=limit,
            offset=offset,
        )
    )

    return _conversation_list_response(page)

@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get conversation",
    description="Return a customer-owned or administratively visible conversation.",
)
def get_conversation(services: ApplicationServicesDependency, principal: CurrentPrincipalDependency, 
                     conversation_id: uuid.UUID = Path(..., description="Conversation identifier.")
) -> ConversationResponse:
    conversation = services.get_conversation.execute(
        GetConversationQuery(conversation_id=conversation_id, principal=principal)
    )

    return _conversation_response(conversation)

@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationMessageListResponse,
    status_code=status.HTTP_200_OK,
    summary="List conversation messages",
    description="Return a chronological, paginated list of customer-visible messages from an authorized conversation.",
    responses={
        401: {
            "model": APIErrorResponse,
            "description": "Authentication required",
        },
        403: {
            "model": APIErrorResponse,
            "description": "Conversation access denied",
        },
        404: {
            "model": APIErrorResponse,
            "description": "Conversation not found",
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
def list_conversation_messages(
    services: ApplicationServicesDependency,
    principal: CurrentPrincipalDependency,
    conversation_id: uuid.UUID = Path(..., description="Conversation whose messages will be returned."),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum number of messages to return."),
    offset: int = Query(default=0, ge=0, description="Number of messages to skip."),
) -> ConversationMessageListResponse:
    result = services.get_conversation_messages.execute(
        GetConversationMessagesQuery(conversation_id=conversation_id, principal=principal, limit=limit, offset=offset)
    )

    return ConversationMessageListResponse(
        items=[_conversation_message_response(item) for item in result.items],
        total=result.total,
        count=result.count,
        limit=result.limit,
        offset=result.offset,
        has_more=result.has_more,
        next_offset=result.next_offset,
    )

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
        401: {
            "model": APIErrorResponse,
            "description": "Authentication required",
        },
        403: {
            "model": APIErrorResponse,
            "description": "Customer access required",
        },
        404: {
            "model": APIErrorResponse,
            "description": "Conversation not found",
        },
        409: {
            "model": APIErrorResponse,
            "description": "Conversation cannot currently accept messages",
        },
        422: {
            "model": APIErrorResponse,
            "description": "Request validation failed",
        },
        500: {
            "model": APIErrorResponse,
            "description": "Unexpected internal failure",
        },
        503: {
            "model": APIErrorResponse,
            "description": "The AI support service is temporarily unavailable",
        },
        504: {
            "model": APIErrorResponse,
            "description": "The AI support provider did not respond in time",
        },
    },
)
def send_message(payload: SendMessageRequest, services: ApplicationServicesDependency, trace_id: TraceIdDependency, principal: CustomerPrincipalDependency,
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
        principal=principal,
        trace_id=trace_id,
    )

    result = services.process_customer_message.execute(command)
    if not result.succeeded:
        _raise_for_pipeline_failure(result)
        
    return SendMessageResponse(
        conversation_id=result.conversation_id,
        customer_message_id=result.customer_message_id,
        ai_run_id=result.ai_run_id,
        trace_id=result.trace_id,
        pipeline_stage=result.pipeline_stage.value,
        intent=result.intent,
        decision=result.decision,
        assistant_message_id=result.assistant_message_id,
        escalation_id=result.escalation_id,
        response=result.response,
        succeeded=result.succeeded,
    )
    
@router.post(
    "/conversations/{conversation_id}/close",
    response_model=CloseConversationResponse,
    status_code=status.HTTP_200_OK,
    summary="Close a conversation",
    description="Close a customer-owned conversation. Customers may close their own conversations, while administrators may close any conversation. Repeated closure is idempotent.",
    responses={
        401: {
            "model": APIErrorResponse,
            "description": "Authentication required",
        },
        403: {
            "model": APIErrorResponse,
            "description": "Conversation closure denied",
        },
        404: {
            "model": APIErrorResponse,
            "description": "Conversation not found",
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
def close_conversation(services: ApplicationServicesDependency, principal: CurrentPrincipalDependency, trace_id: TraceIdDependency,
                       conversation_id: uuid.UUID = Path(..., description="Conversation to close.",)
) -> CloseConversationResponse:
    result = services.close_conversation.execute(
        CloseConversationCommand(
            conversation_id=conversation_id,
            principal=principal,
            trace_id=trace_id,
        )
    )

    return CloseConversationResponse(
        conversation_id=result.conversation_id,
        customer_id=result.customer_id,
        status=result.status,
        resolved_at=result.resolved_at,
        closed_at=result.closed_at,
        updated_at=result.updated_at,
        changed=result.changed,
    )

def _start_conversation_response(result: StartConversationResult) -> StartConversationResponse:
    message_result = result.message_result

    return StartConversationResponse(
        start_request_id=result.request_id,
        idempotency_status=result.status,
        created=result.created,
        replayed=result.replayed,
        conversation_id=message_result.conversation_id,
        customer_message_id=message_result.customer_message_id,
        ai_run_id=message_result.ai_run_id,
        trace_id=message_result.trace_id,
        pipeline_stage=message_result.pipeline_stage.value,
        intent=message_result.intent,
        decision=message_result.decision,
        assistant_message_id=message_result.assistant_message_id,
        escalation_id=message_result.escalation_id,
        response=message_result.response,
        succeeded=message_result.succeeded,
        failure_code=message_result.failure_code,
        failure_retryable=message_result.failure_retryable,
    )

def _create_conversation_response(result: CreateConversationResult) -> CreateConversationResponse:
    return CreateConversationResponse(
        conversation_id=result.conversation_id,
        customer_id=result.customer_id,
        status=result.status,
        channel=result.channel,
        title=result.title,
        created_at=result.created_at,
        updated_at=result.updated_at,
    )
    
def _conversation_response(conversation: ConversationView) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=conversation.conversation_id,
        customer_id=conversation.customer_id,
        status=conversation.status,
        channel=conversation.channel,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        resolved_at=conversation.resolved_at,
        closed_at=conversation.closed_at,
    )


def _conversation_list_response(page: ConversationPage) -> ConversationListResponse:
    return ConversationListResponse(
        items=[_conversation_response(conversation) for conversation in page.items],
        total=page.total,
        count=page.count,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
        next_offset=page.next_offset,
    )

def _conversation_message_response(message: ConversationMessageView) -> ConversationMessageResponse:
    feedback = message.feedback
    feedback_response = ConversationMessageFeedbackResponse(
        feedback_id=feedback.feedback_id,
        rating=feedback.rating,
        helpful=feedback.helpful,
        created_at=feedback.created_at,
    ) if feedback is not None else None


    return ConversationMessageResponse(
        message_id=message.message_id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        sequence_number=message.sequence_number,
        created_at=message.created_at,
        ai_run_id=message.ai_run_id,
        feedback_eligible=message.feedback_eligible,
        feedback=feedback_response,
    )