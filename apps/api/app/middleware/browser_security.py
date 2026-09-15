# AI-customer-support-agent\apps\api\app\middleware\browser_security.py
from __future__ import annotations
from collections.abc import Callable
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from packages.config.settings import Settings

class BrowserSecurityMiddleware:
    """Apply browser response policy outside application error handling."""
    def __init__(self, app: ASGIApp, *, settings_provider: Callable[[], Settings]) -> None:
        self._app = app
        self._settings_provider = settings_provider
        self._cors: CORSMiddleware | None = None

    def _get_cors(self) -> CORSMiddleware:
        if self._cors is None:
            settings = self._settings_provider()
            if not isinstance(settings, Settings):
                raise RuntimeError("Browser security settings are unavailable.")

            self._cors = CORSMiddleware(
                app=self._app,
                allow_origins=list(settings.browser_allowed_origins),
                allow_credentials=True,
                allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
                allow_headers=["Authorization", "Content-Type", "X-Trace-ID"],
                expose_headers=["X-Trace-ID", "Retry-After"],
                max_age=600,
            )

        return self._cors

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Lifespan must reach FastAPI before settings are resolved.
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_auth_path = path == "/v1/auth" or path.startswith("/v1/auth/")

        async def send_with_browser_policy(message: Message) -> None:
            if is_auth_path and message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
                headers["Pragma"] = "no-cache"
                headers["Expires"] = "0"

            await send(message)

        await self._get_cors()(scope, receive, send_with_browser_policy)