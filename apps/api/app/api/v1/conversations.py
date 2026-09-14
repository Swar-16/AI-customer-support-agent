# AI-customer-support-agent\apps\api\app\api\v1\conversations.py
from __future__ import annotations
import uuid
from fastapi import APIRouter, Path, status, Query

from apps.api.app.api.dependencies import ApplicationServicesDependency, CurrentPrincipalDependency, CustomerPrincipalDependency, TraceIdDependency
from apps.api.app.api.schemas.errors import APIErrorResponse
from apps.api.app.api.v1.schemas.conversations import ConversationChannel, ConversationListResponse, ConversationResponse, ConversationStatus
from apps.api.app.api.v1.schemas.conversations import CreateConversationRequest, CreateConversationResponse, SendMessageRequest, SendMessageResponse
from apps.api.app.api.v1.schemas.conversations import ConversationMessageListResponse, ConversationMessageResponse, CloseConversationResponse
from packages.application.conversations.process_customer_message import ProcessCustomerMessageCommand
from packages.application.conversations.create_conversation import CreateConversationCommand, CreateConversationResult
from packages.application.conversations.query_conversations import ConversationPage, ConversationView, GetConversationQuery, ListConversationsQuery
from packages.application.conversations.get_conversation_messages import GetConversationMessagesQuery
from packages.application.conversations.close_conversation import CloseConversationCommand

router = APIRouter(tags=["conversations"])

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
        items=[ConversationMessageResponse(
                message_id=item.message_id,
                conversation_id=item.conversation_id,
                role=item.role,
                content=item.content,
                sequence_number=item.sequence_number,
                created_at=item.created_at,
            )
            for item in result.items
        ],
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