from __future__ import annotations
from typing import Any

class LLMProviderError(RuntimeError):
    """
    Base exception for provider-layer failures.

    These exceptions represent infrastructure/provider failures,
    not customer-facing business failures.
    """
    def __init__(self, *, provider: str, message: str, error_code: str | None = None,
                 retryable: bool = False, metadata: dict[str, Any] | None = None
    ) -> None:

        self.provider = provider
        self.error_code = error_code
        self.retryable = retryable
        self.metadata = dict(metadata or {})

        super().__init__(f"[{provider}] {message}")

class LLMProviderTimeoutError(LLMProviderError):
    def __init__(self, *, provider: str, message: str = "Provider request timed out.", metadata: dict[str, Any] | None = None) -> None:
        super().__init__(provider=provider, message=message, error_code="TIMEOUT", retryable=True, metadata=metadata)

class LLMProviderResponseError(LLMProviderError):
    def __init__(self, *, provider: str, message: str, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(provider=provider, message=message, error_code="INVALID_RESPONSE", retryable=False, metadata=metadata)
        
class LLMProviderRateLimitError(LLMProviderError):
    def __init__(self, *, provider: str, message: str = "Provider rate limit exceeded.", metadata: dict[str, Any] | None = None) -> None:
        super().__init__(provider=provider, message=message, error_code="RATE_LIMITED", retryable=True, metadata=metadata)


class LLMProviderAuthenticationError(LLMProviderError):
    def __init__(self, *, provider: str, message: str = "Provider authentication failed.", metadata: dict[str, Any] | None = None) -> None:
        super().__init__(provider=provider, message=message, error_code="AUTHENTICATION_FAILED", retryable=False, metadata=metadata)


class LLMProviderUnavailableError(LLMProviderError):
    def __init__(self, *, provider: str, message: str = "Provider is temporarily unavailable.", metadata: dict[str, Any] | None = None) -> None:
        super().__init__(provider=provider, message=message, error_code="PROVIDER_UNAVAILABLE", retryable=True, metadata=metadata)