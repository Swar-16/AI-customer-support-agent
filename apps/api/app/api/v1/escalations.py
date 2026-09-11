# AI-customer-support-agent\apps\api\app\api\v1\escalations.py
from __future__ import annotations
import uuid
from typing import Annotated
from fastapi import APIRouter, HTTPException, Path, Query, status, Depends

from apps.api.app.api.v1.schemas.escalations import EscalationListResponse, EscalationPriority, EscalationResponse, CustomerEscalationStatusResponse
from apps.api.app.api.v1.schemas.escalations import EscalationStatus, UpdateEscalationRequest, UpdateEscalationResponse
# from packages.application.escalations.query_escalations import EscalationDoesNotExistError as QueryEscalationDoesNotExistError
from packages.application.escalations.query_escalations import EscalationView, GetEscalationQuery, ListConversationEscalationsQuery, ListEscalationsQuery
# from packages.application.escalations.update_escalation import EscalationDoesNotExistError as UpdateEscalationDoesNotExistError
from packages.application.escalations.update_escalation import UpdateEscalationCommand#, InvalidEscalationTransitionError
from apps.api.app.api.dependencies import ApplicationServicesDependency, CurrentPrincipalDependency, CustomerPrincipalDependency, TraceIdDependency, require_roles
from packages.application.auth.models import AuthRole
from packages.application.escalations.get_customer_escalation_status import GetCustomerEscalationStatusQuery

router = APIRouter(
    prefix="/escalations",
    tags=["escalations"],
    dependencies=[Depends(require_roles(
        AuthRole.SUPPORT_AGENT,
        AuthRole.ADMIN,
    ))],
)
EscalationIdPath = Annotated[uuid.UUID, Path(description="Persistent escalation identifier.")]
ConversationIdPath = Annotated[uuid.UUID, Path(description="Conversation whose escalation history should be returned.")]
PageLimitQuery = Annotated[int, Query(ge=1, le=200, description="Maximum number of escalations to return.")]
PageOffsetQuery = Annotated[int, Query(ge=0, description="Number of matching escalations to skip.")]

@router.get("", response_model=EscalationListResponse, status_code=status.HTTP_200_OK,
            summary="List support escalations", description="Return the active escalation queue or recent escalation history using optional filters.")
def list_escalations(
    services: ApplicationServicesDependency,
    active_only: Annotated[
        bool,
        Query(description="When true, return only open and in-review escalations using priority-first queue ordering."),
    ] = False,
    escalation_status: Annotated[
        EscalationStatus | None,
        Query(
            alias="status",
            description="Filter history by exact escalation status. Cannot be combined with active_only=true.",
        ),
    ] = None,
    priority: Annotated[
        EscalationPriority | None,
        Query(description="Filter by exact escalation priority."),
    ] = None,
    reason_code: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            description="Filter history by exact reason code. Cannot be combined with active_only=true.",
        ),
    ] = None,
    limit: PageLimitQuery = 50,
    offset: PageOffsetQuery = 0,
) -> EscalationListResponse:
    """
    Retrieve escalations for the support dashboard.

    Application-layer query validation remains authoritative. FastAPI query validation handles basic HTTP input errors.
    """
    try:
        page = services.list_escalations.execute(
            ListEscalationsQuery(
                active_only=active_only,
                status=escalation_status,
                priority=priority,
                reason_code=reason_code,
                limit=limit,
                offset=offset,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    items = [_to_escalation_response(item) for item in page.items]
    return EscalationListResponse(
        items=items,
        count=len(items),
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )


@router.get(
    "/{escalation_id}",
    response_model=EscalationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a support escalation")
def get_escalation(escalation_id: EscalationIdPath, services: ApplicationServicesDependency) -> EscalationResponse:
    """Return one escalation with its AI and conversation provenance."""
    escalation = services.get_escalation.execute(GetEscalationQuery(escalation_id=escalation_id))
    return _to_escalation_response(escalation)


@router.patch(
    "/{escalation_id}",
    response_model=UpdateEscalationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update escalation status",
    description="Move an escalation through its controlled human-review lifecycle.",
)
def update_escalation(escalation_id: EscalationIdPath, payload: UpdateEscalationRequest, services: ApplicationServicesDependency,
                      principal: CurrentPrincipalDependency, trace_id: TraceIdDependency) -> UpdateEscalationResponse:
    result = services.update_escalation.execute(
        UpdateEscalationCommand(
            escalation_id=escalation_id,
            target_status=payload.status,
            principal=principal,
            trace_id=trace_id,
        )
    )

    return UpdateEscalationResponse(
        escalation_id=result.escalation_id,
        conversation_id=result.conversation_id,
        ai_run_id=result.ai_run_id,
        previous_status=result.previous_status,
        current_status=result.current_status,
        resolved_at=result.resolved_at,
        updated_at=result.updated_at,
        changed=result.changed,
    )


def _to_escalation_response(escalation: EscalationView) -> EscalationResponse:
    """Convert an application view into its HTTP representation."""
    return EscalationResponse(
        escalation_id=escalation.escalation_id,
        conversation_id=escalation.conversation_id,
        ai_run_id=escalation.ai_run_id,
        trigger_message_id=escalation.trigger_message_id,
        source=escalation.source,
        reason_code=escalation.reason_code,
        reason_summary=escalation.reason_summary,
        priority=escalation.priority,
        status=escalation.status,
        handoff_summary=escalation.handoff_summary,
        metadata=dict(escalation.metadata),
        created_at=escalation.created_at,
        updated_at=escalation.updated_at,
        resolved_at=escalation.resolved_at,
    )

conversation_escalations_router = APIRouter(
    prefix="/conversations",
    tags=["escalations"],
    dependencies=[Depends(require_roles(
        AuthRole.SUPPORT_AGENT,
        AuthRole.ADMIN,
    ))],
)

@conversation_escalations_router.get(
    "/{conversation_id}/escalations",
    response_model=list[EscalationResponse],
    status_code=status.HTTP_200_OK,
    summary="List conversation escalations",
)
def list_conversation_escalations(conversation_id: ConversationIdPath, services: ApplicationServicesDependency, limit: PageLimitQuery = 100) -> list[EscalationResponse]:
    """Return newest-first escalation history for one conversation."""
    escalations = services.list_conversation_escalations.execute(ListConversationEscalationsQuery(conversation_id=conversation_id, limit=limit))

    return [_to_escalation_response(escalation) for escalation in escalations]

customer_escalations_router = APIRouter(
    prefix="/conversations",
    tags=["customer escalations"],
)

@customer_escalations_router.get(
    "/{conversation_id}/escalation-status",
    response_model=CustomerEscalationStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get customer escalation status",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Authentication required",},
        status.HTTP_403_FORBIDDEN: {"description": "Customer role required",},
        status.HTTP_404_NOT_FOUND: {"description": "Conversation or escalation unavailable",},
    },
)
def get_customer_escalation_status(conversation_id: ConversationIdPath, services: ApplicationServicesDependency, principal: CustomerPrincipalDependency) -> CustomerEscalationStatusResponse:
    """Return the newest escalation status for a conversation owned by the authenticated customer."""
    escalation = services.get_customer_escalation_status.execute(
        GetCustomerEscalationStatusQuery(conversation_id=conversation_id, principal=principal)
    )

    return CustomerEscalationStatusResponse(
        escalation_id=escalation.escalation_id,
        conversation_id=escalation.conversation_id,
        status=escalation.status,
        priority=escalation.priority,
        created_at=escalation.created_at,
        updated_at=escalation.updated_at,
        resolved_at=escalation.resolved_at,
    )