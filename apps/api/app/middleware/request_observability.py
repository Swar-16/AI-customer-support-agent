# AI-customer-support-agent\apps\api\app\middleware\request_observability.py
from __future__ import annotations
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from anyio import to_thread
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uuid6 import uuid7

from apps.api.app.api.dependencies import TRACE_HEADER_NAME
from packages.application.observability.record_api_request import RecordAPIRequestCommand

logger = logging.getLogger(__name__)
_TRACE_HEADER_BYTES = TRACE_HEADER_NAME.lower().encode("latin-1")
_MAX_ERROR_BODY_INSPECTION_BYTES = 64 * 1024

class RequestObservabilityMiddleware:
    """
    Record every HTTP request using a stable trace ID.

    The middleware deliberately does not persist request bodies, response bodies, cookies, authorization headers, or arbitrary query parameters.

    Persistence is best-effort: observability failure is logged internally but never changes the API response delivered to the caller.
    """
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        started_at = datetime.now(timezone.utc)
        started_counter = time.perf_counter()
        trace_id, invalid_trace_message = self._resolve_trace_id(scope)
        state = scope.setdefault("state", {})
        state["trace_id"] = trace_id
        status_code = 500
        response_size_bytes = 0
        response_body_prefix = bytearray()
        propagated_exception_type: str | None = None
        route_template: str | None = None
        route_name: str | None = None

        async def observed_send(message: Message) -> None:
            nonlocal status_code
            nonlocal response_size_bytes
            nonlocal route_template
            nonlocal route_name

            if message["type"] == "http.response.start":
                status_code = int(message["status"])

                route_template = self._resolve_route_template(scope)
                route_name = self._resolve_route_name(scope)

                headers = [(name, value) for name, value in message.get("headers", []) if name.lower() != _TRACE_HEADER_BYTES]
                headers.append((_TRACE_HEADER_BYTES, str(trace_id).encode("latin-1"),))
                message["headers"] = headers

            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                response_size_bytes += len(body)
                remaining = _MAX_ERROR_BODY_INSPECTION_BYTES - len(response_body_prefix)
                if remaining > 0 and body:
                    response_body_prefix.extend(body[:remaining])

            await send(message)

        try:
            if invalid_trace_message is not None:
                response = JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "code": "INVALID_TRACE_ID",
                            "message": invalid_trace_message,
                            "trace_id": str(trace_id),
                        }
                    },
                )
                await response(scope, receive, observed_send)

            else:
                await self._app(scope, receive, observed_send)

        except Exception as exc:
            propagated_exception_type = type(exc).__name__
            status_code = 500
            raise

        finally:
            completed_at = datetime.now(timezone.utc)
            latency_ms = max(0, round((time.perf_counter() - started_counter) * 1_000))
            error_code = self._extract_error_code(response_body_prefix)
            if status_code >= 500 and error_code is None:
                error_code = "INTERNAL_ERROR"

            await self._record_best_effort(
                scope=scope,
                trace_id=trace_id,
                route_template=route_template,
                route_name=route_name,
                status_code=status_code,
                error_code=error_code,
                exception_type=propagated_exception_type,
                response_size_bytes=response_size_bytes,
                latency_ms=latency_ms,
                started_at=started_at,
                completed_at=completed_at,
            )

    async def _record_best_effort(self, *, scope: Scope, trace_id: uuid.UUID, route_template: str | None, route_name: str | None,
                                  status_code: int, error_code: str | None, exception_type: str | None, response_size_bytes: int,
                                  latency_ms: int, started_at: datetime, completed_at: datetime) -> None:
        services = getattr(scope["app"].state, "application_services", None)
        recorder = getattr(services, "record_api_request", None)
        if recorder is None:
            logger.warning(
                "api_request_recorder_unavailable",
                extra={
                    "trace_id": str(trace_id),
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                },
            )
            return

        actor_user_id, actor_role = self._resolve_actor(scope)
        command = RecordAPIRequestCommand(
            trace_id=trace_id,
            method=str(scope.get("method", "GET")),
            route_template=route_template,
            request_path=str(scope.get("path", "/")),
            status_code=status_code,
            error_code=error_code,
            exception_type=exception_type,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            client_ip=self._resolve_client_ip(scope),
            user_agent=self._get_header(scope, "user-agent"),
            request_size_bytes=self._resolve_request_size(scope),
            response_size_bytes=response_size_bytes,
            latency_ms=latency_ms,
            started_at=started_at,
            completed_at=completed_at,
            metadata={
                "http_version": scope.get("http_version"),
                "scheme": scope.get("scheme"),
                "route_name": route_name,
            },
        )

        try:
            await to_thread.run_sync(lambda: recorder.execute(command))

        except Exception as exc:
            logger.exception(
                "api_request_persistence_failed",
                exc_info=exc,
                extra={
                    "trace_id": str(trace_id),
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                },
            )
            return

        logger.info(
            "api_request_completed",
            extra={
                "trace_id": str(trace_id),
                "method": scope.get("method"),
                "route_template": route_template,
                "path": scope.get("path"),
                "status_code": status_code,
                "latency_ms": latency_ms,
                "response_size_bytes": response_size_bytes,
                "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
                "actor_role": actor_role,
            },
        )

    @staticmethod
    def _resolve_trace_id(scope: Scope) -> tuple[uuid.UUID, str | None]:
        raw_trace_id = RequestObservabilityMiddleware._get_header(scope, TRACE_HEADER_NAME)
        if raw_trace_id is None:
            return uuid7(), None

        normalized = raw_trace_id.strip()
        if not normalized:
            return (uuid7(), f"{TRACE_HEADER_NAME} cannot be empty.")

        try:
            return uuid.UUID(normalized), None

        except (ValueError, AttributeError):
            return (uuid7(), f"{TRACE_HEADER_NAME} must contain a valid UUID.")

    @staticmethod
    def _resolve_route_template(scope: Scope) -> str | None:
        # Do not treat unmatched/404 paths as route templates.
        if scope.get("endpoint") is None:
            return None

        request_path = scope.get("path")
        if not isinstance(request_path, str) or not request_path:
            return None

        path_params = scope.get("path_params", {})
        if not isinstance(path_params, dict):
            return request_path

        template = request_path
        replacements = sorted(((str(value), f"{{{name}}}") for name, value in path_params.items()), key=lambda item: len(item[0]), reverse=True)
        for concrete_value, placeholder in replacements:
            if concrete_value:
                template = template.replace(concrete_value, placeholder, 1)

        return template

    @staticmethod
    def _resolve_route_name(scope: Scope) -> str | None:
        route = scope.get("route")
        route_name = getattr(route, "name", None)
        if isinstance(route_name, str) and route_name:
            return route_name

        endpoint = scope.get("endpoint")
        endpoint_name = getattr(endpoint, "__name__", None)
        if isinstance(endpoint_name, str) and endpoint_name:
            return endpoint_name

        return None

    @staticmethod
    def _resolve_actor(scope: Scope) -> tuple[uuid.UUID | None, str | None]:
        state = scope.get("state", {})
        actor_user_id = state.get("actor_user_id")
        actor_role = state.get("actor_role")
        if not isinstance(actor_user_id, uuid.UUID):
            return None, None

        if not isinstance(actor_role, str):
            return None, None

        normalized_role = actor_role.strip().lower()
        if normalized_role not in {"customer", "support_agent", "admin", "system",}:
            return None, None

        return actor_user_id, normalized_role

    @staticmethod
    def _resolve_client_ip(scope: Scope) -> str | None:
        client = scope.get("client")

        if not isinstance(client, tuple) or len(client) < 1:
            return None

        host = client[0]
        if not isinstance(host, str):
            return None

        normalized = host.strip()
        return normalized[:45] or None

    @staticmethod
    def _resolve_request_size(scope: Scope) -> int | None:
        value = RequestObservabilityMiddleware._get_header(scope, "content-length")
        if value is None:
            return None

        try:
            size = int(value)
            
        except (TypeError, ValueError):
            return None

        if size < 0:
            return None

        return size

    @staticmethod
    def _extract_error_code(body: bytearray) -> str | None:
        if not body:
            return None

        try:
            payload = json.loads(body.decode("utf-8"))
            
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return None

        if not isinstance(payload, dict):
            return None

        error = payload.get("error")
        if not isinstance(error, dict):
            return None

        code = error.get("code")
        if not isinstance(code, str):
            return None

        normalized = code.strip().upper()
        return normalized or None

    @staticmethod
    def _get_header(scope: Scope, name: str) -> str | None:
        target = name.lower().encode("latin-1")
        for header_name, header_value in scope.get("headers", []):
            if header_name.lower() == target:
                try:
                    return header_value.decode("latin-1")
                
                except UnicodeDecodeError:
                    return None

        return None