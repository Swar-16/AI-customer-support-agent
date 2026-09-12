# AI-customer-support-agent\apps\api\app\api\v1\tickets.py
from __future__ import annotations
import uuid
from typing import Any
from fastapi import APIRouter, Path, Query, status, Depends

from apps.api.app.api.dependencies import ApplicationServicesDependency, CurrentPrincipalDependency, TraceIdDependency, require_roles
from apps.api.app.api.schemas.errors import APIErrorResponse
from apps.api.app.api.v1.schemas.tickets import AddTicketCommentRequest, AddTicketCommentResponse, CreateTicketRequest, CreateTicketResponse
from apps.api.app.api.v1.schemas.tickets import TicketCategory, TicketCommentResponse, TicketDetailResponse, TicketListResponse, TicketPriority
from apps.api.app.api.v1.schemas.tickets import TicketRequesterRole, TicketResponse, TicketStatus, UpdateTicketRequest, UpdateTicketResponse
from packages.application.tickets.add_ticket_comment import AddTicketCommentCommand, AddTicketCommentResult
from packages.application.tickets.create_ticket import CreateTicketCommand, CreateTicketResult
from packages.application.tickets.query_tickets import GetTicketQuery, ListTicketsQuery, TicketCommentView, TicketDetail, TicketPage, TicketView
from packages.application.tickets.update_ticket import UpdateTicketCommand, UpdateTicketResult
from packages.application.auth.models import AuthRole

router = APIRouter(tags=["tickets"])
_COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": APIErrorResponse, "description": "Invalid ticket operation"},
    403: {"model": APIErrorResponse, "description": "Ticket access denied"},
    404: {"model": APIErrorResponse, "description": "Ticket or related resource not found"},
    409: {"model": APIErrorResponse, "description": "Ticket lifecycle or concurrency conflict"},
    422: {"model": APIErrorResponse, "description": "Request validation failed"},
    500: {"model": APIErrorResponse, "description": "Unexpected internal failure"},
}

@router.post(
    "/conversations/{conversation_id}/tickets",
    response_model=CreateTicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a support ticket",
    description="Create an authenticated customer or staff-originated support ticket for a conversation.",
    responses=_COMMON_ERROR_RESPONSES,
)
def create_ticket(payload: CreateTicketRequest, services: ApplicationServicesDependency, principal: CurrentPrincipalDependency,
                  trace_id: TraceIdDependency, conversation_id: uuid.UUID = Path(..., description="Conversation for which the ticket is created."),
) -> CreateTicketResponse:
    command = CreateTicketCommand(
        conversation_id=conversation_id,
        subject=payload.subject,
        description=payload.description,
        principal=principal,
        trace_id=trace_id,
        customer_id=payload.customer_id,
        category=payload.category,
        priority=payload.priority,
        source_message_id=payload.source_message_id,
        metadata=payload.metadata,
    )

    result = services.create_ticket.execute(command)
    return _create_ticket_response(result)

@router.get(
    "/tickets",
    response_model=TicketListResponse,
    status_code=status.HTTP_200_OK,
    summary="List support tickets",
    description="Return customer-owned tickets or an agent/admin support queue. Authorization is enforced by the application service.",
    responses=_COMMON_ERROR_RESPONSES,
)
def list_tickets(services: ApplicationServicesDependency, principal: CurrentPrincipalDependency, 
                 active_only: bool = Query(default=False, description="Return only the active support work queue."),
                 ticket_status: TicketStatus | None = Query(default=None, alias="status", description="Filter by exact ticket status."),
                 priority: TicketPriority | None = Query(default=None, description="Filter by priority."),
                 category: TicketCategory | None = Query(default=None, description="Filter by category."),
                 assigned_agent_id: uuid.UUID | None = Query(default=None, description="Filter by assigned agent."),
                 unassigned_only: bool = Query(default=False, description="Return only unassigned tickets."),
                 limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
) -> TicketListResponse:
    query = ListTicketsQuery(
        principal=principal,
        active_only=active_only,
        status=ticket_status,
        priority=priority,
        category=category,
        assigned_agent_id=assigned_agent_id,
        unassigned_only=unassigned_only,
        limit=limit,
        offset=offset,
    )

    result = services.list_tickets.execute(query)
    return _ticket_list_response(result)

@router.get(
    "/tickets/{ticket_id}",
    response_model=TicketDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get ticket details",
    description="Return one ticket and the comments visible to the requester.",
    responses=_COMMON_ERROR_RESPONSES,
)
def get_ticket(services: ApplicationServicesDependency, principal: CurrentPrincipalDependency, 
               ticket_id: uuid.UUID = Path(..., description="Ticket identifier.")
) -> TicketDetailResponse:
    query = GetTicketQuery(ticket_id=ticket_id, principal=principal)
    result = services.get_ticket.execute(query)
    
    return _ticket_detail_response(result)

