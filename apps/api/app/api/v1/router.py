# AI-customer-support-agent\apps\api\app\api\v1\router.py
from __future__ import annotations
from fastapi import APIRouter

from apps.api.app.api.v1.conversations import router as conversations_router
from apps.api.app.api.v1.health import router as health_router
from apps.api.app.api.v1.escalations import conversation_escalations_router, router as escalations_router
from apps.api.app.api.v1.tickets import router as tickets_router
from apps.api.app.api.v1.feedback import router as feedback_router
from apps.api.app.api.v1.dashboard import router as dashboard_router

API_V1_PREFIX = "/v1"
router = APIRouter(prefix=API_V1_PREFIX)

def register_v1_routes(api_router: APIRouter) -> None:
    """
    Register all version-1 HTTP routers.

    This function is intentionally limited to route composition.
    """
    api_router.include_router(health_router)
    api_router.include_router(conversations_router)
    api_router.include_router(escalations_router)
    api_router.include_router(conversation_escalations_router)
    api_router.include_router(tickets_router)
    api_router.include_router(feedback_router)
    api_router.include_router(dashboard_router)

register_v1_routes(router)