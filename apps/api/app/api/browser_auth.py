# AI-customer-support-agent\apps\api\app\api\browser_auth.py
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import HTTPException, Request, Response

from packages.application.auth.exceptions import InvalidRefreshTokenError
from packages.config.settings import Settings

REFRESH_COOKIE_NAME = "support_ai_refresh"
REFRESH_COOKIE_PATH = "/v1/auth"

_SENSITIVE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, private",
    "Pragma": "no-cache",
    "Expires": "0",
}

def set_sensitive_response_headers(response: Response) -> None:
    """Prevent caching of authentication responses."""
    response.headers.update(_SENSITIVE_HEADERS)

def require_browser_origin(request: Request, settings: Settings) -> None:
    """Require one explicitly authorized Origin for browser auth mutations."""
    origins = request.headers.getlist("origin")
    if len(origins) != 1 or origins[0] not in settings.browser_allowed_origins:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "BROWSER_ORIGIN_FORBIDDEN",
                "message": "This browser origin is not permitted.",
            },
            headers=dict(_SENSITIVE_HEADERS),
        )

def read_refresh_cookie(request: Request) -> str:
    """Read refresh material without exposing it in errors or logs."""
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if token is None or not token or len(token) > 512 or token != token.strip():
        raise InvalidRefreshTokenError()

    return token

def set_refresh_cookie(response: Response, *, refresh_token: str, expires_at: datetime, settings: Settings) -> None:
    """Store refresh material only in an HTTP-only browser cookie."""
    if (not refresh_token or len(refresh_token) > 512
        or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for character in refresh_token)
    ):
        raise ValueError("Invalid refresh-token material.")

    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("Refresh expiry must be timezone-aware.")

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        expires=expires_at.astimezone(timezone.utc),
        path=REFRESH_COOKIE_PATH,
        secure=settings.auth_refresh_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    set_sensitive_response_headers(response)

def clear_refresh_cookie(response: Response, *, settings: Settings) -> None:
    """Delete the cookie using the same scope as issuance."""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=settings.auth_refresh_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    set_sensitive_response_headers(response)