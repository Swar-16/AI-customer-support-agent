# AI-customer-support-agent\apps\api\app\api\v1\escalations.py
from __future__ import annotations
import uuid
from typing import Annotated
from fastapi import APIRouter, HTTPException, Path, Query, status

from apps.api.app.api.dependencies import ApplicationServicesDependency
from apps.api.app.api.v1.schemas.escalations import EscalationListResponse, EscalationPriority, EscalationResponse
from apps.api.app.api.v1.schemas.escalations import EscalationStatus, UpdateEscalationRequest, UpdateEscalationResponse
from packages.application.escalations.query_escalations import EscalationDoesNotExistError as QueryEscalationDoesNotExistError
from packages.application.escalations.query_escalations import EscalationView, GetEscalationQuery, ListConversationEscalationsQuery, ListEscalationsQuery
from packages.application.escalations.update_escalation import EscalationDoesNotExistError as UpdateEscalationDoesNotExistError
from packages.application.escalations.update_escalation import InvalidEscalationTransitionError, UpdateEscalationCommand

router = APIRouter(prefix="/escalations", tags=["escalations"])
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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

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
    try:
        escalation = services.get_escalation.execute(GetEscalationQuery(escalation_id=escalation_id))
    except QueryEscalationDoesNotExistError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return _to_escalation_response(escalation)


@router.patch(
    "/{escalation_id}",
    response_model=UpdateEscalationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update escalation status",
    description="Move an escalation through its controlled human-review lifecycle.",
)
def update_escalation(escalation_id: EscalationIdPath, payload: UpdateEscalationRequest, services: ApplicationServicesDependency) -> UpdateEscalationResponse:
    """Transition an escalation using a row-level database lock."""
    try:
        result = services.update_escalation.execute(UpdateEscalationCommand(escalation_id=escalation_id, target_status=payload.status))
    except UpdateEscalationDoesNotExistError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    except InvalidEscalationTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

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