@router.patch(
    "/tickets/{ticket_id}",
    response_model=UpdateTicketResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a support ticket",
    description="Apply a controlled status, priority, category, or assignment mutation using optimistic concurrency control.",
    responses=_COMMON_ERROR_RESPONSES,
    dependencies=[Depends(require_roles(AuthRole.SUPPORT_AGENT, AuthRole.ADMIN,))]
)
def update_ticket(
    payload: UpdateTicketRequest,
    services: ApplicationServicesDependency,
    principal: CurrentPrincipalDependency,
    trace_id: TraceIdDependency,
    ticket_id: uuid.UUID = Path(..., description="Ticket identifier.")
) -> UpdateTicketResponse:
    command = UpdateTicketCommand(
        ticket_id=ticket_id,
        expected_row_version=payload.expected_row_version,
        principal=principal,
        trace_id=trace_id,
        target_status=payload.target_status,
        priority=payload.priority,
        category=payload.category,
        assigned_agent_id=payload.assigned_agent_id,
        unassign=payload.unassign,
        resolution_summary=payload.resolution_summary,
    )

    result = services.update_ticket.execute(command)
    return _update_ticket_response(result)

@router.post(
    "/tickets/{ticket_id}/comments",
    response_model=AddTicketCommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a ticket comment",
    description="Add an authenticated customer-visible reply or internal support note.",
    responses=_COMMON_ERROR_RESPONSES,
)
def add_ticket_comment(payload: AddTicketCommentRequest, services: ApplicationServicesDependency, principal: CurrentPrincipalDependency,
                       trace_id: TraceIdDependency, ticket_id: uuid.UUID = Path(..., description="Ticket receiving the comment.")
) -> AddTicketCommentResponse:
    command = AddTicketCommentCommand(
        ticket_id=ticket_id,
        principal=principal,
        trace_id=trace_id,
        content=payload.content,
        visibility=payload.visibility,
        metadata=payload.metadata,
    )

    result = services.add_ticket_comment.execute(command)
    return _add_ticket_comment_response(result)


def _create_ticket_response(result: CreateTicketResult) -> CreateTicketResponse:
    return CreateTicketResponse(
        ticket_id=result.ticket_id,
        ticket_number=result.ticket_number,
        ticket_reference=result.ticket_reference,
        conversation_id=result.conversation_id,
        customer_id=result.customer_id,
        escalation_id=result.escalation_id,
        status=result.status,
        priority=result.priority,
        category=result.category,
        created=result.created,
    )

def _update_ticket_response(result: UpdateTicketResult) -> UpdateTicketResponse:
    return UpdateTicketResponse(
        ticket_id=result.ticket_id,
        ticket_number=result.ticket_number,
        ticket_reference=result.ticket_reference,
        conversation_id=result.conversation_id,
        customer_id=result.customer_id,
        previous_status=result.previous_status,
        current_status=result.current_status,
        priority=result.priority,
        category=result.category,
        assigned_agent_id=result.assigned_agent_id,
        resolution_summary=result.resolution_summary,
        row_version=result.row_version,
        assigned_at=result.assigned_at,
        resolved_at=result.resolved_at,
        closed_at=result.closed_at,
        updated_at=result.updated_at,
        changed=result.changed,
    )

def _add_ticket_comment_response(result: AddTicketCommentResult) -> AddTicketCommentResponse:
    return AddTicketCommentResponse(
        comment_id=result.comment_id,
        ticket_id=result.ticket_id,
        author_id=result.author_id,
        author_role=result.author_role,
        visibility=result.visibility,
        content=result.content,
        created_at=result.created_at,
    )

def _ticket_response(view: TicketView) -> TicketResponse:
    return TicketResponse(
        ticket_id=view.ticket_id,
        ticket_number=view.ticket_number,
        ticket_reference=view.ticket_reference,
        conversation_id=view.conversation_id,
        customer_id=view.customer_id,
        source_message_id=view.source_message_id,
        escalation_id=view.escalation_id,
        assigned_agent_id=view.assigned_agent_id,
        source=view.source,
        subject=view.subject,
        description=view.description,
        category=view.category,
        priority=view.priority,
        status=view.status,
        resolution_summary=view.resolution_summary,
        metadata=dict(view.metadata),
        row_version=view.row_version,
        created_at=view.created_at,
        updated_at=view.updated_at,
        assigned_at=view.assigned_at,
        resolved_at=view.resolved_at,
        closed_at=view.closed_at,
    )

def _ticket_comment_response(view: TicketCommentView) -> TicketCommentResponse:
    return TicketCommentResponse(
        comment_id=view.comment_id,
        ticket_id=view.ticket_id,
        author_id=view.author_id,
        author_role=view.author_role,
        visibility=view.visibility,
        content=view.content,
        metadata=dict(view.metadata),
        created_at=view.created_at,
    )

def _ticket_detail_response(detail: TicketDetail) -> TicketDetailResponse:
    return TicketDetailResponse(
        ticket=_ticket_response(detail.ticket),
        comments=[_ticket_comment_response(comment) for comment in detail.comments],
    )

def _ticket_list_response(page: TicketPage) -> TicketListResponse:
    return TicketListResponse(
        items=[_ticket_response(ticket) for ticket in page.items],
        count=page.count,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )