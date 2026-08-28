from __future__ import annotations
import logging
from typing import Literal
from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict

from apps.api.app.api.dependencies import ApplicationServicesDependency

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])

# Response schemas
class HealthResponse(BaseModel):
    """
    Liveness response.

    This endpoint intentionally performs no database or external-provider
    calls. Its only responsibility is to confirm that the HTTP process is
    running and able to serve requests.
    """
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]

class DependencyHealth(BaseModel):
    """
    Health status for one external/runtime dependency.
    """
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "unavailable"]

class ReadinessResponse(BaseModel):
    """
    Readiness status for the API process.

    Unlike liveness, readiness may perform lightweight dependency checks.
    """
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "not_ready"]
    llm_provider: DependencyHealth


# Liveness
@router.get(
    "",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="API liveness check",
    description="Returns successfully when the API process is alive. No external dependencies are contacted.",
)
def health() -> HealthResponse:
    """
    Lightweight process liveness probe.

    This makes the endpoint appropriate for container/orchestrator
    liveness probes.
    """
    return HealthResponse(status="ok")


# Readiness
@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="API readiness check",
    description="Checks whether dependencies required by the AI application are currently usable.",
    responses={
        200: {
            "description": "Application is ready",
        },
        503: {
            "description": "One or more required dependencies are unavailable",
        },
    },
)
def readiness(response: Response, services: ApplicationServicesDependency) -> ReadinessResponse:
    """
    Determine whether this API instance is ready to process AI requests.

    Provider failures are intentionally converted into readiness state
    rather than propagated as HTTP 500 errors.
    """
    provider_available = _check_llm_provider(services=services)
    if not provider_available:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return ReadinessResponse(
            status="not_ready",
            llm_provider=DependencyHealth(status="unavailable")
        )

    return ReadinessResponse(
        status="ready",
        llm_provider=DependencyHealth(status="ok")
    )


# Internal health checks
def _check_llm_provider(*, services: ApplicationServicesDependency) -> bool:
    """
    Perform the provider's lightweight health check.

    All provider-specific failures remain behind the LLMProvider
    abstraction.
    """

    try:
        healthy = services.base_llm_provider.health_check()

    except Exception:
        logger.exception(
            "llm_provider_readiness_check_failed",
            extra={
                "provider": services.base_llm_provider.provider_name,
                "model": services.base_llm_provider.model_name,
            },
        )

        return False

    if not healthy:
        logger.warning(
            "llm_provider_not_ready",
            extra={
                "provider": services.base_llm_provider.provider_name,
                "model": services.base_llm_provider.model_name,
            },
        )

        return False

    return True