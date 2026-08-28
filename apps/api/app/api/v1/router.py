from __future__ import annotations
from fastapi import APIRouter

from apps.api.app.api.v1.conversations import router as conversations_router
from apps.api.app.api.v1.health import router as health_router

API_V1_PREFIX = "/v1"
router = APIRouter(prefix=API_V1_PREFIX)

def register_v1_routes(api_router: APIRouter) -> None:
    """
    Register all version-1 HTTP routers.

    This function is intentionally limited to route composition.
    """
    api_router.include_router(health_router)
    api_router.include_router(conversations_router)

register_v1_routes(router)